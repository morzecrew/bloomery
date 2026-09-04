"""Aggregate assertions over a mart (RFC 0016 §10 → D89).

§10 asked whether mart-level rules were reconcile-shaped or a new surface. They
are **neither**, and the disposition model is what decides it: a quality rule
disposes of a row, and a mart row is derived — no source identity, no reject
table, no replay — so there is nothing to quarantine, repair or bring back.
What is left is D4's other half, "alert me", which is an audit.

The bodies are executed here rather than only rendered. Two shapes have to hold
on every engine: a grouped ``HAVING`` and a bare one with no ``GROUP BY`` at
all. Both were run against DuckDB (below), postgres 16 and
``trinodb/trino:483``, and all three agree — including on the case that decides
the semantics, an empty group.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import duckdb
import pytest
from support.compiling import compile_fixture, load_fixture

from bloomery import Target, compile_project, load_project
from bloomery.emit import ArtifactKind
from bloomery.errors import GuardrailError, SpecParseError, UnsupportedByTarget
from bloomery.resolve import build_project_ir

pytestmark = pytest.mark.unit

FIXTURE = "quality_precedence"
MART = "lines"
BLOCKING = "lines_amount_positive_every_month"
NON_BLOCKING = "lines_rows_present"

ENTITY_MODEL = """
spec_version: 1
entities:
  order_item:
    grain: one row per order line
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      quantity: {type: int}
      order_date: {type: timestamp}
"""

MAPPING = """
mapping_version: 1
target: order_item
source: shop__lines
key:
  order_id: {from: "$.order_id"}
fields:
  quantity: {from: "$.quantity", transform: [to_int]}
  order_date:
    from: "$.order_date"
    transform: [{parse_ts: ISO8601}]
"""


def marts(clause: str) -> str:
    return (
        "marts_version: 1\nmarts:\n  lines:\n    grain: order_item\n"
        "    base: order_item\n    flatten:\n"
        "      - {date: order_date, role: ordered}\n"
        f"    assert:\n{clause}"
    )


def build(clause: str) -> object:
    project = load_project(
        {"entity_model": ENTITY_MODEL, "mapping": MAPPING, "marts": marts(clause)}
    )
    return build_project_ir(project)


GOOD = (
    "      - {name: q_positive, measure: quantity, agg: sum, by: [ordered_month], "
    "min: 1, on_fail: fail}\n"
)


# ....................... #
# What the surface refuses


def test_an_assertion_with_no_bound_is_refused() -> None:
    """A bound is the assertion. Without one the clause names an aggregate and
    says nothing about it."""
    with pytest.raises(SpecParseError, match="at least one of min / max"):
        build("      - {name: q, measure: quantity, agg: sum, on_fail: flag}\n")


@pytest.mark.parametrize("disposition", ["quarantine", "repair"])
def test_a_row_routing_disposition_is_refused(disposition: str) -> None:
    """The decision, enforced at the surface: a mart row has nothing to route.
    Refused rather than lowered to something weaker, so an author who wanted
    quarantine learns that here instead of from a mart that silently only
    alerts."""
    with pytest.raises(SpecParseError):
        build(
            f"      - {{name: q, measure: quantity, agg: sum, min: 1, on_fail: {disposition}}}\n"
        )


def test_a_repeated_grouping_column_is_refused() -> None:
    with pytest.raises(SpecParseError, match="repeats a by: column"):
        build(
            "      - {name: q, measure: quantity, agg: sum, "
            "by: [ordered_month, ordered_month], min: 1, on_fail: flag}\n"
        )


@pytest.mark.parametrize("clause", ["measure: nosuch, agg: sum", "measure: quantity, agg: nosuch"])
def test_an_unknown_measure_or_aggregate_is_refused(clause: str) -> None:
    with pytest.raises((SpecParseError, GuardrailError)):
        build(f"      - {{name: q, {clause}, min: 1, on_fail: flag}}\n")


def test_a_grouping_column_the_mart_does_not_carry_is_refused() -> None:
    """Resolved against the **flattened** column set, not the base entity's:
    ``ordered_month`` is a legitimate grouping column that exists only because
    a ``date:`` step made it, and it is exactly the column §10's example groups
    by. ``ordered_fortnight`` is not one."""
    with pytest.raises(GuardrailError, match="names by column 'ordered_fortnight'"):
        build(
            "      - {name: q, measure: quantity, agg: sum, "
            "by: [ordered_month, ordered_fortnight], min: 1, on_fail: flag}\n"
        )


def test_two_assertions_of_one_name_are_refused() -> None:
    """The name is the audit's identity and its artifact path, so the second
    would overwrite the first."""
    with pytest.raises(GuardrailError, match="named 'q_positive'"):
        build(GOOD + GOOD)


# ....................... #
# What it emits


def _audits() -> dict[str, str]:
    return {
        artifact.path.removeprefix("audits/").removesuffix(".sql"): artifact.content
        for artifact in compile_fixture(FIXTURE)
        if artifact.kind is ArtifactKind.AUDIT
    }


def test_each_assertion_becomes_an_audit_the_mart_model_names() -> None:
    """A bare ``AUDIT`` block loads as a *model* audit and runs only where a
    model's ``audits`` names it — so an assertion emitted as an artifact and
    left unreferenced would ship as a file nothing ever executes."""
    model = next(
        artifact.content
        for artifact in compile_fixture(FIXTURE)
        if artifact.path.endswith(f"mart_{MART}.sql")
    )
    assert f"audits ({BLOCKING}, {NON_BLOCKING})" in model
    assert {BLOCKING, NON_BLOCKING} <= set(_audits())


def test_the_clause_decides_whether_the_run_stops() -> None:
    """The same two readings ``reconcile.on_fail`` carries (D38): SQLMesh
    audits block unless told otherwise, so the blocking form says nothing and
    the other says ``blocking false``."""
    audits = _audits()
    assert "blocking false" not in audits[BLOCKING]
    assert "blocking false" in audits[NON_BLOCKING]


def test_the_bound_is_a_literal_of_the_aggregates_own_type() -> None:
    """``amount`` is ``decimal(38,9)``, so its bound is a number rather than a
    string the engine has to coerce — the reason ``_bound_literal`` is typed at
    all. ``count`` answers in rows however the column is typed, which is why
    the type comes from the *aggregate* and not from the column alone."""
    assert "< 0.000000001" in _audits()[BLOCKING]
    assert "< 1" in _audits()[NON_BLOCKING]


def test_dbt_emits_each_assertion_as_a_singular_test() -> None:
    """RFC 0026: the refusal was about the *artifact*, not the assertion.

    "dbt's schema tests are per-column or per-model predicates, and there is no
    grouped form to approximate it with" was true and incomplete — a singular
    test has no shape constraint at all, and an assertion over a grouped
    aggregate is exactly what it is for.

    Blocking-ness is the clause's own, as on SQLMesh, and the two are asserted
    separately because one proves nothing about the other.
    """
    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "mapping": MAPPING,
            "marts": marts(
                GOOD
                + "      - {name: q_present, measure: quantity, agg: count, "
                "min: 1, on_fail: flag}\n"
            ),
        }
    )
    artifacts = compile_project(project, target=Target.DBT, dialect="duckdb")
    tests = {a.path: a for a in artifacts if a.path.startswith("tests/")}
    assert set(tests) == {"tests/lines_q_positive.sql", "tests/lines_q_present.sql"}
    assert "{{ config(severity='error') }}" in tests["tests/lines_q_positive.sql"].content
    assert "{{ config(severity='warn') }}" in tests["tests/lines_q_present.sql"].content
    # The mart is reached by reference, which is what orders the test after it.
    assert "{{ ref('mart_lines') }}" in tests["tests/lines_q_positive.sql"].content
    # The grouped shape the refusal said had no home, intact.
    assert "GROUP BY" in tests["tests/lines_q_positive.sql"].content


def test_the_fixture_that_used_to_refuse_now_carries_both_kinds_of_check() -> None:
    """``quality_precedence`` refused on dbt for its ``reconcile:`` block, then
    for its ``quarantine:`` policy, and this test pinned *which* refusal it met
    so a later reader would not read it as the mart assertion's.

    Neither refusal exists after RFC 0052, so the thing worth pinning is what
    replaced them: the mart assertion's own singular test and the reconcile
    check's, side by side. They are separate artifacts for separate reasons,
    and one silently absorbing the other is the confusion the old assertion
    guarded against.
    """
    project, catalog = load_fixture(FIXTURE)
    paths = {
        a.path
        for a in compile_project(project, target=Target.DBT, dialect="duckdb", catalog=catalog)
    }
    assert f"tests/{BLOCKING}.sql" in paths
    assert f"tests/{NON_BLOCKING}.sql" in paths
    assert "models/silver/line_amount_matches_row__reconcile.sql" in paths
    assert "tests/line_amount_matches_row_reconcile.sql" in paths


def test_cube_is_not_asked_about_a_check_it_never_emits() -> None:
    """Cube builds nothing (RFC 0017 D52). It writes no silver model, no reject
    table and no audit for *anything*, so refusing this one check would single
    it out among the many this emitter already leaves to whoever maintains the
    tables — while a project full of quality rules compiles to cubes and views
    without a murmur."""
    project, catalog = load_fixture(FIXTURE)
    artifacts = compile_project(project, target=Target.CUBE, dialect="duckdb", catalog=catalog)
    assert artifacts
    assert not [a for a in artifacts if a.kind is ArtifactKind.AUDIT]


# ....................... #
# What the audit body does, executed


@pytest.fixture
def mart() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE m (ordered_month DATE, amount DECIMAL(38, 9))")
    connection.executemany(
        "INSERT INTO m VALUES (?, ?)",
        [
            ("2026-01-01", "4.0"),
            ("2026-01-01", "3.0"),
            # February nets to zero: every row is real, and the *total* is what
            # is wrong — the shape no per-row rule can see.
            ("2026-02-01", "5.0"),
            ("2026-02-01", "-5.0"),
        ],
    )
    return connection


def _body(connection: duckdb.DuckDBPyConnection, name: str) -> list[tuple[object, ...]]:
    body = _audits()[name].partition(");")[2].strip().replace("@this_model", "m")
    return connection.execute(body).fetchall()


def test_the_audit_reports_the_offending_group_and_its_value(
    mart: duckdb.DuckDBPyConnection,
) -> None:
    """An audit passes when it returns no rows, so the rows it *does* return
    are the report — and they carry the value beside the group, because a
    failure a human has to open the warehouse to understand gets ignored."""
    assert _body(mart, BLOCKING) == [(datetime.date(2026, 2, 1), Decimal("0E-9"))]


def test_a_group_within_bounds_is_not_reported(mart: duckdb.DuckDBPyConnection) -> None:
    reported = {row[0] for row in _body(mart, BLOCKING)}
    assert datetime.date(2026, 1, 1) not in reported


def test_the_whole_mart_form_needs_no_grouping(mart: duckdb.DuckDBPyConnection) -> None:
    """An empty ``by`` is one group over the table, which lowers to a bare
    ``HAVING``. Legal on all three shipped dialects — verified by running it on
    each rather than by reading three manuals."""
    assert _body(mart, NON_BLOCKING) == []


def test_an_empty_mart_is_where_the_two_aggregates_part_company(
    mart: duckdb.DuckDBPyConnection,
) -> None:
    """D19 reaching the mart, and the one place it is *not* the whole story.

    ``SUM`` over an empty group is NULL, so the bound comparison is ``UNKNOWN``
    and the grouped assertion stays silent — which is also why an assertion
    cannot see a month that is entirely *missing*: no row means no group at
    all. ``COUNT`` is the exception: it answers 0 rather than NULL, so a
    ``count``-based assertion is the one shape that *can* notice an empty mart,
    and this fixture declares one for exactly that reason.
    """
    mart.execute("DELETE FROM m")
    assert _body(mart, BLOCKING) == []
    assert _body(mart, NON_BLOCKING) == [(0,)]
