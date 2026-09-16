"""The imports document (RFC 0059 §5.1, D1).

Everything here is decidable from the document alone — its shape, its version
pin, and the two depths at which a dependency can declare nothing. Whether the
names it carries resolve against an upstream is the guardrail's question
(``tests/unit/test_guardrails/test_imports.py``), because that needs a second
project.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bloomery import load_project
from bloomery.errors import SpecParseError
from bloomery.spec.imports import ImportSet
from support.compiling import fixture_sources

pytestmark = pytest.mark.unit


def _document(body: str) -> dict[str, str]:
    documents = fixture_sources("minimal")
    documents["imports"] = f"imports_version: 1\nimports:\n{body}"
    return documents


def test_the_three_kinds_parse_and_nothing_else_may_be_named() -> None:
    """§5.1's allow-list is the document's *shape*, and it is the export list's
    shape read from the other side: a list that could name a mapping would be a
    list naming something no export list can hold."""

    parsed = ImportSet.model_validate(
        {
            "imports_version": 1,
            "imports": {"platform": {"entities": ["a"], "marts": ["b"], "metrics": ["c"]}},
        }
    )
    read = parsed.imports["platform"]
    assert (read.entities, read.marts, read.metrics) == (("a",), ("b",), ("c",))

    with pytest.raises(ValidationError, match="mappings"):
        ImportSet.model_validate(
            {"imports_version": 1, "imports": {"platform": {"mappings": ["m"]}}}
        )


def test_a_document_with_no_upstreams_is_refused() -> None:
    """"This project reads nothing" is already what a project with no imports
    document says."""

    with pytest.raises(ValidationError, match="must declare at least one upstream"):
        ImportSet.model_validate({"imports_version": 1, "imports": {}})


def test_an_upstream_that_supplies_nothing_is_refused() -> None:
    """The same mistake one level deeper, and it needs its own check: the
    document is non-empty, so the outer guard passes it."""

    with pytest.raises(ValidationError, match="reads nothing from it"):
        ImportSet.model_validate({"imports_version": 1, "imports": {"platform": {}}})


def test_a_repeated_name_is_refused_rather_than_deduplicated() -> None:
    with pytest.raises(ValidationError, match="repeats 'a' under marts"):
        ImportSet.model_validate(
            {"imports_version": 1, "imports": {"platform": {"marts": ["a", "b", "a"]}}}
        )


def test_one_name_may_be_imported_under_two_kinds() -> None:
    """The namespaces are separate, so an entity and a metric called `order`
    are two things — on this side of the boundary as on the other."""

    parsed = ImportSet.model_validate(
        {"imports_version": 1, "imports": {"p": {"entities": ["order"], "metrics": ["order"]}}}
    )
    assert parsed.imports["p"].entities == parsed.imports["p"].metrics == ("order",)


def test_an_alias_must_be_a_bare_identifier() -> None:
    """P3 builds an imported node's lineage id from the alias, and a lineage id
    is `<kind>.<rest>` with no quoting anywhere."""

    with pytest.raises(ValidationError):
        ImportSet.model_validate(
            {"imports_version": 1, "imports": {"Platform Team": {"marts": ["a"]}}}
        )


def test_the_version_key_is_pinned_to_the_one_bloomery_implements() -> None:
    with pytest.raises(ValidationError):
        ImportSet.model_validate(
            {"imports_version": 2, "imports": {"platform": {"marts": ["a"]}}}
        )


def test_the_document_is_recognised_by_its_version_key() -> None:
    project = load_project(_document("  platform:\n    entities: [customer]\n"))

    assert project.imports is not None
    assert project.imports.imports["platform"].entities == ("customer",)


def test_a_project_allows_at_most_one() -> None:
    documents = _document("  platform:\n    entities: [customer]\n")
    documents["more_imports"] = documents["imports"]

    with pytest.raises(SpecParseError, match="at most one ImportSet document, found 2"):
        load_project(documents)


def test_a_project_with_no_imports_document_has_none() -> None:
    assert load_project(fixture_sources("minimal")).imports is None


@pytest.mark.parametrize(
    ("label", "document"),
    [
        ("no upstreams", {"imports_version": 1, "imports": {}}),
        ("an upstream reading nothing", {"imports_version": 1, "imports": {"p": {}}}),
        ("an upstream with empty lists", {"imports_version": 1, "imports": {"p": {"marts": []}}}),
        (
            "an alias that is not an identifier",
            {"imports_version": 1, "imports": {"Platform Team": {"marts": ["a"]}}},
        ),
    ],
)
def test_the_published_schema_refuses_what_the_loader_refuses(
    label: str, document: dict[str, object]
) -> None:
    """RFC 0020 D10: the schema is a pre-filter and the parser is the
    authority — so the schema may be *stricter*, never looser. A document it
    accepts and the loader rejects is one a proposal loop emits, a user pastes,
    and nothing in either artifact explains.

    Three of these came from the generator's defaults. `patternProperties`
    without `additionalProperties: false` constrains only the keys that match,
    so a non-identifier alias falls through to the default `true`; and three
    arrays with defaults make `minProperties` useless, since `{"marts": []}`
    has a property and reads nothing.
    """

    from jsonschema import Draft202012Validator

    from bloomery import SpecKind, all_spec_schemas

    with pytest.raises(ValidationError):
        ImportSet.model_validate(document)

    schema = Draft202012Validator(all_spec_schemas()[SpecKind.IMPORTS])
    assert list(schema.iter_errors(document)), f"the schema accepts {label}"
