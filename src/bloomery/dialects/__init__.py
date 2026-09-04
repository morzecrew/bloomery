"""SQL dialect ports (RFC 0008): the registry mirrors the transform registry
— immutable default + explicit overlay, collision is an error (RFC 0008 D8).
Lookup by unknown name raises :class:`~bloomery.errors.EmitError` listing known
names.

There is deliberately no way to *enumerate* the registry. A compile that read
one would not be a pure function of its specs — an extension dialect registered
by an unrelated import could decide whether an existing project compiles, the
ambient dependency RFC 0003 forbids (RFC 0016 D56) — so nothing inside bloomery
ever asks. Nor does an extension author need to: D56's escape hatch is passing
the dialect set *explicitly* to
:func:`~bloomery.quality.pattern.unsupported_dialects`, and a caller who
registered a port already holds it —
``unsupported_dialects(pattern, dialects=(*shipped, MyDialect()))``, where
``shipped`` is ``get_dialect(name) for name in PATTERN_TARGET_DIALECTS``."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from bloomery.dialects.base import DIALECT_PORT_MEMBERS, DialectFeature, DialectPort, SQLGlotDialect
from bloomery.dialects.duckdb import DuckDBDialect
from bloomery.dialects.postgres import PostgresDialect
from bloomery.dialects.trino import TrinoDialect
from bloomery.errors import EmitError

if TYPE_CHECKING:
    from collections.abc import Mapping

# ----------------------- #

__all__ = [
    "DialectFeature",
    "DialectPort",
    "DuckDBDialect",
    "PostgresDialect",
    "SQLGlotDialect",
    "TrinoDialect",
    "get_dialect",
    "register_dialect",
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

    missing = [name for name in DIALECT_PORT_MEMBERS if not hasattr(dialect, name)]

    if missing:
        # `DialectPort` is a Protocol, so it is satisfied structurally and never
        # inherited — a port can type-check and still omit a member, and the
        # first anyone hears of it is an `AttributeError` from inside emission,
        # naming an attribute rather than a contract. Checked here because this
        # is the boundary the caller can act at.
        msg = (
            f"dialect {getattr(dialect, 'name', dialect)!r} does not implement "
            f"{', '.join(missing)}, which DialectPort requires (RFC 0008 D1). "
            "Fix: implement the missing member, or subclass SQLGlotDialect, which "
            "supplies a default for every one that has a sensible default"
        )
        raise EmitError(msg)

    if dialect.name in _DEFAULT_DIALECTS or dialect.name in _overlay:
        msg = f"dialect {dialect.name!r} is already registered; shadowing is not allowed"
        raise EmitError(msg)

    _overlay[dialect.name] = dialect


# ....................... #


def get_dialect(name: str) -> DialectPort:
    """Look up a dialect by name; unknown names raise :class:`EmitError`
    listing every known name, sorted."""
    merged = dict(_DEFAULT_DIALECTS) | _overlay
    dialect = merged.get(name)

    if dialect is None:
        msg = f"unknown dialect {name!r}: known dialects are {sorted(merged)}"
        raise EmitError(msg)

    return dialect
