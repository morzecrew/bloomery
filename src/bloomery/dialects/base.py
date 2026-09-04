"""The ``DialectPort`` (RFC 0008 §5.1): SQL rendering + physical type
mapping. Wraps SQLGlot; knows nothing about targets — SQLMesh-on-DuckDB and
dbt-on-DuckDB share every line of dialect logic through this port.

A transform whose AST cannot render on some dialect is an emit-time
:class:`~bloomery.errors.UnsupportedByTarget` failure discovered through
:meth:`DialectPort.supports` — never a typing concern (RFC 0004 D7).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import ClassVar, Protocol, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import UnsupportedByTarget
from bloomery.transforms import DIVIDE_MARKER, ISO_TEXT_MARKER
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
    "DialectFeature",
    "space_separated",
    "strip_iso_text",
    "utc_from_zone",
    "capture_group",
    "DialectPort",
    "SQLGlotDialect",
]


#: The first character after an ISO 8601 calendar date. ``YYYY-MM-DD`` is ten
#: characters, so every ``-`` belonging to the date sits behind this window and
#: every ``+`` or ``-`` inside it belongs to a UTC offset (RFC 0036 D5).
_OFFSET_WINDOW = 11


def _without_offset(text: Expression, parsed: Expression) -> Expression:
    """``parsed``, or NULL when ``text`` carries a numeric UTC offset.

    ``parse_ts: ISO8601`` reads a *local wall clock*, and ``to_utc`` is the only
    door into the always-UTC ``timestamp`` type (RFC 0028). Text spelling its
    own offset — ``2026-01-06T12:00:00+01:00`` — says something that contract
    does not let it say, and every engine bloomery targets resolves the
    contradiction the same silent way: it discards the offset and keeps the
    wall clock, so the instant is wrong by the offset and nothing reports it.
    Measured identically on PostgreSQL 16, Trino 483 and DuckDB — this is not a
    port divergence, which is why the guard is here and not in one of them
    (RFC 0036 D6).

    NULL rather than a conversion, because converting would make one
    declaration mean two different things depending on the row's bytes
    (RFC 0036 D2), and NULL is what the rest of the system already reads: the
    implicit ``coercible`` rule, the reject table, and RFC 0016 D21's blocking
    metadata audit.

    A ``Z`` suffix is deliberately **not** refused. It names UTC, which is the
    zone the target type is already in, so truncating it loses nothing — where
    a numeric offset loses exactly the difference (RFC 0036 D4).

    The window is taken over an explicit ``VARCHAR`` cast for the reason the
    Trino port already casts before its own ``replace``: the marker is text in
    a transform chain by ``parse_ts``'s declared input type, but on RFC 0016
    D21's metadata audit it sits on a **bronze column**, which is whatever the
    project landed. Against a project that lands ``_ingested_at`` typed,
    ``SUBSTRING(<timestamp>, 11)`` does not plan on any of the three engines —
    so a guard reading the operand raw would refuse to compile the audit rather
    than refuse the value, on the one column no ``coercible`` rule can reach.
    The cast is a no-op on the text this normally sees.
    """
    window = exp.Substring(
        this=exp.cast(text, exp.DataType.build("VARCHAR")),
        start=exp.Literal.number(_OFFSET_WINDOW),
    )
    offset_bearing = exp.or_(
        exp.Like(this=window, expression=exp.Literal.string("%+%")),
        exp.Like(this=window.copy(), expression=exp.Literal.string("%-%")),
    )
    return exp.Case(ifs=[exp.If(this=offset_bearing, true=exp.null())], default=parsed)


# ....................... #


def space_separated(text: Expression) -> Expression:
    """``text`` with either ISO 8601 date/time separator rewritten to a space.

    Shared by every port whose own cast will not take a separator ISO 8601
    permits, because the spelling is one body and the engines that need it need
    the *same* one:

    * **Trino** takes neither ``T`` nor ``t`` — measured, ``TRY_CAST`` returns
      NULL for both;
    * **DuckDB** takes ``T`` and raises on ``t`` — ``Conversion Error: invalid
      timestamp field format``, so a plain ``CAST`` aborts the run and a
      ``TRY_CAST`` on a quality-carrying entity quarantines the row;
    * **PostgreSQL** takes both and calls this on nothing.

    ``CAST(… AS VARCHAR)`` first, because the marked operand is not always
    text. A transform chain's is, by ``parse_ts``'s declared input type, and
    there the cast is a no-op — but RFC 0016 D21's metadata audit marks a
    *bronze column*, and a project is free to land ``_ingested_at`` already
    typed. Trino's ``replace`` takes varchar and nothing else, and DuckDB's
    binder matches no ``replace(TIMESTAMP, …)`` either: a port's spelling has to
    be total over what it may be handed, not over what its first caller
    happened to hand it.

    Applied to the *text* rather than to the cast, because the cast may already
    have become a ``TRY_CAST`` (RFC 0027 D4). A no-op on a value that never had
    a separator.
    """
    replaced = cast("Expression", exp.cast(text, exp.DataType.build("VARCHAR")))

    for separator in ("T", "t"):
        replaced = cast(
            "Expression",
            exp.func("replace", replaced, exp.Literal.string(separator), exp.Literal.string(" ")),
        )

    return replaced


# ....................... #


def strip_iso_text(node: Expression, spelling: Callable[[Expression], Expression]) -> Expression:
    """Replace every ISO-text marker in ``node`` with ``spelling(inner)``.

    ``parse_ts: ISO8601`` wraps the text it is about to cast in
    :data:`~bloomery.transforms.ISO_TEXT_MARKER`, because the engines disagree
    about what their own casts accept and the IR carries canonical *text* — so
    by emit time nothing distinguishes an ISO parse's cast from any other cast
    unless the spec layer said so (RFC 0027 §3). ``parse_date: ISO8601`` is
    deliberately **not** marked, so do not add date-specific rewriting here:
    an ISO date has no ``T``, and no engine is helped by rewriting one.

    Every port must call this. ``spelling`` is identity for an engine whose
    cast already takes the ``T`` separator; a port that never calls it is
    refused by :meth:`SQLGlotDialect.render` rather than left to emit a
    function no engine defines — the alternative, defaulting to identity,
    would give a port whose cast rejects the separator silently NULL data.

    Every replacement is wrapped in :func:`_without_offset`, so the refusal of
    offset-bearing text lands on every port at once — including one written
    later, which inherits it by satisfying the "must call this" rule rather
    than by remembering a second one (RFC 0036 D3).
    """

    def replace(child: Expression) -> Expression:
        if isinstance(child, exp.Anonymous) and child.name.upper() == ISO_TEXT_MARKER:
            text = child.expressions[0]
            return _without_offset(text.copy(), spelling(text))

        return child

    return node.transform(replace)


# ....................... #


def utc_from_zone(node: Expression, to_utc: Callable[[Expression], Expression]) -> Expression:
    """Replace every zone interpretation with ``to_utc(interpretation)``.

    ``to_utc`` is the only door into the ``timestamp`` type, and that type is
    **always UTC** and zoneless (RFC 0004 §5.1). Every engine's zone
    interpretation returns a zone-*aware* value instead — the right instant
    carrying a display rule — and every consumer that derives a date, an hour or
    a bucket reads the display rule rather than the instant.

    That made a mart's date role depend on something no spec said: the reader's
    session zone on DuckDB and PostgreSQL, the mapping's own zone on Trino. Two
    rows at one instant, mapped from two shops in two zones, landed in different
    days (RFC 0028 §2).

    So each port normalizes to UTC and drops the zone. ``to_utc`` here is the
    port's spelling of that, applied to the whole interpretation.
    """

    def replace(child: Expression) -> Expression:
        return to_utc(child) if isinstance(child, exp.AtTimeZone) else child

    return node.transform(replace)


# ....................... #


def capture_group(node: Expression) -> Expression:
    """Restore the capture-group argument the canonical round trip demotes.

    ``regex_extract`` builds :class:`sqlglot.exp.RegexpExtract` with ``group``
    set, and that renders correctly on every port. The IR does not keep the
    node: it keeps canonical dialect-neutral **text** and re-parses at emit
    (RFC 0003 D2), and ``REGEXP_EXTRACT(x, p, 1)`` re-parses with the third
    argument bound to ``position`` — the Oracle/PostgreSQL reading — after
    which SQLGlot's duckdb and trino generators **drop it silently**, warning
    to a stderr nothing reads. So ``{regex_extract: [pattern, 1]}`` returned
    group 0, the whole match, on both engines that can run it. No fixture used
    the transform, so no golden showed it; the declared-vs-produced battery is
    what found it (RFC 0028 D5).

    Reading the third argument as the group is correct rather than merely
    convenient: DuckDB and Trino both define ``regexp_extract``'s third
    argument that way, and PostgreSQL — whose ``regexp_substr`` reads it as a
    start position — has no ``regexp_extract`` at all to run either spelling,
    so no engine bloomery emits to takes the demoted meaning. A tree that
    already names a group is left alone.

    :meth:`SQLGlotDialect.render` applies this to every port, but it does so
    *last* — after a port's own rewrites, which is too late for a port that
    needs to read the group in order to spell the call at all. Such a port
    calls this first; the second application is a no-op, because a tree that
    already names a group is returned untouched.
    """

    def replace(child: Expression) -> Expression:
        if not isinstance(child, exp.RegexpExtract):
            return child

        position = child.args.get("position")

        if position is None or child.args.get("group") is not None:
            return child

        child.set("position", None)
        child.set("group", position)

        return child

    return node.transform(replace)


# ....................... #


def _exact_division(node: Expression) -> Expression:
    """Turn the ``divide`` marker into a division the engine keeps exact.

    ``exp.Div(typed=True)`` is what suppresses SQLGlot's
    ``CAST(x AS DOUBLE PRECISION) /`` on PostgreSQL and ``CAST(x AS DOUBLE) /``
    on Trino. It cannot be set by the builder, because the IR keeps canonical
    text and the flag does not survive the re-parse (RFC 0003 D2), and it
    cannot be set on every ``Div`` at render, because a ratio metric's
    ``COUNT(a) / COUNT(b)`` would silently become integer division. The marker
    is the difference, and it is the only thing a port could not have worked
    out for itself (RFC 0029 D3).

    Applied centrally rather than per port: unlike the ISO-text marker, whose
    right treatment differs per engine, this one has a single treatment
    everywhere, so there is no decision for a port to forget and no guard is
    needed.

    DuckDB is left inexact by this and knowingly. Its ``/`` is float division
    and ``//`` is integer division; the engine has no exact decimal division to
    reach for, so the float is bounded by a narrowing cast to the declared type
    rather than removed (RFC 0029 §4, logs/T-0002.md D-003).
    """

    def replace(child: Expression) -> Expression:
        if isinstance(child, exp.Anonymous) and child.name.upper() == DIVIDE_MARKER:
            left, right = child.expressions
            return exp.Div(this=left, expression=right, typed=True)

        return child

    return node.transform(replace)


# ....................... #


class DialectFeature(StrEnum):
    """Capabilities an emitter may query before lowering (RFC 0008 §5.1)."""

    JSON_EXTRACT = "json_extract"
    TIMEZONE_CONVERT = "timezone_convert"
    REGEXP_EXTRACT = "regexp_extract"
    VARIANT_TYPE = "variant_type"
    #: A first-class array type (RFC 0016 D9). Deliberately a *dialect*
    #: feature, not a target ``Feature``, diverging from Document 5 §5.3:
    #: array support is an engine property, and SQLMesh-on-DuckDB and
    #: dbt-on-DuckDB share it — the RFC 0008 D1 split. All three shipped
    #: dialects have arrays (DuckDB ``STRING[]``, Postgres ``TEXT[]``, Trino
    #: ``ARRAY(VARCHAR)``); a dialect without one lowers ``_quality_flags``
    #: and ``failed_rules`` to the comma-delimited string fallback (D23).
    ARRAY = "array"
    #: A cast that yields NULL instead of raising — the shape the
    #: coercion-failure marker needs (RFC 0016 §5.2, D3: "``TRY_CAST``-shaped
    #: lowering **per dialect**"). DuckDB and Trino have ``TRY_CAST``;
    #: Postgres has no equivalent, and SQLGlot's postgres generator renders
    #: :class:`sqlglot.exp.TryCast` as a plain ``CAST``. Silently accepting
    #: that would turn "quarantine the uncastable row" into "abort the run" —
    #: a degradation nobody asked for — so the capability is declared and an
    #: entity carrying ``coercible`` rules refuses to emit on a dialect
    #: without it (RFC 0008 D3: fail loud, never approximate).
    TRY_CAST = "try_cast"
    #: ``SHA256`` over a text value yielding a stable hex *string* — what
    #: ``reject_id`` is (RFC 0016 D21). DuckDB's ``SHA256(VARCHAR)`` returns
    #: the hex digest directly. Trino's ``sha256`` takes ``varbinary`` and
    #: returns ``varbinary``, so the same AST renders a call Trino refuses to
    #: even plan (``Unexpected parameters (varchar) for function sha256``);
    #: the portable spelling there is
    #: ``LOWER(TO_HEX(SHA256(TO_UTF8(...))))``, which is *not* interchangeable
    #: — applying it on DuckDB hex-encodes an already-hex string and doubles
    #: its length. Until the rendering is split per dialect, a dialect without
    #: this feature cannot carry a reject table.
    TEXT_SHA256 = "text_sha256"
    #: Unicode normalization to NFC — what a ``normalize`` rule compares a
    #: value against (RFC 0016 D86). Postgres and Trino spell it
    #: ``NORMALIZE(x, NFC)``; DuckDB has ``nfc_normalize(x)`` and no
    #: ``NORMALIZE`` at all, and SQLGlot's duckdb generator renders
    #: :class:`sqlglot.exp.Normalize` verbatim — a call the engine has never
    #: heard of — so :meth:`DuckDBDialect.render` rewrites it. All three
    #: shipped dialects have the capability; the flag exists so a fourth
    #: without one refuses the rule rather than emitting a function nothing
    #: defines.
    UNICODE_NORMALIZE = "unicode_normalize"
    #: ``JSON_OBJECT('k', v, ...)`` in its positional form — how the reject
    #: table builds ``raw`` and ``key_values`` (RFC 0016 §5.6). Trino accepts
    #: only the SQL-standard ``JSON_OBJECT(KEY 'k' VALUE v)`` spelling and
    #: fails to parse the positional one, so ``lowering._json_object``'s claim
    #: to be "the one construction SQLGlot renders verbatim on every shipped
    #: dialect" holds for DuckDB and Postgres but not Trino.
    JSON_OBJECT_POSITIONAL = "json_object_positional"


# ....................... #


class DialectPort(Protocol):
    """SQL rendering + physical type mapping (RFC 0008 D1)."""

    name: str

    # ....................... #

    begin_transaction: str

    # ....................... #

    def render(self, node: Expression) -> str: ...

    def physical_type(self, t: LogicalType) -> str: ...

    def supports(self, feature: DialectFeature) -> bool: ...

    def text_sha256(self, value: Expression) -> Expression: ...

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression: ...


# ....................... #


class SQLGlotDialect:
    """Base adapter: renders through SQLGlot's generator for
    :attr:`sqlglot_dialect` and maps the seven logical types via
    :attr:`scalar_types` (``decimal(p, s)`` is computed)."""

    # Plain class attributes (not ClassVar): the DialectPort protocol declares
    # ``name`` as an instance attribute, and ClassVar members cannot satisfy it.
    name: str = ""
    sqlglot_dialect: str = ""
    #: How this engine opens a transaction. ``BEGIN`` is the common spelling and
    #: is **not** universal: Trino accepts only the SQL-standard
    #: ``START TRANSACTION`` and answers ``BEGIN`` with a syntax error
    #: (measured, `trinodb/trino:483`). It is a port attribute rather than a
    #: rendered node because no AST node means "open a transaction" — it is
    #: envelope text, and the emitter interpolates it like every other
    #: pre-rendered string (RFC 0008 D4).
    begin_transaction: str = "BEGIN"
    features: ClassVar[frozenset[DialectFeature]] = frozenset(DialectFeature)
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "TEXT",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSON",
    }

    # ....................... #

    def render(self, node: Expression) -> str:
        """Render a dialect-neutral AST as this dialect's SQL text.

        Refuses a tree still carrying the ISO-text marker. Every shipped port
        strips it before delegating here, so this never fires for them; it
        exists for a port registered through
        :func:`~bloomery.dialects.register_dialect` that has not decided what
        its engine needs.

        The check lives at this end rather than in each port because ports
        reach it through ``super().render(...)`` whether or not they override
        :meth:`render`, so one guard covers both shapes. Without it the marker
        would reach the engine as an undefined function and fail at *plan*
        time with the engine's own message — a worse version of the same
        refusal, arriving later and naming nothing actionable.
        """
        surviving = next(
            (
                child
                for child in node.find_all(exp.Anonymous)
                if child.name.upper() == ISO_TEXT_MARKER
            ),
            None,
        )

        if surviving is not None:
            msg = (
                f"dialect {self.name!r} rendered an ISO 8601 parse without deciding what "
                f"its engine needs: the {ISO_TEXT_MARKER} marker reached SQL generation "
                "(RFC 0027). Engines disagree about what their own casts accept — "
                "DuckDB and PostgreSQL take the 'T' separator, Trino returns NULL for it "
                "— so the choice cannot be defaulted without risking silently NULL data. "
                "Fix: call bloomery.dialects.base.strip_iso_text in this port's render, "
                "with an identity spelling if the engine's cast already takes both forms"
            )
            raise UnsupportedByTarget(msg)

        return _exact_division(capture_group(node)).sql(dialect=self.sqlglot_dialect, pretty=True)

    # ....................... #

    def physical_type(self, t: LogicalType) -> str:
        """The engine type for a logical type (RFC 0004 non-goal: physical
        mapping lives here, not in the type layer)."""

        if isinstance(t, DecimalType):
            return f"DECIMAL({t.precision}, {t.scale})"

        return self.scalar_types[type(t)]

    # ....................... #

    def supports(self, feature: DialectFeature) -> bool:
        return feature in self.features

    # ....................... #

    def text_sha256(self, value: Expression) -> Expression:
        """A SHA-256 hex *string* over a text value (RFC 0016 D21).

        Built here rather than in the emitter because the portable spellings
        are not interchangeable: DuckDB's ``SHA256(VARCHAR)`` already returns
        hex, and applying Trino's ``LOWER(TO_HEX(SHA256(TO_UTF8(…))))`` to it
        would hex-encode an already-hex digest and double its length. A
        construction that differs per engine belongs to the port that knows
        the engine (RFC 0008 D1), not to a lowering that is supposed to be
        dialect-neutral.
        """

        return exp.SHA2(this=value, length=exp.Literal.number(256))

    # ....................... #

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``JSON_OBJECT('k', v, …)`` — the positional form, keys in the
        caller's order."""
        arguments: list[Expression] = []

        for key, value in pairs:
            arguments.extend((exp.Literal.string(key), value))

        return cast("Expression", exp.func("JSON_OBJECT", *arguments))
