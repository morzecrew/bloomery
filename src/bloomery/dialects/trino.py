"""The Trino dialect (RFC 0008 D5): the federated-engine port of the M10
port-validation milestone."""

from __future__ import annotations

from typing import ClassVar

from bloomery.dialects.base import DialectFeature, SQLGlotDialect
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
    #: Everything but the two constructions the reject table is built from.
    #: Both were verified against ``trinodb/trino:483`` rather than reasoned
    #: about: ``SHA256`` over the concatenated canon bytes fails to plan
    #: (``Unexpected parameters (varchar) for function sha256`` — Trino's
    #: takes ``varbinary``), and the positional ``JSON_OBJECT('k', v)`` that
    #: builds ``raw``/``key_values`` fails to parse (Trino wants
    #: ``KEY 'k' VALUE v``). Trino keeps ``TRY_CAST``, so it hosts everything
    #: else in RFC 0016; what it cannot host today is quarantine. Declaring
    #: the two gaps turns SQL the engine rejects at run time into a loud
    #: :class:`~bloomery.errors.UnsupportedByTarget` at emit, and lets each be
    #: lifted on its own once the rendering is split per dialect.
    features: ClassVar[frozenset[DialectFeature]] = frozenset(DialectFeature) - {
        DialectFeature.TEXT_SHA256,
        DialectFeature.JSON_OBJECT_POSITIONAL,
    }
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "VARCHAR",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSON",
    }
