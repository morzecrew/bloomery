"""Golden JSON Schema per spec kind (RFC 0020 D3, RFC 0009 §5.4).

The schemas are a published artifact — an editor resolves one by ``$id``, a
control plane validates a form against it, a constrained decoder generates
inside it. That makes a schema change a *user-visible* change, and the point of
a golden is that it arrives as a reviewable diff rather than as a field that
quietly stopped being required.

Two things move these files that are not bloomery edits, and both are meant to:
a Pydantic upgrade that renders a constraint differently, and a transform added
to the registry (RFC 0020 D2 puts the whitelist in the schema, so it must).
Regenerate via ``just snapshot-update``; an unexplained diff fails review like
any other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_snapshot.plugin import Snapshot

from bloomery import SpecKind, all_spec_schemas

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).resolve().parent / "schema"


@pytest.mark.parametrize("kind", list(SpecKind), ids=lambda kind: kind.value)
def test_spec_schema_golden(snapshot: Snapshot, kind: SpecKind) -> None:
    schema = all_spec_schemas()[kind]
    snapshot.snapshot_dir = GOLDEN
    # Indented and newline-terminated: a schema golden is read by people, and a
    # one-line document diffs as one line however small the change.
    snapshot.assert_match(json.dumps(schema, indent=2) + "\n", f"{kind.value}.json")


def test_every_kind_has_a_golden() -> None:
    """The parametrization above covers whichever kinds ``SpecKind`` holds, so
    a seventh kind would silently arrive with no checked-in schema until this
    fails."""
    assert {path.stem for path in GOLDEN.glob("*.json")} == {kind.value for kind in SpecKind}
