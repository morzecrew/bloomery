"""The Trino dialect (RFC 0008 D5): the federated-engine port of the M10
port-validation milestone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import SQLGlotDialect, strip_iso_text, utc_from_zone
from bloomery.typing import (
    BoolType,
    DateType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

# ----------------------- #

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

    # ....................... #

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

        The ISO-text marker becomes a separator rewrite, for the same reason
        one layer down. ``CAST('2026-01-06T12:00:00' AS TIMESTAMP)`` is NULL on
        Trino and a timestamp on the other two ports — Trino takes only the
        space-separated spelling, and `CAST(… AS DATE)` refuses the ``T`` form
        as well. ``REPLACE(text, 'T', ' ')`` accepts both and is a no-op on a
        value that never had one; it is applied to the *text* rather than to
        the cast because the cast may already have become a ``TRY_CAST``
        (RFC 0027 D4).
        """

        def space_separated(text: Expression) -> Expression:
            replaced = exp.func("replace", text, exp.Literal.string("T"), exp.Literal.string(" "))
            return cast("Expression", replaced)

        def utc(at_zone: Expression) -> Expression:
            # `with_timezone` states the zone the zoneless text was written in;
            # `at_timezone(…, 'UTC')` then moves the display to UTC and the cast
            # drops the zone, leaving a zoneless UTC value that reads the same
            # under any session (RFC 0028 §3). A bare `CAST(tstz AS TIMESTAMP)`
            # would keep the value's *own* zone's wall clock instead — the
            # defect, preserved in a shape that looks like the fix.
            stated = exp.func("with_timezone", at_zone.this, at_zone.args["zone"])
            in_utc = exp.func("at_timezone", stated, exp.Literal.string("UTC"))
            return exp.cast(in_utc, exp.DataType.build("TIMESTAMP"))

        rewritten: Expression = strip_iso_text(node.copy(), space_separated)
        return super().render(utc_from_zone(rewritten, utc))

    # ....................... #

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

    # ....................... #

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
