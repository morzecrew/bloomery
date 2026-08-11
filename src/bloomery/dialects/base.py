"""The ``DialectPort`` (RFC 0008 §5.1): SQL rendering + physical type
mapping. Wraps SQLGlot; knows nothing about targets — SQLMesh-on-DuckDB and
dbt-on-DuckDB share every line of dialect logic through this port.

A transform whose AST cannot render on some dialect is an emit-time
:class:`~bloomery.errors.UnsupportedByTarget` failure discovered through
:meth:`DialectPort.supports` — never a typing concern (RFC 0004 D7).
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import ClassVar, Protocol, cast

from sqlglot import exp
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
    #: ``SHA256`` over a text value yielding a stable hex *string* — what
    #: ``reject_id`` is (RFC 0016 D21). DuckDB's ``SHA256(VARCHAR)`` returns
    #: the hex digest directly. Trino's ``sha256`` takes ``varbinary`` and
    #: returns ``varbinary``, so the same AST renders a call Trino refuses to
    #: even plan (``Unexpected parameters (varchar) for function sha256``);
    #: the portable spelling there is
    #: ``LOWER(TO_HEX(SHA256(TO_UTF8(...))))``, which is *not* interchangeable
    #: — applying it on DuckDB hex-encodes an already-hex string and doubles
    #: its length. Until the rendering is split per dialect, a dialect without
    #: this feature cannot carry a reject table.
    TEXT_SHA256 = "text_sha256"
    #: Unicode normalization to NFC — what a ``normalize`` rule compares a
    #: value against (RFC 0016 D86). Postgres and Trino spell it
    #: ``NORMALIZE(x, NFC)``; DuckDB has ``nfc_normalize(x)`` and no
    #: ``NORMALIZE`` at all, and SQLGlot's duckdb generator renders
    #: :class:`sqlglot.exp.Normalize` verbatim — a call the engine has never
    #: heard of — so :meth:`DuckDBDialect.render` rewrites it. All three
    #: shipped dialects have the capability; the flag exists so a fourth
    #: without one refuses the rule rather than emitting a function nothing
    #: defines.
    UNICODE_NORMALIZE = "unicode_normalize"
    #: ``JSON_OBJECT('k', v, ...)`` in its positional form — how the reject
    #: table builds ``raw`` and ``key_values`` (RFC 0016 §5.6). Trino accepts
    #: only the SQL-standard ``JSON_OBJECT(KEY 'k' VALUE v)`` spelling and
    #: fails to parse the positional one, so ``lowering._json_object``'s claim
    #: to be "the one construction SQLGlot renders verbatim on every shipped
    #: dialect" holds for DuckDB and Postgres but not Trino.
    JSON_OBJECT_POSITIONAL = "json_object_positional"


class DialectPort(Protocol):
    """SQL rendering + physical type mapping (RFC 0008 D1)."""

    name: str

    def render(self, node: Expression) -> str: ...

    def physical_type(self, t: LogicalType) -> str: ...

    def supports(self, feature: DialectFeature) -> bool: ...

    def text_sha256(self, value: Expression) -> Expression: ...

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression: ...


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

    def text_sha256(self, value: Expression) -> Expression:
        """A SHA-256 hex *string* over a text value (RFC 0016 D21).

        Built here rather than in the emitter because the portable spellings
        are not interchangeable: DuckDB's ``SHA256(VARCHAR)`` already returns
        hex, and applying Trino's ``LOWER(TO_HEX(SHA256(TO_UTF8(…))))`` to it
        would hex-encode an already-hex digest and double its length. A
        construction that differs per engine belongs to the port that knows
        the engine (RFC 0008 D1), not to a lowering that is supposed to be
        dialect-neutral.
        """
        return exp.SHA2(this=value, length=exp.Literal.number(256))

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``JSON_OBJECT('k', v, …)`` — the positional form, keys in the
        caller's order."""
        arguments: list[Expression] = []
        for key, value in pairs:
            arguments.extend((exp.Literal.string(key), value))
        return cast("Expression", exp.func("JSON_OBJECT", *arguments))
