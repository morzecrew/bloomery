"""The semantic plan (RFC 0040 §4, §8).

§8 asks for each phase's accepted shapes and each phase's refused shapes; the
parity suite in `tests/unit/test_planner/test_parity.py` carries the third and
load-bearing one. What is here is the plan value itself — its shape, its
authorization rule, and the determinism it inherits from the proofs it holds.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from dataclasses import dataclass

import bloomery
import pytest
from bloomery.ir import Additivity, MetricFilterIR
from bloomery import MetricRequest
from bloomery.planner.policy import RowPolicy
from bloomery.planner.request import Op, Predicate
from bloomery.semantic import (
    Aggregate,
    Filter,
    Project,
    Proof,
    Provenance,
    Scan,
    SemanticFact,
    SemanticJudgement,
    SemanticPlan,
)
from bloomery.planner.semantic_plan import _plannable
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


def test_restrictions_compare_as_sets_not_as_written() -> None:
    """The clauses are ANDed, so two metrics restricted by the same clauses in
    different authored order are restricted identically — and
    `resolve.build._metric_filters` keeps authored order deliberately, since it
    is cosmetic in SQL and load-bearing in the artifact bytes. Comparing the
    tuples would refuse a plan those four nodes can state perfectly.
    """
    ir = fixture_ir("period_over_period")
    metrics = {metric.name: metric for metric in ir.metrics}
    original = metrics["large_recent_revenue"]
    assert len(original.filter) == 2, "the fixture stopped carrying two clauses"

    reversed_clauses = dataclasses.replace(
        original, name="reordered", filter=tuple(reversed(original.filter))
    )
    (mart,) = [candidate for candidate in ir.marts if original.name in candidate.measures]
    widened = dataclasses.replace(mart, measures=(*mart.measures, "reordered"))
    request = MetricRequest(metrics=(original.name, "reordered"))

    assert _plannable(request, widened, {**metrics, "reordered": reversed_clauses})


def _restricted(ir: object, name: str, values: tuple[object, ...]) -> object:
    """A copy of `revenue` restricted to `status in values`, under a new name."""
    metrics = {metric.name: metric for metric in ir.metrics}  # type: ignore[attr-defined]

    return dataclasses.replace(
        metrics["revenue"],
        name=name,
        filter=(MetricFilterIR(dimension="status", op="in", values=values),),
    )


def _plannable_pair(ir: object, left: object, right: object) -> bool:
    metrics = {metric.name: metric for metric in ir.metrics}  # type: ignore[attr-defined]
    (mart,) = [
        candidate
        for candidate in ir.marts  # type: ignore[attr-defined]
        if "revenue" in candidate.measures
    ]
    widened = dataclasses.replace(mart, measures=(*mart.measures, "left", "right"))

    return _plannable(
        MetricRequest(metrics=("left", "right")),
        widened,
        {**metrics, "left": left, "right": right},
    )


def test_membership_values_compare_as_a_set_of_rows_admitted() -> None:
    """The same argument one level down, and one more level after that: no
    operator in the vocabulary reads its values positionally, and a repeated
    member admits no extra row. So the three spellings below are one
    restriction. Authored value order is kept in the IR for the same reason
    clause order is, and means nothing here."""
    ir = fixture_ir("period_over_period")
    members = ("paid", "refunded")
    left = _restricted(ir, "left", members)

    assert _plannable_pair(ir, left, _restricted(ir, "right", tuple(reversed(members))))
    assert _plannable_pair(ir, left, _restricted(ir, "right", ("paid", "paid", "refunded")))


def test_a_literal_of_another_type_is_another_restriction() -> None:
    """Sets of the values, not of their text. `1` and `"1"` admit different
    rows, and canonicalizing through `str` flattened them onto one key —
    leaving this comparison to rely on the filter-type guardrail two layers
    away to keep them apart, which is not this function's to assume.
    """
    ir = fixture_ir("period_over_period")

    assert not _plannable_pair(
        ir, _restricted(ir, "left", (1,)), _restricted(ir, "right", ("1",))
    )


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


def _filters(query: object) -> tuple[str, ...]:
    (node,) = [n for n in query.semantic.nodes if isinstance(n, Filter)]  # type: ignore[attr-defined]

    return node.predicates


def test_the_plans_filters_are_the_explanations_filters_in_request_order() -> None:
    """One account of a request, not two. RFC 0039 §7 refuses a second
    explanation surface reconstructed separately, and a plan that rendered its
    own predicates — or ordered them differently — would be exactly that.

    Two filters, deliberately not in sorted order. The single-filter and
    no-filter cases agree with the explanation no matter what either side
    does, which is how a `Filter` that sorted its predicates while the
    explanation kept request order shipped with a test asserting the two were
    equal.
    """
    planner = make_planner()
    query = planner.plan(
        fixture_ir("ecom_basic"),
        MetricRequest(
            metrics=("gross_revenue",),
            filters=(
                Predicate(dimension="quantity", op=Op.GTE, values=(2,)),
                Predicate(dimension="line_no", op=Op.EQ, values=(1,)),
            ),
        ),
        dialect="duckdb",
    )

    assert query.explanation.filters == ("quantity >= 2", "line_no = 1")
    assert _filters(query) == query.explanation.filters


def test_the_plan_names_the_row_policy_the_explanation_only_counts() -> None:
    """The `Explanation` reports a policy as a boolean, because rendering the
    scoping value into a provenance block shown to the requester would
    disclose it (RFC 0013 D9). A plan is lowered rather than shown, and one
    that inherited that omission would be lowered into a broader answer than
    the SQL beside it.
    """
    planner = make_planner()
    query = planner.plan(
        fixture_ir("ecom_basic"),
        MetricRequest(metrics=("gross_revenue",)),
        dialect="duckdb",
        policy=RowPolicy(dimension="order_customer_id", op=Op.EQ, value="c1"),
    )

    assert query.explanation.filters == ()
    assert query.explanation.policy_applied
    assert _filters(query) == ("order_customer_id = 'c1'",)
    assert "c1" in query.sql


def test_the_plan_names_a_metrics_own_restriction() -> None:
    """A filtered metric restricts rows exactly as a request filter does — the
    explanation carries it on that measure's note rather than in `filters`, and
    a plan reading only `filters` would compute the unfiltered sibling.

    Also the control for the mixed-restriction rule below: what that rule
    refuses is metrics restricted *differently*, not filtered metrics, and
    returning `None` for every filtered request would satisfy it otherwise.
    """
    planner = make_planner()
    query = planner.plan(
        fixture_ir("period_over_period"),
        MetricRequest(metrics=("paid_revenue",)),
        dialect="duckdb",
    )
    assert query.semantic is not None

    assert _filters(query) == ("status = 'paid'",)


def test_a_cumulative_metric_gets_no_plan() -> None:
    """`revenue_trailing_7d` *is* a mart measure, so the guard written for the
    derived case let it through — and the plan read as a plain sum per day
    with the seven-day window and `period_agg` nowhere in it. The shapes P1
    cannot express outnumber the one it can, which is why the rule is stated
    positively rather than as a list of exclusions.
    """
    planner = make_planner()
    ir = fixture_ir("period_over_period")
    query = planner.plan(
        ir,
        MetricRequest(metrics=("revenue_trailing_7d",), dimensions=("day",)),
        dialect="duckdb",
    )

    assert query.semantic is None
    assert "revenue_trailing_7d" in {
        measure for mart in ir.marts for measure in mart.measures
    }


def test_a_semi_additive_metric_gets_no_plan() -> None:
    """`stock_on_hand` is lowered as a last-per-day pick joined back and then
    summed. `Aggregate` names a rollup and no aggregation with it, so the plan
    said the one operation this measure is not — the third shape a guard
    written per counterexample let through, and the reason the rule now names
    a property (additivity) instead.
    """
    planner = make_planner()
    ir = fixture_ir("semi_additive_inventory")
    query = planner.plan(
        ir, MetricRequest(metrics=("stock_on_hand",), dimensions=("day",)), dialect="duckdb"
    )

    assert query.semantic is None
    assert "stock_on_hand" in {measure for mart in ir.marts for measure in mart.measures}


def test_metrics_with_different_restrictions_get_no_plan() -> None:
    """`Filter` is a node over the scan, so it says one thing about every
    measure beneath it. A metric's own filter narrows that measure alone —
    pairing `paid_revenue` with `revenue` produced a plan restricting both to
    `status = 'paid'`, which is the previous defect's mirror image: a plan
    claiming a narrower answer than the query computes.
    """
    planner = make_planner()
    query = planner.plan(
        fixture_ir("period_over_period"),
        MetricRequest(metrics=("paid_revenue", "revenue")),
        dialect="duckdb",
    )

    assert query.semantic is None


def test_a_measure_the_mart_does_not_carry_gets_no_plan() -> None:
    """The condition that makes the R008 fact true, tested on its own.

    `average_order_value` is also non-additive, so once the guard grew an
    additivity condition the end-to-end test below stopped proving *which*
    condition refused it — deleting the mart-measure check left the suite
    green. An additive metric absent from the mart is the case only this
    condition catches; no fixture reaches it through `plan`, so it is asked of
    `_plannable` directly.
    """
    ir = fixture_ir("ecom_basic")
    metrics = {metric.name: metric for metric in ir.metrics}
    (mart,) = [candidate for candidate in ir.marts if "gross_revenue" in candidate.measures]
    stripped = dataclasses.replace(
        mart, measures=tuple(m for m in mart.measures if m != "gross_revenue")
    )
    assert metrics["gross_revenue"].additivity is Additivity.ADDITIVE

    assert not _plannable(MetricRequest(metrics=("gross_revenue",)), stripped, metrics)
    assert _plannable(MetricRequest(metrics=("gross_revenue",)), mart, metrics)


def test_a_derived_metric_gets_no_plan() -> None:
    """`average_order_value` is a ratio over `order_count` and `revenue`, so
    the requested name is not a mart measure at all. P1's vocabulary has no
    node for the division, and a plan projecting a column no node produces —
    resting on a fact claiming the ratio is stored — would be a plan that lies
    twice. `QueryPlan.semantic` being optional is for exactly this.
    """
    planner = make_planner()
    ir = fixture_ir("non_additive_aov")
    query = planner.plan(ir, MetricRequest(metrics=("average_order_value",)), dialect="duckdb")

    assert query.semantic is None
    assert "average_order_value" not in {
        measure for mart in ir.marts for measure in mart.measures
    }


def test_the_plan_renders_as_a_pipeline() -> None:
    """The form a human reads, and eventually what `explain` prints (§7).

    Found by patch coverage: every node had a `render` and no test called one,
    so the whole readable half of this IR was shipping unexercised while
    `shape` and `serialize` were well covered.
    """
    plan = _plan("ecom_basic", "gross_revenue", ("order_date",))

    assert plan.render().splitlines() == [
        "Scan(order_items @ order_item)",
        "  -> Filter(none)",
        "    -> Aggregate(gross_revenue : order_item -> order_item by order_date)",
        "      -> Project(order_date, gross_revenue)",
    ]


def test_an_empty_grouping_renders_as_a_total_not_as_nothing() -> None:
    """`Aggregate` with no dimensions is a grand total, and a reader seeing an
    empty parenthesis would not know whether the grouping was absent or lost."""
    plan = _plan("ecom_basic", "gross_revenue")
    (aggregate,) = [node for node in plan.nodes if isinstance(node, Aggregate)]

    assert aggregate.render().endswith("by total)")


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


_CLOSED = Proof(
    rule="R002",
    conclusion=SemanticJudgement("Determines"),
    facts=(SemanticFact(source="spec:x", provenance=Provenance.DECLARED, statement="x"),),
)

_OPEN = Proof(
    rule="R002",
    conclusion=SemanticJudgement("Determines"),
    facts=(
        SemanticFact(
            source="guess:x", provenance=Provenance.INFERRED_HEURISTIC, statement="probably x"
        ),
    ),
)


def test_a_multiplying_node_without_a_proof_is_invalid_ir() -> None:
    """D2: not merely unexplained. The distinction decides whether the check
    can be skipped under time pressure, so it raises on construction rather
    than offering itself to a caller who has to remember to ask."""
    with pytest.raises(ValueError, match="without a closed proof"):
        SemanticPlan((_Multiplying(),))  # type: ignore[arg-type]


def test_a_proof_that_rests_on_a_heuristic_does_not_authorize() -> None:
    """Closed, not merely present. A leaf nothing closes is a derivation
    nobody stands behind, and a check reading the field for its existence
    rather than its content accepts one — the same shape as trusting a refusal
    because an exception object was constructed.
    """
    assert not _OPEN.closed

    with pytest.raises(ValueError, match="without a closed proof"):
        SemanticPlan((_Multiplying(proof=_OPEN),))  # type: ignore[arg-type]


def test_an_aggregate_without_a_proof_is_invalid_ir() -> None:
    """D2's sentence names the multiplicity-changing node, and no P1 node type
    multiplies — read literally it would hold over an empty set for this whole
    phase. The aggregate is itself a claim: that these measures may be rolled
    to this grain. An unproven one is the fan-out bug with a plan wrapped
    around it.
    """
    with pytest.raises(ValueError, match="without a closed proof"):
        SemanticPlan(
            (
                Scan(relation="m", grain="g"),
                Aggregate(input_grain="g", output_grain="g", measures=("m",)),
            )
        )


def test_a_plan_with_no_nodes_is_invalid() -> None:
    """The empty case, decided rather than inherited from the reduction.

    An empty sequence satisfies "every multiplying node carries a proof"
    perfectly, so without this a plan that computes nothing is one `check`
    calls valid — the same shape as a proof resting on no facts.
    """
    with pytest.raises(ValueError, match="computes nothing"):
        SemanticPlan(())


def _reads_semantic(source: str) -> list[int]:
    """Every line of ``source`` that reads a ``.semantic`` attribute."""

    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "semantic"
    ]


def test_nothing_in_the_tree_reads_the_plan_yet() -> None:
    """P1 is the IR alone, pinned rather than left for a reader to infer from a
    plan sitting beside the SQL.

    Wiring a target to the plan would change what the query is generated from,
    which is the one thing this phase must not do if §8's parity suite is to
    mean anything (D5). Asserted structurally because there is no behaviour to
    observe: the plan being unread is exactly why it changes nothing, so the
    only evidence is that no module reads it. When P2 wires a target, this is
    where someone has to say so deliberately.

    Over the parsed tree, not a regex. A grep for ``.semantic`` matches every
    ``from bloomery.semantic import`` line in the package and does not match
    the construction site at all, so making it quiet took exclusions that
    would also have hidden a real reader landing in an excluded file — and the
    claim it was quoted for was wrong as written (logs/T-0021.md, D-127). An
    ``ast.Attribute`` named ``semantic`` is the thing being asserted about.
    """
    # The locator, checked against a reader before being trusted about their
    # absence. A structural canary asserts an empty result, so one that stopped
    # locating anything is indistinguishable from one finding nothing — the
    # sweep's own mutation to this line survived until this line existed.
    assert _reads_semantic("value = query.semantic\n") == [1]

    source = pathlib.Path(bloomery.__file__).parent
    readers = sorted(
        f"{path.relative_to(source)}:{line}"
        for path in source.rglob("*.py")
        for line in _reads_semantic(path.read_text(encoding="utf-8"))
    )

    assert readers == [], f"something now reads the plan: {readers}"


def test_a_multiplying_node_with_a_closed_proof_is_accepted() -> None:
    """The control. Without it the rules above would pass for a check that
    refused every plan containing the stand-in, proof or not."""

    assert SemanticPlan((_Multiplying(proof=_CLOSED),)).nodes  # type: ignore[arg-type]


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
