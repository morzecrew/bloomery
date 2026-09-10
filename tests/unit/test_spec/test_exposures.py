"""The exposures document (RFC 0056 §5.1).

Everything here is decidable from the document alone — its kind vocabulary, its
shape, and the two ways an exposure can be self-defeating without naming
anything that does not exist. Whether the names it *does* carry resolve is the
guardrail's question (``tests/unit/test_guardrails/test_exposures.py``).
"""

from __future__ import annotations

from typing import get_args

import pytest

from bloomery import load_project
from bloomery.errors import SpecParseError
from bloomery.spec.exposures import ExposureKind, ExposureSet
from support.compiling import fixture_sources

pytestmark = pytest.mark.unit


def _exposure(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "dashboard",
        "owner": "analytics@example.com",
        "depends_on": {"marts": ["order_items"]},
    }
    return {**base, **overrides}


def _validate(**overrides: object) -> ExposureSet:
    return ExposureSet.model_validate(
        {"exposures_version": 1, "exposures": {"weekly_revenue_review": _exposure(**overrides)}}
    )


@pytest.mark.parametrize("kind", get_args(ExposureKind))
def test_every_dbt_exposure_type_is_accepted(kind: str) -> None:
    """D3: dbt's vocabulary verbatim, so each of its five is a member here.

    Parametrized off the type itself rather than a list written out again — a
    member added to one and not the other is what this would otherwise miss.
    """

    assert _validate(kind=kind).exposures["weekly_revenue_review"].kind == kind


def test_a_kind_dbt_does_not_have_is_refused() -> None:
    """``report`` is the one an author reaches for and dbt does not define; an
    earlier draft of RFC 0056 §5.1 had it in the enum and ``analysis`` out."""

    with pytest.raises(ValueError, match="Input should be"):
        _validate(kind="report")


def test_an_exposure_that_names_nothing_is_refused() -> None:
    """Both of an exposure's jobs are edges, so one with no dependency does
    neither — while still reporting clean, which is the failure mode the
    feature exists to remove."""

    with pytest.raises(ValueError, match="must depend on at least one metric or mart"):
        _validate(depends_on={})


def test_a_repeated_dependency_is_refused() -> None:
    """Every edge and every impact row is derived per name, so a name listed
    twice is one graph edge built twice and one exposure reported twice against
    a single change."""

    with pytest.raises(ValueError, match="depends_on.metrics repeats 'gross_revenue'"):
        _validate(depends_on={"metrics": ["gross_revenue", "gross_revenue"]})


def test_the_url_is_carried_and_not_interpreted() -> None:
    """D6: text, and only text. A compiler that validated it would be making a
    network request to decide whether a spec parses."""

    parsed = _validate(url="not://a-url-anything-would-accept")
    assert parsed.exposures["weekly_revenue_review"].url == "not://a-url-anything-would-accept"


def test_the_url_is_optional() -> None:
    assert _validate().exposures["weekly_revenue_review"].url is None


def test_an_unknown_key_is_refused() -> None:
    """``SpecModel`` forbids extras project-wide; pinned here because an
    exposure is the document most likely to grow a field someone read about in
    dbt's schema and expected to work."""

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _validate(maturity="high")


def test_a_second_exposures_document_is_refused() -> None:
    """At most one per project, like every other kind (RFC 0002 §5.5)."""

    sources = fixture_sources("ecom_basic")
    sources["exposures_again"] = sources["exposures"]

    with pytest.raises(SpecParseError, match="at most one ExposureSet document"):
        load_project(sources)


def test_the_version_key_identifies_the_document() -> None:
    """It is the kind discriminator, so a document without one cannot be
    identified at all — and one written for a future bloomery is refused
    rather than read as v1 (RFC 0018 D7)."""

    with pytest.raises(ValueError, match="Input should be 1"):
        ExposureSet.model_validate({"exposures_version": 2, "exposures": {}})
