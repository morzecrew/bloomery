"""The ``DialectPort`` (RFC 0008 §5.1): SQL rendering + physical type
mapping. Wraps SQLGlot; knows nothing about targets — SQLMesh-on-DuckDB and
dbt-on-DuckDB share every line of dialect logic through this port.

A transform whose AST cannot render on some dialect is an emit-time
:class:`~bloomery.errors.UnsupportedByTarget` failure discovered through
:meth:`DialectPort.supports` — never a typing concern (RFC 0004 D7).
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Protocol

from sqlglot.expressions.core import Expression

from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

__all__ = [
    "DialectFeature",
    "DialectPort",
    "SQLGlotDialect",
]


class DialectFeature(StrEnum):
    """Capabilities an emitter may query before lowering (RFC 0008 §5.1)."""

    JSON_EXTRACT = "json_extract"
    TIMEZONE_CONVERT = "timezone_convert"
    REGEXP_EXTRACT = "regexp_extract"
    VARIANT_TYPE = "variant_type"
    #: A first-class array type (RFC 0016 D9). Deliberately a *dialect*
    #: feature, not a target ``Feature``, diverging from Document 5 §5.3:
    #: array support is an engine property, and SQLMesh-on-DuckDB and
    #: dbt-on-DuckDB share it — the RFC 0008 D1 split. All three shipped
    #: dialects have arrays (DuckDB ``STRING[]``, Postgres ``TEXT[]``, Trino
    #: ``ARRAY(VARCHAR)``); a dialect without one lowers ``_quality_flags``
    #: and ``failed_rules`` to the comma-delimited string fallback (D23).
    ARRAY = "array"
    #: A cast that yields NULL instead of raising — the shape the
    #: coercion-failure marker needs (RFC 0016 §5.2, D3: "``TRY_CAST``-shaped
    #: lowering **per dialect**"). DuckDB and Trino have ``TRY_CAST``;
    #: Postgres has no equivalent, and SQLGlot's postgres generator renders
    #: :class:`sqlglot.exp.TryCast` as a plain ``CAST``. Silently accepting
    #: that would turn "quarantine the uncastable row" into "abort the run" —
    #: a degradation nobody asked for — so the capability is declared and an
    #: entity carrying ``coercible`` rules refuses to emit on a dialect
    #: without it (RFC 0008 D3: fail loud, never approximate).
    TRY_CAST = "try_cast"


class DialectPort(Protocol):
    """SQL rendering + physical type mapping (RFC 0008 D1)."""

    name: str

    def render(self, node: Expression) -> str: ...

    def physical_type(self, t: LogicalType) -> str: ...

    def supports(self, feature: DialectFeature) -> bool: ...


class SQLGlotDialect:
    """Base adapter: renders through SQLGlot's generator for
    :attr:`sqlglot_dialect` and maps the seven logical types via
    :attr:`scalar_types` (``decimal(p, s)`` is computed)."""

    # Plain class attributes (not ClassVar): the DialectPort protocol declares
    # ``name`` as an instance attribute, and ClassVar members cannot satisfy it.
    name: str = ""
    sqlglot_dialect: str = ""
    features: ClassVar[frozenset[DialectFeature]] = frozenset(DialectFeature)
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "TEXT",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSON",
    }

    def render(self, node: Expression) -> str:
        """Render a dialect-neutral AST as this dialect's SQL text."""
        return node.sql(dialect=self.sqlglot_dialect, pretty=True)

    def physical_type(self, t: LogicalType) -> str:
        """The engine type for a logical type (RFC 0004 non-goal: physical
        mapping lives here, not in the type layer)."""
        if isinstance(t, DecimalType):
            return f"DECIMAL({t.precision}, {t.scale})"
        return self.scalar_types[type(t)]

    def supports(self, feature: DialectFeature) -> bool:
        return feature in self.features
