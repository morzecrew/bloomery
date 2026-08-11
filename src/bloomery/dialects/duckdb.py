"""The DuckDB dialect (RFC 0008 D5): the primary execution-test engine
(RFC 0009 tier 4)."""

from __future__ import annotations

from typing import ClassVar, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import SQLGlotDialect
from bloomery.typing import (
    BoolType,
    DateType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

__all__ = [
    "DuckDBDialect",
]


class DuckDBDialect(SQLGlotDialect):
    """DuckDB: SQLGlot's ``duckdb`` generator plus DuckDB's native types."""

    name: str = "duckdb"
    sqlglot_dialect: str = "duckdb"
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "VARCHAR",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSON",
    }

    def render(self, node: Expression) -> str:
        """Render, rewriting ``NORMALIZE(x, NFC)`` to DuckDB's spelling — the
        input node is never mutated (the port contract shares ASTs across
        dialects).

        DuckDB has ``nfc_normalize`` and no ``NORMALIZE``, and SQLGlot's duckdb
        generator renders :class:`sqlglot.exp.Normalize` verbatim rather than
        refusing it, so the untouched AST would emit a call the engine has
        never heard of. Verified live: the ``normalize`` rule's execution tier
        fails without this.
        """
        rewritten = node.copy().transform(_nfc_normalize)
        return super().render(rewritten)


def _nfc_normalize(node: Expression) -> Expression:
    """``NORMALIZE(x, NFC)`` → ``NFC_NORMALIZE(x)``.

    Only NFC is reachable: the spec surface admits no other normal form,
    precisely because this function is the only one DuckDB has (RFC 0016 D86).
    A form that somehow arrived here would silently normalize to the wrong one,
    so it raises rather than guessing.
    """
    if not isinstance(node, exp.Normalize):
        return node
    form = node.args.get("form")
    if form is not None and form.name.upper() != "NFC":
        msg = f"duckdb can only normalize to NFC, not {form.name!r}"
        raise ValueError(msg)
    return cast("Expression", exp.func("NFC_NORMALIZE", node.this.copy()))
