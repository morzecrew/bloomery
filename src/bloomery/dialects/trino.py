"""The Trino dialect (RFC 0008 D5): the federated-engine port of the M10
port-validation milestone."""

from __future__ import annotations

from typing import ClassVar

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
    "TrinoDialect",
]


class TrinoDialect(SQLGlotDialect):
    """Trino: SQLGlot's ``trino`` generator plus Trino's native types.

    ``variant`` maps to Trino's ``JSON`` type — Trino has a first-class
    ``JSON`` type (queryable via ``json_extract``/``json_query``), so the
    semi-structured escape hatch needs no VARCHAR downgrade.
    """

    name: str = "trino"
    sqlglot_dialect: str = "trino"
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "VARCHAR",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSON",
    }
