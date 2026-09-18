"""The dangling-export guard (S-0002/D-1, `LOCKED`).

An export list is entirely references, so a name that resolves to nothing is
the whole of what can go wrong with one — and it goes wrong twice over. Nothing
upstream builds an export, so nothing upstream notices; downstream the name is
simply absent from the surface, which is what a deliberate non-export looks
like too. These tests are about the refusal happening at all, about it
happening against the documents the author wrote rather than the draft the
flattener built, and about the one name whose refusal has to say something
narrower than "not declared".
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import DanglingExport, GuardrailError
from support.compiling import FIXTURES, fixture_sources

pytestmark = pytest.mark.unit


def _compile(exports: str, *, sources: dict[str, str] | None = None) -> None:
    documents = sources if sources is not None else fixture_sources("ecom_basic")
    documents["exports"] = exports
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    build_project_ir(load_project(documents), catalog=catalog)


def _exports(*, entities: str = "[]", marts: str = "[]", metrics: str = "[]") -> str:
    return f"""
exports_version: 1
exports:
  entities: {entities}
  marts: {marts}
  metrics: {metrics}
"""


def test_a_surface_of_declared_names_compiles() -> None:
    """The clean case, and it is not vacuous: `ecom_basic` declares all three
    of these, so the guard is answering rather than abstaining."""

    _compile(_exports(entities="[order]", marts="[order_items]", metrics="[gross_revenue]"))


def test_an_entity_the_project_does_not_declare_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile(_exports(entities="[orders]"))

    leaf = caught.value.collected[0]
    assert isinstance(leaf, DanglingExport)
    message = str(caught.value)
    assert "exports entity 'orders'" in message
    # The refusal ends on what the project *does* declare, because the mistake
    # it catches is a rename that landed in one document and not the other.
    assert "'order'" in message
    assert leaf.source_path == "exports: exports"


def test_a_mart_the_project_does_not_declare_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile(_exports(marts="[order_lines]"))

    assert isinstance(caught.value.collected[0], DanglingExport)
    assert "exports mart 'order_lines'" in str(caught.value)


def test_a_metric_the_project_does_not_declare_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile(_exports(metrics="[revenue_gross]"))

    assert isinstance(caught.value.collected[0], DanglingExport)
    assert "exports metric 'revenue_gross'" in str(caught.value)


def test_an_unreachable_metric_is_still_a_declared_one() -> None:
    """D1's word is *declared*, and `margin` is declared: no mapping supplies
    `cogs`, so resolution reports it unreachable and it never reaches
    ``ProjectIR.metrics``.

    Refusing it would make the export list's validity depend on whether some
    other document happens to supply a leaf — a compile error about a metric,
    reported against a boundary. It is also the case that proves the guard
    reads the authored documents rather than the draft.
    """

    _compile(_exports(metrics="[margin]"))


def test_a_rollup_named_under_marts_is_told_it_is_a_rollup() -> None:
    """`rollup_mart` declares `order_items_monthly` as a rollup of a mart.

    "Not declared" is a refusal the author disproves by opening the marts
    document, so the message says the narrower true thing: this list names
    marts. Admitting a rollup is a grammar change with legs into §5.5's
    cross-project `ref()`, which is why it is refused here rather than waved
    through as obviously reasonable.
    """

    with pytest.raises(GuardrailError) as caught:
        _compile(_exports(marts="[order_items_monthly]"), sources=fixture_sources("rollup_mart"))

    message = str(caught.value)
    assert "declares as a rollup rather than a mart" in message
    assert "Fix: export the mart the rollup is of" in message


def test_every_dangling_name_is_reported_not_only_the_first() -> None:
    """An export list is authored as three lists, and a list is usually got
    wrong the same way more than once — one refusal per round-trip would make
    an author fix a rename four times."""

    with pytest.raises(GuardrailError) as caught:
        _compile(_exports(entities="[a, b]", marts="[c]", metrics="[d]"))

    assert len(caught.value.collected) == 4
    assert all(isinstance(leaf, DanglingExport) for leaf in caught.value.collected)


def test_a_project_that_declares_no_metrics_says_so_rather_than_trailing_off() -> None:
    """The empty case of the "Declared metrics:" list, decided rather than
    inherited: a project may carry an exports document and no metrics document
    at all, and a refusal ending on a bare colon reads as one that was cut off.
    """

    sources = fixture_sources("minimal")
    with pytest.raises(GuardrailError) as caught:
        _compile(_exports(metrics="[anything]"), sources=sources)

    assert "Declared metrics: (none)" in str(caught.value)


def test_no_exports_document_is_no_refusal() -> None:
    """Absence is how a project says it publishes nothing, and it is the state
    every project in the corpus is in but one — `ecom_basic` carries the
    document, so this asks a fixture that does not."""

    ir = build_project_ir(load_project(fixture_sources("minimal")))
    assert ir.exports is None
