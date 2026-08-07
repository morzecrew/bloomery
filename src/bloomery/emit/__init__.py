"""The emit stage (RFC 0008): target emitters consuming :class:`ProjectIR`
— never specs — and the emitter registry mirroring the transform registry
(immutable default + explicit overlay, collision is an error, RFC 0008 D8)."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from bloomery.emit.base import (
    ArtifactKind,
    EmitContext,
    EmittedArtifact,
    Feature,
    TargetCapabilities,
    TargetEmitter,
)
from bloomery.emit.cube import CubeEmitter
from bloomery.emit.dbt import DbtEmitter
from bloomery.emit.sqlmesh import SQLMeshEmitter
from bloomery.errors import EmitError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ArtifactKind",
    "CubeEmitter",
    "DbtEmitter",
    "EmitContext",
    "EmittedArtifact",
    "Feature",
    "SQLMeshEmitter",
    "TargetCapabilities",
    "TargetEmitter",
    "get_emitter",
    "register_emitter",
]

_DEFAULT_EMITTERS: Mapping[str, TargetEmitter] = MappingProxyType(
    {
        "cube": CubeEmitter(),
        "dbt": DbtEmitter(),
        "sqlmesh": SQLMeshEmitter(),
    }
)
_overlay: dict[str, TargetEmitter] = {}


def register_emitter(emitter: TargetEmitter) -> None:
    """Register an extension target emitter (public API, spec §8; RFC 0008
    D8). A name collision with any existing emitter raises
    :class:`EmitError` — shadowing a target silently is forbidden."""
    if emitter.name in _DEFAULT_EMITTERS or emitter.name in _overlay:
        msg = f"target emitter {emitter.name!r} is already registered; shadowing is not allowed"
        raise EmitError(msg)
    _overlay[emitter.name] = emitter


def get_emitter(name: str) -> TargetEmitter:
    """Look up a target emitter by name; unknown names raise
    :class:`EmitError` listing every known name, sorted."""
    merged = dict(_DEFAULT_EMITTERS) | _overlay
    emitter = merged.get(name)
    if emitter is None:
        msg = f"unknown target {name!r}: known targets are {sorted(merged)}"
        raise EmitError(msg)
    return emitter
