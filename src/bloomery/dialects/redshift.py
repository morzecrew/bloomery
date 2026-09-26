"""The Redshift dialect (S-0015): the warehouse-engine port, written against
Redshift's own semantics.

:class:`RedshiftDialect` deliberately does **not** subclass
:class:`~bloomery.dialects.postgres.PostgresDialect` (S-0015/D-1). Redshift
forked PostgreSQL 8.0 and has diverged for two decades: ``pg_input_is_valid``,
``JSONB``, ``NORMALIZE``, arrays and ``regexp_substr``'s capture-group argument
are all PostgreSQL spellings Redshift either rejects or reads differently, and
inheritance would make every one of them silently legal here. Each rewrite the
PostgreSQL port carries was audited against Redshift separately; the two that
survive the audit — :func:`~bloomery.dialects.postgres.zoneless_parse` and
:func:`~bloomery.dialects.postgres.ends_with_as_right` — are imported as named
helpers, which is what S-0015/D-1 permits (S-0015/D-7).

What the audit rejected, and why:

``_variant_is_jsonb``
    Redshift has no ``JSONB``, and SQLGlot's redshift generator renders
    ``CAST(x AS JSON)`` as a **no-op** — the cast disappears and the value stays
    whatever it was. ``variant`` is ``SUPER`` here and the cast becomes
    ``JSON_PARSE`` (S-0015/D-4) — see :func:`_super_cast`.

``_jsonb_extraction``
    ``SUPER`` and PartiQL are a different data model, not a different spelling
    of ``jsonb``'s operators, so the ``->`` chain is not translated — the port
    refuses ``json_path`` until the PartiQL navigation is built (S-0015/D-4).

``_guarded_try_cast`` / ``pg_input_is_valid``
    The guard is a PostgreSQL system function Redshift does not define, and it
    exists only because PostgreSQL lacks ``TRY_CAST``. Redshift renders
    ``TRY_CAST`` natively for a scalar type, so there is nothing to guard —
    with one exception, which is why the guard shape reappears in
    :func:`_super_cast` rather than disappearing: ``SUPER`` has no ``TRY_CAST``.

the reserved-word list
    SQLGlot's redshift generator carries its own ``RESERVED_KEYWORDS`` and
    quotes them (``x."order"``), unlike its postgres generator, which quotes
    nothing and is why the PostgreSQL port keeps a list. Redshift's list is not
    PostgreSQL's — ``aes128``, ``allowoverwrite``, ``sysdate`` are reserved here
    and unknown there — so carrying PostgreSQL's would be both redundant and
    short.

``regexp_substr``'s capture group
    PostgreSQL 15's six-argument form takes the group as its **sixth**
    argument. Redshift's takes at most five and reads the third as a *start
    position*, so the PostgreSQL spelling would silently mean something else;
    the group is expressed through the ``'e'`` match parameter instead, which
    reaches the first subexpression only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import ClassVar, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import (
    DialectFeature,
    SQLGlotDialect,
    capture_group,
    strip_iso_text,
    utc_from_zone,
)
from bloomery.dialects.postgres import ends_with_as_right, zoneless_parse
from bloomery.errors import UnsupportedByTarget
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
    "RedshiftDialect",
]

#: ``REGEXP_SUBSTR``'s match parameters. ``'c'`` is case-sensitive matching —
#: the default, spelled out so the argument list reaches the fifth position;
#: ``'e'`` additionally extracts the pattern's **first** subexpression, which is
#: the only capture group Redshift can name.
_WHOLE_MATCH = "c"
_FIRST_GROUP = "e"


class RedshiftDialect(SQLGlotDialect):
    """Redshift: SQLGlot's ``redshift`` generator plus Redshift's own types.

    ``string`` is ``VARCHAR(MAX)``, not ``TEXT``. Redshift accepts ``TEXT`` as a
    column type and quietly means ``VARCHAR(256)`` by it — a truncation that
    looks like a working column until a value exceeds it, which is the class of
    silent data loss S-0025/D-3 refuses.

    ``variant`` is ``SUPER``: Redshift's semi-structured type, navigated with
    PartiQL rather than with ``jsonb``'s operators (S-0015/D-4).
    """

    name: str = "redshift"
    sqlglot_dialect: str = "redshift"
    #: Everything except three, each a capability Redshift genuinely lacks
    #: rather than spells differently:
    #:
    #: ``ARRAY`` — Redshift has no array *column* type. ``SUPER`` can hold an
    #: array and ``ARRAY()`` constructs one, but a table column cannot be
    #: declared ``VARCHAR[]``, so ``_quality_flags`` and ``failed_rules`` take
    #: the delimited-string fallback (S-0015/D-6).
    #:
    #: ``UNICODE_NORMALIZE`` — Redshift defines no normalization function at
    #: all; ``NORMALIZE(x, NFC)`` renders verbatim and fails at run time. This
    #: is the case :class:`DialectFeature`'s own note anticipates: a port
    #: without one refuses the rule rather than emitting a function nothing
    #: defines.
    #:
    #: ``JSON_EXTRACT`` — see :func:`_refuse_super_navigation`.
    features: ClassVar[frozenset[DialectFeature]] = frozenset(DialectFeature) - {
        DialectFeature.ARRAY,
        DialectFeature.UNICODE_NORMALIZE,
        DialectFeature.JSON_EXTRACT,
    }
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "VARCHAR(MAX)",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "SUPER",
    }

    # ....................... #

    def render(self, node: Expression) -> str:
        """Render Redshift's spellings — the input node is never mutated (the
        port contract shares ASTs across dialects).

        The ISO-text marker strips to nothing. Redshift's datetime input
        accepts the ``T`` separator, as PostgreSQL's does, so there is nothing
        for this port to add (S-0044); the offset refusal
        :func:`~bloomery.dialects.base.strip_iso_text` wraps around it arrives
        with the call rather than being remembered separately.

        ``capture_group`` runs first because :func:`_regexp_substr` has to read
        the group to choose a match parameter at all; the base render applies it
        again, and a tree that already names a group is untouched.
        """

        rewritten = capture_group(node.copy())
        rewritten = strip_iso_text(rewritten, lambda text: text)
        rewritten = utc_from_zone(rewritten, _convert_timezone)
        rewritten = rewritten.transform(zoneless_parse)
        rewritten = rewritten.transform(ends_with_as_right)
        rewritten = rewritten.transform(_starts_with_as_left)
        rewritten = rewritten.transform(_regexp_substr)
        rewritten = rewritten.transform(_super_cast)
        rewritten = rewritten.transform(_null_if_invalid)
        rewritten = rewritten.transform(_date_spine)
        # The replay statements build `CurrentTimestamp` directly to stamp
        # `resolved_at`/`last_evaluated_at`, never through `utc_now`; the
        # generator spells it `GETDATE()`, the session's wall clock, which is
        # the S-0045 defect arriving through a node the emit layer builds.
        rewritten = rewritten.transform(
            lambda n: self.utc_now() if isinstance(n, exp.CurrentTimestamp) else n
        )
        _refuse_super_navigation(rewritten)
        return super().render(rewritten)

    # ....................... #

    def utc_now(self) -> Expression:
        """``CAST(CONVERT_TIMEZONE('UTC', CAST(GETDATE() AS TIMESTAMP WITH TIME ZONE)) AS TIMESTAMP)``.

        Redshift has no ``timezone(zone, ts)``, so the base spelling would emit
        a function it does not define. Two Redshift facts pick the operand:

        * ``CURRENT_TIMESTAMP`` (and ``NOW``) is leader-node-only, and a
          statement that also references a user table is rejected outright
          ("not supported on Redshift tables"). The one caller is the replay
          ``INSERT INTO bronze.<relation> … SELECT … FROM
          silver.<entity>__reject``, which reads a user table, so the
          zone-aware clock cannot be used at all.
        * ``GETDATE()`` runs on the compute nodes but returns a *zoneless*
          value in the session's zone, and two-argument ``CONVERT_TIMEZONE``
          reads a zoneless operand as UTC — handing it ``GETDATE()`` under a
          non-UTC session would relabel the session's wall clock as UTC and
          move the instant (the S-0045 defect wearing the shape of the fix).

        The cast between them is what makes the spelling correct: casting a
        ``TIMESTAMP`` to ``TIMESTAMPTZ`` attaches the session zone, which is
        exactly the zone ``GETDATE()`` reported in, so ``CONVERT_TIMEZONE``
        then has a real zone to convert from and lands the instant in UTC,
        under any session zone, on the compute nodes. The functions that
        would read the session zone back explicitly (``CURRENT_SETTING``)
        are leader-node-only too, which is why the cast carries it instead.
        """

        return exp.cast(
            exp.Anonymous(
                this="CONVERT_TIMEZONE",
                expressions=[
                    exp.Literal.string("UTC"),
                    exp.cast(exp.func("GETDATE"), exp.DataType.build("TIMESTAMPTZ")),
                ],
            ),
            exp.DataType.build("TIMESTAMP"),
        )

    # ....................... #

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``OBJECT('k', v, …)`` — Redshift's ``SUPER`` constructor.

        Redshift has no ``JSON_OBJECT``; SQLGlot inherits PostgreSQL's handling
        and renders the SQL-standard ``JSON_OBJECT('k': v)``, which Redshift
        does not parse. ``OBJECT`` takes the same positional key/value sequence
        and yields ``SUPER``, which is what ``variant`` is on this port.
        """
        arguments: list[Expression] = []

        for key, value in pairs:
            arguments.extend((exp.Literal.string(key), value))

        return cast("Expression", exp.func("OBJECT", *arguments))


# ....................... #


def _convert_timezone(at_zone: Expression) -> Expression:
    """``x AT TIME ZONE 'z'`` → ``CONVERT_TIMEZONE('z', 'UTC', x)``.

    ``to_utc`` states the zone a zoneless wall clock was written in and must
    land in the always-UTC zoneless ``timestamp`` type (S-0021). Redshift's
    three-argument ``CONVERT_TIMEZONE(source, target, ts)`` is exactly that in
    one call: it reads ``x`` as being in ``source`` and returns a zoneless
    ``TIMESTAMP`` in ``target``, so no second step and no cast are needed.

    Deliberately not PostgreSQL's ``x AT TIME ZONE 'z' AT TIME ZONE 'UTC'``
    chain: Redshift's ``AT TIME ZONE`` promotes through the *session* zone the
    way Trino's does (S-0025/D-3), so the double application does not cancel.
    """

    return cast(
        "Expression",
        exp.func(
            "CONVERT_TIMEZONE",
            at_zone.args["zone"].copy(),
            exp.Literal.string("UTC"),
            at_zone.this.copy(),
        ),
    )


# ....................... #


def _starts_with_as_left(node: Expression) -> Expression:
    """``STARTS_WITH(x, p)`` → ``LEFT(x, LENGTH(p)) = p``.

    Redshift defines no ``starts_with`` — the mirror of the gap PostgreSQL has
    at ``ends_with``, and the reason this port needs a rewrite its neighbour
    does not. SQLGlot's redshift generator does supply one, ``x LIKE p || '%'``,
    and it is wrong for this use: ``LIKE`` reads ``%`` and ``_`` in the prefix
    as wildcards, so ``strip_prefix`` over a prefix containing either would
    match values it must not. ``LEFT``/``LENGTH`` is exact.
    """

    if not isinstance(node, exp.StartsWith):
        return node

    prefix = node.expression
    head = exp.func("LEFT", node.this.copy(), exp.Length(this=prefix.copy()))
    return exp.EQ(this=cast("Expression", head), expression=prefix.copy())


# ....................... #


def _regexp_substr(node: Expression) -> Expression:
    """``REGEXP_EXTRACT(x, p, n)`` → ``REGEXP_SUBSTR(x, p, 1, 1, 'c'|'e')``.

    Redshift has no ``regexp_extract``, and its ``regexp_substr`` is **not**
    PostgreSQL 15's: it takes ``(source, pattern, position, occurrence,
    parameters)`` and stops there. PostgreSQL's sixth argument — the capture
    group index — has no counterpart, and SQLGlot renders
    ``REGEXP_EXTRACT(x, p, 1)`` here as ``REGEXP_SUBSTR(x, p, 1)``, where the
    ``1`` binds to *position* and the group is silently gone. That is the
    "plausible-looking spelling the engine reads differently" S-0015/D-1 is
    about, and it is why this port does not inherit ``_pg_text_functions``.

    The group is expressed through the ``'e'`` match parameter, which extracts
    the pattern's first subexpression. Redshift can name no other, so a group
    index above one is refused rather than approximated with the whole match
    (S-0025/D-3).
    """

    if not isinstance(node, exp.RegexpExtract):
        return node

    group = node.args.get("group")
    index = int(group.name) if group is not None else 0

    if index > 1:
        msg = (
            f"regex_extract asks for capture group {index}, and dialect 'redshift' can "
            "name only the first: REGEXP_SUBSTR's 'e' match parameter extracts the "
            "pattern's first subexpression and Redshift has no group-index argument. "
            "Fix: rewrite the pattern so the wanted group is the first subexpression, "
            "or compile this project for a dialect whose regexp_extract takes an index"
        )
        raise UnsupportedByTarget(msg)

    parameters = _FIRST_GROUP if index == 1 else _WHOLE_MATCH

    return cast(
        "Expression",
        exp.func(
            "REGEXP_SUBSTR",
            node.this.copy(),
            node.expression.copy(),
            exp.Literal.number(1),  # start position
            exp.Literal.number(1),  # first match
            exp.Literal.string(parameters),
        ),
    )


# ....................... #


def _super_cast(node: Expression) -> Expression:
    """A neutral cast to ``JSON`` becomes ``SUPER`` construction (S-0015/D-4).

    ``variant`` is ``SUPER`` here, and the *neutral* type for it is ``JSON`` —
    what :func:`bloomery.transforms.neutral_type` names and what every neutral
    variant cast in the tree therefore says. SQLGlot's redshift generator
    renders that cast as a **no-op**: ``CAST(x AS JSON)`` emits ``x``, so a
    ``variant`` transform silently produced whatever it was handed, usually
    ``VARCHAR``. ``JSON_PARSE`` is Redshift's own text-to-``SUPER`` constructor
    and is what the cast means here.

    ``TRY_CAST`` keeps its NULL-on-failure meaning, and that is the whole reason
    this function distinguishes the two rather than rewriting
    :class:`sqlglot.exp.Cast` — which :class:`sqlglot.exp.TryCast` is a subclass
    of. ``JSON_PARSE`` *raises* on malformed input and Redshift has no
    ``TRY_CAST`` to ``SUPER``, so a bare ``JSON_PARSE`` under the quality system
    would abort the run where the spec says quarantine the row: the
    ``coercible`` rule's failure marker is "the cast produced NULL", and a cast
    that cannot produce one can never fire it. ``CAN_JSON_PARSE`` is Redshift's
    own answer to "would ``JSON_PARSE`` succeed", which makes the guarded form
    accept exactly what ``JSON_PARSE`` accepts — the same argument
    ``pg_input_is_valid`` carries on the PostgreSQL port, reached from the
    opposite direction.
    """

    if not isinstance(node, exp.Cast) or node.to.this is not exp.DataType.Type.JSON:
        return node

    value = node.this
    parsed = cast("Expression", exp.func("JSON_PARSE", value.copy()))

    if not isinstance(node, exp.TryCast):
        return parsed

    valid = cast("Expression", exp.func("CAN_JSON_PARSE", value.copy()))
    return exp.Case(ifs=[exp.If(this=valid, true=parsed)])


# ....................... #


def _refuse_super_navigation(node: Expression) -> None:
    """Refuse ``json_path`` on this port rather than translating it (S-0015/D-4).

    The PostgreSQL port lowers the transform to a ``->`` chain over ``JSONB``.
    ``SUPER`` is not ``JSONB`` spelled differently: it is navigated with PartiQL
    — ``x.a.b``, ``x[0]`` — whose reading of a missing key, a type mismatch and
    an array index is its own, and whose operand must already *be* ``SUPER``
    rather than text. SQLGlot renders the neutral extraction as
    ``JSON_EXTRACT_PATH_TEXT``, which Redshift does define and which returns
    **text**, so the transform would declare ``variant`` and produce a string:
    a translation that mostly works, which is the outcome D-4 refuses.

    Only :class:`sqlglot.exp.JSONExtract` is refused. A bronze path lowers to
    :class:`sqlglot.exp.JSONExtractScalar`, is declared ``string``, and
    Redshift's ``JSON_EXTRACT_PATH_TEXT`` over a text column returns text
    correctly — refusing that would refuse every mapping this port can emit.
    """

    if node.find(exp.JSONExtract) is None:
        return

    msg = (
        "dialect 'redshift' has no json_path lowering: variant is SUPER here, which is "
        "navigated with PartiQL rather than with JSONB's operators, and the extraction "
        "SQLGlot renders returns text — so the transform would declare variant and "
        "produce a string. Fix: extract the path in the mapping's bronze reader, which "
        "is declared string, or compile this project for a dialect with a variant "
        "extraction"
    )
    raise UnsupportedByTarget(msg)


# ....................... #


def _null_if_invalid(node: Expression) -> Expression:
    """``JSON_EXTRACT_PATH_TEXT(x, 'a', 'b')`` → the same call with
    ``null_if_invalid`` set: malformed JSON yields NULL instead of an error.

    A bronze path lowers to :class:`sqlglot.exp.JSONExtractScalar`, and the
    spelling SQLGlot renders is right as far as it goes — but Redshift's
    ``JSON_EXTRACT_PATH_TEXT`` *raises* on a source value that is not JSON,
    and the raise happens before any ``TRY_CAST`` around it runs, so one
    malformed row aborts the load where the quality system says quarantine it
    (S-0033/D-30's degradation by another route). The function's optional last
    argument, ``null_if_invalid``, is Redshift's own answer: NULL for a value
    that does not parse, which the ``coercible`` rule then reads as the
    failure it is. Only a plain key path is rewritten; an index or a wildcard
    is left to the generator, which already refuses what it cannot spell.
    """

    if not isinstance(node, exp.JSONExtractScalar) or not isinstance(node.expression, exp.JSONPath):
        return node

    steps = [step for step in node.expression.expressions if not isinstance(step, exp.JSONPathRoot)]

    if not steps or not all(isinstance(step, exp.JSONPathKey) for step in steps):
        return node

    return exp.Anonymous(
        this="JSON_EXTRACT_PATH_TEXT",
        expressions=[
            node.this.copy(),
            *(exp.Literal.string(str(step.this)) for step in steps),
            exp.true(),
        ],
    )


# ....................... #


def _date_literal(bound: Expression | None) -> date:
    """The calendar date a series bound spells, from ``CAST('YYYY-MM-DD' AS
    DATE)`` or the bare string literal; anything else is a bound this port
    cannot count rows from."""

    literal = bound.this if isinstance(bound, exp.Cast) else bound

    if not (isinstance(literal, exp.Literal) and literal.is_string):
        msg = (
            f"the Redshift port needs a literal date bound to size its calendar, "
            f"got {bound.sql() if bound is not None else 'nothing'}"
        )
        raise UnsupportedByTarget(msg)

    try:
        return date.fromisoformat(literal.this)

    except ValueError as exc:
        msg = f"the Redshift port cannot read {literal.this!r} as a calendar date bound"
        raise UnsupportedByTarget(msg) from exc


_TENS = "(" + " UNION ALL ".join(f"SELECT {n} AS d" for n in range(10)) + ")"


def _date_spine(node: Expression) -> Expression:
    """``GENERATE_SERIES(start, end, INTERVAL '1' DAY) AS t(c)`` in FROM
    position → a row-generating subquery Redshift can actually run.

    The calendar's neutral series node (``dim_date_select``) is a row source
    on every shipped port. Redshift's ``GENERATE_SERIES`` is PostgreSQL's in
    name only: it takes integers, not a date pair and an interval, and it is
    leader-node-only, so a ``CREATE TABLE … AS`` over it — which is what a
    ``dim_date`` model is — is refused whatever the arguments. The rendering
    parses, so the offline rungs cannot see this; the engine refuses it on the
    first run.

    Rows are generated the way Redshift's own idiom (and dbt's) does it: a
    ten-row literal relation cross-joined with itself once per decimal digit
    of the count, numbered by ``ROW_NUMBER()`` and cut at the count — pure
    SQL, executed on the compute nodes, no sequence, no recursion. The count
    is read from the series' own literal bounds, inclusive at both ends as
    the calendar is on every shipped port; a series this port cannot read — a
    non-literal bound, a step other than one day — is refused by name rather
    than rendered into SQL the engine rejects (S-0025/D-3).
    """

    if not (isinstance(node, exp.Table) and isinstance(node.this, exp.GenerateSeries)):
        return node

    series = node.this
    step = series.args.get("step")
    alias = node.args.get("alias")
    unit = step.args.get("unit") if isinstance(step, exp.Interval) else None

    if not (
        isinstance(step, exp.Interval)
        and step.this.name == "1"
        and unit is not None
        and unit.name.upper() == "DAY"
        and isinstance(alias, exp.TableAlias)
        and alias.columns
    ):
        msg = (
            "the Redshift port renders a series row source only as a one-day calendar "
            f"with a column alias, got {node.sql()}"
        )
        raise UnsupportedByTarget(msg)

    first = _date_literal(series.args.get("start"))
    rows = (_date_literal(series.args.get("end")) - first).days + 1
    digits = len(str(max(rows - 1, 0)))
    joins = " CROSS JOIN ".join(f"{_TENS} AS d{i}" for i in range(digits))
    column = alias.columns[0].name
    # S608 reads a SELECT built from an f-string as an injection vector. What
    # is interpolated is a calendar date this function parsed, integers it
    # computed, and an identifier the neutral tree already carried.
    spine = parse_one(
        f"SELECT DATEADD(DAY, n, CAST('{first.isoformat()}' AS DATE)) AS {column} "  # noqa: S608
        f"FROM (SELECT ROW_NUMBER() OVER () - 1 AS n FROM {joins}) AS numbers WHERE n < {rows}",
        read="redshift",
    )

    return exp.Subquery(this=spine, alias=exp.TableAlias(this=exp.to_identifier(alias.name)))
