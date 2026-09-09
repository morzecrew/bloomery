"""Rollup lowering and its refusals (RFC 0058 §5.2, P2).

The obligation itself is tested in `tests/unit/test_semantic/test_rollup.py`;
what is tested here is the *stage* — that a declared rollup reaches
`ProjectIR.rollups` when R013 discharges, that it reaches nothing when it does
not, and that the two declarations R013 never reads are refused rather than
silently dropped from an emitted aggregate.

The last of those is the one worth writing down. A `filter:` and a
`cumulative:` both sit on an `additive` metric, so both pass the class
question; a rollup builds one aggregate over the parent's rows, so both would
be dropped, and the column would hold a number that is not the metric it is
named after.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from support.compiling import load_fixture

from bloomery import build_project_ir, load_project
from bloomery.errors import GuardrailError, SpecParseError, UnprovableRollup
from bloomery.marts import lower_rollups

pytestmark = pytest.mark.unit

_SOURCES = {
    "entity_model": """\
spec_version: 1
entities:
  order_item:
    grain: one row per line
    key: [order_id, line_no]
    fields:
      order_id: {type: string, required: true}
      line_no: {type: int, required: true}
      amount: {type: "decimal(12,2)"}
      buyer_id: {type: string}
      status: {type: string}
      order_date: {type: date}
""",
    "mapping_items": """\
mapping_version: 1
source: src__items
target: order_item
key:
  order_id: {from: "$.oid", transform: [to_string]}
  line_no: {from: "$.line", transform: [to_int]}
fields:
  amount: {from: "$.amount"}
  buyer_id: {from: "$.buyer", transform: [to_string]}
  status: {from: "$.status", transform: [to_string]}
  order_date: {from: "$.od", transform: [{parse_date: ISO8601}]}
""",
    "metrics": """\
metrics_version: 1
metrics:
  revenue:
    grain: order_item
    additivity: additive
    agg: sum
    expr: "amount"
  buyers:
    grain: order_item
    additivity: distinct_count
    agg: count_distinct
    expr: "buyer_id"
  paid_revenue:
    grain: order_item
    additivity: additive
    agg: sum
    expr: "amount"
    filter:
      - {dimension: status, op: eq, values: [paid]}
  running_revenue:
    grain: order_item
    additivity: additive
    agg: sum
    expr: "amount"
    cumulative: {grain_to_date: month}
""",
}

_MART = """\
marts_version: 1
marts:
  items:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: ordered}
    measures: [{measures}]
{rollups}"""


def _lowering(*, measures: str, rollups: str) -> object:
    """Lower the rollups against a draft that already carries the marts.

    A rollup names a mart, and R013's premise is the mart contract, so the
    parent has to be a resolved `MartIR` before the obligation can be asked —
    which is why the draft here is built from the marts document too, and not
    from the entity sources alone the way `lower_marts`' own tests can.
    """

    declared = _MART.replace("{measures}", measures)
    project = load_project({**_SOURCES, "marts": declared.replace("{rollups}", rollups)})
    assert project.marts is not None
    # The draft is built from the same document with its rollups removed. It
    # has to carry the marts — R013's premise is the mart contract — and it
    # must not carry the rollups, because `build_project_ir` runs the guardrail
    # stage and an unprovable one would refuse before this function returned
    # anything to look at.
    draft = build_project_ir(load_project({**_SOURCES, "marts": declared.replace("{rollups}", "")}))

    return lower_rollups(project.marts, draft)


def _rollup(of: str = "items", keep: str = "ordered_month", measures: str = "revenue") -> str:
    return f"rollups:\n  monthly:\n    of: {of}\n    keep: [{keep}]\n    measures: [{measures}]\n"


# ....................... #
# What discharges


def test_a_provable_rollup_reaches_the_ir() -> None:
    lowering = _lowering(measures="revenue", rollups=_rollup())

    assert lowering.violations == ()
    assert [rollup.name for rollup in lowering.rollups] == ["monthly"]
    assert lowering.rollups[0].of == "items"
    assert lowering.rollups[0].keep == ("ordered_month",)


def test_the_kept_columns_are_canonical() -> None:
    """Sorted and deduplicated on the node, so the projection and the GROUP BY
    the emitter builds from it cannot disagree about their order."""

    lowering = _lowering(measures="revenue", rollups=_rollup(keep="ordered_year, ordered_month"))

    assert lowering.rollups[0].keep == ("ordered_month", "ordered_year")


def test_a_rollup_may_take_the_provable_subset_of_a_marts_measures() -> None:
    """The reason `measures:` is declarable on a rollup at all.

    `items` carries `buyers`, which no rollup may re-aggregate. Asking the
    obligation about the *parent's* measure list would refuse every rollup of
    that mart, including one carrying only `revenue` — a mart with one distinct
    count would have no provable rollup, however much of it is additive. The
    obligation is put with the measures the rollup carries (§5.2), and the
    check that they are the parent's is separate.
    """

    lowering = _lowering(measures="buyers, revenue", rollups=_rollup(measures="revenue"))

    assert lowering.violations == ()
    assert [rollup.measures for rollup in lowering.rollups] == [("revenue",)]


def test_a_project_with_no_rollups_lowers_to_nothing() -> None:
    lowering = _lowering(measures="revenue", rollups="")

    assert lowering.rollups == ()
    assert lowering.violations == ()


# ....................... #
# What R013 refuses


def test_a_distinct_count_measure_refuses_the_rollup() -> None:
    """Summing per-group distinct counts double-counts an identity present in
    two groups, which is what the word exists to stop (RFC 0038 §4)."""

    lowering = _lowering(measures="revenue, buyers", rollups=_rollup(measures="buyers"))

    assert lowering.rollups == ()
    assert [type(v).__name__ for v in lowering.violations] == ["UnprovableRollup"]
    assert "distinct_count_not_reaggregable" in lowering.violations[0].args[0]
    assert lowering.violations[0].source_path == "marts: marts.monthly"


def test_a_measure_the_parent_does_not_carry_refuses_the_rollup() -> None:
    """Asked here rather than left to R013: the obligation is put with the
    rollup's own measure list, so it would find every one of them carried."""

    lowering = _lowering(measures="revenue", rollups=_rollup(measures="buyers"))

    assert lowering.rollups == ()
    assert isinstance(lowering.violations[0], UnprovableRollup)
    assert "which mart 'items' does not" in lowering.violations[0].args[0]


@pytest.mark.parametrize(
    ("measure", "dropped"),
    [("paid_revenue", "a filter:"), ("running_revenue", "a cumulative:")],
)
def test_a_declaration_the_aggregate_would_drop_refuses_the_rollup(
    measure: str, dropped: str
) -> None:
    """Both are `additive`, so both pass the class question. What refuses them
    is that a rollup builds one aggregate over the parent's rows and neither
    declaration survives it."""

    lowering = _lowering(measures=f"revenue, {measure}", rollups=_rollup(measures=measure))

    assert lowering.rollups == ()
    assert isinstance(lowering.violations[0], UnprovableRollup)
    assert dropped in lowering.violations[0].args[0]
    assert lowering.violations[0].source_path == "marts: marts.monthly.measures"


# ....................... #
# What the spec layer refuses, before a stage sees it


@pytest.mark.parametrize(
    ("rollups", "expected"),
    [
        (_rollup(of="ghost"), "which this document does not declare as a mart"),
        (_rollup(keep="ordered_month, ordered_month"), "repeats a keep: column"),
        ("rollups:\n  items:\n    of: items\n    keep: [ordered_month]\n", "takes the name of a mart"),
    ],
)
def test_the_document_refuses_what_it_can_answer_alone(rollups: str, expected: str) -> None:
    """A parent this document does not declare, a grouping level stated twice,
    and a rollup taking a mart's name are all answerable from the marts
    document, which is what the spec layer is for. The name collision is the
    one with teeth: both are relations of the gold layer, so the two would
    build one table."""

    with pytest.raises(SpecParseError) as excinfo:
        load_project({**_SOURCES, "marts": _MART.replace("{measures}", "revenue").replace("{rollups}", rollups)})

    assert expected in str(excinfo.value)


# ....................... #
# The stage refuses, and the pipeline stops


def test_an_unprovable_rollup_refuses_the_project() -> None:
    """D5 (`LOCKED`): refused, never warned about. A rollup is read instead of
    the detail table, so a wrong one answers quickly and plausibly."""

    project = load_project(
        {
            **_SOURCES,
            "marts": _MART.replace("{measures}", "revenue, buyers").replace(
                "{rollups}", _rollup(measures="buyers")
            ),
        }
    )

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(project)

    assert [type(leaf) for leaf in excinfo.value.collected] == [UnprovableRollup]
    assert "is not provable" in str(excinfo.value)


def test_a_provable_rollup_compiles_and_lands_on_the_ir() -> None:
    project, catalog = load_fixture("rollup_mart")
    ir = build_project_ir(project, catalog)

    assert [rollup.name for rollup in ir.rollups] == ["order_items_monthly"]
    assert [mart.name for mart in ir.marts] == ["order_items"]


def test_a_rollup_of_a_mart_that_did_not_lower_is_skipped_in_silence() -> None:
    """The parent's own violation is the actionable one.

    The spec layer already refuses an `of:` naming a mart this document does
    not declare, so the only way to reach a missing parent is one that failed
    to lower. A second leaf saying the rollup could not be checked would send
    an author to the rollup, which is not where the fix is.
    """

    broken = _MART.replace("{measures}", "revenue").replace(
        "measures: [revenue]", "measures: [revenue]\n    partition_by: [days(nope)]"
    )
    project = load_project({**_SOURCES, "marts": broken.replace("{rollups}", _rollup())})
    assert project.marts is not None
    draft = build_project_ir(
        load_project({**_SOURCES, "marts": _MART.replace("{measures}", "revenue").replace("{rollups}", "")})
    )
    lowering = lower_rollups(project.marts, replace(draft, marts=()))

    assert lowering.rollups == ()
    assert lowering.violations == ()
