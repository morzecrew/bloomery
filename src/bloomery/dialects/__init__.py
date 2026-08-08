"""SQL dialect ports (RFC 0008): the registry mirrors the transform registry
— immutable default + explicit overlay, collision is an error, iteration
sorted (RFC 0008 D8). Lookup by unknown name raises
:class:`~bloomery.errors.EmitError` listing known names."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from bloomery.dialects.base import DialectFeature, DialectPort, SQLGlotDialect
from bloomery.dialects.duckdb import DuckDBDialect
from bloomery.dialects.postgres import PostgresDialect
from bloomery.dialects.trino import TrinoDialect
from bloomery.errors import EmitError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DialectFeature",
    "DialectPort",
    "DuckDBDialect",
    "PostgresDialect",
    "SQLGlotDialect",
    "TrinoDialect",
    "get_dialect",
    "register_dialect",
    "registered_dialects",
]

_defaults: dict[str, DialectPort] = {
    "duckdb": DuckDBDialect(),
    "postgres": PostgresDialect(),
    "trino": TrinoDialect(),
}
_DEFAULT_DIALECTS: Mapping[str, DialectPort] = MappingProxyType(_defaults)
_overlay: dict[str, DialectPort] = {}


def register_dialect(dialect: DialectPort) -> None:
    """Register an extension dialect (RFC 0008 D8). A name collision with any
    existing dialect, default or overlay, raises :class:`EmitError`."""
    if dialect.name in _DEFAULT_DIALECTS or dialect.name in _overlay:
        msg = f"dialect {dialect.name!r} is already registered; shadowing is not allowed"
        raise EmitError(msg)
    _overlay[dialect.name] = dialect


def registered_dialects() -> tuple[DialectPort, ...]:
    """Every dialect the process knows — defaults plus overlay — sorted by
    name.

    Read what this is **not**: it is not what the compile stage checks
    ``pattern`` quality rules against. That set is the immutable constant
    :data:`~bloomery.quality.pattern.PATTERN_TARGET_DIALECTS`, precisely
    because this function is process-global and mutable — an extension
    dialect registered by an unrelated import could otherwise decide whether
    an existing project compiles, the ambient dependency RFC 0003 forbids
    (RFC 0016 D56).

    Its use is the other side of that decision: D56's escape hatch is that a
    caller targeting an extension dialect passes the set *explicitly* to
    :func:`~bloomery.quality.pattern.unsupported_dialects`, and this is how
    such a caller enumerates one that includes its own registration. Nothing
    inside bloomery calls it, by design — a compile that consulted it would
    not be a pure function of the specs.
    """
    merged = dict(_DEFAULT_DIALECTS) | _overlay
    return tuple(merged[name] for name in sorted(merged))


def get_dialect(name: str) -> DialectPort:
    """Look up a dialect by name; unknown names raise :class:`EmitError`
    listing every known name, sorted."""
    merged = dict(_DEFAULT_DIALECTS) | _overlay
    dialect = merged.get(name)
    if dialect is None:
        msg = f"unknown dialect {name!r}: known dialects are {sorted(merged)}"
        raise EmitError(msg)
    return dialect
