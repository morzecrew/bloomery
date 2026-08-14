"""Docs snippets that claim to be a fixture must *be* that fixture.

RFC 0021 §6 asked for the how-to page's snippets to be extracted from the
fixture rather than retyped, and gave the reason: **a docs example that drifts
from a passing fixture is worse than no example, because it is trusted.** A
reader copies a wiring out of a page and expects it to compile; if it stopped
compiling three releases ago, nothing said so.

Extraction at build time would need a pipeline this project does not have and
does not want. This is the same guarantee from the other side: the page keeps
its snippet inline — where a reader can see it in context, with the prose that
explains each key — and the moment it stops matching the fixture that the
golden, execution and e2e tiers all run, the build fails here.

Comments are stripped before comparing. The fixture's are for someone reading
the corpus and the page's explanations are prose around the block; requiring
those to match would make the check about formatting rather than about the
spec, and a check people work around is worse than none.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
DOCS = ROOT / "pages" / "docs"

#: ``(page, snippet title, fixture document)``. The title is the fenced block's
#: ``title="…"``, which is what a reader reads as "this is that file".
EXTRACTED = [
    (
        "how-to/resolve-identities.md",
        "steps.yaml",
        "identity_resolution/steps.yaml",
    ),
    (
        "how-to/resolve-identities.md",
        "metrics.yaml",
        "identity_resolution/metrics.yaml",
    ),
]


def _fenced(page: Path, title: str) -> str:
    """The one fenced block whose ``title=`` is ``title``."""
    pattern = re.compile(
        rf'```[a-z]* title="{re.escape(title)}"\n(?P<body>.*?)```', re.DOTALL
    )
    matches = pattern.findall(page.read_text())
    assert len(matches) == 1, f"{page.name}: expected one block titled {title!r}, found {len(matches)}"
    return str(matches[0])


def _significant(text: str) -> list[str]:
    """The lines that carry meaning: no comments, no blank lines.

    Trailing whitespace goes too — invisible in an editor, and a diff nobody
    can see is a failure nobody can act on.
    """
    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return lines


@pytest.mark.parametrize(("page", "title", "document"), EXTRACTED)
def test_a_docs_snippet_matches_the_fixture_it_names(
    page: str, title: str, document: str
) -> None:
    assert _significant(_fenced(DOCS / page, title)) == _significant(
        (FIXTURES / document).read_text()
    )


def test_the_pages_artifact_listing_is_what_the_compiler_emits() -> None:
    """The "What comes out" block is a *complete* list, and reads as one.

    It first shipped with three of the eight paths missing — the two mapped
    sources and `dim_date` — with nothing marking it partial, so a reader would
    have concluded a step project emits no ordinary silver models. A retyped
    list drifts the same way a retyped snippet does.
    """
    from support.compiling import compile_fixture

    page = (DOCS / "how-to" / "resolve-identities.md").read_text()
    block = re.search(r"## What comes out\n\n```\n(?P<body>.*?)```", page, re.DOTALL)
    assert block is not None, "the page must still have a 'What comes out' block"
    listed = sorted(line.split()[0] for line in block["body"].splitlines() if line.strip())
    assert listed == sorted(a.path for a in compile_fixture("identity_resolution"))


def test_the_snippet_check_can_actually_fail() -> None:
    """The control. A comparison that silently matched everything — because the
    regex found no block, or because stripping removed every line — would pass
    exactly as green as a correct one, and this file would be decoration."""
    page, title, document = EXTRACTED[0]
    snippet = _significant(_fenced(DOCS / page, title))
    assert snippet, "the snippet must have significant lines"
    assert snippet != _significant((FIXTURES / "minimal" / "mapping.yaml").read_text())


def test_every_extracted_page_and_document_exists() -> None:
    """A typo'd path would make the parametrization fail loudly, but a *stale*
    entry — a page renamed, a fixture retired — is the quieter one."""
    for page, _title, document in EXTRACTED:
        assert (DOCS / page).is_file(), page
        assert (FIXTURES / document).is_file(), document
