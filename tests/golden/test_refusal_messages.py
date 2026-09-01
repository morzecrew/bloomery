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
