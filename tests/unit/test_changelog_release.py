"""The changelog is machine-read during a release, so it is checked like code.

`release.yaml`'s `github-release` job hands `CHANGELOG.md` to
`mindsers/changelog-reader-action` and asks for the section named after the tag.
That job `needs: publish` — so if the section is missing, misnamed, or shaped in
a way the parser does not recognise, the release fails **after** the wheel is on
PyPI, and a PyPI upload cannot be taken back. Every other gate in this repo
guards something a rerun can fix; this one guards the step where a rerun is not
available.

RFC 0025 D8 already ordered the work ("cut the changelog section before the
tag"), and an ordering nothing checks is a convention. This is the check.

**How it works.** The rules below are a port of the action's own parser at the
commit `release.yaml` pins — `get-entries.ts`, `parse-entry.ts` and
`parse-entry-content.ts` — rather than of the Keep a Changelog prose. What
decides whether a release succeeds is the code that runs, and the two differ:
the parser accepts a bare `Unreleased` and a section with no date, neither of
which the format describes. A test written against the prose would pass while
the release failed, which is the failure it exists to prevent.

`test_the_pinned_action_is_the_one_this_was_ported_from` is what keeps that
honest: bump the action and this fails, saying to re-read the parser.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yaml"

#: The commit `release.yaml` pins `mindsers/changelog-reader-action` to, and the
#: source the rules below were read from.
PINNED_ACTION_REF = "1faaf50aa09d5793d9a100819973df801febfb31"

#: `get-entries.ts`: entries are split on a `## ` heading at line start.
_SEPARATOR = "\n## "

#: `get-entries.ts` `extractVersionToken`: bracketed first, else the first word.
_BRACKETED = re.compile(r"^\[([^\]]+)\]")
_BARE = re.compile(r"^(\S+)")

#: `parse-entry.ts`: the id is the first run of version-ish characters in the
#: half before ` - `, and the date the first digits-and-dashes run after it.
_VERSION_CHARS = re.compile(r"[a-zA-Z0-9.\-+]+")
_DATE_CHARS = re.compile(r"[0-9-]+")

#: node-semver's `valid()`, which is what the action calls to decide whether a
#: heading names a release at all.
_SEMVER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")

#: `parse-entry.ts` drops link-reference definitions from an entry's body.
_LINK_DEFINITION = re.compile(r"^\[.*\]:\s*http")

#: `parse-entry-content.ts` splits an entry body into `### ` sections.
_SECTION = re.compile(r"^###\s*", re.M)


class Entry:
    """One `## ` section, as the action would see it."""

    def __init__(self, chunk: str) -> None:
        title, _, rest = chunk.strip().partition("\n")
        version_part, _, date_part = title.partition(" - ")
        found = _VERSION_CHARS.search(version_part)
        self.id = found.group(0) if found is not None else ""
        stamped = _DATE_CHARS.search(date_part) if date_part else None
        self.date = stamped.group(0) if stamped is not None else None
        self.body = "\n".join(
            line for line in rest.splitlines() if not _LINK_DEFINITION.match(line)
        )

    @property
    def is_unreleased(self) -> bool:
        return self.id.lower() == "unreleased"

    def sections(self) -> list[tuple[str, list[str]]]:
        """`(heading, lines beneath it)` per `### ` block.

        `parse-entry-content.ts` splits on `^###\\s*` and calls **every** chunk a
        section — including the text before the first heading, whose "type" is
        then whatever its opening line says. That is worth knowing rather than
        hiding: an entry with a paragraph of preamble has a section named after
        the paragraph. It is harmless in practice, because
        `has-correct-sections.ts` only runs against a *previous* entry and the
        previous entry is always `[Unreleased]`, whose id no version scheme can
        diff — so the rule sees `null` and stands down. This method returns the
        real headings; :attr:`preamble` is the rest.
        """
        blocks = _SECTION.split(self.body)
        found = []
        for block in blocks[1:]:
            if not block.strip():
                continue
            heading, *items = block.strip().splitlines()
            found.append((heading.strip(), items))
        return found

    @property
    def preamble(self) -> str:
        """Whatever sits between the `## ` heading and the first `### ` one."""
        return _SECTION.split(self.body)[0].strip()


def entries() -> list[Entry]:
    """Every chunk the action would keep — `get-entries.ts` in full."""
    kept = []
    for chunk in CHANGELOG.read_text().split(_SEPARATOR):
        bracketed = _BRACKETED.match(chunk)
        bare = _BARE.match(chunk)
        if bracketed is not None:
            token = bracketed.group(1)
        elif bare is not None:
            token = bare.group(1)
        else:
            continue
        if token.lower() == "unreleased" or _SEMVER.match(token):
            kept.append(Entry(chunk))
    return kept


def released() -> list[Entry]:
    return [entry for entry in entries() if not entry.is_unreleased]


# ....................... #
# The port is a port of the right thing


def test_the_pinned_action_is_the_one_this_was_ported_from() -> None:
    """A bumped action is a changed parser, and this file stops describing it.

    Failing here is not "the bump is wrong" — it is "re-read
    `get-entries.ts` and `parse-entry.ts` at the new ref, then move
    `PINNED_ACTION_REF`". Silently keeping stale rules would leave a green test
    asserting the behaviour of a version nothing runs.
    """
    workflow = RELEASE_WORKFLOW.read_text()
    assert "mindsers/changelog-reader-action" in workflow, (
        "the release no longer reads the changelog with this action; "
        "this file's rules describe that action's parser and nothing else"
    )
    assert PINNED_ACTION_REF in workflow, (
        f"release.yaml pins a changelog-reader-action other than {PINNED_ACTION_REF}, "
        "which is the commit these parsing rules were read from"
    )


# ....................... #
# What the release needs to find


def test_there_is_a_released_section_to_publish() -> None:
    """Before the first tag there was none, and the release job would have
    failed at the last step with the package already public."""
    assert released(), (
        "CHANGELOG.md has no released section — the release job asks for the "
        "one named after the tag and fails if it is absent (RFC 0025 D8)"
    )


def test_every_released_section_carries_a_date() -> None:
    """The parser tolerates a missing date; Keep a Changelog does not, and the
    date is what a reader uses to place a release. Held to the stricter of the
    two, since only one of them is checkable after the fact."""
    undated = [entry.id for entry in released() if entry.date is None]
    assert undated == [], f"released sections with no ` - YYYY-MM-DD` date: {undated}"
    malformed = [
        entry.id
        for entry in released()
        if entry.date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.date)
    ]
    assert malformed == [], f"released sections whose date is not ISO: {malformed}"


def test_every_released_section_has_a_section_with_items() -> None:
    """`has-sections.ts`: a `###` heading with nothing under it is a finding.

    It is also the shape a half-finished cut leaves behind — the headings moved
    across and the bullets did not — and it would publish a release note that is
    a list of empty headings.
    """
    for entry in released():
        found = entry.sections()
        assert found, f"[{entry.id}] has no ### section; its release note would be prose only"
        empty = [heading for heading, items in found if not [i for i in items if i.strip()]]
        assert empty == [], f"[{entry.id}] has empty section(s): {empty}"


def test_released_sections_use_the_keep_a_changelog_vocabulary() -> None:
    """`has-correct-sections.ts` enforces this only against a *previous* entry,
    so the first release is exempt from the action's own check — and a first
    release is exactly when a stray heading would be introduced."""
    allowed = {"added", "changed", "deprecated", "removed", "fixed", "security"}
    for entry in released():
        strays = [h for h, _ in entry.sections() if h.lower() not in allowed]
        assert strays == [], (
            f"[{entry.id}] uses section heading(s) {strays}; Keep a Changelog "
            f"names exactly {sorted(allowed)}"
        )


def test_an_unreleased_section_is_open_for_the_next_change() -> None:
    """CONTRIBUTING tells contributors to write under `[Unreleased]`, so cutting
    a release without reopening one leaves that instruction pointing nowhere —
    and the next entry lands inside the released section instead."""
    assert any(entry.is_unreleased for entry in entries()), (
        "no [Unreleased] section: CONTRIBUTING directs every user-facing change "
        "there, and a cut that does not reopen one sends the next entry into a "
        "release that already shipped"
    )


def test_every_released_version_has_a_link_reference() -> None:
    """The `[0.1.0]` in a heading renders as a broken link without one, on a
    page whose whole job is to be read by someone deciding whether to upgrade."""
    text = CHANGELOG.read_text()
    for entry in released():
        assert f"\n[{entry.id}]: http" in text, (
            f"[{entry.id}] has no link reference at the foot of the file"
        )
