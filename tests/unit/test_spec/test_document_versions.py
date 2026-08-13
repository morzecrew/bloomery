"""Every document version key refuses a version bloomery does not implement
(RFC 0018 D7).

The keys were there from the start and did nothing. `spec_version: 99` loaded
and was read as v1 — a spec authored against a future bloomery *misread* rather
than refused, which is precisely the failure a version key exists to prevent.
Only `steps_version` was `Literal[1]`; the other five were `int` with `ge=1`.

That includes `catalog_version`, which the design named as existing and did not
count among the permissive ones. It is the same defect, so it is pinned here
too — five keys changed, not four.

The key is also the **document-kind discriminator**: `load_project` identifies a
document by which version key it carries. That is why the RFC's draft proposal —
make the key optional, "missing means version 1" — would have broken loading
rather than preserving it, and why the last test here exists: a future attempt
to relax the key has to fail this file first.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import SpecParseError

pytestmark = pytest.mark.unit

FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "ecom_basic"

#: Every key that identifies a project document, and the file carrying it.
PROJECT_VERSION_KEYS = (
    "spec_version",
    "mapping_version",
    "metrics_version",
    "marts_version",
)


def project_documents(**rewrite: str) -> dict[str, str]:
    """The fixture's project documents, optionally with one key's value
    replaced. The catalog is excluded — it loads through `load_catalog`."""
    documents = {}
    for path in sorted(FIXTURE.glob("*.yaml")):
        if path.name == "catalog.yaml":
            continue
        text = path.read_text()
        for key, value in rewrite.items():
            text = re.sub(rf"^{key}: 1$", f"{key}: {value}", text, flags=re.M)
        documents[path.name] = text
    return documents


def test_the_fixture_loads_at_version_one() -> None:
    """The control. Every assertion below is only meaningful if the unmodified
    documents load — otherwise a refusal proves nothing about the version."""
    assert load_project(project_documents()) is not None
    assert load_catalog((FIXTURE / "catalog.yaml").read_text()) is not None


@pytest.mark.parametrize("key", PROJECT_VERSION_KEYS)
@pytest.mark.parametrize("version", ["0", "2", "99"])
def test_a_project_document_refuses_a_version_it_does_not_implement(key: str, version: str) -> None:
    with pytest.raises(SpecParseError) as excinfo:
        load_project(project_documents(**{key: version}))
    assert "Input should be 1" in str(excinfo.value)


@pytest.mark.parametrize("version", ["0", "2", "99"])
def test_the_catalog_refuses_a_version_it_does_not_implement(version: str) -> None:
    """`catalog_version` was permissive too, and the design did not count it."""
    text = re.sub(
        r"^catalog_version: 1$",
        f"catalog_version: {version}",
        (FIXTURE / "catalog.yaml").read_text(),
        flags=re.M,
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(text)
    assert "Input should be 1" in str(excinfo.value)


def test_a_step_document_refuses_a_version_it_does_not_implement() -> None:
    """`steps_version` was already `Literal[1]` — pinned so the one key that
    was right does not regress to match the four that were wrong."""
    steps = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "step_resolution"
    documents = {
        path.name: re.sub(r"^steps_version: 1$", "steps_version: 2", path.read_text(), flags=re.M)
        for path in sorted(steps.glob("*.yaml"))
        if path.name != "catalog.yaml"
    }
    with pytest.raises(SpecParseError) as excinfo:
        load_project(documents)
    assert "Input should be 1" in str(excinfo.value)


def test_a_document_with_no_version_key_is_still_an_unknown_kind() -> None:
    """The discriminator property, pinned.

    The version key is how `load_project` tells a mapping from a metric set.
    Making it optional — the draft's "missing means version 1" — would make the
    kinds indistinguishable, so this is the test a future relaxation must argue
    with rather than discover.
    """
    documents = project_documents()
    name = next(n for n in documents if n.startswith("mapping"))
    documents[name] = re.sub(r"^mapping_version: 1\n", "", documents[name], flags=re.M)
    with pytest.raises(SpecParseError) as excinfo:
        load_project(documents)
    assert "unknown spec kind" in str(excinfo.value)


def test_the_entity_model_key_keeps_its_irregular_name() -> None:
    """`spec_version`, not `entity_model_version` — inconsistent and
    load-bearing. Renaming it is a breaking spec change that buys consistency
    and nothing else, so the irregularity is documented rather than fixed."""
    project = load_project(project_documents())
    assert project.entity_model.spec_version == 1
    assert not hasattr(project.entity_model, "entity_model_version")
