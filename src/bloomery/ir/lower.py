"""Dialect-neutral lowering primitives shared by the IR builder (RFC 0005),
the mart flattener (RFC 0010), and the guardrail stage's path-conflict
amendment (RFC 0006 D7).

Four tiny pure functions: JSONPath-lite extraction against the bronze
relation, the dialect-neutral SQLGlot type for a logical type, the
canonical-text wrap into :class:`~bloomery.ir.nodes.SqlExpr`, and the
spec-string → :class:`~bloomery.ir.nodes.PartitionSpec` parse. They live in
the IR layer because every consumer sits above it and the results are IR
values — physical DDL types remain the dialect port's job (RFC 0008).
"""

from __future__ import annotations

import re

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.ir.nodes import PartitionSpec, SqlExpr
from bloomery.spec.common import PARTITION_SPEC_PATTERN
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
    "partition_specs",
]

_PARTITION_RE = re.compile(PARTITION_SPEC_PATTERN)

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


def canon(node: Expression) -> SqlExpr:
    """Canonical dialect-neutral text (RFC 0003 §5.2)."""
    return SqlExpr(node.sql(pretty=False))


def extraction(path: str) -> Expression:
    """Lower a JSONPath-lite ``$.a.b`` against the bronze relation: the first
    segment is the physical column, deeper segments are JSON extraction."""
    segments = path.removeprefix("$.").split(".")
    column = exp.column(segments[0])
    if len(segments) == 1:
        return column
    remainder = "$." + ".".join(segments[1:])
    return exp.JSONExtractScalar(this=column, expression=exp.Literal.string(remainder))


def partition_specs(entries: tuple[str, ...]) -> tuple[PartitionSpec, ...]:
    """Parse spec-layer partition entries (``col`` or ``fn(col)``, RFC 0002
    §5.5) into :class:`PartitionSpec` values, authored order preserved
    (RFC 0003 D4)."""
    specs: list[PartitionSpec] = []
    for entry in entries:
        match = _PARTITION_RE.match(entry)
        if match is None or match.group(2) is None:  # bare column form
            specs.append(PartitionSpec(transform=None, column=entry))
        else:
            specs.append(PartitionSpec(transform=match.group(1), column=match.group(2)))
    return tuple(specs)
