"""The DuckDB dialect (S-0025/D-5): the primary execution-test engine
( tier 4)."""

from __future__ import annotations

from typing import ClassVar, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import (
    SQLGlotDialect,
    epoch_timestamps,
    pick_spelled,
    space_separated,
    strip_iso_text,
    utc_from_zone,
    utc_instant,
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
    "DuckDBDialect",
]


class DuckDBDialect(SQLGlotDialect):
    """DuckDB: SQLGlot's ``duckdb`` generator plus DuckDB's native types."""

    name: str = "duckdb"
    sqlglot_dialect: str = "duckdb"
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
        """Render, rewriting ``NORMALIZE(x, NFC)`` to DuckDB's spelling — the
        input node is never mutated (the port contract shares ASTs across
        dialects).

        DuckDB has ``nfc_normalize`` and no ``NORMALIZE``, and SQLGlot's duckdb
        generator renders :class:`sqlglot.exp.Normalize` verbatim rather than
        refusing it, so the untouched AST would emit a call the engine has
        never heard of. Verified live: the ``normalize`` rule's execution tier
        fails without this.

        The ISO-text marker becomes a separator rewrite, for one spelling out
        of the three ISO 8601 permits. DuckDB's cast takes ``T`` and the space
        form and **raises** on the lowercase ``t`` — *Conversion Error: invalid
        timestamp field format* — so a bare entity aborted the run on it and a
        quality-carrying one quarantined the row, on text PostgreSQL and Trino
        both read. This port used to add nothing here, and its docstring said
        so; the claim was measured false (S-0044, S-0052).
        """

        def utc(interpretation: Expression) -> Expression:
            # `<tstz> AT TIME ZONE 'UTC'` yields a zoneless TIMESTAMP holding
            # the UTC wall clock, identically under any session (S-0045/the-fix-and-why-it-is-not-a-choice).
            return exp.AtTimeZone(this=interpretation, zone=exp.Literal.string("UTC"))

        rewritten = strip_iso_text(node.copy(), space_separated, instant=utc_instant)
        rewritten = epoch_timestamps(rewritten, _make_timestamp)
        rewritten = pick_spelled(rewritten, _picked)
        rewritten = utc_from_zone(rewritten, utc)
        rewritten = rewritten.transform(_nfc_normalize)
        return super().render(rewritten)


# ....................... #


def _make_timestamp(count: Expression, per_second: int) -> Expression:
    """``make_timestamp(n * 1000000 / per_second)``: microseconds since 1970 as a
    zoneless ``TIMESTAMP``, the same under every session zone (S-0096/D-6).
    ``to_timestamp`` returns a ``TIMESTAMPTZ`` whose cast reads the session."""

    micros = exp.Mul(this=count, expression=exp.Literal.number(1_000_000 // per_second))
    return exp.Anonymous(this="make_timestamp", expressions=[micros])


def _picked(items: Expression, field: str, text: str, take: str, _json: bool) -> Expression:
    """``pick`` on DuckDB (S-0095/D-4), measured over the design's edge cases:

    ``CASE WHEN json_type(m, '$.take') NOT IN ('OBJECT','ARRAY') THEN
    json_extract_string(m, '$.take') END`` over the first element ``m`` of
    ``list_filter(<the list as JSON[]>, e -> <e is an object whose scalar field
    reads as the text>)``. ``TRY_CAST`` to ``JSON`` makes text that is not JSON
    NULL, and the list is cast only once it is an array. The lambda reads the
    field with ``json_extract_string`` rather than ``->>``: SQLGlot renders the
    arrow lambda, and DuckDB parses ``e -> … e ->> '$.f'`` as JSON arrows.
    """

    def json_type(value: Expression, path: str | None = None) -> Expression:
        args = [value] if path is None else [value, exp.Literal.string(path)]
        return exp.Anonymous(this="json_type", expressions=args)

    def scalar(value: Expression, path: str) -> Expression:
        return exp.Not(
            this=exp.In(
                this=json_type(value, path),
                expressions=[exp.Literal.string("OBJECT"), exp.Literal.string("ARRAY")],
            )
        )

    def text_at(value: Expression, path: str) -> Expression:
        return exp.Anonymous(
            this="json_extract_string", expressions=[value, exp.Literal.string(path)]
        )

    parsed = exp.TryCast(this=items.copy(), to=exp.DataType.build("JSON"))
    as_list = exp.Case(
        ifs=[
            exp.If(
                this=exp.EQ(this=json_type(parsed.copy()), expression=exp.Literal.string("ARRAY")),
                true=exp.cast(parsed.copy(), exp.DataType.build("JSON[]")),
            )
        ]
    )
    element = exp.column("e")
    matches = exp.and_(
        exp.EQ(this=json_type(element.copy()), expression=exp.Literal.string("OBJECT")),
        scalar(element.copy(), f"$.{field}"),
        exp.EQ(this=text_at(element.copy(), f"$.{field}"), expression=exp.Literal.string(text)),
    )
    first = exp.Anonymous(
        this="list_extract",
        expressions=[
            exp.Anonymous(
                this="list_filter",
                expressions=[
                    as_list,
                    exp.Lambda(this=matches, expressions=[exp.to_identifier("e")]),
                ],
            ),
            exp.Literal.number(1),
        ],
    )
    return exp.Case(
        ifs=[exp.If(this=scalar(first.copy(), f"$.{take}"), true=text_at(first, f"$.{take}"))]
    )


# ....................... #


def _nfc_normalize(node: Expression) -> Expression:
    """``NORMALIZE(x, NFC)`` → ``NFC_NORMALIZE(x)``.

    Only NFC is reachable: the spec surface admits no other normal form,
    precisely because this function is the only one DuckDB has (S-0033/D-86).
    A form that somehow arrived here would silently normalize to the wrong one,
    so it raises rather than guessing.
    """

    if not isinstance(node, exp.Normalize):
        return node

    form = node.args.get("form")

    if form is not None and form.name.upper() != "NFC":
        msg = f"duckdb can only normalize to NFC, not {form.name!r}"
        raise ValueError(msg)

    return cast("Expression", exp.func("NFC_NORMALIZE", node.this.copy()))
