"""Golden refusal text (RFC 0025 §5.1's missing half): the messages are the
product, so their exact words are an artifact, reviewed like one.

The refusal census proves every documented class is *constructed* and the
docs floor proves the suggestions are *structured*; neither notices a message
degrading — a dropped "Fix:", a source path that stops rendering, a sentence
rewritten into jargon. These snapshots do. The corpus is the specs this
repository already maintains as refusal specimens: the two spec fixtures that
refuse at evaluation, and the five cases ``examples/refusals`` promises will
refuse ("if one ever stops naming the reason and the fix, it is a defect in
the message rather than a detail of this example" — now enforced rather than
asserted).

Regenerate via ``just snapshot-update``; an unexplained diff fails review like
any other golden change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_snapshot.plugin import Snapshot

from bloomery import Stage, Target, compile_project, evaluate, load_catalog, load_project
from bloomery.errors import BloomeryError
from support.compiling import load_fixture

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).parent / "refusals"
CASES = Path(__file__).resolve().parents[2] / "examples" / "refusals" / "cases"

#: The spec fixtures that refuse at ``evaluate`` with no step registry — each
#: pinned here so a fixture that quietly starts compiling fails this test
#: rather than snapshotting an empty refusal list.
REFUSING_FIXTURES = ("fanout_trap", "scd2_mart_refusal")

#: The example cases, pinned for the same reason ``run.py`` refuses a case
#: that compiles: an example claiming a refusal that no longer happens.
REFUSAL_CASES = (
    "fanout",
    "mixed-currency",
    "scd2-flatten",
    "unimplemented-convert",
    "wrong-grain",
)


def _rendered(errors: tuple[BloomeryError, ...]) -> str:
    """One block per refusal, the way the CLI addresses it: class, source
    path, then the message verbatim."""
    blocks = [
        f"{type(error).__name__}\n"
        f"source: {error.source_path or '(none)'}\n"
        f"{error}\n"
        for error in errors
    ]
    return "\n".join(blocks)


@pytest.mark.parametrize("name", REFUSING_FIXTURES)
def test_fixture_refusal_text_golden(snapshot: Snapshot, name: str) -> None:
    project, catalog = load_fixture(name)
    evidence = evaluate(project, catalog=catalog)
    assert evidence.stage_reached is not Stage.COMPLETE, f"{name} no longer refuses"
    snapshot.snapshot_dir = GOLDEN
    snapshot.assert_match(
        f"stage: {evidence.stage_reached.name}\n\n{_rendered(tuple(evidence.refusals))}",
        f"{name}.txt",
    )


@pytest.mark.parametrize("case", REFUSAL_CASES)
def test_example_refusal_text_golden(snapshot: Snapshot, case: str) -> None:
    directory = CASES / case
    catalog_path = directory / "catalog.yaml"
    catalog = load_catalog(catalog_path.read_text()) if catalog_path.exists() else None
    documents = {
        path.name: path.read_text()
        for path in sorted(directory.glob("*.yaml"))
        if path.name != "catalog.yaml"
    }
    with pytest.raises(BloomeryError) as excinfo:
        compile_project(
            load_project(documents), target=Target.SQLMESH, dialect="duckdb", catalog=catalog
        )
    refusal = excinfo.value
    errors = refusal.collected or (refusal,)
    snapshot.snapshot_dir = GOLDEN
    snapshot.assert_match(_rendered(tuple(errors)), f"example-{case}.txt")


# ....................... #
# Advisory text (RFC 0033 §8)
#
# The sibling the RFC asks for, and it exists for the same reason the blocks
# above do: an advisory message degrading silently — a dropped "Fix:", a
# rewritten sentence that stops saying the construct is legal — is the same
# defect class as a refusal message degrading, and no other tier notices.
#
# The corpus is the fixtures that actually produce one. `ecom_basic` is the
# only one today, which is a fact about the fixtures rather than a limit here:
# a fixture that starts producing an advisory joins this list, and one that
# stops is a signal, not a saving.

ADVISORY_FIXTURES = ("ecom_basic",)


def _advisory_text(evidence_advisories: tuple[object, ...]) -> str:
    """One block per advisory: code, source path, then the message verbatim —
    the same three-part rendering `_rendered` uses for a refusal, so a reader
    comparing the two channels reads one shape."""
    blocks = [
        f"{advisory.code.value}\n"  # type: ignore[attr-defined]
        f"source: {advisory.source_path or '(none)'}\n"  # type: ignore[attr-defined]
        f"{advisory.message}\n"  # type: ignore[attr-defined]
        for advisory in evidence_advisories
    ]
    return "\n".join(blocks)


@pytest.mark.parametrize("name", ADVISORY_FIXTURES)
def test_advisory_text_golden(snapshot: Snapshot, name: str) -> None:
    project, catalog = load_fixture(name)
    evidence = evaluate(project, catalog=catalog)
    assert evidence.advisories, f"{name} no longer produces an advisory"
    snapshot.snapshot_dir = GOLDEN
    snapshot.assert_match(_advisory_text(evidence.advisories), f"advisory-{name}.txt")
