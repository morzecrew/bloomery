"""Emitter port surface (RFC 0008 §5.1 amended): artifact checksums and the
emitter registry."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Iterator

import pytest

from bloomery.emit import (
    ArtifactKind,
    EmitContext,
    EmittedArtifact,
    SQLMeshEmitter,
    get_emitter,
    register_emitter,
)
from bloomery.errors import EmitError

pytestmark = pytest.mark.unit

emit_module = importlib.import_module("bloomery.emit")


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(emit_module, "_overlay", {})
    yield


def test_artifact_create_computes_the_sha256_checksum() -> None:
    artifact = EmittedArtifact.create(
        path="models/silver/event.sql", content="SELECT 1\n", kind=ArtifactKind.MODEL
    )
    assert artifact.checksum == hashlib.sha256(b"SELECT 1\n").hexdigest()
    assert artifact.kind is ArtifactKind.MODEL


def test_emit_context_is_frozen() -> None:
    context = EmitContext(dialect=object(), naming=object(), fingerprint="blm1:x")  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        context.fingerprint = "blm1:y"  # type: ignore[misc]


def test_get_emitter_returns_the_default() -> None:
    assert get_emitter("sqlmesh").name == "sqlmesh"


def test_unknown_target_lists_known_names() -> None:
    expected = r"unknown target 'looker': known targets are \['cube', 'dbt', 'sqlmesh'\]"
    with pytest.raises(EmitError, match=expected):
        get_emitter("looker")


def test_register_emitter_collision_is_an_error() -> None:
    with pytest.raises(EmitError, match="'sqlmesh' is already registered"):
        register_emitter(SQLMeshEmitter())


def test_register_emitter_overlay() -> None:
    class _Custom(SQLMeshEmitter):
        name = "custom"

    register_emitter(_Custom())
    assert get_emitter("custom").name == "custom"


# ....................... #
# No two artifacts may claim one path (RFC 0008 D8/D28, reached through the
# audit namespace rather than through relations).

_COLLIDING_ENTITY_MODEL = """
spec_version: 1
entities:
  order_item:
    grain: one row per order line
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      quantity: {type: int}
      order_date: {type: timestamp}
"""

_COLLIDING_MAPPING = """
mapping_version: 1
target: order_item
source: shop__lines
key:
  order_id: {from: "$.order_id"}
fields:
  quantity: {from: "$.quantity", transform: [to_int]}
  order_date: {from: "$.order_date", transform: [{parse_ts: ISO8601}]}
"""


def _marts(first: str, second: str) -> str:
    """Two marts, each with one assertion. An audit's name is
    ``<mart>_<assertion>``, so the *pair* decides whether two audits land on
    one path — which is why neither name alone can be validated."""
    return (
        "marts_version: 1\nmarts:\n"
        + "".join(
            f"  {mart}:\n"
            "    grain: order_item\n"
            "    base: order_item\n"
            "    flatten:\n"
            "      - {date: order_date, role: ordered}\n"
            "    assert:\n"
            f"      - {{name: {clause}, measure: quantity, agg: sum, min: 1, on_fail: fail}}\n"
            for mart, clause in (first.split("."), second.split("."))
        )
    )


def _compile(marts: str, target: str) -> tuple[EmittedArtifact, ...]:
    from bloomery import compile_project, load_project

    project = load_project(
        {
            "entity_model": _COLLIDING_ENTITY_MODEL,
            "mapping": _COLLIDING_MAPPING,
            "marts": marts,
        }
    )
    return compile_project(project, target=target, dialect="duckdb")


@pytest.mark.parametrize("target", ["sqlmesh", "dbt"])
def test_two_artifacts_at_one_path_are_refused(target: str) -> None:
    """One contract, both SQL targets, one battery.

    ``mart_assert_name`` is ``<mart>_<assertion>`` and both halves are author
    chosen, so a mart ``a`` asserting ``b_c`` and a mart ``a_b`` asserting
    ``c`` produce one audit name from two legitimate declarations. Neither name
    is wrong on its own; only the pair is, which is why a per-namespace prefix
    cannot catch this and a general guard can.

    Emitting both compiles clean and leaves the caller's path-to-content map
    holding whichever was written last — a declared quality gate that silently
    does not exist, which is the failure RFC 0008 D3 refuses. SQLMesh has
    refused it since RFC 0017; dbt could not, because until RFC 0026 it wrote
    no audit artifacts to collide.
    """
    with pytest.raises(EmitError) as excinfo:
        _compile(_marts("a.b_c", "a_b.c"), target)
    message = str(excinfo.value)
    # The path, so the author knows which two declarations to separate.
    assert "a_b_c.sql" in message
    assert "silently win" in message


@pytest.mark.parametrize("target", ["sqlmesh", "dbt"])
def test_the_same_two_marts_with_distinct_names_both_emit(target: str) -> None:
    """The control. A guard that refused this pair as well would be refusing
    two marts rather than a collision, and every assertion here is the same
    shape as the one above."""
    artifacts = _compile(_marts("a.b_c", "a_b.d"), target)
    paths = {a.path for a in artifacts}
    assert len(paths) == len(artifacts)
    assert len([p for p in paths if p.endswith(("a_b_c.sql", "a_b_d.sql"))]) == 2
