"""The corpus-wide pin that a single-project compile did not move (S-0002/I-1).

Composition put an imported node in front of every emitter: a mart's base
entity is looked up through a view that may hold the upstream's, dbt learned a
second shape of ``ref()``, and Cube and MetricFlow describe an imported mart as
they describe their own. A project carrying neither an exports nor an imports
document must be untouched by all of it, and "untouched" is a claim about
*every* fixture rather than the dozen the per-target goldens carry.

One file rather than a tree of them, and checksums rather than bodies: the
per-fixture goldens already hold the bytes and review the diffs, so what is
missing is breadth. A line here moving says which fixture, which target and
which artifact — enough to open the golden that holds the body, or to compile
the fixture and read it. A fixture with no golden at all is covered here and
nowhere else, which is the point.

Regenerate via ``just snapshot-update``, as every golden is; a moved line is
reviewed like source, and an unexplained one fails review.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import Target
from bloomery.errors import BloomeryError
from support.compiling import compile_fixture, spec_fixture_names

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent

#: Every core target, on one dialect. The dialect sweep is
#: ``test_sqlmesh_dialects``' question; this one asks whether composition
#: reached a single-project compile, and that answer does not vary by dialect.
DIALECT = "duckdb"


def _corpus() -> str:
    """``<fixture> <target> <path> <checksum>`` per artifact, plus one
    ``refused`` line per fixture a target declines.

    The refusals are recorded rather than skipped: a refusal that stopped
    firing is a compile that moved as surely as a checksum that changed, and
    swallowing one here would leave the sweep passing with less in it.
    """

    lines: list[str] = []

    for name in spec_fixture_names():
        for target in sorted(Target, key=lambda member: member.value):
            try:
                artifacts = compile_fixture(name, target=target, dialect=DIALECT)
            except BloomeryError as refusal:
                lines.append(f"{name} {target.value} refused {type(refusal).__name__}")
                continue
            lines.extend(
                f"{name} {target.value} {artifact.path} {artifact.checksum}"
                for artifact in artifacts
            )

    return "\n".join(lines) + "\n"


def test_single_project_compiles_did_not_move(snapshot: Snapshot) -> None:
    snapshot.snapshot_dir = GOLDEN / "corpus"
    snapshot.assert_match(_corpus(), "single_project.txt")
