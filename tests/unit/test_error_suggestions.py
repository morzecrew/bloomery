"""Structured fix suggestions on the refusals (RFC 0020 §5.4, D7–D8, D11).

Five refusals carry a machine-readable next action beside the prose. Each
property here is checked twice — once on input that triggers a real
suggestion, once on input where there is genuinely nothing to suggest — because
"empty" is the half that goes wrong: a field that silently stays at its default
when the answer *was* computable is indistinguishable, to a caller, from one
that correctly reports "no suggestion exists".

:class:`~bloomery.errors.GrainViolation`'s ``offending_measures`` is checked in
``tests/unit/test_marts/test_flatten.py``, beside the two violations that raise
it — the flattener is where the trigger machinery lives, and duplicating a
sixty-line spec here to re-raise it would test the copy.

The complementary property — that every field is *always present*, whichever
branch raised — is :func:`test_every_suggestion_field_is_always_present`, which
constructs each error bare. A field only set on the interesting path is a field
a caller has to guard with ``getattr``, which is the ergonomics this section
exists to remove.
"""

from __future__ import annotations

import pytest

from bloomery import MetricRequest
from bloomery.errors import (
    GrainViolation,
    MartCoverage,
    UnknownMember,
    UnknownStep,
    UnreachableAtGrain,
    UnsupportedFilter,
    UnsupportedSetRelation,
    UnsupportedTextOperator,
)
from bloomery.naming import DefaultNaming
from bloomery.planner import Op, parse_filter_json
from bloomery.planner.coverage import check
from bloomery.steps import EMPTY_REGISTRY, StepRegistry
from support.planning import fixture_ir
from support.steps import registry_for

pytestmark = pytest.mark.unit

NAMING = DefaultNaming()


def _refuse[E: Exception](error_type: type[E], fixture: str, request: MetricRequest) -> E:
    with pytest.raises(error_type) as caught:
        check(fixture_ir(fixture), request, naming=NAMING)
    return caught.value


# ....................... #
# UnknownMember.did_you_mean — the field RFC 0011's docstring has promised
# since it was written, while the match was computed and thrown into prose.


def test_did_you_mean_carries_the_match_the_message_names() -> None:
    error = _refuse(UnknownMember, "non_additive_aov", MetricRequest(metrics=("revenu",)))
    assert error.did_you_mean == "revenue"
    # One computation, two surfaces: a second search here could disagree with
    # the sentence beside it, which is worse than no field at all.
    assert "did you mean 'revenue'" in str(error)


def test_did_you_mean_covers_dimensions_as_well_as_metrics() -> None:
    error = _refuse(
        UnknownMember,
        "non_additive_aov",
        MetricRequest(metrics=("revenue",), dimensions=("ordered_mnth",)),
    )
    assert error.did_you_mean == "ordered_month"


def test_did_you_mean_is_none_when_nothing_is_close() -> None:
    error = _refuse(UnknownMember, "non_additive_aov", MetricRequest(metrics=("zzz",)))
    assert error.did_you_mean is None
    assert "known" in str(error)


def test_did_you_mean_is_none_for_an_unreachable_metric() -> None:
    """The metric exists and is spelled right; its leaves are unmapped.

    A closest-match suggestion here would be actively misleading — it would
    point at a *different* metric when the repair is to map ``cogs``.
    """
    error = _refuse(UnknownMember, "ecom_basic", MetricRequest(metrics=("margin",)))
    assert error.did_you_mean is None
    assert "cogs" in str(error)


# ....................... #
# UnreachableAtGrain.covering_marts


def test_covering_marts_reports_the_split_as_data() -> None:
    error = _refuse(
        UnreachableAtGrain,
        "multi_mart_refusal",
        MetricRequest(metrics=("shipping_cost", "line_discount")),
    )
    coverage = error.covering_marts
    assert {entry.metric for entry in coverage} == {"shipping_cost", "line_discount"}
    # Two metrics on two grains served by two marts — the whole content of the
    # conflict, which a tuple of mart names could not carry.
    assert len({entry.mart for entry in coverage}) > 1
    assert len({entry.grain for entry in coverage}) > 1
    assert all(isinstance(entry, MartCoverage) for entry in coverage)


def test_covering_marts_names_the_logical_mart_not_the_gold_relation() -> None:
    error = _refuse(
        UnreachableAtGrain,
        "multi_mart_refusal",
        MetricRequest(metrics=("shipping_cost", "line_discount")),
    )
    for entry in error.covering_marts:
        assert "." not in entry.mart


def test_covering_marts_is_empty_when_no_mart_serves_the_metric() -> None:
    """``()`` is the *other* refusal, not a missing value.

    A split across grains says "request them separately"; nothing covering
    the metric at all says "define a mart". A caller reading the field alone
    must be able to tell those apart, so the empty tuple has to mean the
    second and only the second.
    """
    ir = fixture_ir("ecom_basic")
    unserved = next(
        metric.name
        for metric in ir.metrics
        if not any(metric.name in mart.measures for mart in ir.marts)
    )
    error = _refuse(UnreachableAtGrain, "ecom_basic", MetricRequest(metrics=(unserved,)))
    assert error.covering_marts == ()
    assert "served by no mart" in str(error)


# ....................... #
# UnknownStep.available_versions


def test_available_versions_lists_what_the_registry_holds() -> None:
    registry = registry_for("step_resolution")
    ref = registry.steps[0][0][0]
    with pytest.raises(UnknownStep) as caught:
        registry.resolve(ref, 99)
    assert caught.value.available_versions == registry.versions_of(ref)
    assert caught.value.available_versions != ()


def test_available_versions_is_empty_for_an_unregistered_ref() -> None:
    with pytest.raises(UnknownStep) as caught:
        EMPTY_REGISTRY.resolve("nope", 1)
    assert caught.value.available_versions == ()


def test_available_versions_is_empty_when_other_steps_exist_but_not_this_ref() -> None:
    """The third branch of the same refusal — a populated registry that holds
    no version of *this* ref. Pinning a different version cannot help, and the
    empty tuple is what says so."""
    registry = registry_for("step_resolution")
    assert registry.steps  # a populated registry, unlike the case above
    with pytest.raises(UnknownStep) as caught:
        registry.resolve("no_such_step", 1)
    assert caught.value.available_versions == ()


# ....................... #
# UnsupportedFilter.nearest_supported


def test_nearest_supported_points_regex_at_like() -> None:
    with pytest.raises(UnsupportedTextOperator) as caught:
        parse_filter_json({"sku": {"$regex": "^A"}})
    assert caught.value.nearest_supported == Op.LIKE
    # A StrEnum, so the value the error carries and the member a caller
    # compares against are the same thing — no lookup table in between.
    assert Op(caught.value.nearest_supported) is Op.LIKE


def test_nearest_supported_is_none_when_no_operator_would_do() -> None:
    with pytest.raises(UnsupportedSetRelation) as caught:
        parse_filter_json({"tags": {"$superset": ["a"]}})
    assert caught.value.nearest_supported is None
    # The reason code stays the primary contract (D8): nothing is discoverable
    # only through a suggestion.
    assert caught.value.reason == "unsupported_set_relation"


def test_nearest_supported_is_none_for_a_deliberately_ambiguous_refusal() -> None:
    """``$empty`` refuses *because* ``eq ""`` and ``is_null true`` are
    different questions. Naming one would fabricate the choice the refusal
    exists to make the author state; the message names both."""
    with pytest.raises(UnsupportedTextOperator) as caught:
        parse_filter_json({"note": {"$empty": True}})
    assert caught.value.nearest_supported is None
    assert "eq ''" in str(caught.value)
    assert "is_null true" in str(caught.value)


# ....................... #
# The shape every field shares (D7): always present, never fabricated.


def test_every_suggestion_field_is_always_present() -> None:
    """Constructed bare — the branch that has nothing to say.

    In Python a collection field is ``()`` and a scalar is ``None``; "the
    attribute is absent" is not a third representation. A caller that had to
    write ``getattr(err, "did_you_mean", None)`` would be back to parsing the
    message.
    """
    assert UnknownMember("x").did_you_mean is None
    assert UnreachableAtGrain("x").covering_marts == ()
    assert GrainViolation("x").offending_measures == ()
    assert UnknownStep("x").available_versions == ()
    assert UnsupportedFilter("x").nearest_supported is None


def test_suggestion_carrying_errors_still_aggregate() -> None:
    """``from_collected`` is inherited by every leaf, so a suggestion-carrying
    ``__init__`` that dropped ``collected`` would turn an inherited classmethod
    into a ``TypeError`` — silently, since no batched stage raises these five
    today."""
    for error_type in (UnknownMember, UnreachableAtGrain, GrainViolation, UnknownStep):
        aggregate = error_type.from_collected((error_type("one"), error_type("two")))
        assert len(aggregate.collected) == 2
        assert "2 error(s):" in str(aggregate)
    filter_aggregate = UnsupportedFilter.from_collected((UnsupportedFilter("one"),))
    assert len(filter_aggregate.collected) == 1


def test_an_empty_registry_is_not_mistaken_for_a_populated_one() -> None:
    """Guards the fixture the two ``available_versions`` emptiness cases lean
    on: both assert ``()``, and they would both pass vacuously if
    ``registry_for`` had quietly started returning an empty registry."""
    assert StepRegistry().steps == ()
    assert registry_for("step_resolution").steps != ()
