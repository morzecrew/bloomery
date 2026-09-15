"""The exports document (RFC 0059 §5.1, D1).

Everything here is decidable from the document alone — its shape, its version
pin, and the two ways an export list can be self-defeating without naming
anything that does not exist. Whether the names it *does* carry resolve is the
guardrail's question (``tests/unit/test_guardrails/test_exports.py``).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bloomery import load_project
from bloomery.errors import SpecParseError
from bloomery.spec.exports import ExportSet
from support.compiling import fixture_sources

pytestmark = pytest.mark.unit


def _document(body: str) -> dict[str, str]:
    documents = fixture_sources("minimal")
    documents["exports"] = f"exports_version: 1\nexports:\n{body}"
    return documents


def test_the_three_kinds_parse_and_nothing_else_may_be_named() -> None:
    """§5.1's allow-list is the document's *shape*, so the deny-list needs no
    check: there is no key to put a mapping, a step or a quality surface under,
    and an unknown key is a hard error because every spec model is strict.
    """

    parsed = ExportSet.model_validate(
        {
            "exports_version": 1,
            "exports": {"entities": ["a"], "marts": ["b"], "metrics": ["c"]},
        }
    )
    assert (parsed.exports.entities, parsed.exports.marts, parsed.exports.metrics) == (
        ("a",),
        ("b",),
        ("c",),
    )

    with pytest.raises(ValidationError, match="mappings"):
        ExportSet.model_validate({"exports_version": 1, "exports": {"mappings": ["m"]}})


def test_an_export_list_that_publishes_nothing_is_refused() -> None:
    """"This project publishes nothing" is already what a project with no
    exports document says. An empty one adds a file, changes no behaviour, and
    reads to anyone opening it as a boundary somebody drew."""

    with pytest.raises(ValidationError) as caught:
        ExportSet.model_validate({"exports_version": 1, "exports": {}})

    assert "must export at least one entity, mart or metric" in str(caught.value)


def test_a_repeated_name_is_refused_rather_than_deduplicated() -> None:
    """Collapsing it silently would leave the author's mistake in the document
    — and a downstream refusal that prints the export list would print the name
    twice."""

    with pytest.raises(ValidationError) as caught:
        ExportSet.model_validate({"exports_version": 1, "exports": {"marts": ["a", "b", "a"]}})

    assert "exports.marts repeats 'a'" in str(caught.value)
    assert "Fix: name each mart once" in str(caught.value)


def test_each_kind_checks_its_own_repeats() -> None:
    """One name may legitimately appear under two kinds — the namespaces are
    separate, so an entity and a metric called `order` are two things."""

    parsed = ExportSet.model_validate(
        {"exports_version": 1, "exports": {"entities": ["order"], "metrics": ["order"]}}
    )
    assert parsed.exports.entities == parsed.exports.metrics == ("order",)


def test_the_version_key_is_pinned_to_the_one_bloomery_implements() -> None:
    """An unbounded int accepts a document written for a future bloomery and
    silently applies v1 semantics to it (RFC 0018 D7)."""

    with pytest.raises(ValidationError):
        ExportSet.model_validate({"exports_version": 2, "exports": {"marts": ["a"]}})


def test_the_document_is_recognised_by_its_version_key() -> None:
    project = load_project(_document("  entities: [customer]\n"))

    assert project.exports is not None
    assert project.exports.exports.entities == ("customer",)


def test_a_project_allows_at_most_one() -> None:
    documents = _document("  entities: [customer]\n")
    documents["more_exports"] = documents["exports"]

    with pytest.raises(SpecParseError, match="at most one ExportSet document, found 2"):
        load_project(documents)


def test_a_project_with_no_exports_document_has_none() -> None:
    assert load_project(fixture_sources("minimal")).exports is None
