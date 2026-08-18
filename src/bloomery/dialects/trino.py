"""The Trino dialect (RFC 0008 D5): the federated-engine port of the M10
port-validation milestone."""

from __future__ import annotations

from collections.abc import Sequence
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

    def render(self, node: Expression) -> str:
        """Render with zone *interpretation* spelled the way Trino spells it —
        the input node is never mutated (the port contract shares ASTs across
        dialects).

        ``to_utc`` means "interpret this zoneless timestamp as being in
        ``zone``" (RFC 0004 §5.1), and builds :class:`sqlglot.exp.AtTimeZone`
        for it because that is what ``AT TIME ZONE`` means on DuckDB and on
        PostgreSQL — both return the instant 11:00Z for a 12:00 value read as
        ``Europe/Berlin``.

        Trino's ``AT TIME ZONE`` means something else. Given a zoneless
        timestamp it promotes the value with the **session** zone first and
        only then converts to the named one, so the instant is unchanged and
        the argument moves nothing but the display: with the session on UTC,
        ``CAST('2026-01-06 12:00:00' AS TIMESTAMP) AT TIME ZONE
        'Europe/Berlin'`` is instant 12:00Z, an hour later than the other two
        ports produce from the same spec. ``with_timezone`` is Trino's
        spelling of the interpretation, and returns 11:00Z as they do
        (verified against trinodb/trino:483).

        One spec meaning two things on two engines, announced nowhere, is
        exactly what RFC 0008 D3 exists to prevent — so the divergence is
        closed here rather than documented as a caveat.
        """
        rewritten: Expression = node.copy()
        for at_zone in reversed(tuple(rewritten.find_all(exp.AtTimeZone))):
            interpretation = cast(
                "Expression", exp.func("with_timezone", at_zone.this, at_zone.args["zone"])
            )
            if at_zone is rewritten:
                rewritten = interpretation
            else:
                at_zone.replace(interpretation)
        return super().render(rewritten)

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
