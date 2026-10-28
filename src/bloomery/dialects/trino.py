"""The Trino dialect (S-0025/D-5): the federated-engine port of the M10
port-validation milestone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import (
    SQLGlotDialect,
    epoch_timestamps,
    pick_spelled,
    space_separated,
    strip_iso_text,
    utc_from_zone,
)
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
    #: Trino implements the SQL standard here and nothing else: ``BEGIN`` is a
    #: syntax error, not a synonym. Measured against `trinodb/trino:483`.
    begin_transaction: str = "START TRANSACTION"
    #: Everything, since S-0033/D-83 split the two constructions the reject
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
        ``zone``" (S-0021/logical-types-bloomery-typing-types-py), and builds :class:`sqlglot.exp.AtTimeZone`
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
        exactly what S-0025/D-3 exists to prevent — so the divergence is
        closed here rather than documented as a caveat.

        The ISO-text marker becomes a separator rewrite, for the same reason
        one layer down. ``CAST('2026-01-06T12:00:00' AS TIMESTAMP)`` is NULL on
        Trino and a timestamp on the other two ports — Trino takes only the
        space-separated spelling, and `CAST(… AS DATE)` refuses the ``T`` form
        as well. ``REPLACE(CAST(text AS VARCHAR), 'T', ' ')`` accepts both and is a
        no-op on a value that never had one; it is applied to the *text* rather
        than to the cast because the cast may already have become a
        ``TRY_CAST`` (S-0044/D-4).
        """

        def utc(at_zone: Expression) -> Expression:
            # `with_timezone` states the zone the zoneless text was written in;
            # `at_timezone(…, 'UTC')` then moves the display to UTC and the cast
            # drops the zone, leaving a zoneless UTC value that reads the same
            # under any session (S-0045/the-fix-and-why-it-is-not-a-choice). A bare `CAST(tstz AS TIMESTAMP)`
            # would keep the value's *own* zone's wall clock instead — the
            # defect, preserved in a shape that looks like the fix.
            stated = exp.func("with_timezone", at_zone.this, at_zone.args["zone"])
            in_utc = exp.func("at_timezone", stated, exp.Literal.string("UTC"))
            return exp.cast(in_utc, exp.DataType.build("TIMESTAMP"))

        def instant(aware: exp.Cast) -> Expression:
            # Trino's zone-aware cast takes the space separator only, like its
            # zoneless one; `at_timezone` then moves the instant to UTC and the
            # cast drops the zone, as in `utc_now` (S-0081/D-2).
            aware.set("this", space_separated(aware.this))
            in_utc = exp.func("at_timezone", aware, exp.Literal.string("UTC"))
            return exp.cast(in_utc, exp.DataType.build("TIMESTAMP"))

        rewritten: Expression = strip_iso_text(node.copy(), space_separated, instant=instant)
        rewritten = epoch_timestamps(rewritten, _epoch_date_add)
        rewritten = pick_spelled(rewritten, _picked)
        return super().render(utc_from_zone(rewritten, utc))

    # ....................... #

    def partition_transform(self, transform: str) -> str:
        """``day``, ``month``, ``year`` or ``hour`` — the Iceberg connector's
        singular spelling of the spec's plural transform (S-0087/D-8).

        Trino's Iceberg catalog refuses ``days(col)``; its Hive catalog takes
        no transform at all, which is a docs matter, not a spelling.
        """
        return transform.removesuffix("s")

    # ....................... #

    def text_sha256(self, value: Expression) -> Expression:
        """``LOWER(TO_HEX(SHA256(TO_UTF8(…))))``.

        Trino's ``sha256`` takes ``varbinary`` and returns ``varbinary``, so
        the plain spelling does not even plan: *Unexpected parameters
        (varchar) for function sha256*. ``TO_UTF8`` on the way in and
        ``TO_HEX`` on the way out give the same hex digest the other dialects
        produce directly; ``LOWER`` because Trino's ``to_hex`` is uppercase
        and ``reject_id`` must agree across engines (S-0033/D-21).
        """
        digest = exp.func("SHA256", exp.func("TO_UTF8", value))
        return exp.Lower(this=exp.func("TO_HEX", digest))

    # ....................... #

    def utc_now(self) -> Expression:
        """``CAST(at_timezone(CURRENT_TIMESTAMP, 'UTC') AS TIMESTAMP)``.

        Trino has no ``timezone(zone, ts)``. ``at_timezone`` moves an instant's
        display to UTC and the cast drops the zone, which is the same two steps
        the base spelling takes in one function — and deliberately **not**
        ``with_timezone``, which states the zone of a zoneless value and is a
        type error on ``CURRENT_TIMESTAMP``, an instant that already has one.
        """

        return exp.cast(
            exp.func("at_timezone", exp.CurrentTimestamp(), exp.Literal.string("UTC")),
            exp.DataType.build("TIMESTAMP"),
        )

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


# ....................... #


def _epoch_date_add(count: Expression, per_second: int) -> Expression:
    """``date_add('second', n, TIMESTAMP '1970-01-01 00:00:00.000000')`` (or
    ``'millisecond'``): zoneless, where ``from_unixtime`` returns a zoned value
    read in the session zone (S-0096/D-7). The literal carries six digits so a
    millisecond count keeps its fraction."""

    unit = "second" if per_second == 1 else "millisecond"
    epoch = exp.cast(
        exp.Literal.string("1970-01-01 00:00:00.000000"), exp.DataType.build("TIMESTAMP(6)")
    )
    return exp.Anonymous(this="date_add", expressions=[exp.Literal.string(unit), count, epoch])


def _picked(items: Expression, field: str, text: str, take: str, json: bool) -> Expression:
    """``pick`` on Trino (S-0095/D-4): ``json_extract_scalar`` of the take from
    the first element ``filter`` keeps whose field reads as the text.
    ``json_extract_scalar`` is NULL for an object or an array, which is the
    scalar rule on both the field and the take. Text is parsed with a guarded
    ``json_parse`` before the ``ARRAY(JSON)`` cast, which takes a JSON value: a
    cast from text to ``JSON`` would make a JSON string."""

    field_path = exp.Literal.string(f"$.{field}").sql(dialect="trino")
    take_path = exp.Literal.string(f"$.{take}").sql(dialect="trino")
    matched = exp.Literal.string(text).sql(dialect="trino")
    value = "pick_list" if json else "TRY(json_parse(pick_list))"
    template = (
        f"json_extract_scalar(element_at(filter(TRY_CAST({value} AS ARRAY(JSON)), "
        f"e -> json_extract_scalar(e, {field_path}) = {matched}), 1), {take_path})"
    )

    def substituted(child: Expression) -> Expression:
        if isinstance(child, exp.Column) and child.name == "pick_list":
            return items.copy()
        return child

    return cast("Expression", parse_one(template, read="trino")).transform(substituted)
