"""Property tier (RFC 0009 §5.5): compile-twice byte identity across every
(target × dialect) cell, emitted SQL parsing under the target dialect, Cube
YAML round-tripping and dialect independence, and SELECT-columns ⇔
declared-fields — the invariants that must hold for every input."""

from __future__ import annotations

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlglot import exp, parse, parse_one

from bloomery import Target, compile_project, load_project
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.errors import UnsupportedByTarget
from support.compiling import (
    compile_fixture,
    extract_select,
    fixture_sources,
    load_fixture,
    resolve_dbt_references,
)

pytestmark = pytest.mark.property

FIXTURE_NAMES = [
    "ecom_basic",
    "minimal",
    "path_conflict",
    "role_playing_dates",
    "scd2_customers",
    "semi_additive_inventory",
]

DIALECTS = ["duckdb", "postgres", "trino"]


def compile_or_refusal(
    name: str, target: Target, dialect: str
) -> tuple[EmittedArtifact, ...] | str:
    """Artifacts, or the refusal message for a cell that cannot be emitted.

    Some (fixture × target × dialect) cells are *deliberately* unemittable:
    ``semi_additive_inventory`` carries the RFC 0016 quality surface, which
    dbt has no reject/replay lowering for (§5.4's target-coverage note) and
    which Postgres cannot express the coercion-failure marker for (§5.2 — it
    has no ``TRY_CAST``). Both refuse loudly rather than approximating
    (RFC 0008 D3), and the refusal is as much a compile output as the SQL is —
    so determinism has to cover it too.
    """
    try:
        return compile_fixture(name, target=target, dialect=dialect)
    except UnsupportedByTarget as refusal:
        return str(refusal)


CUBE_FIXTURES = [
    "ecom_basic",
    "non_additive_aov",
    "role_playing_dates",
    "semi_additive_inventory",
]


@settings(max_examples=20, deadline=None)
@given(
    name=st.sampled_from(FIXTURE_NAMES),
    target=st.sampled_from(list(Target)),
    dialect=st.sampled_from(DIALECTS),
)
def test_compile_twice_yields_identical_bytes(name: str, target: Target, dialect: str) -> None:
    first = compile_or_refusal(name, target, dialect)
    second = compile_or_refusal(name, target, dialect)
    assert first == second  # paths, contents, and checksums — full byte identity


def exp_keywords(content: str) -> set[str]:
    """The SQL statement keywords appearing in a file, for asserting that one
    contains no SQL at all."""
    return {word for word in ("SELECT", "FROM", "WHERE", "JOIN") if word in content.upper()}


def _sql_bodies(target: Target, content: str) -> list[str]:
    """Every SELECT in one emitted artifact — usually one, sometimes two.

    The reject model is the exception and the reason this returns a list: dbt
    has no ``when_matched``, so the incremental and first-run bodies are two
    **pre-rendered** SELECTs chosen by ``{% if is_incremental() %}``
    (RFC 0052 D2). Parsing only the first arm would leave the incremental one
    unchecked by this property, and it is already the branch a single
    ``dbt build`` never executes.
    """
    if target is Target.SQLMESH:
        return [extract_select(content)]
    # A dbt model is header + config, a blank line, then the SELECT; a
    # snapshot additionally wraps it in {% snapshot %} block markers.
    body = content.partition("\n\n")[2]
    if body.rstrip("\n").endswith("{% endsnapshot %}"):
        body = body.rpartition("\n\n")[0]

    if "{% if is_incremental() %}" in body:
        incremental, _, remainder = body.partition("{% if is_incremental() %}")[2].partition(
            "{% else %}"
        )
        arms = [incremental, remainder.partition("{% endif %}")[0]]
    else:
        arms = [body]

    # Since D20 a dbt body states its inputs as `ref()`/`source()`, so it is a
    # template rather than SQL. The property is about the SQL underneath, and
    # dropping dbt from it would be a coverage loss rather than a substitution.
    return [resolve_dbt_references(arm.strip()) for arm in arms]


def _replay_statements(content: str) -> list[str]:
    """The SQL out of a replay artifact, whichever target wrapped it.

    dbt's is a `run-operation` macro: each statement sits in its own
    `{% set statement_N %}…{% endset %}` block, because Jinja renders a
    block-set's body and leaves `{{ ref(...) }}` alone inside a quoted string
    (RFC 0052 §5.2). SQLMesh's is a commented file whose statements follow the
    header. Both reduce to the same list, so the property below reads one
    shape.
    """
    if "{% macro" in content:
        blocks = [
            # Since D20 a dbt body states its inputs as `ref()`, here as much
            # as in a model, so the references resolve before parsing for the
            # same reason `_sql_body` resolves them: the property is about the
            # SQL underneath the template.
            resolve_dbt_references(block.partition("%}")[2].partition("{% endset %}")[0])
            for block in content.split("{% set statement_")[1:]
        ]
        assert blocks, "a dbt replay macro with no statement blocks is an empty macro"
        return blocks

    return [content.partition("-- artifact and never")[2].partition("\n\n")[2]]


@settings(max_examples=30, deadline=None)
@given(
    name=st.sampled_from(FIXTURE_NAMES),
    target=st.sampled_from([Target.SQLMESH, Target.DBT]),
    dialect=st.sampled_from(DIALECTS),
)
def test_emitted_sql_parses_under_the_target_dialect(
    name: str, target: Target, dialect: str
) -> None:
    emitted = compile_or_refusal(name, target, dialect)
    if isinstance(emitted, str):
        return  # a deliberate refusal — there is no SQL to parse
    for artifact in emitted:
        if not artifact.path.endswith(".sql"):
            continue
        if artifact.kind is ArtifactKind.REPLAY:
            # The replay artifact is a statement script, not a SELECT
            # (RFC 0016 §5.6): the caller runs it, so what must hold is that
            # every statement parses under the dialect it was rendered for.
            #
            # The two targets wrap those statements differently — SQLMesh in a
            # commented file the operator runs, dbt in a `run-operation` macro
            # whose `{% set %}` blocks hold one statement each (RFC 0052 §5.2)
            # — so the wrapper is stripped per target and the *statements* are
            # what the property is asserted over, identically for both.
            statements = [
                node
                for body in _replay_statements(artifact.content)
                for node in parse(body, dialect=dialect)
                if node is not None
            ]
            assert statements
            assert all(isinstance(node, (exp.Merge, exp.Update)) for node in statements)
            continue
        if artifact.path == "macros/generate_schema_name.sql":
            # The one `.sql` bloomery emits that contains no SQL — it is a
            # Jinja macro returning a schema *name* (RFC 0008 D20). Asserted
            # rather than skipped, so "this file has no SQL to parse" stays a
            # claim the suite checks instead of a hole the exemption opens.
            assert not exp_keywords(artifact.content)
            continue
        if artifact.path.startswith("macros/"):
            # The dbt generic test (RFC 0008 D18) is a SELECT with two Jinja
            # holes rather than a whole query. Filling them keeps it inside the
            # property rather than exempt from it: this file *is* emitted SQL,
            # and skipping it would leave the one artifact whose body no golden
            # reads as SQL unchecked by anything.
            select = (
                artifact.content.partition("%}")[2]
                .partition("{% endtest %}")[0]
                .replace("{{ model }}", "silver.model")
                .replace("{{ expression }}", "1 = 1")
            )
            assert isinstance(parse_one(select, dialect=dialect), exp.Select)
            continue
        # Audit bodies select from SQLMesh's @this_model macro — substitute a
        # plain relation so the SELECT itself must still parse (RFC 0008 D4).
        # A ``fail``-rule audit is a **UNION** of its two populations — the
        # pre-route extract and the entity (RFC 0016 D67) — which is a query
        # like any other, and the property is that it parses as one.
        for body in _sql_bodies(target, artifact.content):
            select = body.replace("@this_model", "silver.model")
            parsed = parse_one(select, dialect=dialect)
            assert isinstance(parsed, (exp.Select, exp.Union))


@settings(max_examples=10, deadline=None)
@given(name=st.sampled_from(CUBE_FIXTURES))
def test_cube_yaml_round_trips_and_ignores_the_dialect(name: str) -> None:
    baseline = compile_fixture(name, target=Target.CUBE, dialect="duckdb")
    for artifact in baseline:
        document = yaml.safe_load(artifact.content)  # round-trips as YAML
        assert isinstance(document, dict)
        assert yaml.safe_load(artifact.content) == document
    for dialect in DIALECTS:
        # Cube YAML is dialect-independent (RFC 0008 §5.4): the dialect axis
        # must not reach the bytes.
        assert compile_fixture(name, target=Target.CUBE, dialect=dialect) == baseline


@settings(max_examples=10, deadline=None)
@given(order=st.permutations(sorted(fixture_sources("minimal"))))
def test_compile_is_invariant_under_source_insertion_order(order: list[str]) -> None:
    sources = fixture_sources("minimal")
    reordered = {name: sources[name] for name in order}
    baseline = compile_fixture("minimal")
    permuted = compile_project(load_project(reordered), target=Target.SQLMESH, dialect="duckdb")
    assert permuted == baseline


def test_minimal_select_columns_match_declared_fields_both_directions() -> None:
    project, _ = load_fixture("minimal")
    artifact = next(a for a in compile_fixture("minimal") if a.path.endswith(".sql"))
    parsed = parse_one(extract_select(artifact.content), dialect="duckdb")
    assert isinstance(parsed, exp.Select)
    emitted = {projection.alias_or_name for projection in parsed.expressions}
    # Every silver entity also carries the two generated quality columns
    # (RFC 0016 §5.5) — they are compiler-owned, reserved at spec parse, and
    # therefore never declared fields.
    declared = set(project.entity_model.entities["event"].fields) | {
        "_quality_flags",
        "_quality_ok",
    }
    assert emitted == declared
