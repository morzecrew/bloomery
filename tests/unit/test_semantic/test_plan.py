"""The semantic plan (RFC 0040 §4, §8).

§8 asks for each phase's accepted shapes and each phase's refused shapes; the
parity suite in `tests/unit/test_planner/test_parity.py` carries the third and
load-bearing one. What is here is the plan value itself — its shape, its
authorization rule, and the determinism it inherits from the proofs it holds.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from bloomery import MetricRequest
from bloomery.semantic import (
    Aggregate,
    Filter,
    Project,
    Proof,
    Scan,
    SemanticJudgement,
    SemanticPlan,
)
from support.planning import fixture_ir, make_planner

pytestmark = pytest.mark.unit


def _plan(fixture: str, metric: str, dimensions: tuple[str, ...] = ()) -> SemanticPlan:
    planner = make_planner()
    query = planner.plan(
        fixture_ir(fixture),
        MetricRequest(metrics=(metric,), dimensions=dimensions),
        dialect="duckdb",
    )
    assert query.semantic is not None

    return query.semantic


# ----------------------- #
# Accepted shapes


def test_a_planned_request_carries_its_plan() -> None:
    """D7 closed as "beside": `QueryPlan` keeps everything it printed before
    and gains the plan, so nothing that reads it today reads differently."""
    plan = _plan("ecom_basic", "gross_revenue", ("order_date",))

    assert plan.shape == ("scan", "filter", "aggregate", "project")


def test_the_plan_names_the_mart_and_its_grain() -> None:
    plan = _plan("ecom_basic", "gross_revenue")
    scan = plan.nodes[0]

    assert isinstance(scan, Scan)
    assert (scan.relation, scan.grain) == ("order_items", "order_item")


def test_the_aggregate_stays_inside_the_mart_at_p1() -> None:
    """P1 plans within one pre-joined mart, so nothing is rolled *between*
    grains — input and output are the mart's own. An aggregate that claimed a
    coarser output grain here would be asserting a cross-entity rollup this
    phase never checked (logs/T-0021.md, D-116)."""
    plan = _plan("ecom_basic", "gross_revenue", ("order_date",))
    (aggregate,) = [node for node in plan.nodes if isinstance(node, Aggregate)]

    assert aggregate.input_grain == aggregate.output_grain == "order_item"
    assert aggregate.measures == ("gross_revenue",)
    assert aggregate.dimensions == ("order_date",)


def test_the_aggregate_cites_the_mart_contract() -> None:
    """R008, and not a grain rule. What authorizes a P1 aggregate is that a
    mart may embed a measure only at its own grain — checked when the project
    compiled — rather than any claim about reaching one entity from another."""
    plan = _plan("ecom_basic", "gross_revenue")
    (proof,) = plan.proofs

    assert proof.rule == "R008"
    assert proof.closed
    assert "mart:order_items.gross_revenue" in {fact.source for fact in proof.leaves}


def test_a_measure_is_one_fact_each_not_one_for_the_mart() -> None:
    """The mart contract is per-measure: two measures on one mart are two
    separate claims that each originates there, and a single fact naming the
    mart would let one of them be wrong without the proof's leaves changing.

    Found by sabotage — reducing the facts to the first measure failed nothing,
    because every other test here asks for one metric.
    """
    planner = make_planner()
    query = planner.plan(
        fixture_ir("quality_precedence"),
        MetricRequest(metrics=("quality_rows_deduped", "quality_rows_evaluated")),
        dialect="duckdb",
    )
    assert query.semantic is not None
    (proof,) = query.semantic.proofs

    assert {fact.source for fact in proof.leaves} == {
        "mart:data_quality.quality_rows_deduped",
        "mart:data_quality.quality_rows_evaluated",
    }


def test_a_measureless_request_still_projects_its_dimensions() -> None:
    """Grouping with no dimensions is a total, and the plan says so rather than
    omitting the node — a reader asking what the shape was gets four nodes for
    every request."""
    plan = _plan("ecom_basic", "gross_revenue")
    (project,) = [node for node in plan.nodes if isinstance(node, Project)]

    assert project.columns == ("gross_revenue",)


def test_the_projection_keeps_request_order_not_sorted_order() -> None:
    """A result's column order is part of the answer. Everything else in this
    package canonicalizes; this deliberately does not."""
    plan = _plan("scd2_as_of", "revenue", ("order_date", "customer_segment"))
    (project,) = [node for node in plan.nodes if isinstance(node, Project)]

    assert project.columns == ("order_date", "customer_segment", "revenue")


def test_the_plans_filters_are_the_explanations_filters() -> None:
    """One account of a request, not two. RFC 0039 §7 refuses a second
    explanation surface reconstructed separately, and a plan that rendered its
    own predicates would be exactly that."""
    planner = make_planner()
    query = planner.plan(
        fixture_ir("ecom_basic"),
        MetricRequest(metrics=("gross_revenue",)),
        dialect="duckdb",
    )
    assert query.semantic is not None
    (filter_node,) = [node for node in query.semantic.nodes if isinstance(node, Filter)]

    assert filter_node.predicates == query.explanation.filters


# ----------------------- #
# The authorization rule (D2)


@dataclass(frozen=True, slots=True)
class _Multiplying:
    """A node that duplicates rows, which no P1 node type does.

    D2's check cannot be reached by any plan this phase builds — a mart is
    pre-joined and an aggregate reduces — so without a stand-in the rule is a
    detection branch that has never run, trusted at P2 on the strength of never
    having been exercised. This is the smallest thing that reaches it.
    """

    proof: Proof | None = None

    @property
    def multiplies(self) -> bool:
        return True

    def document(self) -> dict[str, object]:
        return {"node": "multiplying"}

    def render(self) -> str:
        return "Multiplying()"


def test_a_multiplying_node_without_a_proof_is_invalid_ir() -> None:
    """D2: not merely unexplained. The distinction decides whether the check
    can be skipped under time pressure, so it raises on construction rather
    than offering itself to a caller who has to remember to ask."""
    with pytest.raises(ValueError, match="no proof"):
        SemanticPlan((_Multiplying(),))  # type: ignore[arg-type]


def test_a_multiplying_node_with_a_proof_is_accepted() -> None:
    """The control. Without it the rule above would pass for a check that
    refused every plan containing the stand-in, proof or not."""
    authorized = _Multiplying(
        proof=Proof(rule="R002", conclusion=SemanticJudgement("Determines"))
    )

    assert SemanticPlan((authorized,)).nodes  # type: ignore[arg-type]


def test_no_node_type_this_phase_ships_can_multiply() -> None:
    """The claim the docstrings make, asserted rather than promised — and the
    canary for P2. Adding `PreservingJoin` makes this fail, which is where
    someone has to decide what authorizes it rather than inheriting a rule
    written for nodes that never needed one."""
    nodes = (
        Scan(relation="m", grain="g"),
        Filter(predicates=("x > 1",)),
        Aggregate(input_grain="g", output_grain="g", measures=("m",)),
        Project(columns=("a",)),
    )

    assert not any(node.multiplies for node in nodes)


# ----------------------- #
# Determinism (RFC 0003, carried from the proofs)


def test_a_plan_serializes_identically_for_one_request() -> None:
    left = _plan("ecom_basic", "gross_revenue", ("order_date",))
    right = _plan("ecom_basic", "gross_revenue", ("order_date",))

    assert left.serialize() == right.serialize()


def test_serialization_carries_nothing_process_varying() -> None:
    encoded = _plan("ecom_basic", "gross_revenue", ("order_date",)).serialize()

    assert "0x" not in encoded
    assert "object at" not in encoded


def test_measures_and_dimensions_are_canonical_on_an_aggregate() -> None:
    """Node *order* is the plan's meaning and is never sorted; the collections
    inside a node are, so two aggregates over the same set compare equal."""
    forward = Aggregate(
        input_grain="g", output_grain="g", measures=("b", "a"), dimensions=("d", "c")
    )

    assert forward.measures == ("a", "b")
    assert forward.dimensions == ("c", "d")


def test_node_order_is_never_sorted() -> None:
    """The one thing in this package that must not be canonicalized: a plan is
    a pipeline, and sorting it would reorder the computation."""
    plan = SemanticPlan(
        (
            Project(columns=("a",)),
            Scan(relation="m", grain="g"),
        )
    )

    assert plan.shape == ("project", "scan")
