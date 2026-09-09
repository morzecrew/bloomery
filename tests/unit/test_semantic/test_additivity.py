"""The second question a rollup asks (RFC 0039 §3 — R011 and R012).

`can_roll_up` answers whether values may travel from one grain to another.
These rules answer what may be done with them on arrival, and the two are
separable in exactly one direction: a measure whose grain proof is perfect can
still be wrong to sum, and a measure whose grain proof fails is wrong to sum
whatever its additivity says. Every test below is about keeping those two
answers apart, because a single rule that returned "no" for both could not tell
an author which one to fix.
"""

from __future__ import annotations

import dataclasses

import pytest

from bloomery.ir import Additivity, Ratio
from bloomery.semantic import (
    Proof,
    Provenance,
    Refutation,
    prove_additive_rollup,
    prove_ratio_reconstruction,
)
from support.grain_model import (
    ITEM_ORDER,
    ORDER,
    ORDER_ITEM,
    grain,
    metric,
    project,
)

pytestmark = pytest.mark.unit

ITEM = grain("order_item", "order_id", "line_id")
ORDER_GRAIN = grain("order", "order_id")

REVENUE = metric("revenue", "order_item", Additivity.ADDITIVE)
LINES = metric("lines", "order_item", Additivity.ADDITIVE, agg="count")
AVERAGE = metric(
    "average_line_value",
    "order_item",
    Additivity.RATIO,
    agg=None,
    ratio=Ratio(numerator="revenue", denominator="lines"),
)
SESSIONS = metric("sessions", "order_item", Additivity.DISTINCT_COUNT, agg="count_distinct")

PROJECT = project((ORDER, ORDER_ITEM), (ITEM_ORDER,), (REVENUE, LINES, AVERAGE, SESSIONS))


# ....................... #


def test_an_additive_measure_rolls_up_and_says_what_let_it() -> None:
    """R011 over R006: the grain proof is a premise rather than a repeat, so
    the two facts a reader needs — the route and the licence to sum — are both
    in one tree and neither is asserted twice."""
    answer = prove_additive_rollup(REVENUE, ITEM, ORDER_GRAIN, PROJECT)

    assert isinstance(answer, Proof)
    assert answer.rule == "R011"
    assert answer.conclusion.kind == "AdditiveRollup"
    assert dict(answer.conclusion.operands)["measure"] == "revenue"
    # The grain half is carried, not restated.
    assert [premise.rule for premise in answer.premises] == ["R006"]
    assert [fact.provenance for fact in answer.facts] == [Provenance.DECLARED]


def test_a_non_additive_measure_is_refused_on_a_route_that_exists() -> None:
    """The separation, in the direction that matters. The grain proof succeeds
    — `order_item` reaches `order` by a declared `many_to_one` — and the
    refusal is about the measure rather than the route, which is what tells an
    author to change the metric and not the relationships."""
    answer = prove_additive_rollup(AVERAGE, ITEM, ORDER_GRAIN, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_additive"
    assert answer.judgement.kind == "AdditiveRollup"
    assert "is declared ratio" in answer.obligations[0].found
    # `DECLARED`, not `UNKNOWN`: the additivity is written down and is the
    # wrong one. Reporting it absent sends an author to declare what is there.
    assert [fact.provenance for fact in answer.rejected] == [Provenance.DECLARED]


def test_a_failed_grain_proof_is_returned_rather_than_relabelled() -> None:
    """The other direction. Asking to sum an order-grained measure at line
    grain is a refinement, and the refusal keeps `SafeRollup`'s judgement — so
    a caller can tell "these values may not travel this way" from "this measure
    may not be summed", which is §6's smallest-failed-obligation rule applied
    to a two-part question."""
    answer = prove_additive_rollup(REVENUE, ORDER_GRAIN, ITEM, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.judgement.kind == "SafeRollup"
    assert answer.reason == "refinement"


@pytest.mark.parametrize("additivity", sorted(set(Additivity) - {Additivity.ADDITIVE}, key=str))
def test_only_additive_closes_the_obligation(additivity: Additivity) -> None:
    """Every member of the closed set except one is refused, rather than the
    three that were thought of. `Additivity` gained `distinct_count` after this
    rule was designed; a test written against a list would have admitted it."""
    answer = prove_additive_rollup(
        dataclasses.replace(REVENUE, additivity=additivity), ITEM, ORDER_GRAIN, PROJECT
    )

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_additive"


# ....................... #


def test_a_ratio_is_rebuilt_from_operands_that_each_roll_up() -> None:
    """R012's premises are R011 answers, one per operand — which is the whole
    claim. A ratio is sound at the target grain exactly when its inputs are,
    and any other premise would let a ratio over a non-additive operand prove
    itself."""
    answer = prove_ratio_reconstruction(AVERAGE, ITEM, ORDER_GRAIN, PROJECT)

    assert isinstance(answer, Proof)
    assert answer.rule == "R012"
    assert answer.conclusion.kind == "RatioReconstruction"
    assert [premise.rule for premise in answer.premises] == ["R011", "R011"]
    assert {dict(premise.conclusion.operands)["measure"] for premise in answer.premises} == {
        "revenue",
        "lines",
    }


def test_a_ratio_over_a_non_additive_operand_is_refused() -> None:
    """The adversarial half of R012 (§10): remove the property one premise
    rests on and the conclusion must not survive. The refusal names the
    *operand*, not the ratio, because that is the metric an author edits."""
    answer = prove_ratio_reconstruction(
        dataclasses.replace(AVERAGE, ratio=Ratio(numerator="sessions", denominator="lines")),
        ITEM,
        ORDER_GRAIN,
        PROJECT,
    )

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_additive"
    assert dict(answer.judgement.operands)["measure"] == "sessions"


def test_an_operand_no_project_declares_is_unknown_and_not_declared() -> None:
    """The two absences the provenance vocabulary keeps apart: a wrong
    additivity is a fact that exists and says the wrong thing (`DECLARED`), a
    missing operand is no fact at all (`UNKNOWN`). Neither closes an
    obligation, and only the second means "there is nothing here"."""
    answer = prove_ratio_reconstruction(
        dataclasses.replace(AVERAGE, ratio=Ratio(numerator="nowhere", denominator="lines")),
        ITEM,
        ORDER_GRAIN,
        PROJECT,
    )

    assert isinstance(answer, Refutation)
    assert answer.reason == "operand_unreachable"
    assert [fact.provenance for fact in answer.rejected] == [Provenance.UNKNOWN]


def test_a_metric_with_no_ratio_cannot_be_reconstructed() -> None:
    """The empty case, decided rather than inherited: asking a plain measure to
    reconstruct itself has no operands to work from, and returning a proof over
    zero premises would be a derivation that derived nothing."""
    answer = prove_ratio_reconstruction(REVENUE, ITEM, ORDER_GRAIN, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_a_ratio"
