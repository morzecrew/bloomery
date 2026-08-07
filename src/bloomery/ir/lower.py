"""Dialect-neutral lowering primitives shared by the IR builder (RFC 0005)
and the guardrail stage's path-conflict amendment (RFC 0006 D7).

Three tiny pure functions: JSONPath-lite extraction against the bronze
relation, the dialect-neutral SQLGlot type for a logical type, and the
canonical-text wrap into :class:`~bloomery.ir.nodes.SqlExpr`. They live in the
IR layer because both consumers sit above it and the results are IR values —
physical DDL types remain the dialect port's job (RFC 0008).
"""

from __future__ import annotations

from sqlglot import exp

from bloomery.ir.nodes import SqlExpr
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
    "canon",
    "extraction",
    "generic_type",
]

_GENERIC_TYPES: dict[type[LogicalType], str] = {
    StringType: "TEXT",
    IntType: "BIGINT",
    BoolType: "BOOLEAN",
    DateType: "DATE",
    TimestampType: "TIMESTAMP",
    VariantType: "JSON",
}


def generic_type(t: LogicalType) -> exp.DataType:
    """The dialect-neutral SQLGlot type for a logical type. Physical DDL
    types are the dialect port's job (RFC 0008); this cast is rendered per
    dialect at emit from the neutral AST."""
    if isinstance(t, DecimalType):
        return exp.DataType.build(f"DECIMAL({t.precision}, {t.scale})")
    return exp.DataType.build(_GENERIC_TYPES[type(t)])


def canon(node: exp.Expression) -> SqlExpr:
    """Canonical dialect-neutral text (RFC 0003 §5.2)."""
    return SqlExpr(node.sql(pretty=False))


def extraction(path: str) -> exp.Expression:
    """Lower a JSONPath-lite ``$.a.b`` against the bronze relation: the first
    segment is the physical column, deeper segments are JSON extraction."""
    segments = path.removeprefix("$.").split(".")
    column = exp.column(segments[0])
    if len(segments) == 1:
        return column
    remainder = "$." + ".".join(segments[1:])
    return exp.JSONExtractScalar(this=column, expression=exp.Literal.string(remainder))
