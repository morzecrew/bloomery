"""The Snowflake dialect (S-0013): the first cloud port, established by the
offline rungs — unit, golden and ``sqlglot.parse_one(rendered, read="snowflake")``
syntax sanity.

Every rewrite here answers a Snowflake question, not a PostgreSQL or Trino one
(S-0013/D-2). Three of the six rewrite points need something on this port
(timestamps, the ``TRY_CAST`` family, ``JSON_OBJECT``); three need nothing
(ISO separator aside, regexp capture groups, ``text_sha256``) and say so in a
docstring rather than in code. Beside the six, one rewrite is this port's
alone: the calendar's series row source, which SQLGlot spells here as a scalar
function the engine cannot select from (:func:`_date_spine`).
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
    "SnowflakeDialect",
]

#: Snowflake's reserved key words (Snowflake docs, "Reserved & limited
#: keywords"): none of them may name a table or column unquoted. SQLGlot's
#: snowflake generator (at the locked pin) quotes nothing here — verified:
#: ``SELECT x FROM silver.order`` — so :meth:`SnowflakeDialect.render` quotes
#: them itself. Quoting is not case-neutral on this engine, which is where the
#: postgres port's mechanism stops applying: an unquoted identifier folds to
#: UPPERCASE and a quoted one is taken verbatim, so ``silver."order"`` is a
#: different object from the ``silver.order`` a model declares (SQLMesh
#: resolves that name as ``"SILVER"."ORDER"``). A reserved identifier is
#: therefore quoted in its folded spelling, ``silver."ORDER"``, which names the
#: same object as every unquoted reference to it. The lists are not
#: interchangeable in either direction: ``qualify``, ``minus``, ``sample`` and
#: ``increment`` are reserved here and free on PostgreSQL, while ``offset``,
#: ``analyse`` and ``limit`` are the other way round.
_RESERVED = frozenset(
    {
        "all", "alter", "and", "any", "as", "between", "by", "case", "cast",
        "check", "column", "connect", "connection", "constraint", "create",
        "cross", "current", "current_date", "current_time",
        "current_timestamp", "current_user", "database", "delete", "distinct",
        "drop", "else", "exists", "false", "following", "for", "from", "full",
        "grant", "group", "gscluster", "having", "ilike", "in", "increment",
        "inner", "insert", "intersect", "into", "is", "issue", "join",
        "lateral", "left", "like", "localtime", "localtimestamp", "minus",
        "natural", "not", "null", "of", "on", "or", "order", "organization",
        "qualify", "regexp", "revoke", "right", "rlike", "row", "rows",
        "sample", "schema", "select", "set", "some", "start", "table",
        "tablesample", "then", "to", "trigger", "true", "try_cast", "union",
        "unique", "update", "using", "values", "view", "when", "whenever",
        "where", "with",
    }
)  # fmt: skip

#: Snowflake's ``NUMBER`` tops out at 38 digits of precision, and there is no
#: wider fixed-point type to fall back to (Snowflake docs, "Data types for
#: fixed-point numbers"). bloomery's ``decimal(p, s)`` has no upper bound —
#: ``DecimalType(40, 2)`` parses — so the refusal has to live on the port.
_MAX_PRECISION = 38


class SnowflakeDialect(SQLGlotDialect):
    """Snowflake: SQLGlot's ``snowflake`` generator plus Snowflake's own types.

    ``timestamp`` maps to ``TIMESTAMP_NTZ`` and never to ``TIMESTAMP_LTZ``
    (S-0013/D-1): ``TIMESTAMP_LTZ`` renders against the reader's session zone,
    which is the reader-dependence the always-UTC zoneless invariant exists to
    remove (S-0021/logical-types-bloomery-typing-types-py, S-0045/what-was-measured). Bare ``TIMESTAMP`` is not the same
    answer spelled shorter: on Snowflake it is an *alias* resolved through the
    ``TIMESTAMP_TYPE_MAPPING`` parameter, which an account or a session may
    point at ``TIMESTAMP_LTZ`` — so a column declared ``TIMESTAMP`` could
    become the one type D-1 forbids without a line of bloomery changing. Every
    ``TIMESTAMP`` in a rendered tree is therefore rewritten to the explicit
    type as well (:func:`_zoneless_timestamp`); casts carry Snowflake's
    ``TIMESTAMPNTZ`` alias, which is SQLGlot's spelling of the same type.

    ``variant`` maps to ``VARIANT`` rather than keeping the base adapter's
    ``JSON`` (S-0013/D-6): Snowflake has no ``JSON`` type at all, and
    ``VARIANT`` is what its own semi-structured functions —
    ``PARSE_JSON``, ``GET_PATH`` — take and return. SQLGlot already renders a
    neutral ``CAST(x AS JSON)`` as ``CAST(x AS VARIANT)``, so the type map and
    the rendered casts agree.

    ``int`` maps to ``NUMBER(38, 0)``, which is what Snowflake stores: its
    ``BIGINT`` is a documented synonym for exactly that and not a 64-bit
    integer, and ``physical_type`` is a one-way door once artifacts exist
    (S-0013/D-6) — better that it state the range it has.
    """

    name: str = "snowflake"
    sqlglot_dialect: str = "snowflake"
    #: Snowflake accepts ``BEGIN``, ``BEGIN WORK``, ``BEGIN TRANSACTION`` and
    #: ``START TRANSACTION`` as synonyms (Snowflake docs, ``BEGIN``), so the
    #: base spelling needs nothing here — unlike Trino, which takes the
    #: standard one only.
    begin_transaction: str = "BEGIN"
    #: Everything except Unicode normalization. Snowflake has no NFC
    #: normalization function — no ``NORMALIZE``, and nothing under another
    #: name (its Unicode surface is collation, which compares rather than
    #: rewrites) — and SQLGlot's snowflake generator renders
    #: :class:`sqlglot.exp.Normalize` verbatim, so a ``normalize`` rule would
    #: compile clean and die on a function the engine never defined. The flag
    #: turns that into an emit-time refusal (S-0033/D-86, S-0025/D-3), which
    #: is the answer S-0013/D-2 calls for where a rewrite point has no
    #: spelling to offer.
    features: ClassVar[frozenset[DialectFeature]] = frozenset(DialectFeature) - {
        DialectFeature.UNICODE_NORMALIZE
    }
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "VARCHAR",
        IntType: "NUMBER(38, 0)",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP_NTZ",
        VariantType: "VARIANT",
    }

    # ....................... #

    def physical_type(self, t: LogicalType) -> str:
        """The base mapping, plus Snowflake's fixed-point ceiling.

        ``NUMBER`` carries at most 38 digits and Snowflake has no wider
        fixed-point type, so a ``decimal(40, 2)`` — which the spec layer
        accepts — has no physical answer here. Refused at emit naming the
        bound, rather than rendered into DDL the engine rejects with its own
        message (S-0025/D-3).
        """

        if isinstance(t, DecimalType) and t.precision > _MAX_PRECISION:
            msg = (
                f"decimal({t.precision}, {t.scale}) exceeds Snowflake's fixed-point "
                f"precision of {_MAX_PRECISION} digits, and Snowflake has no wider "
                "fixed-point type. Fix: declare a precision within the bound, or compile "
                "this project for a dialect that carries more"
            )
            raise UnsupportedByTarget(msg)

        return super().physical_type(t)

    # ....................... #

    def render(self, node: Expression) -> str:
        """Render with the timestamp type made explicit, every current-instant
        node given its UTC spelling, ``TRY_CAST`` given the shape Snowflake's
        own restriction requires, and reserved identifiers quoted — the input
        node is never mutated (the port contract shares ASTs across dialects).

        Three of S-0013's six rewrite points need nothing here, and each one
        was checked rather than assumed:

        * **Regexp capture groups.** SQLGlot renders
          :class:`sqlglot.exp.RegexpExtract` on this dialect as
          ``REGEXP_SUBSTR(x, p, 1, 1, 'c', <group>)``, whose sixth argument is
          Snowflake's ``group_num`` — the same position PostgreSQL's
          ``regexp_substr`` uses, reached without PostgreSQL's rewrite because
          the generator already spells it. The shared
          :func:`~bloomery.dialects.base.capture_group` restoration, which the
          base render applies to every tree, is what makes the group survive
          the canonical round trip (S-0045/D-5); nothing port-specific is left.
        * **``text_sha256``.** Snowflake's ``SHA2(msg, 256)`` takes a string
          and returns the lowercase hex digest directly, which is
          ``reject_id``'s contract (S-0033/D-21) — so the base spelling is
          already right and Trino's ``TO_UTF8``/``TO_HEX``/``LOWER`` wrapping,
          which exists because *its* ``sha256`` is binary in and binary out,
          would be a copied rewrite answering nobody's question here
          (S-0013/D-2).
        * **The offset guard.** S-0052's ``SUBSTRING(CAST(x AS VARCHAR), 11)``
          plus two ``LIKE``s renders verbatim on this dialect and means what
          it means everywhere else.

        The ISO-text marker is not one of those three: this port strips it to
        the shared space-separated spelling. Snowflake's ``AUTO`` input format
        does document the ``T``-separated ISO 8601 form, so identity is the
        *likely* answer — but the two spellings fail asymmetrically. If ``T``
        is accepted, the rewrite costs a ``REPLACE`` over a value that then
        parses identically; if some ISO form is not, identity returns NULL for
        good data, which is the defect S-0044 and S-0052 exist to close. The
        strictly-safe spelling is taken until the live execution corpus —
        which is where a NULL can be observed at all, since ``EXPLAIN`` cannot
        see one — settles it (S-0013/local-execution).
        """

        def utc(at_zone: Expression) -> Expression:
            # `CONVERT_TIMEZONE(<from>, 'UTC', <ts>)` — the *three*-argument
            # form, which reads a zoneless timestamp as being in the named zone
            # and returns a zoneless TIMESTAMP_NTZ in the target one. That is
            # `to_utc` exactly, in one call and with no cast to drop a zone.
            #
            # SQLGlot renders `exp.AtTimeZone` as the two-argument form
            # instead, and that is a different function: it expects an instant,
            # promotes a zoneless operand using the *session* zone before
            # converting, and returns a zone-aware TIMESTAMP_TZ. Both halves
            # are wrong here — the reader's session decides the instant, and
            # the result carries a display rule (S-0045/what-was-measured).
            return cast(
                "Expression",
                exp.func(
                    "CONVERT_TIMEZONE",
                    at_zone.args["zone"],
                    exp.Literal.string("UTC"),
                    at_zone.this,
                ),
            )

        rewritten = strip_iso_text(node.copy(), space_separated)
        rewritten = utc_from_zone(rewritten, utc)
        rewritten = rewritten.transform(_utc_current_timestamp)
        rewritten = rewritten.transform(_zoneless_parse)
        rewritten = rewritten.transform(_string_try_cast)
        rewritten = rewritten.transform(_zoneless_timestamp)
        rewritten = rewritten.transform(_semi_structured_array)
        rewritten = rewritten.transform(_date_spine)

        for identifier in rewritten.find_all(exp.Identifier):
            if identifier.this.lower() in _RESERVED:
                # The folded spelling, quoted — see `_RESERVED`.
                identifier.set("this", identifier.this.upper())
                identifier.set("quoted", True)

        return super().render(rewritten)

    # ....................... #

    def utc_now(self) -> Expression:
        """``SYSDATE()``.

        Snowflake's ``SYSDATE`` is documented as the system's current instant
        *in UTC*, typed ``TIMESTAMP_NTZ`` — zoneless UTC, which is what this
        method owes (S-0021/logical-types-bloomery-typing-types-py). The base spelling cannot be used: there is
        no ``timezone(zone, ts)`` function on this engine, and
        ``CURRENT_TIMESTAMP`` is ``TIMESTAMP_LTZ``, so casting it would keep
        the session's wall clock — the S-0045/what-was-measured defect wearing the shape of
        its fix.
        """

        return cast("Expression", exp.func("SYSDATE"))

    # ....................... #

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``OBJECT_CONSTRUCT_KEEP_NULL('k', v, …)``.

        Snowflake has no ``JSON_OBJECT`` at all — the positional form SQLGlot
        would render verbatim is a function the engine never defined — and its
        object builder drops any pair whose value is NULL. The reject table's
        ``raw`` and ``key_values`` are built from exactly the row that failed,
        so a NULL cell dropping its key would make the quarantined payload
        disagree with every other port's (S-0033/quarantine-one-reject-table-per-entity):
        ``OBJECT_CONSTRUCT_KEEP_NULL`` is the variant that keeps them, and the
        reason the ``_KEEP_NULL`` suffix is load-bearing rather than
        defensive.
        """
        arguments: list[Expression] = []

        for key, value in pairs:
            arguments.extend((exp.Literal.string(key), value))

        return cast("Expression", exp.func("OBJECT_CONSTRUCT_KEEP_NULL", *arguments))


# ....................... #


def _zoneless_timestamp(node: Expression) -> Expression:
    """A neutral ``TIMESTAMP`` type becomes the explicit ``TIMESTAMP_NTZ``.

    On Snowflake ``TIMESTAMP`` is an alias, not a type: it resolves through
    the ``TIMESTAMP_TYPE_MAPPING`` parameter, whose default is
    ``TIMESTAMP_NTZ`` and which an account or a session may point at
    ``TIMESTAMP_LTZ``. Every cast bloomery renders would then produce a
    session-zone-dependent value, which is what S-0013/D-1 forbids by name —
    and nothing in the emitted SQL would look different. Naming the type
    closes the door the parameter leaves open.
    """

    if isinstance(node, exp.DataType) and node.this is exp.DataType.Type.TIMESTAMP:
        return exp.DataType.build("TIMESTAMPNTZ")

    return node


# ....................... #


def _utc_current_timestamp(node: Expression) -> Expression:
    """``CURRENT_TIMESTAMP`` → ``SYSDATE()``, the same UTC spelling
    :meth:`SnowflakeDialect.utc_now` owes.

    A current-instant node reaches a rendered tree without passing through
    ``utc_now``: the replay statements build :class:`sqlglot.exp.CurrentTimestamp`
    directly to stamp ``resolved_at`` and ``last_evaluated_at``. On Snowflake
    that renders ``CURRENT_TIMESTAMP()``, which is ``TIMESTAMP_LTZ``, and
    assigning it into a ``TIMESTAMP_NTZ`` column converts it *through the
    session zone* — so the stored zoneless value is the writer's local wall
    clock and two writers disagree about the same instant. That is the
    reader-dependence S-0013/D-1 forbids by name, arriving through a node the
    emit layer builds rather than through this port's type map.

    ``SYSDATE()`` is the engine's current instant in UTC, already typed
    ``TIMESTAMP_NTZ``, so the assignment converts nothing. The rewrite lands
    here rather than at the emit layer because a neutral
    ``CURRENT_TIMESTAMP`` is legal on the three shipped ports, whose
    ``timestamp`` columns are not zone-converted on assignment; it is this
    engine's typing that makes it a defect, and per-engine spellings are what
    a port is.
    """

    if isinstance(node, exp.CurrentTimestamp):
        return cast("Expression", exp.func("SYSDATE"))

    return node


# ....................... #


def _semi_structured_array(node: Expression) -> Expression:
    """Arrays in the spelling Snowflake's semi-structured surface documents.

    Two substitutions, both away from a construct SQLGlot renders and Snowflake
    does not document for the shape bloomery emits:

    * ``[a, b]`` → ``ARRAY_CONSTRUCT(a, b)``. Both spellings are documented —
      the bracket form for constants, ``ARRAY_CONSTRUCT`` for arbitrary
      expressions — and this rewrite reaches only the arrays bloomery builds,
      such as ``_quality_flags`` on a clean row (S-0033/D-23). SQLGlot's own
      snowflake generator still emits bracket constants in the NULL guard it
      wraps around ``ARRAY_CAT``, after this pass has run, so an artifact
      carries both forms: this is a choice of the documented spelling for
      what bloomery constructs, not a removal of the bracket form.
    * ``ARRAY(VARCHAR)`` → ``ARRAY``. Snowflake's semi-structured array is
      untyped — its elements are ``VARIANT`` — and a per-element type belongs
      to the newer *structured* type surface, whose availability depends on the
      account. The flag column's contract needs membership and size, which
      ``ARRAY_CONTAINS`` and ``ARRAY_SIZE`` give over the untyped array, so
      declaring an element type buys nothing and risks DDL the account
      refuses. This is also where the Trino port's rendering must **not** be
      inherited: ``ARRAY(VARCHAR)`` is its native spelling and only looks
      native here (S-0013/D-2).
    """

    if isinstance(node, exp.Array):
        return cast(
            "Expression",
            exp.func("ARRAY_CONSTRUCT", *(element.copy() for element in node.expressions)),
        )

    if isinstance(node, exp.DataType) and node.this is exp.DataType.Type.ARRAY:
        return exp.DataType.build("ARRAY")

    return node


# ....................... #


def _zoneless_parse(node: Expression) -> Expression:
    """``TO_TIMESTAMP(x, fmt)`` → ``CAST(TO_TIMESTAMP(x, fmt) AS TIMESTAMP_NTZ)``.

    ``parse_ts`` reads a *local wall clock* and must produce it zoneless;
    Snowflake's ``TO_TIMESTAMP`` returns the ``TIMESTAMP_TYPE_MAPPING`` type,
    so under an account pointing that at ``TIMESTAMP_LTZ`` the parsed clock
    comes back with the session zone attached.

    The cast is the fix and it is not a formality: Snowflake converts
    ``TIMESTAMP_LTZ`` to ``TIMESTAMP_NTZ`` *through the session zone* — the
    same attachment ``TO_TIMESTAMP`` just made — so the two cancel and the
    written clock survives under any session, while under the default mapping
    the cast is a no-op.

    ``parse_date``'s ``TO_DATE`` needs none of this: a date has no zone to
    attach.
    """

    if not isinstance(node, exp.StrToTime):
        return node

    return exp.cast(node, exp.DataType.build("TIMESTAMPNTZ"))


# ....................... #


def _string_try_cast(node: Expression) -> Expression:
    """``TRY_CAST(x AS t)`` → ``TRY_CAST(CAST(x AS VARCHAR) AS t)``, really emitted.

    Two Snowflake facts meet here. The engine's ``TRY_CAST`` accepts a
    **string** source only, and SQLGlot's snowflake generator knows it: its
    ``trycast_sql`` emits a plain ``CAST`` unless the operand's annotated type
    is text or the node carries ``requires_string``. A neutral tree's operands
    are unannotated, so the verbatim rendering of
    ``TRY_CAST(_ingested_at AS TIMESTAMP)`` is ``CAST(...)`` — silently turning
    "quarantine the uncastable row" into "abort the run", the same degradation
    S-0033/D-30 refused on PostgreSQL, arriving here through a generator
    detail rather than a missing keyword.

    So the operand is cast to ``VARCHAR`` first, which satisfies the engine's
    restriction over *whatever* it is handed — a chain's inner cast may be
    numeric (``to_int(to_decimal(x))``), and S-0033/D-21's metadata audit
    marks a bronze column a project may have landed already typed — and
    ``requires_string`` is set, which is what makes SQLGlot render the keyword.
    NULL propagates through both casts, so a NULL input stays a NULL result
    rather than becoming one by failure. An operand that is *already* a cast to
    text satisfies the restriction as it stands and is left alone — a chain's
    ``to_string`` step is the common case, and a second identical cast around
    it would be noise in every reviewed artifact.
    """

    if not isinstance(node, exp.TryCast):
        return node

    value = node.this.copy()

    if not (isinstance(value, exp.Cast) and value.to.is_type(*exp.DataType.TEXT_TYPES)):
        value = exp.cast(value, exp.DataType.build("VARCHAR"))

    return exp.TryCast(this=value, to=node.to.copy(), requires_string=True)


# ....................... #


def _date_literal(bound: Expression | None) -> date:
    """The calendar date a series bound spells, from ``CAST('YYYY-MM-DD' AS
    DATE)`` or the bare string literal; anything else is a bound this port
    cannot count rows from."""

    literal = bound.this if isinstance(bound, exp.Cast) else bound

    if not (isinstance(literal, exp.Literal) and literal.is_string):
        msg = (
            f"the Snowflake port needs a literal date bound to count generator rows, "
            f"got {bound.sql() if bound is not None else 'nothing'}"
        )
        raise UnsupportedByTarget(msg)

    try:
        return date.fromisoformat(literal.this)

    except ValueError as exc:
        msg = f"the Snowflake port cannot read {literal.this!r} as a calendar date bound"
        raise UnsupportedByTarget(msg) from exc


def _date_spine(node: Expression) -> Expression:
    """``GENERATE_SERIES(start, end, INTERVAL '1' DAY) AS t(c)`` in FROM
    position → a generator subquery Snowflake can actually run.

    The calendar's neutral series node (``dim_date_select``) is a row source
    on every shipped port — ``GENERATE_SERIES`` returns a set on DuckDB and
    PostgreSQL, ``UNNEST(SEQUENCE(...))`` is a table on Trino — and SQLGlot's
    snowflake generator spells it ``ARRAY_GENERATE_RANGE(...)``, a scalar
    function returning an ARRAY of *integers*: it takes neither DATE bounds
    nor an INTERVAL step, and it cannot stand in FROM without
    ``TABLE(FLATTEN(...))``. The parser accepts the call, so the offline
    syntax rung cannot see this; the engine refuses it on the first run.

    Snowflake's row generator is ``TABLE(GENERATOR(ROWCOUNT => n))`` with a
    literal count, so the count is computed here from the series' own literal
    bounds — the calendar body interpolates spec-validated years and nothing
    else (S-0020/D-2), which is what makes the bounds readable at emit time;
    both ends are inclusive, as they are on every shipped port.
    ``ROW_NUMBER() OVER (ORDER BY SEQ4())`` rather than ``SEQ4()`` alone: the
    sequence is documented as not gap-free, the row number is. A series this
    port cannot read — a non-literal bound, a step other than one day — is
    refused by name rather than rendered into SQL the engine rejects
    (S-0025/D-3).
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
            "the Snowflake port renders a series row source only as a one-day calendar "
            f"with a column alias, got {node.sql()}"
        )
        raise UnsupportedByTarget(msg)

    first = _date_literal(series.args.get("start"))
    rows = (_date_literal(series.args.get("end")) - first).days + 1
    # S608 reads a SELECT built from an f-string as an injection vector. What
    # is interpolated is a calendar date this function parsed, an integer it
    # computed, and an identifier the neutral tree already carried.
    spine = parse_one(
        f"SELECT DATEADD(DAY, ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1, "  # noqa: S608
        f"CAST('{first.isoformat()}' AS DATE)) AS {alias.columns[0].name} "
        f"FROM TABLE(GENERATOR(ROWCOUNT => {rows}))",
        read="snowflake",
    )

    return exp.Subquery(this=spine, alias=exp.TableAlias(this=exp.to_identifier(alias.name)))
