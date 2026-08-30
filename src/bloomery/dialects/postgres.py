"""The Postgres dialect (RFC 0008 D5): the relational-engine port of the M10
port-validation milestone, and the engine-tier execution dialect (RFC 0009
§5.2 tier 5)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Final, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import (
    SQLGlotDialect,
    capture_group,
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
    "PostgresDialect",
]

#: PostgreSQL's reserved key words (PostgreSQL docs, appendix C): the
#: ``reserved`` category plus the ``reserved (can be function or type name)``
#: category — neither may name a table or column unquoted. SQLGlot's postgres
#: generator (at the locked pin) quotes nothing here, unlike its duckdb and
#: trino generators, so an entity named ``order`` would render illegally;
#: :meth:`PostgresDialect.render` quotes these itself.
_RESERVED = frozenset(
    {
        "all", "analyse", "analyze", "and", "any", "array", "as", "asc",
        "asymmetric", "authorization", "binary", "both", "case", "cast",
        "check", "collate", "collation", "column", "concurrently",
        "constraint", "create", "cross", "current_catalog", "current_date",
        "current_role", "current_schema", "current_time",
        "current_timestamp", "current_user", "default", "deferrable", "desc",
        "distinct", "do", "else", "end", "except", "false", "fetch", "for",
        "foreign", "freeze", "from", "full", "grant", "group", "having",
        "ilike", "in", "initially", "inner", "intersect", "into", "is",
        "isnull", "join", "lateral", "leading", "left", "like", "limit",
        "localtime", "localtimestamp", "natural", "not", "notnull", "null",
        "offset", "on", "only", "or", "order", "outer", "overlaps",
        "placing", "primary", "references", "returning", "right", "select",
        "session_user", "similar", "some", "symmetric", "table",
        "tablesample", "then", "to", "trailing", "true", "union", "unique",
        "user", "using", "variadic", "verbose", "when", "where", "window",
        "with",
    }
)  # fmt: skip


class PostgresDialect(SQLGlotDialect):
    """Postgres: SQLGlot's ``postgres`` generator plus Postgres native types.

    ``variant`` maps to ``JSONB``, not ``JSON``: Postgres's binary form is
    the idiomatic semi-structured column (indexable, canonicalized), while
    plain ``JSON`` is a text blob that preserves key order and duplicates —
    properties bloomery's ``variant`` never promises.
    """

    name: str = "postgres"
    sqlglot_dialect: str = "postgres"
    #: Everything, since RFC 0016 D84 gave ``TRY_CAST`` a Postgres spelling.
    #: Postgres has no ``TRY_CAST`` keyword and SQLGlot's generator quietly
    #: renders one as a plain ``CAST``; :meth:`render` rewrites it instead
    #: into a guard around Postgres' *own* input parser, so the accept/reject
    #: set is the engine's rather than a regex approximation of it.
    scalar_types: ClassVar[dict[type[LogicalType], str]] = {
        StringType: "TEXT",
        IntType: "BIGINT",
        BoolType: "BOOLEAN",
        DateType: "DATE",
        TimestampType: "TIMESTAMP",
        VariantType: "JSONB",
    }

    # ....................... #

    def render(self, node: Expression) -> str:
        """Render with reserved identifiers quoted and JSON extraction made
        ``jsonb``-safe — the input node is never mutated (the port contract
        shares ASTs across dialects).

        ``TRY_CAST`` becomes a guard around Postgres' own input parser
        (RFC 0016 D84) — see :func:`_guarded_try_cast`.

        SQLGlot's postgres generator renders extraction as
        ``JSON_EXTRACT_PATH_TEXT(...)``, which exists only for the ``json``
        type — bloomery's ``variant`` is ``JSONB`` (verified live: the
        engine tier fails without this). A bronze path's ``->>`` extraction is
        declared ``string`` and stays on the ``json`` functions; the
        ``json_path`` transform is declared ``variant`` and goes through
        :func:`_jsonb_extraction` instead.

        The ISO-text marker strips to nothing: Postgres' own cast takes both
        ISO spellings, so there is nothing for this port to add (RFC 0027).
        """

        def utc(interpretation: Expression) -> Expression:
            # `<tstz> AT TIME ZONE 'UTC'` yields a zoneless TIMESTAMP holding
            # the UTC wall clock, identically under any session (RFC 0028 §3).
            return exp.AtTimeZone(this=interpretation, zone=exp.Literal.string("UTC"))

        # Before `_pg_text_functions`, which has to read the capture group to
        # spell `regexp_substr` at all; the base render applies it again, and
        # a tree that already names a group is untouched.
        rewritten = capture_group(node.copy())
        rewritten = strip_iso_text(rewritten, lambda text: text)
        rewritten = utc_from_zone(rewritten, utc)
        rewritten = rewritten.transform(_zoneless_parse)
        rewritten = rewritten.transform(_pg_text_functions)
        rewritten = rewritten.transform(_guarded_try_cast)

        for identifier in rewritten.find_all(exp.Identifier):
            if identifier.this.lower() in _RESERVED:
                identifier.set("quoted", True)

        rewritten = rewritten.transform(_variant_is_jsonb)

        for extract in rewritten.find_all(exp.JSONExtractScalar):
            path = extract.args.get("expression")
            if not isinstance(path, exp.JSONPath):
                continue
            parts = path.expressions
            if len(parts) == 2 and isinstance(parts[1], exp.JSONPathKey):
                extract.set("only_json_types", True)  # ``->``/``->>`` form
            else:
                extract.set("this", exp.cast(extract.this, exp.DataType.build("JSON")))

        rewritten = rewritten.transform(_jsonb_extraction)
        return super().render(rewritten)

    # ....................... #

    def text_sha256(self, value: Expression) -> Expression:
        """``ENCODE(SHA256(CONVERT_TO(…, 'UTF8')), 'hex')``.

        Postgres' ``sha256`` takes and returns ``bytea``, so the plain
        spelling does not fail — it silently yields *bytes* where every other
        dialect yields a hex string, which would make ``reject_id`` disagree
        across engines while looking like it worked (RFC 0016 D83). Verified
        against postgres 16 to equal the digest DuckDB returns directly.
        """
        encoded = exp.func("CONVERT_TO", value, exp.Literal.string("UTF8"))
        digest = exp.func("SHA256", encoded)
        return cast("Expression", exp.func("ENCODE", digest, exp.Literal.string("hex")))

    # ....................... #

    def json_object(self, pairs: Sequence[tuple[str, Expression]]) -> Expression:
        """``JSON_BUILD_OBJECT('k', v, …)``.

        Postgres has no positional ``json_object``: the SQL/JSON one arrived
        in 16 taking the ``KEY … VALUE`` form only, and the positional builder
        has always been spelled ``json_build_object``.
        """
        arguments: list[Expression] = []

        for key, value in pairs:
            arguments.extend((exp.Literal.string(key), value))

        return cast("Expression", exp.func("JSON_BUILD_OBJECT", *arguments))


# ....................... #


#: Datetime inputs Postgres accepts whose value depends on *when the query
#: runs* — they resolve to the transaction timestamp (RFC 0016 D84).
#:
#: A bronze cell literally spelling ``now`` would otherwise coerce to a
#: different value on every run, so a backfill would disagree with the run it
#: replaces — the one thing RFC 0003 exists to prevent. Refusing them makes
#: such a cell a *coercion failure*, which the ``coercible`` rule then
#: disposes of like any other bad value: a quarantined row rather than a
#: silently unstable one. ``epoch``, ``infinity`` and ``-infinity`` are
#: constants and stay accepted.
_RUN_DEPENDENT: Final[tuple[str, ...]] = ("now", "today", "tomorrow", "yesterday")

#: The deny-list as an anchored pattern, whitespace included (RFC 0016 D93).
#:
#: It was ``LOWER(BTRIM(value)) IN (...)``, and bare ``BTRIM`` removes *spaces
#: only*. Verified on PostgreSQL 16: ``'now\t'``, ``'now\n'`` and ``'now\r'``
#: each pass ``pg_input_is_valid``, survive the trim with their whitespace
#: intact, miss the deny-list, and cast to the transaction timestamp — so the
#: guard was comparing a string the engine would never see.
#:
#: ``[[:space:]]`` rather than an ``E' \t\n\r\f\v'`` trim argument because
#: the emitted SQL is a reviewed artifact: an escape string puts literal
#: control characters in every golden, which is the readability argument D86
#: already made for spelling invisible characters as codepoints.
_RUN_DEPENDENT_PATTERN: Final[str] = "^[[:space:]]*(" + "|".join(_RUN_DEPENDENT) + ")[[:space:]]*$"

#: The types whose Postgres input parser accepts a run-dependent literal.
_TEMPORAL: Final[frozenset[str]] = frozenset({"DATE", "TIMESTAMP", "TIMESTAMPTZ"})


def _variant_is_jsonb(node: Expression) -> Expression:
    """A neutral ``CAST(x AS JSON)`` is ``CAST(x AS JSONB)`` on this port.

    ``variant`` maps to ``JSONB`` here, but the *neutral* type for it is
    ``JSON`` — that is what :func:`bloomery.transforms.neutral_type` names and
    what every neutral cast in the tree therefore says. Rendering it verbatim
    made a ``variant`` column's cast disagree with the column's own declared
    physical type, which PostgreSQL then refuses to mix: ``COALESCE(jsonb,
    json)`` does not coerce (``42846``) and ``NULLIF(jsonb, json)`` has no
    operator (``42883``).

    Applied before the ``JSONExtractScalar`` lowering below, which adds a
    ``CAST(... AS JSON)`` of its own and means it: ``json_extract_path_text``
    is a ``json`` function, and a bronze path is declared ``string`` rather
    than ``variant``, so that cast is about reaching the right *function* and
    not about the column's type.
    """

    if isinstance(node, exp.DataType) and node.this is exp.DataType.Type.JSON:
        return exp.DataType.build("JSONB")

    return node


# ....................... #


def _jsonb_extraction(node: Expression) -> Expression:
    """``json_path`` extraction, kept in ``jsonb`` end to end and whole.

    ``variant`` is ``JSONB`` on this port, so a transform declared to produce
    one has to produce one, and neither shipped spelling did (RFC 0029 §2.4):
    a path deeper than one key went through ``CAST(x AS JSON)`` and
    ``json_extract_path``, which return **json**, and a single-key path over a
    ``string`` column rendered ``s -> 'a'``, for which PostgreSQL has no
    operator at all (``42883``).

    Casting the operand and letting SQLGlot chain the ``->`` operators covers
    every path shape with one branch: ``-> 'a' -> 'b'`` for keys, ``-> 0`` for
    a subscript, and the bare cast for a root-only path, which is the identity.
    Verified against postgres 16 that each returns ``jsonb`` and the right
    value, arrays included.

    **A function form cannot do this.** An earlier version of this fix reached
    for ``jsonb_extract_path``, which takes text path elements, and so had to
    pull the keys out of the path — silently dropping every subscript with
    them, so ``$[0]`` returned the whole document. The operator form has no
    such step, which is why it is the one to prefer even though the function
    form reads more like the path it came from.

    Only :class:`sqlglot.exp.JSONExtract` is rewritten. A bronze path lowers to
    :class:`sqlglot.exp.JSONExtractScalar`, is declared ``string``, and
    ``->>``/``json_extract_path_text`` return text correctly — moving it here
    would change a column's type to fix nothing.
    """

    if not isinstance(node, exp.JSONExtract):
        return node

    path = node.args.get("expression")

    if not isinstance(path, exp.JSONPath):
        return node

    operand = exp.cast(node.this, exp.DataType.build("JSONB"))
    return exp.JSONExtract(this=operand, expression=path.copy(), only_json_types=True)


# ....................... #


def _pg_text_functions(node: Expression) -> Expression:
    """Two text functions PostgreSQL does not have, in spellings it does.

    Both were emitted verbatim and failed at plan time with ``42883``
    (RFC 0029 §2.3) — a whitelisted transform that compiles clean and dies on
    the first run, on a shipped dialect.

    ``ENDS_WITH(x, s)`` → ``RIGHT(x, LENGTH(s)) = s``. PostgreSQL has
    ``starts_with`` and no mirror of it, which is why ``strip_prefix`` ran and
    ``strip_suffix`` did not. ``RIGHT``/``LENGTH`` is an exact equivalent
    rather than a near one — deliberately not ``LIKE '%' || s``, which would
    read ``%`` and ``_`` in the suffix as wildcards. Verified against DuckDB on
    a suffix containing ``%``.

    ``REGEXP_EXTRACT(x, p, n)`` → ``REGEXP_SUBSTR(x, p, 1, 1, '', n)``.
    PostgreSQL 16 has no ``regexp_extract`` at all; ``regexp_substr``'s sixth
    argument is the capture group, so the group index survives rather than
    being dropped the way SQLGlot's duckdb and trino generators dropped it
    (RFC 0028 D5). Verified equal to DuckDB for group 0 and group 1. A
    non-match returns NULL here and ``''`` on DuckDB, which is the divergence
    ``regex_extract`` already declares by carrying ``nullifies=True`` on the
    portable reading.

    ``regexp_substr`` arrived in PostgreSQL 15 and ``pg_input_is_valid``
    (RFC 0016 D84) already puts this port's floor at 16, so nothing new is
    required of the engine.
    """

    if isinstance(node, exp.EndsWith):
        suffix = node.expression
        tail = exp.func("RIGHT", node.this.copy(), exp.Length(this=suffix.copy()))
        return exp.EQ(this=cast("Expression", tail), expression=suffix.copy())

    if isinstance(node, exp.RegexpExtract):
        group = node.args.get("group") or exp.Literal.number(0)
        return cast(
            "Expression",
            exp.func(
                "REGEXP_SUBSTR",
                node.this.copy(),
                node.expression.copy(),
                exp.Literal.number(1),  # start position
                exp.Literal.number(1),  # first match
                exp.Literal.string(""),  # no flags
                group.copy(),
            ),
        )

    return node


# ....................... #


def _zoneless_parse(node: Expression) -> Expression:
    """``TO_TIMESTAMP(x, fmt)`` → ``CAST(TO_TIMESTAMP(x, fmt) AS TIMESTAMP)``.

    ``parse_ts`` parses a *local wall clock*; ``to_utc`` is the only door into
    the always-UTC ``timestamp`` type (RFC 0004 §5.1), so the value this step
    produces must be the clock that was written, zoneless. PostgreSQL's
    ``to_timestamp(text, text)`` instead returns ``timestamptz``, having
    attached the **session** zone to the parsed clock — so the same row stored
    a different instant depending on who ran it. Measured on postgres 16 for
    ``2026-01-06 23:30:00``: ``+00`` under UTC, ``+14`` under
    Pacific/Kiritimati, ``-08`` under America/Los_Angeles.

    The cast is the fix and it is not a formality: PostgreSQL converts
    ``timestamptz`` to ``timestamp`` *through the session zone*, which is
    exactly the attachment ``to_timestamp`` just made, so the two cancel and
    the written clock comes back unchanged under every session.

    ``AT TIME ZONE 'UTC'`` — the spelling that fixed the zone-aware value in
    RFC 0028 — is the wrong tool here and was measured to prove it: it reads
    the value in UTC rather than undoing the session attachment, giving
    ``09:30`` under Pacific/Kiritimati and ``2026-01-07 07:30`` under
    America/Los_Angeles for the same input. It looks like the neighbouring fix
    and moves the clock (RFC 0029 §2.4).

    ``parse_date``'s ``TO_DATE`` needs none of this: it returns ``date``, which
    has no zone to attach.
    """

    if not isinstance(node, exp.StrToTime):
        return node

    return exp.cast(node, exp.DataType.build("TIMESTAMP"))


# ....................... #


def _guarded_try_cast(node: Expression) -> Expression:
    """``TRY_CAST(x AS t)`` → ``CASE WHEN pg_input_is_valid(x, 't') THEN CAST(x AS t) END``.

    Postgres has no NULL-on-failure cast, and rendering ``TRY_CAST`` as a
    plain ``CAST`` turns "quarantine the uncastable row" into "abort the run"
    — which is why D30 refused quality-carrying entities here at all.

    The guard is ``pg_input_is_valid`` (Postgres 16+), not a per-type regex.
    That matters: it is the engine's *own* input parser, so the guarded form
    accepts exactly what ``CAST`` accepts and returns NULL exactly where
    ``CAST`` would raise — an equivalence that holds by construction rather
    than by a pattern someone has to keep in step with the parser. Measured
    over the dirty corpus: 284 of 285 (value × type) cases identical, the one
    difference being ``'now'``, which is not a difference in the guard at all.

    Temporal casts carry one deliberate *narrowing*, and it is the reason that
    285th case exists: Postgres accepts ``now``/``today``/``tomorrow``/
    ``yesterday`` as datetime input and resolves them to the transaction
    timestamp, so the same row coerces to a different value on every run.
    Those are excluded, making such a cell a coercion failure instead of a
    silently unstable value.

    The rewrite is safe against constant folding only because the input is a
    column. Over a folded constant Postgres evaluates the ``THEN`` branch at
    plan time and raises — which is how this was nearly mismeasured.
    """

    if not isinstance(node, exp.TryCast):
        return node

    value = node.this
    type_name = node.to.sql(dialect="postgres")
    valid = cast(
        "Expression",
        exp.func("pg_input_is_valid", value.copy(), exp.Literal.string(type_name)),
    )

    if node.to.this.name.upper() in _TEMPORAL:
        stable = exp.Not(
            this=exp.RegexpLike(
                this=exp.Lower(this=value.copy()),
                expression=exp.Literal.string(_RUN_DEPENDENT_PATTERN),
            )
        )
        valid = exp.And(this=valid, expression=stable)

    return exp.Case(ifs=[exp.If(this=valid, true=exp.cast(value.copy(), node.to.copy()))])
