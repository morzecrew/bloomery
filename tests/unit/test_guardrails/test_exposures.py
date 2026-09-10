"""The dangling-exposure guard (RFC 0056 D2, `LOCKED`).

An exposure is entirely references, so a name that resolves to nothing is the
whole of what can go wrong with one — and it goes wrong *quietly*: the impact
report walks the exposures matching a change, a dependency matching no node
matches no change, and the report comes back naming nobody. These tests are
about the refusal happening at all, and about it happening against the
documents the author wrote rather than against the draft the flattener built.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import DanglingExposure, GuardrailError
from support.compiling import FIXTURES, fixture_sources

pytestmark = pytest.mark.unit


def _compile(exposures: str, *, sources: dict[str, str] | None = None) -> None:
    documents = sources if sources is not None else fixture_sources("ecom_basic")
    documents["exposures"] = exposures
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    build_project_ir(load_project(documents), catalog=catalog)


def _exposure(*, metrics: str = "[]", marts: str = "[]") -> str:
    return f"""
exposures_version: 1
exposures:
  weekly_revenue_review:
    kind: dashboard
    owner: analytics@example.com
    depends_on:
      metrics: {metrics}
      marts: {marts}
"""


def test_an_exposure_naming_a_declared_metric_and_mart_compiles() -> None:
    """The clean case, and it is not vacuous: `ecom_basic` declares both of
    these, so the guard is answering rather than abstaining."""

    _compile(_exposure(metrics="[gross_revenue]", marts="[order_items]"))


def test_a_metric_the_project_does_not_declare_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile(_exposure(metrics="[revenue_gross]"))

    leaf = caught.value.collected[0]
    assert isinstance(leaf, DanglingExposure)
    message = str(caught.value)
    assert "depends on metric 'revenue_gross'" in message
    # The refusal ends on what the project *does* declare, because the mistake
    # it catches is a rename that landed in one document and not the other.
    assert "'gross_revenue'" in message
    assert leaf.source_path == "exposures: exposures.weekly_revenue_review"


def test_a_mart_the_project_does_not_declare_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile(_exposure(marts="[order_lines]"))

    assert isinstance(caught.value.collected[0], DanglingExposure)
    assert "depends on mart 'order_lines'" in str(caught.value)


def test_an_unreachable_metric_is_still_a_declared_one() -> None:
    """D2's word is *declared*, and `margin` is declared: no mapping supplies
    `cogs`, so resolution reports it unreachable and it never reaches
    ``ProjectIR.metrics``.

    Refusing it would make an exposure's validity depend on whether some
    *other* document happens to supply a leaf — which is a compile error about
    a metric, reported against a dashboard.
    """

    _compile(_exposure(metrics="[margin]"))


def test_a_rollup_named_under_marts_is_told_it_is_a_rollup() -> None:
    """`rollup_mart` declares `order_items_monthly` as a rollup of a mart.

    "Not declared" would be a refusal the author can disprove by opening the
    marts document, so the message says the narrower true thing instead
    (logs/T-0038.md).
    """

    with pytest.raises(GuardrailError) as caught:
        _compile(
            _exposure(marts="[order_items_monthly]"), sources=fixture_sources("rollup_mart")
        )

    message = str(caught.value)
    assert "declares as a rollup rather than a mart" in message
    assert "Fix: name the mart the rollup is of" in message


def test_every_dangling_name_is_reported_not_only_the_first() -> None:
    """An exposure is authored as a list, and a list is usually got wrong the
    same way more than once — one refusal per round-trip would make an author
    fix a rename four times."""

    with pytest.raises(GuardrailError) as caught:
        _compile(_exposure(metrics="[a_metric, b_metric]", marts="[a_mart]"))

    assert len(caught.value.collected) == 3
    assert all(isinstance(leaf, DanglingExposure) for leaf in caught.value.collected)


def test_a_project_with_no_exposures_document_is_not_refused() -> None:
    """The guard's own abstention, pinned: every fixture but one declares no
    exposures, and a guard that raised on their absence would be found by every
    other test rather than by this one."""

    sources = fixture_sources("ecom_basic")
    del sources["exposures"]
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    build_project_ir(load_project(sources), catalog=catalog)
