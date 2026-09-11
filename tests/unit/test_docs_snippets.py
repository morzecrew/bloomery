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
from support.compiling import compile_fixture

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
    # RFC 0024 §7. The union merge's how-to shows all three documents because
    # the *whole* of what a project writes is those three — the feature's claim
    # is that it needs no new syntax, and a page that showed only a fragment
    # would leave a reader wondering what else was on the page it did not show.
    (
        "how-to/merge-sources.md",
        "entity_model.yaml",
        "multi_source/entity_model.yaml",
    ),
    (
        "how-to/merge-sources.md",
        "mapping_platform.yaml",
        "multi_source/mapping_platform.yaml",
    ),
    (
        "how-to/merge-sources.md",
        "mapping_legacy.yaml",
        "multi_source/mapping_legacy.yaml",
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


# ....................... #
# A snippet that claims to run must run (RFC 0068 §6)


def test_the_reproduce_recipe_actually_runs() -> None:
    """The how-to's compile block is executed, not read.

    RFC 0068 §6 asks only that the block be "checked against the library's
    actual signatures". Executing it is strictly stronger — it catches a wrong
    keyword *and* a recipe that stopped working — and it is affordable only
    because the page splits fetching from compiling: the fetch half is a `git
    show` or a `SELECT`, chosen per store and unrunnable here, while the
    compile half is self-contained (logs/T-0042.md).

    This is the page a reader opens mid-incident. A recipe that has drifted is
    worse there than anywhere else, because the reader has no attention left to
    debug it.
    """
    from bloomery.cli import io  # noqa: PLC0415 — the CLI's door, standing in for the caller's store

    sources, catalog_text = io.read_spec_directory(str(FIXTURES / "ecom_basic"))
    block = _fenced(DOCS / "how-to" / "reproduce-a-past-artifact-set.md", "reproduce.py")

    # `sources` and `catalog_text` are what step 1 of the page returns; the
    # block is run exactly as printed, with nothing else in scope.
    scope: dict[str, object] = {"sources": sources, "catalog_text": catalog_text}
    exec(compile(block, "reproduce.py", "exec"), scope)  # noqa: S102 — the page's own text is the fixture

    artifacts = scope["artifacts"]
    assert artifacts, "the page's recipe compiled nothing"


def test_the_timeline_recipe_actually_runs() -> None:
    """The timeline how-to's block is executed too, for the same reason and on
    the same seam (RFC 0069 §7).

    The history it walks is the corpus's own five-version project, handed in as
    `versions` — the shape step 1 of the page says it returns. A reader who
    copies this block is mid-incident and has no attention left to debug a
    recipe that drifted.
    """
    from bloomery.cli import io  # noqa: PLC0415 — the CLI's door, standing in for the caller's store

    versions = []
    for step in range(1, 6):
        sources, catalog_text = io.read_spec_directory(str(FIXTURES / f"evolution_v{step}"))
        versions.append((f"v{step}", sources, catalog_text))

    block = _fenced(DOCS / "how-to" / "trace-a-definition-over-time.md", "timeline.py")
    scope: dict[str, object] = {"versions": versions}
    exec(compile(block, "timeline.py", "exec"), scope)  # noqa: S102 — the page's own text is the fixture

    walk = scope["walk"]
    assert [entry.label for entry in walk.entries] == [f"v{step}" for step in range(1, 6)]


def test_the_recipe_check_can_actually_fail() -> None:
    """The control for the test above, in the shape this file already uses.

    A recipe drifting from the API raises rather than returning something
    wrong, so the guard is only worth having if a broken block is seen as
    broken — asserted against a keyword the signature does not have, which is
    the failure the check exists for.
    """
    broken = "from bloomery import load_project\nload_project(specs=sources)\n"

    with pytest.raises(TypeError):
        exec(compile(broken, "broken.py", "exec"), {"sources": {}})  # noqa: S102

