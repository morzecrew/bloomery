"""The rollup mart's obligation (RFC 0058 §5.2 — R013).

R011 and R012 ask whether values that travelled from one *entity* grain to
another may be summed on arrival. This asks the same second question about a
different source: a mart, which has already proved the travelling half by being
a mart. So every test here is about the class question and about the two ways a
caller can put the question wrongly — a measure that is not this mart's, and a
grouping the mart cannot offer.

What is deliberately absent is a grain derivation. RFC 0058 D12 rests that half
on R008 rather than re-deriving it, and a test asserting a closure walk here
would be asserting that this module does something it must not.
"""

from __future__ import annotations

import dataclasses

import pytest

from bloomery.ir import Additivity, Ratio
from bloomery.semantic import (
    Proof,
    Provenance,
    Refutation,
    prove_mart_rollup,
    prove_measure_rollup,
)
from bloomery.semantic import rollup as rollup_module
from support.grain_model import ITEM_ORDER, ORDER, ORDER_ITEM, mart, metric, project

pytestmark = pytest.mark.unit

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
BALANCE = metric("balance", "order_item", Additivity.SEMI_ADDITIVE)
MARGIN = metric("margin", "order_item", Additivity.NON_ADDITIVE, agg=None)
#: Declared at the *order*, so a mart at line grain is not the one it is
#: embedded in — the premise R008 supplies, asked of a caller that got it wrong.
SHIPPING = metric("shipping", "order", Additivity.ADDITIVE)
#: Declared additive with neither `agg:` nor `expr:` — a shape nothing before
#: this module refuses, and one whose "may it be summed" has no subject.
HOLLOW = metric("hollow", "order_item", Additivity.ADDITIVE, agg=None)

PROJECT = project(
    (ORDER, ORDER_ITEM),
    (ITEM_ORDER,),
    (REVENUE, LINES, AVERAGE, SESSIONS, BALANCE, MARGIN, SHIPPING, HOLLOW),
)

DIMENSIONS = ("customer_segment", "ordered_day", "ordered_month", "region")
KEEP = ("customer_segment", "ordered_month")


def items(*measures: str) -> object:
    return mart("order_items", "order_item", measures=measures, dimensions=DIMENSIONS)


# ....................... #
# The class question — the whole of R013


def test_an_additive_measure_rolls_up() -> None:
    answer = prove_measure_rollup(REVENUE, items("revenue"), KEEP, PROJECT)

    assert isinstance(answer, Proof)
    assert answer.rule == "R013"
    assert answer.closed


def test_the_grain_half_is_cited_as_the_mart_contract() -> None:
    """RFC 0058 D12: R008, never a closure walk over the kept dimensions."""

    answer = prove_measure_rollup(REVENUE, items("revenue"), KEEP, PROJECT)

    assert isinstance(answer, Proof)
    assert [premise.rule for premise in answer.premises] == ["R008"]
    assert {fact.source for fact in answer.premises[0].facts} == {
        "mart:order_items",
        "metric:revenue",
    }


@pytest.mark.parametrize(
    ("measure", "reason"),
    [
        (BALANCE, "semi_additive_rollup_unsupported"),
        (MARGIN, "non_additive_not_summable"),
        (SESSIONS, "distinct_count_not_reaggregable"),
        (
            dataclasses.replace(REVENUE, name="stock", additivity=Additivity.SNAPSHOT),
            "snapshot_needs_time_selection",
        ),
    ],
)
def test_each_refused_class_keeps_its_own_reason(measure: object, reason: str) -> None:
    """Kept apart rather than collapsed into "unsafe": each names a different
    repair, and an author acts on the repair rather than on the verdict."""

    answer = prove_measure_rollup(measure, items(measure.name), KEEP, PROJECT)  # type: ignore[attr-defined,arg-type]

    assert isinstance(answer, Refutation)
    assert answer.reason == reason
    assert answer.remediation
    assert [fact.provenance for fact in answer.rejected] == [Provenance.DECLARED]


def test_a_refused_class_names_the_word_the_author_wrote() -> None:
    """`DECLARED`, not `UNKNOWN`. The additivity is written down and is the
    wrong one for a rollup; reporting it absent sends an author to declare a
    word that is already there."""

    answer = prove_measure_rollup(SESSIONS, items("sessions"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.rejected[0].statement == "additivity is distinct_count"


def test_every_additivity_has_a_rollup_answer() -> None:
    """The mapping is total over the closed set (RFC 0038 D1). A member added
    without a decision here must fail at the commit rather than at a call
    site."""

    assert set(rollup_module._REFUSALS) == set(Additivity)


def test_an_unmapped_class_raises_rather_than_being_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserted through the function rather than against the mapping: what
    matters is that the *subscript* is what reads it, so a fallback introduced
    later would fail here even with the mapping still total."""

    monkeypatch.delitem(rollup_module._REFUSALS, Additivity.ADDITIVE)

    with pytest.raises(KeyError):
        prove_measure_rollup(REVENUE, items("revenue"), KEEP, PROJECT)


# ....................... #
# The premise R008 supplies, asked of a caller that got it wrong


def test_a_measure_that_is_not_the_marts_is_refused_before_its_class() -> None:
    """`shipping` is additive, so a class-first order would prove this."""

    answer = prove_measure_rollup(SHIPPING, items("shipping"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_the_mart_grain"
    assert "order_item" in answer.obligations[0].found


def test_a_measure_the_mart_does_not_carry_is_refused() -> None:
    """A rollup re-aggregates what its parent stores. The composing entry point
    cannot reach this — it iterates `mart.measures` — so the guard has to live
    where the per-measure question is entered, which is the same asymmetry the
    ratio path already refuses as `operand_not_carried`."""

    answer = prove_measure_rollup(REVENUE, items("lines"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "measure_not_carried"
    assert answer.rejected[0].statement == "carries lines"


def test_carriage_is_asked_before_the_grain() -> None:
    """`shipping` is neither carried nor at the mart's grain. The absent measure
    is the outer fact: an author told to fix a grain would fix it and meet the
    same refusal."""

    answer = prove_measure_rollup(SHIPPING, items("revenue"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "measure_not_carried"


def test_a_measure_with_no_aggregation_has_nothing_to_re_aggregate() -> None:
    """`additive` is a claim about a measure, and a metric declaring neither
    `agg:` nor `expr:` has none to make it about. Nothing before this refuses
    the shape — `_has_no_measure` in `guardrails/metrics` refuses it only under
    `cumulative:` and says the rest reaches the emitter — so it arrives here
    declared additive with nothing to sum."""

    answer = prove_measure_rollup(HOLLOW, items("hollow"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "nothing_to_aggregate"
    assert answer.rejected[0].provenance is Provenance.UNKNOWN


def test_a_ratio_operand_with_no_aggregation_is_refused_by_the_same_guard() -> None:
    """One guard, both callers: the operand is additive and carried, so the
    ratio path admits it and the recursion is where it stops."""

    hollow_ratio = dataclasses.replace(
        AVERAGE, ratio=Ratio(numerator="hollow", denominator="lines")
    )
    answer = prove_measure_rollup(
        hollow_ratio, items("average_line_value", "hollow", "lines"), KEEP, PROJECT
    )

    assert isinstance(answer, Refutation)
    assert answer.reason == "nothing_to_aggregate"


# ....................... #
# A ratio is rebuilt, never summed (R012's shape)


def test_a_ratio_rebuilds_from_operands_the_rollup_carries() -> None:
    answer = prove_measure_rollup(
        AVERAGE, items("average_line_value", "revenue", "lines"), KEEP, PROJECT
    )

    assert isinstance(answer, Proof)
    assert answer.rule == "R013"
    # The operands' proofs and nothing else: a ratio is calculated, not
    # embedded, so R008 is cited inside each operand's subtree rather than for
    # the quotient the mart never stores.
    assert [premise.rule for premise in answer.premises] == ["R013", "R013"]
    assert [premise.premises[0].rule for premise in answer.premises] == ["R008", "R008"]
    assert answer.closed


def test_a_ratio_whose_operand_the_rollup_does_not_carry_is_refused() -> None:
    """The Cube emitter drops a named ratio whose components are absent, so a
    proof here would certify a measure that never lands."""

    answer = prove_measure_rollup(AVERAGE, items("average_line_value", "revenue"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "operand_not_carried"
    assert "lines" in answer.obligations[0].found


def test_a_ratio_whose_operand_is_not_a_metric_is_refused() -> None:
    absent = dataclasses.replace(AVERAGE, ratio=Ratio(numerator="revenue", denominator="ghost"))
    answer = prove_measure_rollup(
        absent, items("average_line_value", "revenue", "ghost"), KEEP, PROJECT
    )

    assert isinstance(answer, Refutation)
    assert answer.reason == "operand_unreachable"
    assert answer.rejected[0].provenance is Provenance.UNKNOWN


def test_a_ratio_over_a_non_additive_operand_is_refused() -> None:
    """A ratio is exactly as sound as the two sums beneath it — and refusing a
    non-additive operand rather than recursing is also what bounds this: two
    ratios may name each other, and nothing in the spec layer forbids it."""

    nested = dataclasses.replace(
        AVERAGE, ratio=Ratio(numerator="average_line_value", denominator="lines")
    )
    answer = prove_measure_rollup(nested, items("average_line_value", "lines"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "operand_not_additive"
    assert answer.rejected[0].statement == "additivity is ratio"


def test_a_ratio_word_without_a_ratio_block_is_refused() -> None:
    """The shape guard refuses this spec when a project compiles; this function
    takes a metric from a caller and re-asks."""

    shapeless = dataclasses.replace(AVERAGE, ratio=None)
    answer = prove_measure_rollup(shapeless, items("average_line_value"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_a_ratio"


def test_a_ratio_operand_at_another_grain_surfaces_its_own_refutation() -> None:
    """The operand check is additivity only, so the grain premise is what stops
    this — and its refutation says which measure and which grain, where a
    reworded one here would say neither."""

    crossed = dataclasses.replace(
        AVERAGE, ratio=Ratio(numerator="shipping", denominator="lines")
    )
    answer = prove_measure_rollup(crossed, items("average_line_value", "shipping", "lines"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "not_the_mart_grain"
    assert "shipping" in answer.obligations[0].required


# ....................... #
# The whole declaration


def test_a_rollup_proves_once_every_measure_does() -> None:
    answer = prove_mart_rollup(items("revenue", "lines"), KEEP, PROJECT)

    assert isinstance(answer, Proof)
    assert [premise.conclusion.operands[-1] for premise in answer.premises] == [
        ("measure", "lines"),
        ("measure", "revenue"),
    ]
    assert answer.closed


def test_a_rollup_is_refused_by_its_first_failing_measure() -> None:
    """`mart.measures` is sorted, so which failure is reported is a property of
    the spec rather than of a traversal."""

    answer = prove_mart_rollup(items("revenue", "sessions"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "distinct_count_not_reaggregable"


def test_a_rollup_keeping_nothing_is_refused_before_any_measure_is_read() -> None:
    """Both guards produce this reason — the per-measure one fires too, since
    the composing call reaches it. What only the composing guard gives is a
    judgement that names *no* measure: an empty grouping is a malformed
    question about the rollup, and answering it against whichever measure
    sorted first would send an author to look at that measure.
    """

    answer = prove_mart_rollup(items("revenue"), (), PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "no_kept_dimensions"
    assert answer.judgement.kind == "RollupMart"
    assert "measure" not in dict(answer.judgement.operands)


def test_an_empty_grouping_outranks_an_empty_measure_list() -> None:
    """Two degenerate inputs at once, and the order between them is a choice:
    the grouping is refused first, so an author reads one repair rather than
    fixing the measures and meeting the same refusal again."""

    bare = mart("order_items", "order_item", dimensions=DIMENSIONS)
    answer = prove_mart_rollup(bare, (), PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "no_kept_dimensions"


def test_a_rollup_keeping_a_dimension_the_mart_lacks_is_refused() -> None:
    answer = prove_mart_rollup(items("revenue"), ("ordered_month", "channel"), PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "unknown_dimension"
    assert [fact.source for fact in answer.rejected] == ["dimension:order_items.channel"]
    assert "ordered_day" in answer.remediation


def test_a_mart_carrying_no_measure_is_refused_rather_than_trivially_proved() -> None:
    """Every measure of an empty set is re-aggregable, so a reduction would
    prove this — and a proof resting on nothing is the one thing a closed-world
    checker may never report as proven (RFC 0039 D1)."""

    answer = prove_mart_rollup(items(), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "no_measures"


def test_a_measure_that_is_not_a_metric_is_refused() -> None:
    answer = prove_mart_rollup(items("ghost"), KEEP, PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "unknown_measure"
    assert answer.rejected[0].provenance is Provenance.UNKNOWN


# ....................... #
# Canonical form


def test_the_kept_dimensions_are_canonical() -> None:
    """Naming one dimension twice is one grouping stated twice, and the order
    they arrive in is the caller's. Both are canonicalized rather than refused,
    the way a repeated as-of anchor is."""

    scrambled = prove_mart_rollup(
        items("revenue"), ("ordered_month", "customer_segment", "ordered_month"), PROJECT
    )
    canonical = prove_mart_rollup(items("revenue"), KEEP, PROJECT)

    assert isinstance(scrambled, Proof)
    assert isinstance(canonical, Proof)
    assert scrambled.serialize() == canonical.serialize()


def test_the_measure_question_refuses_an_empty_grouping_too() -> None:
    """The class question does not read `keep`, so without this the public
    per-measure entry point would prove a measure against a rollup that groups
    by nothing — a guard the composing caller has and the other does not."""

    answer = prove_measure_rollup(REVENUE, items("revenue"), (), PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "no_kept_dimensions"


def test_a_mart_with_no_dimensions_at_all_says_so() -> None:
    """The empty case of the offer list, decided rather than rendered as a
    sentence that trails off after "offers"."""

    bare = mart("order_items", "order_item", measures=("revenue",))
    answer = prove_mart_rollup(bare, ("ordered_month",), PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "unknown_dimension"
    assert answer.remediation.endswith("offers none at all")


def test_a_rollup_carrying_a_ratio_beside_its_operands_proves() -> None:
    """The composition, not just the per-measure answer: `prove_mart_rollup`
    walks a mart whose measures include the ratio and both its operands."""

    answer = prove_mart_rollup(items("average_line_value", "lines", "revenue"), KEEP, PROJECT)

    assert isinstance(answer, Proof)
    assert len(answer.premises) == 3
    assert answer.closed


def test_the_measure_question_refuses_an_unknown_dimension_too() -> None:
    """The other half of the same asymmetry: the class question never reads
    `keep`, so both malformed groupings have to be refused wherever the
    question is entered, not only where it is composed."""

    answer = prove_measure_rollup(REVENUE, items("revenue"), ("channel",), PROJECT)

    assert isinstance(answer, Refutation)
    assert answer.reason == "unknown_dimension"
