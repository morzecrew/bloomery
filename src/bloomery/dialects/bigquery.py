"""The BigQuery dialect (S-0014): the first cloud-engine port, and the first
whose semantics are decided rather than inherited from SQLGlot's generator.

Three of this port's spellings are choices somebody made, not defaults that
happened to work on the fixture corpus:

* ``timestamp`` is ``DATETIME``, never ``TIMESTAMP`` (S-0014/D-1);
* the safe cast is ``SAFE_CAST``, and it stays one after the ``Cast →
  TryCast`` rewrite (S-0014/D-2);
* a declared ``decimal(p, s)`` is ``NUMERIC`` or ``BIGNUMERIC`` by stated
  bounds, and is refused past them (S-0014/D-7).
"""

from __future__ import annotations

from typing import ClassVar, Final, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import (
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
    "BigQueryDialect",
]

#: GoogleSQL's ``NUMERIC`` bounds as ``(integer digits, scale)``: a
#: parameterized ``NUMERIC(P, S)`` takes ``S`` in ``[0, 9]`` and ``P`` in
#: ``[max(1, S), S + 29]`` (S-0014/D-7). The precision bound is *relative to*
#: the scale because the type carries 29 integer digits and the scale extends
#: it — reading the unparameterized maximum of 38 as an independent precision
#: bound emits ``NUMERIC(38, 0)``, which is 38 integer digits into a
#: 29-integer-digit type and which BigQuery refuses to create. A declared
#: decimal inside the bounds keeps its exact precision and scale.
_NUMERIC_BOUNDS: Final = (29, 9)

#: The same for ``BIGNUMERIC``, which carries 38 integer digits: ``S`` in
#: ``[0, 38]`` and ``P`` in ``[max(1, S), S + 38]`` (S-0014/D-7). The
#: unparameterized form reaches further, but bloomery always declares both,
#: and a declared type has to mean one thing.
_BIGNUMERIC_BOUNDS: Final = (38, 38)


class BigQueryDialect(SQLGlotDialect):
    """BigQuery: SQLGlot's ``bigquery`` generator plus GoogleSQL's own types.

    ``timestamp`` is ``DATETIME`` (S-0014/D-1). bloomery's ``timestamp`` is a
    zoneless UTC wall clock (S-0021/logical-types-bloomery-typing-types-py) and BigQuery is the first
    engine bloomery targets that spells the two apart: its ``TIMESTAMP`` is an
    *instant* carrying no zone of its own, and its ``DATETIME`` is a wall clock
    carrying no instant. The zoneless one is what the type means, so the
    zoneless one is what it maps to — and every value that enters the type does
    so through :func:`~bloomery.dialects.base.utc_from_zone`, which converts to
    UTC before dropping the zone, so the wall clock this port stores is always
    the UTC one.

    Mapping to ``TIMESTAMP`` instead would read the same on the fixture corpus
    and diverge the day a session zone is not UTC: BigQuery renders and
    compares a ``TIMESTAMP`` through the session's zone, so ``DATE(ts)`` and
    any bucket derived from it would depend on the reader rather than on the
    spec — the defect S-0045 measured on the other three ports, arriving here
    through the type rather than through the conversion.

    Every :class:`~bloomery.dialects.base.DialectFeature` is declared: BigQuery
    has ``JSON``, ``ARRAY``, ``SAFE_CAST``, ``REGEXP_CONTAINS`` /
    ``REGEXP_EXTRACT``, ``NORMALIZE(x, NFC)``, positional ``JSON_OBJECT``,
    ``IS NOT DISTINCT FROM``, zone conversion, and a SHA-256 this port hexes
    below.
    """

    name: str = "bigquery"
    sqlglot_dialect: str = "bigquery"
    #: ``BEGIN`` alone opens a *block* in GoogleSQL scripting, not a
    #: transaction, so the bare spelling would run the envelope's statements
    #: outside any transaction at all rather than fail loudly.
    begin_transaction: str = "BEGIN TRANSACTION"
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "STRING",
        IntType: "INT64",
        BoolType: "BOOL",
        DateType: "DATE",
        TimestampType: "DATETIME",
        VariantType: "JSON",
    }

    # ....................... #

    def physical_type(self, t: LogicalType) -> str:
        """The GoogleSQL type for a logical type, with ``decimal(p, s)``
        placed on one of the two decimal types by its bounds (S-0014/D-7).

        ``NUMERIC`` where the declaration fits in it, ``BIGNUMERIC`` where it
        does not, and a refusal past both — never a silent widening. The two
        are not interchangeable: ``BIGNUMERIC`` reaches further and costs more
        storage, and a declaration that exceeds even its bounds has no
        representation at all here, so the only alternatives to refusing are
        dropping the precision the author declared or dropping the scale.

        What decides the placement is the *integer* digits, ``P - S``, and not
        the precision on its own: GoogleSQL bounds a parameterized type's
        precision relative to its scale (see :data:`_NUMERIC_BOUNDS`), so
        ``decimal(30, 0)`` is past ``NUMERIC`` even though 30 is under its
        unparameterized maximum of 38, while ``decimal(38, 9)`` fits.
        """

        if isinstance(t, DecimalType):
            return self._decimal_type(t)

        return self.scalar_types[type(t)]

    # ....................... #

    @staticmethod
    def _decimal_type(t: DecimalType) -> str:
        for physical, (integer_digits, scale) in (
            ("NUMERIC", _NUMERIC_BOUNDS),
            ("BIGNUMERIC", _BIGNUMERIC_BOUNDS),
        ):
            if t.scale <= scale and t.precision - t.scale <= integer_digits:
                return f"{physical}({t.precision}, {t.scale})"

        msg = (
            f"dialect 'bigquery' cannot express decimal({t.precision}, {t.scale}): "
            f"NUMERIC(P, S) holds scale <= {_NUMERIC_BOUNDS[1]} with at most "
            f"{_NUMERIC_BOUNDS[0]} integer digits (P - S) and BIGNUMERIC(P, S) holds scale <= "
            f"{_BIGNUMERIC_BOUNDS[1]} with at most {_BIGNUMERIC_BOUNDS[0]}. Fix: declare a "
            "decimal within those bounds — widening it here would store a different type than "
            "the one declared"
        )
        raise UnsupportedByTarget(msg)

    # ....................... #

    def render(self, node: Expression) -> str:
        """Render through GoogleSQL, with the zone interpretation, the ISO
        separator and the capture group spelled the way this engine spells them
        — the input node is never mutated (the port contract shares ASTs across
        dialects).

        ``to_utc`` means "interpret this zoneless wall clock as being in
        ``zone``, then keep it as a zoneless UTC wall clock" (S-0045). BigQuery
        spells the two halves as separate conversions:
        ``TIMESTAMP(<datetime>, <zone>)`` reads the wall clock in that zone and
        yields the instant, and ``DATETIME(<timestamp>, 'UTC')`` reads the
        instant back off the UTC clock. SQLGlot's own rendering of
        :class:`sqlglot.exp.AtTimeZone` nests the same two functions the other
        way round, which converts *from* UTC rather than *to* it.

        The ISO-text marker becomes a separator rewrite rather than an
        identity. GoogleSQL's ``DATETIME`` literal grammar takes the space form
        on every documented spelling, where the ``T`` and lowercase ``t`` forms
        are where engines have already been measured to disagree (S-0044,
        S-0052) — so this port takes the spelling that needs no engine to be
        asked, and :func:`~bloomery.dialects.base.space_separated` is a no-op on
        text that never carried a separator.

        The ``dim_date`` calendar's generate-series becomes an array to unnest,
        because GoogleSQL has no series-returning table function at all — see
        :func:`_unnested_series`.

        ``SAFE_CAST`` needs nothing here (S-0014/D-2): SQLGlot's bigquery
        generator renders :class:`sqlglot.exp.TryCast` as ``SAFE_CAST``, which
        is GoogleSQL's NULL-on-failure cast, so the coercion lowering's
        contract survives the ``Cast → TryCast`` rewrite the way it does on
        DuckDB and Trino rather than needing Postgres' guard.

        One consequence is recorded rather than fixed: GoogleSQL does not
        accept a *parameterized* type in a ``CAST``, so a narrowing
        ``CAST(x AS DECIMAL(12, 4))`` renders as ``CAST(x AS NUMERIC)`` and
        lands on ``NUMERIC``'s own scale of 9. The value is exact and the
        declared column type still carries the author's scale
        (:meth:`physical_type`); what is lost is the rounding the cast performs
        elsewhere. There is no spelling of the cast that keeps it. What the
        cast must keep is the *width*: a declaration past ``NUMERIC``'s bounds
        is cast to ``BIGNUMERIC`` (:func:`_wide_decimal_cast`), or a valid
        30-digit value would come back NULL from a ``SAFE_CAST`` to the
        narrower type and be quarantined on its way to a column that holds it.
        """

        def utc(at_zone: Expression) -> Expression:
            instant = exp.func("TIMESTAMP", at_zone.this, at_zone.args["zone"])
            return cast("Expression", exp.func("DATETIME", instant, exp.Literal.string("UTC")))

        rewritten: Expression = strip_iso_text(node.copy(), _space_separated_without_zulu)
        rewritten = utc_from_zone(rewritten, utc)
        # Before the guard, which reads the group: the base render restores it
        # too, but only after every port rewrite has already run.
        rewritten = capture_group(rewritten).transform(_expressible_capture_group)
        rewritten = rewritten.transform(_substr)
        rewritten = rewritten.transform(_wide_decimal_cast)
        # The replay statements build `CurrentTimestamp` directly to stamp
        # `resolved_at`/`last_evaluated_at`, never through `utc_now`. Here that
        # renders `CURRENT_TIMESTAMP()`, an *instant*, which GoogleSQL refuses
        # to assign to a `DATETIME` column — and would read through the
        # session zone if it did not (S-0045, S-0014/D-1).
        rewritten = rewritten.transform(
            lambda n: self.utc_now() if isinstance(n, exp.CurrentTimestamp) else n
        )
        _exists_for_tuple_in(rewritten)
        return super().render(rewritten.transform(_unnested_series))

    # ....................... #

    def text_sha256(self, value: Expression) -> Expression:
        """``TO_HEX(SHA256(…))``.

        GoogleSQL's ``SHA256`` returns ``BYTES``, so the plain spelling gives
        ``reject_id`` a value of the wrong type rather than the lowercase hex
        digest S-0033/D-21 requires every engine to agree on — the same gap
        Trino had, for the same reason.

        Built as :class:`sqlglot.exp.LowerHex` rather than as
        :class:`sqlglot.exp.Lower` over a ``TO_HEX`` call: SQLGlot reads
        ``TO_HEX`` as the case-*unspecified* :class:`sqlglot.exp.Hex`, whose
        bigquery rendering is ``UPPER(TO_HEX(…))``, so the obvious spelling
        lowercases an uppercasing of something already lowercase. The
        lowercase node states the contract and renders as the single call.
        """

        return exp.LowerHex(this=exp.func("SHA256", value))

    # ....................... #

    def utc_now(self) -> Expression:
        """``CURRENT_DATETIME('UTC')``.

        The zone is stated rather than inherited, for the reason the base
        spelling states it (S-0045): a bare ``CURRENT_DATETIME()`` reads off
        the *session's* clock, so two rows written at one instant by two
        readers in two zones land in different days. BigQuery has no
        ``timezone(zone, ts)`` for the base spelling to reach, and needs none —
        the zoned overload of ``CURRENT_DATETIME`` returns exactly what
        ``timestamp`` is: a zoneless wall clock already on UTC.
        """

        return cast("Expression", exp.func("CURRENT_DATETIME", exp.Literal.string("UTC")))


# ....................... #


def _wide_decimal_cast(node: Expression) -> Expression:
    """A cast to a decimal past ``NUMERIC``'s bounds targets ``BIGNUMERIC``.

    The transform chain builds ``CAST(x AS DECIMAL(P, S))`` and the quality
    path turns it into a ``TryCast``; SQLGlot's bigquery generator drops the
    parameters and renders ``NUMERIC``. For a declaration ``NUMERIC`` holds
    that is the recorded scale loss above and nothing more. For one it does not
    — ``decimal(30, 0)``, placed on ``BIGNUMERIC(30, 0)`` by
    :meth:`BigQueryDialect.physical_type` (S-0014/D-7) — a ``SAFE_CAST`` to
    ``NUMERIC`` returns NULL for a valid 30-digit value, and the quality
    system quarantines a row the declared column would have taken. The cast's
    target follows the same placement as the column's type.
    """

    if not isinstance(node, exp.Cast) or not node.to.is_type(exp.DataType.Type.DECIMAL):
        return node

    parameters = node.to.expressions

    if len(parameters) != 2:
        return node

    try:
        precision, scale = (int(parameter.name) for parameter in parameters)
    except ValueError:
        return node

    integer_digits, max_scale = _NUMERIC_BOUNDS

    if scale <= max_scale and precision - scale <= integer_digits:
        return node

    node.set("to", exp.DataType.build("BIGNUMERIC"))
    return node


# ....................... #


def _space_separated_without_zulu(text: Expression) -> Expression:
    """``RTRIM(<space-separated text>, 'Zz')``: the ISO spelling this port
    casts, with a trailing ``Z`` dropped.

    The offset guard refuses text whose time part states an offset (S-0052)
    and lets ``Z`` through, because on every other shipped port the cast
    reads ``Z`` as the UTC it is and the wall clock comes out unchanged.
    GoogleSQL's ``DATETIME`` cast does not parse a zone marker at all, so a
    valid UTC value ending in ``Z`` cast to NULL here and the quality system
    quarantined the row as a coercion failure it was not. ``Z`` is UTC, and
    the zoneless UTC wall clock is exactly what ``timestamp`` stores
    (S-0014/D-1), so dropping the marker changes no value.
    """

    return cast("Expression", exp.func("RTRIM", space_separated(text), exp.Literal.string("Zz")))


# ....................... #


def _exists_for_tuple_in(tree: Expression) -> None:
    """``(a, b) IN (SELECT x, y FROM t)`` → ``EXISTS (SELECT … FROM t WHERE x =
    a AND y = b)``, in place.

    The replay's resolution ``UPDATE`` marks the reject rows a landed row
    superseded with a row-value ``IN`` over a subquery, which every other
    shipped port accepts. GoogleSQL's ``IN`` takes a single-column subquery
    only — a tuple on its left is a syntax error — so the statement failed
    before any reject row was marked resolved. The correlated ``EXISTS`` says
    the same thing in the grammar this engine has.

    The left side names the outer row, and inside an ``UPDATE`` that row has no
    alias to name it by: the columns it shares with the subquery's table
    (``_source_row_id``) would resolve to the inner one and compare it with
    itself. So the update's target is given an alias and the left side is
    qualified by it.
    """

    for node in list(tree.find_all(exp.In)):
        query = node.args.get("query")

        if not isinstance(node.this, exp.Tuple) or query is None:
            continue

        inner = query.this if isinstance(query, exp.Subquery) else query

        if not isinstance(inner, exp.Select):
            continue

        update = node.find_ancestor(exp.Update)
        qualifier: str | None = None

        if update is not None and isinstance(update.this, exp.Table):
            if not update.this.alias:
                update.this.set("alias", exp.TableAlias(this=exp.to_identifier("_row")))

            qualifier = update.this.alias

        left = [member.copy() for member in node.this.expressions]

        if qualifier is not None:
            for member in left:
                if isinstance(member, exp.Column):
                    member.set("table", exp.to_identifier(qualifier))

        matched = inner.copy()
        matched = matched.where(
            exp.and_(
                *(
                    exp.EQ(this=projected.unalias().copy(), expression=member)
                    for projected, member in zip(inner.expressions, left, strict=True)
                )
            )
        )
        node.replace(exp.Exists(this=matched))


# ....................... #


def _substr(node: Expression) -> Expression:
    """``SUBSTRING(…)`` → ``SUBSTR(…)``.

    ``SUBSTR`` is GoogleSQL's own name for the function and SQLGlot's bigquery
    generator emits the ANSI one, which leaves the offset guard's
    ``SUBSTRING(x, 11)`` window (S-0052/D-5) resting on an alias rather than on
    the documented spelling. Both re-parse, so no rung below the engine would
    report the difference — which is the reason to spell it the engine's way
    here instead of finding out from a live lane.
    """

    if not isinstance(node, exp.Substring):
        return node

    arguments = [node.this, node.args["start"]]
    length = node.args.get("length")

    if length is not None:
        arguments.append(length)

    return exp.Anonymous(this="SUBSTR", expressions=arguments)


# ....................... #


def _unnested_series(node: Expression) -> Expression:
    """``FROM GENERATE_SERIES(a, b, step) AS t(c)`` →
    ``FROM UNNEST(GENERATE_DATE_ARRAY(a, b, step)) AS c``.

    The ``dim_date`` calendar is a FROM-clause table function on every shipped
    port (``GENERATE_SERIES`` on DuckDB and Postgres, ``UNNEST(SEQUENCE(…))``
    on Trino). GoogleSQL has no series-returning table function: it has array
    *generators*, and an array reaches the FROM clause only through ``UNNEST``.
    SQLGlot's bigquery generator renders the bare ``GENERATE_ARRAY(…)`` there
    instead, which is neither legal nor a date generator — and it re-parses
    cleanly, so no rung below the engine would report it.

    ``GENERATE_DATE_ARRAY`` where the bounds are dates and ``GENERATE_ARRAY``
    otherwise, because the two are separate functions here rather than one
    overload. The step is renumbered because GoogleSQL's ``INTERVAL`` takes an
    ``INT64`` and the neutral spelling carries the ANSI quoted form.

    The alias loses its column list: an ``UNNEST`` alias names the element
    directly, and the column list is what SQLGlot was already dropping with a
    warning nothing reads.
    """

    if not isinstance(node, exp.Table) or not isinstance(node.this, exp.GenerateSeries):
        return node

    series = node.this
    start, end = series.args["start"], series.args["end"]
    step = series.args.get("step")
    dated = isinstance(start, exp.Cast) and start.to.this is exp.DataType.Type.DATE
    arguments = [start, end] if step is None else [start, end, _int64_interval(step)]

    generator = exp.Anonymous(
        this="GENERATE_DATE_ARRAY" if dated else "GENERATE_ARRAY", expressions=arguments
    )
    node.set("this", exp.Anonymous(this="UNNEST", expressions=[generator]))

    alias = node.args.get("alias")

    if alias is not None:
        alias.set("columns", None)

    return node


# ....................... #


def _int64_interval(step: Expression) -> Expression:
    """``INTERVAL '1' DAY`` → ``INTERVAL 1 DAY``.

    GoogleSQL's interval constructor takes an ``INT64``, where the ANSI
    spelling the neutral body carries quotes the count. A step that is not a
    quoted integer is left alone — this normalizes a spelling, it does not
    reinterpret a value.
    """

    if not isinstance(step, exp.Interval):
        return step

    count = step.this

    if isinstance(count, exp.Literal) and count.is_string and count.this.isdigit():
        step.set("this", exp.Literal.number(count.this))

    return step


# ....................... #


def _expressible_capture_group(node: Expression) -> Expression:
    """Refuse a ``regex_extract`` whose group BigQuery cannot address.

    GoogleSQL's ``REGEXP_EXTRACT`` takes no group argument: it returns the
    pattern's single capturing group where there is one and the whole match
    otherwise, so group 1 is the only index it can be asked for. SQLGlot's
    bigquery generator drops any other group *silently* and returns the same
    SQL — which would answer ``{regex_extract: [pattern, 2]}`` with group 1 and
    call it a success, the failure mode S-0025/D-3 exists to convert into a
    refusal.
    """

    group = node.args.get("group") if isinstance(node, exp.RegexpExtract) else None

    if group is not None and group.name != "1":
        msg = (
            f"dialect 'bigquery' cannot extract capture group {group.name}: GoogleSQL's "
            "REGEXP_EXTRACT addresses the pattern's single capturing group and no other. "
            "Fix: rewrite the pattern so the wanted group is its only capturing one"
        )
        raise UnsupportedByTarget(msg)

    return node
