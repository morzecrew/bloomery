"""SQL dialect ports (RFC 0008): the registry mirrors the transform registry
— immutable default + explicit overlay, collision is an error, iteration
sorted (RFC 0008 D8). Lookup by unknown name raises
:class:`~bloomery.errors.EmitError` listing known names."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from bloomery.dialects.base import DialectFeature, DialectPort, SQLGlotDialect
from bloomery.dialects.duckdb import DuckDBDialect
from bloomery.errors import EmitError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DialectFeature",
    "DialectPort",
    "DuckDBDialect",
    "SQLGlotDialect",
    "get_dialect",
    "register_dialect",
]

_defaults: dict[str, DialectPort] = {"duckdb": DuckDBDialect()}
_DEFAULT_DIALECTS: Mapping[str, DialectPort] = MappingProxyType(_defaults)
_overlay: dict[str, DialectPort] = {}


def register_dialect(dialect: DialectPort) -> None:
    """Register an extension dialect (RFC 0008 D8). A name collision with any
    existing dialect, default or overlay, raises :class:`EmitError`."""
    if dialect.name in _DEFAULT_DIALECTS or dialect.name in _overlay:
        msg = f"dialect {dialect.name!r} is already registered; shadowing is not allowed"
        raise EmitError(msg)
    _overlay[dialect.name] = dialect


def get_dialect(name: str) -> DialectPort:
    """Look up a dialect by name; unknown names raise :class:`EmitError`
    listing every known name, sorted."""
    merged = dict(_DEFAULT_DIALECTS) | _overlay
    dialect = merged.get(name)
    if dialect is None:
        msg = f"unknown dialect {name!r}: known dialects are {sorted(merged)}"
        raise EmitError(msg)
    return dialect
