"""The Trino dialect (RFC 0008 D5): the federated-engine port of the M10
port-validation milestone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

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
    #: Everything, since RFC 0016 D83 split the two constructions the reject
    #: table is built from. Both gaps were real and verified against
    #: ``trinodb/trino:483``: ``SHA256`` over the concatenated canon bytes did
    #: not plan (``Unexpected parameters (varchar) for function sha256`` —
    #: Trino's takes ``varbinary``), and the positional ``JSON_OBJECT('k', v)``
    #: did not parse (Trino wants ``KEY 'k' VALUE v``). Both now have a
    #: spelling on this port rather than a refusal at emit; the feature flags
    #: stay in the vocabulary because a fourth dialect may still lack either.
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "VARCHAR",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSON",
    }

    def text_sha256(self, value: Expression) -> Expression:
        """``LOWER(TO_HEX(SHA256(TO_UTF8(…))))``.

        Trino's ``sha256`` takes ``varbinary`` and returns ``varbinary``, so
        the plain spelling does not even plan: *Unexpected parameters
        (varchar) for function sha256*. ``TO_UTF8`` on the way in and
        ``TO_HEX`` on the way out give the same hex digest the other dialects
        produce directly; ``LOWER`` because Trino's ``to_hex`` is uppercase
        and ``reject_id`` must agree across engines (RFC 0016 D21).
        """
        digest = exp.func("SHA256", exp.func("TO_UTF8", value))
        return exp.Lower(this=exp.func("TO_HEX", digest))

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``JSON_OBJECT(KEY 'k' VALUE v, …)`` — the SQL-standard spelling.

        Trino does not parse the positional form the other two accept. The
        keyword form is what SQLGlot emits for ``exp.JSONObject`` built from
        ``JSONKeyValue`` pairs.
        """
        return exp.JSONObject(
            expressions=[
                exp.JSONKeyValue(this=exp.Literal.string(key), expression=value)
                for key, value in pairs
            ]
        )
