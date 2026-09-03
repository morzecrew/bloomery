"""The dbt emitter (RFC 0008 §5.5): config headers per materialization, the
snapshot lowering for SCD type 2, audit → schema-test lowering, scaffold and
sources artifacts, fail-loud unsupported paths, and the port-abstraction
proof itself — dbt and SQLMesh emit byte-identical SELECTs."""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest
import yaml
from sqlglot import exp, parse_one

from bloomery import Target
from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind, EmitContext, EmittedArtifact
from bloomery.emit.dbt import DbtEmitter
from bloomery.emit.dbt import _reference_map  # pyright: ignore[reportPrivateUsage]
from bloomery.emit.lower import THIS_MODEL
from bloomery.emit.sqlmesh import SQLMeshEmitter
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import (
    VALID_FROM,
    VALID_TO,
    AuditIR,
    ColumnIR,
    DedupeIR,
    Determinism,
    EntityIR,
    Materialization,
    OnFail,
    ProjectIR,
    QualityRuleIR,
    ReconcileIR,
    Lineage,
    SCDKind,
    SourceColumnIR,
    SourceIR,
    SqlExpr,
    StepIR,
    StepKind,
)
from bloomery.naming import DefaultNaming, PrefixNaming
from bloomery.typing import DecimalType, IntType, LogicalType, StringType
from support.compiling import compile_fixture, extract_select, resolve_dbt_references

pytestmark = pytest.mark.unit


def _ctx(naming: DefaultNaming | PrefixNaming | None = None) -> EmitContext:
    return EmitContext(
        dialect=get_dialect("duckdb"),
        naming=naming if naming is not None else DefaultNaming(),
        fingerprint="blm1:test",
    )


def _column(name: str, column_type: LogicalType) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=column_type,
        canonical=None,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=False,
    )


def _projection(name: str) -> SourceColumnIR:
    """This source\'s lowering of the column (RFC 0024 D26)."""
    return SourceColumnIR(name=name, expr=SqlExpr(name))


#: Every column these builders declare, lowered as itself. The emitted
#: SELECT projects `SourceIR.columns`, so a name missing here is a column
#: the model cannot produce (RFC 0024 D26).
_SOURCE = SourceIR(
    relation="src",
    columns=tuple(
        _projection(name)
        for name in (
            "amount",
            "item_id",
            "qty",
            "sku",
        )
    ),
)


def _entity(
    *,
    name: str = "item",
    key: tuple[str, ...] = ("item_id",),
    scd: SCDKind = SCDKind.TYPE1,
    materialization: Materialization = Materialization.FULL,
    audits: tuple[AuditIR, ...] = (),
) -> EntityIR:
    return EntityIR(
        name=name,
        grain=f"one row per {name}",
        key=key,
        scd=scd,
        materialization=materialization,
        partition_by=(),
        columns=(
            _column("amount", DecimalType(12, 4)),
            _column("item_id", StringType()),
            _column("qty", IntType()),
            _column("sku", StringType()),
        ),
        sources=(_SOURCE,),
        audits=tuple(sorted(audits, key=lambda a: (a.kind, a.column))),
    )


def _emit(entity: EntityIR) -> dict[str, EmittedArtifact]:
    artifacts = DbtEmitter().emit(ProjectIR(entities=(entity,)), _ctx())
    return {a.path: a for a in artifacts}


def _dbt_select(content: str) -> str:
    """The SELECT of a dbt model artifact: everything after the blank line
    that closes the header + config block."""
    _envelope, _sep, select = content.partition("\n\n")
    return select.strip()


@pytest.mark.parametrize(
    ("materialization", "config_line"),
    [
        (Materialization.FULL, "{{ config(materialized='table') }}"),
        (
            Materialization.INCREMENTAL_BY_KEY,
            "{{ config(materialized='incremental', unique_key='item_id') }}",
        ),
        (
            Materialization.INCREMENTAL_BY_PARTITION,
            "{{ config(materialized='incremental', unique_key='item_id') }}",
        ),
    ],
)
def test_materialization_lowers_to_a_config_header(
    materialization: Materialization, config_line: str
) -> None:
    artifacts = _emit(_entity(materialization=materialization))
    model = artifacts["models/silver/item.sql"]
    assert model.kind is ArtifactKind.MODEL
    assert config_line in model.content
    assert "-- fingerprint: blm1:test" in model.content


def test_composite_key_incremental_renders_a_unique_key_list() -> None:
    entity = _entity(key=("item_id", "qty"), materialization=Materialization.INCREMENTAL_BY_KEY)
    model = _emit(entity)["models/silver/item.sql"]
    assert "unique_key=['item_id', 'qty']" in model.content


def test_scd2_lowers_to_a_check_strategy_snapshot() -> None:
    artifacts = _emit(_entity(scd=SCDKind.TYPE2))
    assert "models/silver/item.sql" not in artifacts  # the snapshot replaces it
    snapshot = artifacts["snapshots/item_snapshot.sql"]
    assert snapshot.kind is ArtifactKind.MODEL
    assert snapshot.content.count("{% snapshot item_snapshot %}") == 1
    assert snapshot.content.rstrip("\n").endswith("{% endsnapshot %}")
    assert (
        "{{ config(target_schema='silver', unique_key='item_id', "
        "strategy='check', check_cols='all', "
        "snapshot_meta_column_names={'dbt_valid_from': 'valid_from', "
        "'dbt_valid_to': 'valid_to'}) }}"
    ) in snapshot.content
    assert "FROM {{ source('bronze', 'src') }}" in snapshot.content


def test_the_snapshot_names_its_interval_the_way_the_ir_does() -> None:
    """Both targets must spell the validity interval identically or the as-of
    join cannot be lowered once (RFC 0023 §5.3, D7): dbt's own defaults are
    `dbt_valid_from`/`dbt_valid_to`, so the rename is what makes the shared
    predicate resolve on this target too."""
    snapshot = _emit(_entity(scd=SCDKind.TYPE2))["snapshots/item_snapshot.sql"]
    assert f"'dbt_valid_from': '{VALID_FROM}'" in snapshot.content
    assert f"'dbt_valid_to': '{VALID_TO}'" in snapshot.content


def test_scd2_snapshot_respects_the_naming_policy_schema() -> None:
    artifacts = DbtEmitter().emit(
        ProjectIR(entities=(_entity(scd=SCDKind.TYPE2),)), _ctx(PrefixNaming(prefix="acme"))
    )
    snapshot = next(a for a in artifacts if a.path == "snapshots/item_snapshot.sql")
    assert "target_schema='acme_silver'" in snapshot.content


def test_scd2_with_composite_key_is_refused() -> None:
    entity = _entity(key=("item_id", "qty"), scd=SCDKind.TYPE2)
    with pytest.raises(UnsupportedByTarget, match=r"'item'.*composite key.*scd_type_2"):
        DbtEmitter().emit(ProjectIR(entities=(entity,)), _ctx())


def test_audits_lower_to_schema_tests() -> None:
    entity = _entity(
        audits=(
            AuditIR(kind="not_null", column="item_id"),
            AuditIR(kind="enum", column="qty", params=(("value_0000", "1"), ("value_0001", "2"))),
            AuditIR(kind="min", column="amount", params=(("value", "0"),)),
            AuditIR(kind="max", column="qty", params=(("value", "10"),)),
            AuditIR(kind="regex", column="sku", params=(("pattern", "^A-"),)),
            AuditIR(kind="reconcile", column="amount", params=(("shadow", "amount__direct"),)),
        )
    )
    schema = _emit(entity)["models/schema.yml"]
    assert schema.kind is ArtifactKind.CONFIG
    document = cast("dict[str, object]", yaml.safe_load(schema.content))
    (model,) = cast("list[dict[str, object]]", document["models"])
    assert model["name"] == "item"
    # audits are sorted by (kind, column) on EntityIR — the order is theirs
    assert model["data_tests"] == [
        {"bloomery_expression_is_true": {"arguments": {"expression": "qty <= 10"}}},
        {"bloomery_expression_is_true": {"arguments": {"expression": "amount >= 0"}}},
        {
            "bloomery_expression_is_true": {
                "arguments": {"expression": "amount IS NOT DISTINCT FROM amount__direct"}
            }
        },
        {
            "bloomery_expression_is_true": {
                "arguments": {"expression": "REGEXP_MATCHES(sku, '^A-')"}
            }
        },
    ]
    assert model["columns"] == [
        # `not_null` takes no arguments, so it stays a bare name on every
        # version — the nesting D22 adopted is a change to *parameterized*
        # tests only.
        {"name": "item_id", "data_tests": ["not_null"]},
        {"name": "qty", "data_tests": [{"accepted_values": {"arguments": {"values": [1, 2]}}}]},
    ]


def test_generic_test_arguments_are_nested_which_is_what_sets_the_floor() -> None:
    """RFC 0008 D22 — the emitted form and the supported dbt range are one
    decision, pinned together because neither is safe to change alone.

    dbt 1.10 moved generic-test arguments under an ``arguments`` property and
    deprecated the flat form. The two are **mutually exclusive**, not
    stylistic, and the boundary is *not* a minor version — measured by
    compiling this project's own ``schema.yml`` on eight real installs:

    =================  =======  ========  ========  ========  =======  ======
    form               1.9.10   1.10.5    1.10.7    1.10.8    1.11.12  1.12.0
    =================  =======  ========  ========  ========  =======  ======
    flat               ok       ok+warn   ok+warn   ok+warn   ok+warn  ok+warn
    nested (this one)  error    error     error     ok        ok       ok
    =================  =======  ========  ========  ========  =======  ======

    Through 1.10.7 the nested form needs the
    ``require_generic_test_arguments_property`` behaviour flag and without it
    dbt passes ``arguments`` to the macro as a literal keyword — "macro ...
    takes no keyword argument 'arguments'". 1.10.8 makes it the default.

    So the floor is **1.10.8**, which is neither the minor version this was
    first written against (``>=1.10``, wrong: it admits 1.10.0–1.10.7) nor a
    round number. ``pyproject.toml`` carries that bound, and it and this form
    move together or not at all.
    """
    entity = _entity(
        audits=(
            AuditIR(kind="enum", column="qty", params=(("value_0000", "1"),)),
            AuditIR(kind="min", column="amount", params=(("value", "0"),)),
        )
    )
    document = cast(
        "dict[str, object]", yaml.safe_load(_emit(entity)["models/schema.yml"].content)
    )
    (model,) = cast("list[dict[str, object]]", document["models"])
    declared = cast("list[object]", model["data_tests"]) + [
        test
        for column in cast("list[dict[str, object]]", model["columns"])
        for test in cast("list[object]", column["data_tests"])
    ]
    parameterized = [test for test in declared if isinstance(test, dict)]
    assert parameterized, "no parameterized test emitted — the pin would be vacuous"
    for test in parameterized:
        (body,) = cast("dict[str, object]", test).values()
        # Exactly `arguments`, not `arguments` plus stragglers: a half-migrated
        # entry parses on 1.10 and warns like the flat form it still partly is.
        assert list(cast("dict[str, object]", body)) == ["arguments"]


MACRO_PATH = "macros/bloomery_expression_is_true.sql"


def test_the_expression_test_is_defined_by_the_project_that_declares_it() -> None:
    """RFC 0008 D18. The emitted project used to name
    ``dbt_utils.expression_is_true`` and ship no ``packages.yml``, so every
    project with a ``min``/``max``/``regex``/``reconcile`` assert declared a
    test dbt could not build — ``dbt compile`` stopped at "'dbt_utils' is
    undefined". A compiler whose artifacts are a pure function of its specs
    cannot emit a file whose meaning lives behind a network fetch."""
    entity = _entity(audits=(AuditIR(kind="min", column="amount", params=(("value", "0"),)),))
    macro = _emit(entity)[MACRO_PATH]
    # The audit *body* for this target, exactly as `audits/<name>.sql` is on
    # the SQLMesh side — same kinds, same predicate, same kind of artifact.
    assert macro.kind is ArtifactKind.AUDIT
    assert "{% test bloomery_expression_is_true(model, expression) %}" in macro.content
    assert "WHERE NOT ({{ expression }})" in macro.content
    # The macro body spells its own name (a literal, so no escaping layer sits
    # between it and the file) while `schema.yml` spells it from the constant.
    # Two spellings, so they are pinned to each other here rather than left to
    # `dbt compile` to discover.
    schema = _emit(entity)["models/schema.yml"].content
    (name,) = re.findall(r"\{% test (\w+)\(", macro.content)
    assert f"{name}:" in schema


def test_the_macro_rides_exactly_with_the_test_that_needs_it() -> None:
    """Both directions of the invariant, because each failure is silent in its
    own way: a project declaring the test without the macro will not compile,
    and one carrying the macro unused ships a file nothing references."""
    needs = _entity(audits=(AuditIR(kind="regex", column="sku", params=(("pattern", "^A-"),)),))
    assert MACRO_PATH in _emit(needs)
    # `not_null` is native on both targets (D16), so it needs nothing of ours.
    does_not = _entity(audits=(AuditIR(kind="not_null", column="item_id"),))
    emitted = _emit(does_not)
    assert MACRO_PATH not in emitted
    assert "bloomery_expression_is_true" not in emitted["models/schema.yml"].content


def test_scd2_audits_attach_under_snapshots() -> None:
    entity = _entity(scd=SCDKind.TYPE2, audits=(AuditIR(kind="not_null", column="sku"),))
    schema = _emit(entity)["models/schema.yml"]
    document = cast("dict[str, object]", yaml.safe_load(schema.content))
    assert "models" not in document
    (snapshot,) = cast("list[dict[str, object]]", document["snapshots"])
    assert snapshot["name"] == "item_snapshot"


def test_an_audit_kind_outside_the_closed_vocabulary_is_refused() -> None:
    """RFC 0026 §5.4 counted this among the five refusals a singular test
    lifts. It is not one, and the reason is worth pinning rather than
    rediscovering.

    There is nothing to route. The ``assert:`` vocabulary is closed at six
    kinds — ``guardrails/asserts.py`` and ``guardrails/conflict.py`` are the
    only places an ``AuditIR`` is built — and ``audit_predicate`` knows exactly
    the four custom ones, so a seventh kind has no body on *any* target: the
    SQLMesh emitter reaches the same branch and dies on a ``KeyError``. The
    kind below is reachable only by hand-building the IR, which is what this
    test does.

    So the guard stays, and its message now says what is actually wrong. It is
    an internal-consistency assertion, not a dbt limitation — see
    ``logs/T-0003.md`` D-013.
    """
    entity = _entity(audits=(AuditIR(kind="freshness", column="sku"),))
    with pytest.raises(UnsupportedByTarget) as excinfo:
        DbtEmitter().emit(ProjectIR(entities=(entity,)), _ctx())
    message = str(excinfo.value)
    assert "'item'" in message
    assert "'freshness'" in message
    assert "'sku'" in message
    # Not "dbt cannot": no target can.
    assert "closed assert: vocabulary" in message
    assert "no target" in message


def test_reconcile_refusal_names_the_check_and_the_decision_authorizing_it() -> None:
    """RFC 0016 §5.4's target-coverage sentence scopes dbt's refusal to the
    reject/replay artifacts; the reconcile refusal is a *separate* claim, and
    an unauthorized refusal is exactly the "code contradicts the RFC" defect.
    D58 authorizes it, so the message that stops the compile cites the row a
    reader can check it against."""
    check = ReconcileIR(
        name="totals_match",
        left="sum(item.amount) by order_id",
        right="order.total",
        tolerance=Decimal("0.01"),
        on_fail=OnFail.FLAG,
    )
    with pytest.raises(UnsupportedByTarget) as excinfo:
        DbtEmitter().emit(ProjectIR(entities=(_entity(),), reconcile=(check,)), _ctx())
    message = str(excinfo.value)
    assert "totals_match" in message
    assert "RFC 0016 D58" in message
    # It refuses the *reconcile* surface, not the reject/replay one — naming the
    # wrong thing is how the scope crept in the first place.
    assert "__reject" not in message
    assert excinfo.value.source_path == "entity_model: reconcile"
    # RFC 0026 D8: the surviving half of D58's argument is the comparison
    # *model*. The other half — "no non-blocking test to approximate the audit
    # with" — is now false, since a singular test carrying severity='warn' is
    # exactly one, so the message must not still claim it.
    assert "comparison model" in message
    assert "non-blocking" not in message


def test_a_merged_entity_emits_the_collision_audit_it_used_to_be_refused_for() -> None:
    """RFC 0024 D30 lifted (RFC 0026 D9).

    D30's argument was correct when it was written: the merge's *correctness
    condition* is a blocking audit, this emitter's whole test surface was
    ``schema.yml`` entries, and a ``GROUP BY <key> HAVING COUNT(DISTINCT
    _source) > 1`` is none of those. What changed is the emitter, not the
    reasoning — so the assertion is that the audit is now **emitted**, not that
    the refusal was wrong.

    The audit reads bronze rather than the model, so in dbt it is ordered
    after the *sources* instead of after ``item``. That is what D13's placement
    costs on this target and it is not a weakening of D5: a failing test on a
    node's parents stops that node's descendants, and the check is about bronze
    data either way.

    ``severity='error'`` is written out because D5 makes this audit blocking
    and not configurable to a weaker disposition: a key in two sources is
    either genuine duplication or a shared key space by accident, and both are
    refusals.
    """
    merged = replace(
        _entity(),
        sources=(_SOURCE, replace(_SOURCE, relation="src_b")),
    )
    artifacts = DbtEmitter().emit(ProjectIR(entities=(merged,)), _ctx())
    (test,) = [a for a in artifacts if a.path == "tests/item_source_collision.sql"]
    assert test.kind is ArtifactKind.AUDIT
    assert "{{ config(severity='error') }}" in test.content
    assert "COUNT(DISTINCT _source) > 1" in test.content
    # It reads the **union stage**, not the model (D13, restored by P2b):
    # dedupe collapses rows sharing an entity key, so an audit below it would
    # be reading the one relation guaranteed not to contain what it looks for.
    # Sources, therefore, and never a literal relation — the reference is what
    # makes the test resolve at all.
    assert "{{ source('bronze', 'src') }}" in test.content
    assert "{{ source('bronze', 'src_b') }}" in test.content
    assert "bronze.src" not in test.content


def test_a_merged_entity_declares_every_source(  # D20, whole
) -> None:
    """One ``source()`` per mapping — the prediction RFC 0024 D20 made about
    the union, which was always true and is now the whole of what dbt needs:
    the day the refusal lifted, both relations had to resolve."""
    merged = replace(_entity(), sources=(_SOURCE, replace(_SOURCE, relation="src_b")))
    references = _reference_map(ProjectIR(entities=(merged,)), _ctx())
    assert ("bronze", "src") in references
    assert ("bronze", "src_b") in references


def test_scaffold_and_sources_artifacts() -> None:
    artifacts = _emit(_entity())
    project = cast("dict[str, object]", yaml.safe_load(artifacts["dbt_project.yml"].content))
    assert project == {
        "name": "bloomery",
        "version": "1.0.0",
        "profile": "bloomery",
        "model-paths": ["models"],
        "snapshot-paths": ["snapshots"],
        "macro-paths": ["macros"],
        # Declared though it is dbt's own default, exactly as `macro-paths` is
        # (RFC 0026 §6): the claim is that the emitted project states its own
        # layout, *not* that removing the line would stop dbt finding the
        # tests — it would not, and an earlier draft of this said otherwise.
        "test-paths": ["tests"],
        "models": {"bloomery": {"silver": {"+schema": "silver"}}},
    }
    sources = cast("dict[str, object]", yaml.safe_load(artifacts["models/sources.yml"].content))
    assert sources == {
        "version": 2,
        "sources": [{"name": "bronze", "schema": "bronze", "tables": [{"name": "src"}]}],
    }


def test_a_tier_one_macro_step_contributes_no_singular_test() -> None:
    """Tier 1 is spliced into the consuming SELECT at lowering, so by the time
    an emitter sees the IR it is already inside whichever model reads it — and
    it declares no outputs, so there is nothing for an audit to judge.

    The skip is written as ``is not SQL_MODEL`` rather than ``is SQL_MACRO``,
    which is the same condition ``_step_artifacts`` beside it uses. That is not
    style: a Tier 3 step has no ``ref()`` in the reference map, so reaching the
    resolver with one would raise ``KeyError`` instead of the refusal
    ``refuse_python_models`` gives first. Writing the condition so it does not
    lean on another function's ordering is what this pins.
    """
    macro = StepIR(
        ref="score",
        version=1,
        kind=StepKind.SQL_MACRO,
        determinism=Determinism.PURE,
        runtime_lock="sha256:x",
        lineage=Lineage.COLUMN,
        outputs=(),
        body=SqlExpr("LOWER(x)"),
    )
    artifacts = DbtEmitter().emit(ProjectIR(entities=(_entity(),), steps=(macro,)), _ctx())
    assert not [a for a in artifacts if a.path.startswith("tests/")]


def test_the_emitted_project_carries_the_operator_contract() -> None:
    """RFC 0026 §5.5 calls this sentence the RFC's cost and says it is not
    optional; §10 asks where it lives. It lives in both places, because they
    have different readers.

    The docs page is read by whoever compiled the project. ``dbt_project.yml``
    is read by whoever *runs* it, who may be neither the same person nor a
    bloomery user at all — and for that reader, nothing else in the emitted
    bytes says that ``dbt run`` produces models with their gates unevaluated.

    Asserted here rather than left to the goldens alone: a golden records
    whatever the emitter last produced, so it would follow this sentence out of
    the file without a word.
    """
    project = _emit(_entity())["dbt_project.yml"].content
    assert "`dbt build`, not `dbt run`" in project
    # Both directions, for the same reason the docs page states both: a reader
    # given only the first has the wrong model of the target.
    assert "--warn-error" in project
    # ...and it is a comment, so the document itself still parses.
    document = cast("dict[str, object]", yaml.safe_load(project))
    assert document["name"] == "bloomery"


def test_sources_respect_the_naming_policy() -> None:
    artifacts = DbtEmitter().emit(
        ProjectIR(entities=(_entity(),)), _ctx(PrefixNaming(prefix="acme"))
    )
    sources_artifact = next(a for a in artifacts if a.path == "models/sources.yml")
    document = cast("dict[str, object]", yaml.safe_load(sources_artifact.content))
    (source,) = cast("list[dict[str, object]]", document["sources"])
    assert source["name"] == "acme_bronze"
    assert source["schema"] == "acme_bronze"


# ....................... #
# The port-abstraction proof (RFC 0008 D5): same SELECT, different envelope.


def _erase_namespaces(sql: str, dialect: str) -> str:
    """The same SELECT with every table's namespace dropped.

    D20's `ref()` names a *model*, and a model name carries no namespace — so
    after resolving references the dbt side says `order_item` where SQLMesh
    says `silver.order_item`. Erasing the namespace on **both** sides is what
    lets the rest of the SELECT still be compared byte for byte; that the
    namespaces themselves agree is a different claim, asserted by
    `test_a_reference_resolves_to_the_relation_the_naming_policy_names`.
    """
    tree = parse_one(sql, dialect=dialect)
    for table in tree.find_all(exp.Table):
        table.set("db", None)
        table.set("catalog", None)
    # `identify=True` on both sides: re-parsing a resolved `ref('order')`
    # yields a bare identifier where the SQLMesh side had a qualified one,
    # and the two render their quoting differently for a reserved word.
    return tree.sql(dialect=dialect, pretty=True, identify=True)


@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "trino"])
def test_dbt_and_sqlmesh_emit_identical_selects(dialect: str) -> None:
    """D5's proof, restated for D20 and no weaker for it.

    It used to compare the two bodies byte for byte. It cannot now: a dbt model
    states its inputs as `ref()`/`source()` so dbt can order the DAG and place
    the relations, which is the whole of D20. What still holds — and is the
    thing D5 is actually about — is that **no lowering is duplicated**: resolve
    the references, drop the namespaces, and the two targets' SQL is identical
    on every projection, join, cast and dialect quirk. The entire difference
    between the targets is one documented substitution over table nodes.
    """
    sqlmesh = {
        a.path: a
        for a in compile_fixture("ecom_basic", dialect=dialect)
        if a.kind is ArtifactKind.MODEL
    }
    dbt = {
        a.path: a
        for a in compile_fixture("ecom_basic", target=Target.DBT, dialect=dialect)
        if a.path.endswith(".sql") and not a.path.startswith("macros/")
    }
    assert set(sqlmesh) == set(dbt)  # every model path exists on both targets
    for path, sqlmesh_artifact in sqlmesh.items():
        rendered = resolve_dbt_references(_dbt_select(dbt[path].content))
        assert _erase_namespaces(extract_select(sqlmesh_artifact.content), dialect) == (
            _erase_namespaces(rendered, dialect)
        ), path


def test_a_dedupe_entity_gets_its_ingestion_metadata_check() -> None:
    """RFC 0016 D21 on dbt, which never refused it and never emitted it.

    The duplicate-identity half is a window count, and SQL forbids a window
    function in ``WHERE`` — so the body wraps the model once and filters over
    the projected count, which is not a row predicate and so had no
    ``schema.yml`` home. It was silently absent rather than refused, under
    RFC 0016 §5.4's target-coverage sentence; that sentence was written when
    this emitter had no artifact for it.

    ``dedupe:`` with no ``quality:`` surface is the shape that reaches it, and
    it is an ordinary one: deduping does not opt an entity into coercion
    routing.
    """
    entity = replace(
        _entity(),
        dedupe=DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id",)),
    )
    artifacts = {a.path: a for a in DbtEmitter().emit(ProjectIR(entities=(entity,)), _ctx())}
    test = artifacts["tests/item_ingestion_metadata.sql"]
    assert "COUNT(*) OVER (PARTITION BY _source_row_id)" in test.content
    assert "{{ ref('item') }}" in test.content
    assert "{{ config(severity='error') }}" in test.content


def test_an_entity_fail_audit_lowers_even_though_no_spec_reaches_it() -> None:
    """The other half of the same extension, and the honest note about it.

    An ``on_fail: fail`` rule on an entity is a whole-query check over two
    populations (RFC 0016 D32/D67), and it lowers here correctly. **No spec can
    reach it on this target today**: declaring any ``quality:`` surface opts
    the entity into coercion routing, the implicit ``coercible`` rules default
    to ``quarantine``, and a *key* column's cannot be overridden because a key
    mapping takes no ``quality:`` block — so ``_refuse_quarantine`` raises
    first, every time.

    The lowering stays, because it is the right one and it goes live the day
    dbt grows a reject model. What it must not do is stay *untested*, which is
    how an unreachable branch rots — so the IR is built directly here, past the
    guardrail that would refuse the spec.
    """
    entity = replace(
        _entity(),
        quality=(
            QualityRuleIR(
                name="sku_present",
                kind="not_null",
                column="sku",
                on_fail=OnFail.FAIL,
            ),
        ),
    )
    artifacts = {a.path: a for a in DbtEmitter().emit(ProjectIR(entities=(entity,)), _ctx())}
    test = artifacts["tests/item_sku_present.sql"]
    assert "{{ ref('item') }}" in test.content
    assert "@this_model" not in test.content
    assert "{{ config(severity='error') }}" in test.content


#: Fixtures whose checks have no ``schema.yml`` shape, with the relation each
#: check is attached to. The relation is what the comparison below has to
#: normalize away: SQLMesh writes ``@this_model`` and dbt writes a ``ref()``,
#: and everything else about the two bodies must be the same query.
_AUDIT_FIXTURES = {
    "multi_source": {"order_line_source_collision": "order_line"},
    "coverage_check": {"every_customer_has_an_order_coverage": "order"},
}


def _normalize_audit(sql: str, dialect: str, self_relation: str) -> str:
    """One audit body in a form the two targets can be compared in.

    Two substitutions, both named rather than incidental. ``@this_model``
    becomes the relation it stands for, because that is the *only* thing
    RFC 0026 D10 lets the targets differ about. Namespaces are then erased on
    both sides for the reason ``_erase_namespaces`` gives — a ``ref()`` names a
    model, and a model name carries none.

    The macro is substituted in the **text**, before parsing, because it is not
    SQL: sqlglot reads ``@this_model`` as a parameter rather than as a table,
    so there is no table node to rewrite. That is also why the emitter builds
    the relation in instead of rewriting it afterwards — the same fact seen
    from the other side.
    """
    tree = parse_one(sql.replace(THIS_MODEL, self_relation), dialect=dialect)
    return _erase_namespaces(tree.sql(dialect=dialect), dialect)


@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "trino"])
@pytest.mark.parametrize("fixture", sorted(_AUDIT_FIXTURES))
def test_the_two_targets_emit_the_same_audit_body(fixture: str, dialect: str) -> None:
    """RFC 0026 §6, and the reason the RFC asked for it in those words: "the
    two targets' audit bodies are compared, not merely both asserted".

    A test that pinned each target's body separately would pass straight
    through a divergence — both assertions would be about text somebody wrote
    down, and neither about the two being the same check. This is the
    ``reading-isnt-proof`` shape: one contract, two implementations, one
    battery.

    It is also what makes D10's envelope split *provable* rather than merely
    intended. The split claims the body is shared and only the wrapper is a
    target's; if a body were ever rebuilt on one side, this is where it shows.
    """
    expected = _AUDIT_FIXTURES[fixture]
    sqlmesh = {
        a.path.removeprefix("audits/").removesuffix(".sql"): extract_select(a.content)
        for a in compile_fixture(fixture, dialect=dialect)
        if a.kind is ArtifactKind.AUDIT and a.path.startswith("audits/")
    }
    dbt = {
        a.path.removeprefix("tests/").removesuffix(".sql"): _dbt_select(a.content)
        for a in compile_fixture(fixture, target=Target.DBT, dialect=dialect)
        if a.path.startswith("tests/")
    }
    assert set(sqlmesh) == set(dbt) == set(expected), fixture
    for name, relation in expected.items():
        assert _normalize_audit(sqlmesh[name], dialect, relation) == _normalize_audit(
            resolve_dbt_references(dbt[name]), dialect, relation
        ), name


@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "trino"])
def test_the_metadata_audit_is_one_body_in_two_spellings(dialect: str) -> None:
    """The one body RFC 0026 D10 did *not* unify, held to the same standard.

    Every other audit body is built once in shared lowering and wrapped by each
    target. The ingestion-metadata audit is not: SQLMesh has spelled its
    windowed wrap in a Jinja envelope since RFC 0016, and RFC 0026 §4 rules out
    changing an audit body that is already correct — a pretty-printed AST is
    not byte-identical to a hand-written template line, so unifying it would
    re-stamp every SQLMesh golden carrying one.

    So there are two spellings, deliberately, and this is what stops them
    drifting. Without it the *shared* bodies would be pinned by
    ``test_the_two_targets_emit_the_same_audit_body`` and the one genuinely
    duplicated body would be the only one nothing watched — which is the
    parallel maintenance D10 exists to prevent, surviving in the single place
    D10 could not reach.
    """
    entity = replace(
        _entity(),
        dedupe=DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id",)),
    )
    ir = ProjectIR(entities=(entity,))
    ctx = EmitContext(
        dialect=get_dialect(dialect), naming=DefaultNaming(), fingerprint="blm1:test"
    )
    sqlmesh = next(
        a for a in SQLMeshEmitter().emit(ir, ctx) if a.path.endswith("_ingestion_metadata.sql")
    )
    dbt = next(
        a for a in DbtEmitter().emit(ir, ctx) if a.path.endswith("_ingestion_metadata.sql")
    )
    assert _normalize_audit(extract_select(sqlmesh.content), dialect, "item") == _normalize_audit(
        resolve_dbt_references(_dbt_select(dbt.content)), dialect, "item"
    )


def test_the_comparison_above_can_fail() -> None:
    """Its control. Both sides go through one normalizer, and a normalizer that
    collapsed too much would make every comparison pass — so a body that
    genuinely differs has to come out different."""
    one = _normalize_audit("SELECT a FROM @this_model", "duckdb", "t")
    other = _normalize_audit("SELECT b FROM @this_model", "duckdb", "t")
    assert one != other
    # ...and the substitution it exists for really happens.
    assert "@this_model" not in one
    assert _normalize_audit("SELECT a FROM t", "duckdb", "t") == one


def test_a_reference_resolves_to_the_relation_the_naming_policy_names() -> None:
    """The half the comparison above erases, asserted directly — and the half
    D22 thought adopting `ref()` had to give up. A `ref()` carries no
    namespace, so what pins the relation is the `+schema` config, and what
    makes `+schema` mean the naming policy's word rather than dbt's default
    `<target>_<custom>` is the `generate_schema_name` override.
    """
    artifacts = {
        a.path: a.content
        for a in DbtEmitter().emit(
            ProjectIR(entities=(_entity(),)), _ctx(PrefixNaming(prefix="acme"))
        )
    }
    # The model is written where the policy says, and read by the name dbt
    # knows it as — those are different strings, and both have to be right.
    assert "models/acme_silver/item.sql" in artifacts
    project = cast("dict[str, object]", yaml.safe_load(artifacts["dbt_project.yml"]))
    models = cast("dict[str, dict[str, object]]", project["models"])
    assert models["bloomery"] == {"acme_silver": {"+schema": "acme_silver"}}
    # ...and the override that makes `+schema: acme_silver` mean `acme_silver`
    # rather than dbt's default `<target.schema>_acme_silver`.
    macro = artifacts["macros/generate_schema_name.sql"]
    assert "{{ custom_schema_name | trim }}" in macro
    assert "{{ target.schema }}_" not in macro
    # The source keeps its namespace, because `source()` carries one.
    assert "{{ source('acme_bronze', 'src') }}" in artifacts["models/acme_silver/item.sql"]


def test_sqlmesh_and_dbt_render_the_same_scd2_select() -> None:
    entity = _entity(scd=SCDKind.TYPE2)
    ir = ProjectIR(entities=(entity,))
    sqlmesh_model = next(
        a for a in SQLMeshEmitter().emit(ir, _ctx()) if a.kind is ArtifactKind.MODEL
    )
    snapshot = _emit(entity)["snapshots/item_snapshot.sql"]
    snapshot_select = snapshot.content.partition("\n\n")[2].rpartition("\n\n")[0].strip()
    assert extract_select(sqlmesh_model.content) == resolve_dbt_references(snapshot_select)


def test_empty_project_emits_only_the_scaffold() -> None:
    artifacts = DbtEmitter().emit(ProjectIR(), _ctx())
    assert [a.path for a in artifacts] == [
        "dbt_project.yml",
        "macros/generate_schema_name.sql",
    ]
