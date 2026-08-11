"""The dbt emitter (RFC 0008 §5.5): config headers per materialization, the
snapshot lowering for SCD type 2, audit → schema-test lowering, scaffold and
sources artifacts, fail-loud unsupported paths, and the port-abstraction
proof itself — dbt and SQLMesh emit byte-identical SELECTs."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import cast

import pytest
import yaml
from sqlglot import exp, parse_one

from bloomery import Target
from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind, EmitContext, EmittedArtifact
from bloomery.emit.base import Feature
from bloomery.emit.dbt import DbtEmitter
from bloomery.emit.sqlmesh import SQLMeshEmitter
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import (
    AuditIR,
    ColumnIR,
    EntityIR,
    Materialization,
    OnFail,
    ProjectIR,
    ReconcileIR,
    SCDKind,
    SourceIR,
    SqlExpr,
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
        expr=SqlExpr(name),
        recipe_id=None,
        renamed_from=None,
        required=False,
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
        source=SourceIR(relation="src"),
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


def test_capabilities_mirror_the_tables_dbt_builds() -> None:
    assert DbtEmitter().capabilities().supported == frozenset(
        {
            Feature.SCD_TYPE_2,
            Feature.VARIANT_COLUMN,
            Feature.INCREMENTAL,
            Feature.AUDITS,
            Feature.SEMI_ADDITIVE,
            Feature.NON_ADDITIVE,
            Feature.CUMULATIVE,
            Feature.DERIVED_METRIC,
        }
    )


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
        "strategy='check', check_cols='all') }}"
    ) in snapshot.content
    assert "FROM {{ source('bronze', 'src') }}" in snapshot.content


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
    stylistic — measured by compiling this project's own ``schema.yml`` on four
    real installs rather than inferred from a changelog:

    ==========================  =========  ==========  ==========  =========
    form                        1.9.10     1.10.22     1.11.12     1.12.0
    ==========================  =========  ==========  ==========  =========
    flat                        ok         ok + warns  ok + warns  ok + warns
    nested (this one)           **error**  ok          ok          ok
    ==========================  =========  ==========  ==========  =========

    So the only version this costs is **1.9**; every release from 1.10 takes
    the form dbt intends to keep, and nothing is owed later. The floor in
    ``pyproject.toml`` is that one column — raising or lowering it without
    moving this form, or the reverse, emits a project the declared range
    cannot compile.
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


def test_unmappable_audit_kind_is_refused() -> None:
    entity = _entity(audits=(AuditIR(kind="freshness", column="sku"),))
    with pytest.raises(UnsupportedByTarget, match=r"'item'.*'freshness'.*'sku'"):
        DbtEmitter().emit(ProjectIR(entities=(entity,)), _ctx())


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
    assert "non-blocking" in message
    assert "__reject" not in message
    assert excinfo.value.source_path == "entity_model: reconcile"


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
        "models": {"bloomery": {"silver": {"+schema": "silver"}}},
    }
    sources = cast("dict[str, object]", yaml.safe_load(artifacts["models/sources.yml"].content))
    assert sources == {
        "version": 2,
        "sources": [{"name": "bronze", "schema": "bronze", "tables": [{"name": "src"}]}],
    }


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
