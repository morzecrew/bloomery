"""The Databricks SQL dialect (S-0016): the lakehouse port.

Databricks SQL and nothing else (S-0016/D-9). The port renders text and only
text — no Spark session, no driver, no cloud SDK (S-0016/D-1) — so every claim
here is a claim about the *rewrite*, and the engine-side evidence belongs to
the live lane the same document describes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import (
    DialectFeature,
    SQLGlotDialect,
    capture_group,
    space_separated,
    strip_iso_text,
    utc_from_zone,
)
from bloomery.errors import UnsupportedByTarget
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

# ----------------------- #

__all__ = [
    "DatabricksDialect",
]

#: The zoneless wall-clock timestamp type. A bloomery ``timestamp`` is always
#: UTC and zoneless (S-0021), and Databricks' plain ``TIMESTAMP`` is an
#: *instant* rendered through the session zone — the S-0045 defect by another
#: spelling. Every neutral ``TIMESTAMP`` in a tree becomes this one.
_NTZ: Final = "TIMESTAMP_NTZ"

#: Databricks' maximum ``DECIMAL`` precision.
_MAX_DECIMAL_PRECISION: Final = 38

#: Databricks' reserved words (the ANSI SQL-2016 reserved set Databricks
#: adopts). They may not name a table or a column unquoted while ANSI mode is
#: on, which it is by default on a SQL warehouse; SQLGlot's databricks
#: generator carries no reserved-word set at all, so ``FROM silver.order``
#: renders bare and fails to parse on the engine. Quoted here, with backticks,
#: exactly as the Postgres port quotes its own.
_RESERVED = frozenset(
    {
        "all", "and", "any", "as", "authorization", "both", "case", "cast",
        "check", "collate", "column", "constraint", "create", "cross",
        "current_date", "current_time", "current_timestamp", "current_user",
        "distinct", "else", "end", "escape", "except", "false", "fetch",
        "filter", "for", "foreign", "from", "full", "grant", "group",
        "having", "in", "inner", "intersect", "into", "is", "join",
        "lateral", "leading", "left", "natural", "not", "null", "on", "only",
        "or", "order", "outer", "overlaps", "primary", "references", "right",
        "select", "session_user", "some", "table", "then", "time", "to",
        "trailing", "union", "unique", "unknown", "user", "using", "when",
        "where", "with",
    }
)  # fmt: skip


class DatabricksDialect(SQLGlotDialect):
    """Databricks SQL: SQLGlot's ``databricks`` generator plus the rewrites
    this engine needs.

    ``timestamp`` is ``TIMESTAMP_NTZ`` (S-0016/D-8). The alternative,
    ``TIMESTAMP``, is an instant whose every derived date, hour and bucket
    reads the *session* zone — two rows at one instant landing on two days for
    two readers, which is the defect S-0045 removed from the three shipped
    ports and which this port would reintroduce by inheriting a default. The
    choice pins the surrogate session to ANSI mode, where a failing ``CAST``
    raises rather than yielding NULL and ``TRY_CAST`` is the NULL-on-failure
    cast the quality layer needs.

    ``variant`` is ``STRING``. Databricks has no ``JSON`` type — SQLGlot
    renders the neutral ``CAST(x AS JSON)`` verbatim, naming a type the engine
    does not have — and the ``:`` accessor SQLGlot lowers ``json_path`` to
    reads JSON out of a ``STRING`` column directly. The native ``VARIANT`` is
    deliberately not reached for: it is runtime-gated, it needs
    ``parse_json`` rather than a cast, and ``variant`` here promises only
    semi-structured access, which the string carrier already gives.
    """

    name: str = "databricks"
    sqlglot_dialect: str = "databricks"
    #: Databricks SQL has **no** multi-statement transaction: every statement
    #: is its own atomic Delta commit and ``BEGIN`` is not a synonym for
    #: anything. The inherited spelling is kept rather than invented, and the
    #: dbt replay envelope that interpolates it (the only reader) is not
    #: claimed by this port — dbt-on-Databricks is no cell of this phase's
    #: matrix.
    begin_transaction: str = "BEGIN"
    #: Everything but :attr:`DialectFeature.UNICODE_NORMALIZE`: Databricks has
    #: no ``NORMALIZE`` and no equivalent of DuckDB's ``nfc_normalize``, so a
    #: ``normalize`` rule is refused at emit rather than rendered into a call
    #: nothing defines (S-0025/D-3). The rest have a spelling here — several of
    #: them this port's own, below.
    features: ClassVar[frozenset[DialectFeature]] = frozenset(DialectFeature) - {
        DialectFeature.UNICODE_NORMALIZE
    }
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "STRING",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: _NTZ,
        VariantType: "STRING",
    }

    # ....................... #

    def render(self, node: Expression) -> str:
        """Render for Databricks SQL — the input node is never mutated (the
        port contract shares ASTs across dialects).

        Six rewrites, each for a construction SQLGlot renders *plausibly* and
        this engine reads differently or not at all:

        * zone interpretation, which SQLGlot lowers to ``FROM_UTC_TIMESTAMP``
          — the opposite direction (see :func:`_to_utc`);
        * the ISO-text marker, which becomes a separator rewrite: Databricks'
          own parser takes ``T`` and the space form but not the lowercase
          ``t`` ISO 8601 also permits, and under ANSI mode that is a raised
          error rather than a NULL;
        * ``regexp_extract``, whose capture index SQLGlot's databricks
          generator drops exactly as its duckdb and trino ones do
          (S-0045/D-5), and whose default index here is **1** rather than 0 —
          so the index is always stated (:func:`_regexp_extract`);
        * ``to_timestamp``, which returns a session-zone instant
          (:func:`_zoneless_parse`);
        * the calendar's series table, whose alias SQLGlot folds into the
          ``EXPLODE`` call as a second argument (:func:`_series_table`);
        * date truncation, which SQLGlot lowers to ``TRUNC``, a function that
          takes none of the units below a month (:func:`_date_trunc`).

        Then the physical types: every neutral ``TIMESTAMP`` becomes
        ``TIMESTAMP_NTZ`` and every neutral ``JSON`` becomes ``STRING``, so a
        cast inside an expression agrees with the column's declared type
        rather than quietly meaning the other thing.
        """

        # Before `_regexp_extract`, which has to read the capture group to
        # spell the call at all; the base render applies it again, and a tree
        # that already names a group is untouched.
        rewritten = capture_group(node.copy())
        rewritten = strip_iso_text(rewritten, space_separated)
        rewritten = utc_from_zone(rewritten, _to_utc)
        rewritten = rewritten.transform(_zoneless_parse)
        rewritten = rewritten.transform(_regexp_extract)
        rewritten = rewritten.transform(_series_table)
        rewritten = rewritten.transform(_date_trunc)
        rewritten = rewritten.transform(_physical_types)

        for identifier in rewritten.find_all(exp.Identifier):
            if identifier.this.lower() in _RESERVED:
                identifier.set("quoted", True)

        return super().render(rewritten)

    # ....................... #

    def physical_type(self, t: LogicalType) -> str:
        """The engine type for a logical type, refusing a decimal this engine
        cannot hold.

        Databricks caps ``DECIMAL`` at precision 38. A wider declaration is a
        compile-time refusal rather than a column the warehouse rejects when
        the first ``CREATE TABLE`` runs, or — worse — a value silently
        rounded (S-0025/D-3).
        """

        if isinstance(t, DecimalType) and t.precision > _MAX_DECIMAL_PRECISION:
            msg = (
                f"dialect 'databricks' cannot hold decimal({t.precision}, {t.scale}): "
                f"DECIMAL precision is capped at {_MAX_DECIMAL_PRECISION} on this engine. "
                f"Fix: declare a precision of {_MAX_DECIMAL_PRECISION} or less"
            )
            raise UnsupportedByTarget(msg)

        return super().physical_type(t)

    # ....................... #

    def utc_now(self) -> Expression:
        """``CAST(TO_UTC_TIMESTAMP(CURRENT_TIMESTAMP(), CURRENT_TIMEZONE()) AS TIMESTAMP_NTZ)``.

        Databricks has no ``timezone(zone, ts)`` the base spelling reaches for.
        ``CURRENT_TIMESTAMP()`` is an instant, so its wall clock is the
        session's; naming that same zone as the one to interpret it in is what
        turns the session's clock into UTC's, and the cast then keeps the wall
        clock rather than the instant. Session-independent by construction:
        whatever the session zone is, it appears on both sides and cancels.
        """

        return exp.cast(
            exp.func("TO_UTC_TIMESTAMP", exp.CurrentTimestamp(), exp.func("CURRENT_TIMEZONE")),
            exp.DataType.build(_NTZ),
        )

    # ....................... #

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``TO_JSON(NAMED_STRUCT('k', v, …))``.

        Databricks has no ``json_object`` function in either the positional or
        the ``KEY … VALUE`` form. ``named_struct`` takes the alternating pairs
        the other ports' builders take, and ``to_json`` serializes the struct
        to the JSON text the reject table's ``raw`` and ``key_values`` carry
        (S-0033/D-83).
        """
        arguments: list[Expression] = []

        for key, value in pairs:
            arguments.extend((exp.Literal.string(key), value))

        return cast("Expression", exp.func("TO_JSON", exp.func("NAMED_STRUCT", *arguments)))


# ....................... #


def _to_utc(at_zone: Expression) -> Expression:
    """``CAST(TO_UTC_TIMESTAMP(x, zone) AS TIMESTAMP_NTZ)``.

    ``to_utc`` means *interpret this zoneless timestamp as being in zone*
    (S-0021) and is the only door into the always-UTC ``timestamp`` type.
    SQLGlot renders the neutral :class:`sqlglot.exp.AtTimeZone` on this dialect
    as ``FROM_UTC_TIMESTAMP(x, zone)`` — which is the *other* direction: it
    reads the value as UTC and renders it in ``zone``, so every interpreted
    instant would come out wrong by twice the offset and nothing would say so.

    ``to_utc_timestamp`` is the right half of that pair, and it is a wall-clock
    function: it reads the value's wall clock, treats it as being in ``zone``,
    and produces the UTC wall clock. The cast keeps that clock and drops the
    zone, which is what the type is.
    """

    shifted = exp.func("TO_UTC_TIMESTAMP", at_zone.this.copy(), at_zone.args["zone"].copy())
    return exp.cast(shifted, exp.DataType.build(_NTZ))


# ....................... #


def _zoneless_parse(node: Expression) -> Expression:
    """``TO_TIMESTAMP(x, fmt)`` → ``CAST(TO_TIMESTAMP(x, fmt) AS TIMESTAMP_NTZ)``.

    ``parse_ts`` parses a *local wall clock*, and ``to_utc`` is the only door
    into the always-UTC ``timestamp`` type, so this step must produce the clock
    that was written. Databricks' ``to_timestamp`` returns a ``TIMESTAMP``
    instead — the parsed clock with the **session** zone attached — so the same
    row would store a different instant depending on who ran it, the defect
    S-0046 measured on PostgreSQL's ``to_timestamp``.

    The cast is the fix and not a formality: Databricks converts ``TIMESTAMP``
    to ``TIMESTAMP_NTZ`` by taking the session-zone wall clock, which is
    exactly the clock ``to_timestamp`` just attached the zone to, so the two
    cancel and the written clock comes back under every session.

    ``parse_date``'s ``TO_DATE`` needs none of this: it returns ``DATE``, which
    has no zone to attach.
    """

    if not isinstance(node, exp.StrToTime):
        return node

    return exp.cast(node, exp.DataType.build(_NTZ))


# ....................... #


def _regexp_extract(node: Expression) -> Expression:
    """``REGEXP_EXTRACT(x, p, n)`` with the capture index always stated.

    Two independent reasons, and either alone would be enough. SQLGlot's
    databricks generator drops the ``group`` argument silently, the way its
    duckdb and trino generators did until S-0045/D-5 — so ``{regex_extract:
    [pattern, 1]}`` would return the whole match. And this engine's default
    index is **1**, where DuckDB's and Trino's is 0, so even an omitted
    argument means something different here: stating it is the only spelling
    that means the same thing on all four ports.
    """

    if not isinstance(node, exp.RegexpExtract):
        return node

    group = node.args.get("group") or exp.Literal.number(0)
    # `exp.Anonymous` rather than `exp.func("REGEXP_EXTRACT", …)`: the latter
    # resolves back to `exp.RegexpExtract`, whose third positional argument
    # binds to `position` and is then dropped by the generator again — the
    # rewrite would render exactly what it exists to repair.
    return exp.Anonymous(
        this="REGEXP_EXTRACT",
        expressions=[node.this.copy(), node.expression.copy(), group.copy()],
    )


# ....................... #


def _series_table(node: Expression) -> Expression:
    """``GENERATE_SERIES(a, b, s) AS t(c)`` → ``EXPLODE(SEQUENCE(a, b, s)) AS t(c)``.

    ``dim_date``'s calendar is a FROM-clause table function over a neutral
    ``GENERATE_SERIES``. SQLGlot's databricks generator turns the series into
    ``EXPLODE(SEQUENCE(...))`` correctly but folds the table alias *into the
    call* — ``EXPLODE(SEQUENCE(...), _u(date_day))`` — which names a
    two-argument ``explode`` the engine does not have, so the only artifact
    that needs the rewrite is also the only one that would not run.

    Wrapping the series in an opaque call leaves nothing for the generator to
    fold: the alias stays a table alias and renders ``AS date_day(date_day)``,
    the same column name the three shipped ports resolve.
    """

    if not isinstance(node, exp.Table):
        return node

    series = node.this

    if not isinstance(series, exp.GenerateSeries) or node.args.get("alias") is None:
        return node

    arguments = [
        series.args[key].copy() for key in ("start", "end", "step") if series.args.get(key)
    ]
    return exp.Table(
        this=exp.Anonymous(this="EXPLODE", expressions=[exp.func("SEQUENCE", *arguments)]),
        alias=node.args["alias"].copy(),
    )


# ....................... #


def _date_trunc(node: Expression) -> Expression:
    """``DATE_TRUNC(unit, x)`` with the unit stated as a string, never ``TRUNC``.

    SQLGlot's databricks generator lowers the neutral ``DATE_TRUNC('DAY', x)``
    to ``TRUNC(x, 'DAY')``. Databricks' ``trunc`` takes only the units at or
    above a week — ``WEEK``, ``MONTH``/``MM``/``MON``, ``QUARTER``,
    ``YEAR``/``YYYY``/``YY`` — and returns NULL for anything finer, so the day
    bucket every mart's time column is built from would be silently empty:
    ``ordered_day`` is both the incremental time column and the partition key.
    ``date_trunc`` takes the whole ladder including ``DAY`` and below, and it
    is what the three shipped ports render, so the four cells agree again.

    The call is opaque rather than rebuilt from :class:`sqlglot.exp.DateTrunc`,
    because the generator would lower whatever is handed back to ``TRUNC``
    again — the same reason :func:`_regexp_extract` is opaque.
    """

    if not isinstance(node, exp.DateTrunc | exp.TimestampTrunc):
        return node

    unit = node.args["unit"]
    # `DateTrunc` carries a string literal, `TimestampTrunc` a bare `Var`.
    name = unit.name if isinstance(unit, exp.Var | exp.Literal) else unit.sql()
    return exp.Anonymous(
        this="DATE_TRUNC",
        expressions=[exp.Literal.string(name.upper()), node.this.copy()],
    )


# ....................... #


def _physical_types(node: Expression) -> Expression:
    """A neutral ``TIMESTAMP`` is ``TIMESTAMP_NTZ`` here, and a neutral
    ``JSON`` is ``STRING``.

    Both are the type map applied *inside* expressions. A column declared
    ``timestamp`` is ``TIMESTAMP_NTZ``, so a cast in the expression that fills
    it has to say the same thing — otherwise the value is built as an instant
    and stored as a wall clock, which is the zone bug wearing the right column
    type. Likewise ``JSON``, which this engine does not have at all.
    """

    if not isinstance(node, exp.DataType):
        return node

    if node.this is exp.DataType.Type.TIMESTAMP:
        return exp.DataType.build(_NTZ)

    if node.this is exp.DataType.Type.JSON:
        return exp.DataType.build("STRING")

    return node
