"""The Trino dialect (RFC 0008 D5, M10): physical types for all seven
logical types and dialect-specific rendering of neutral ASTs."""

from __future__ import annotations

import pytest
from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects import TrinoDialect
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

pytestmark = pytest.mark.unit

DIALECT = TrinoDialect()


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        (StringType(), "VARCHAR"),
        (IntType(), "BIGINT"),
        (DecimalType(12, 4), "DECIMAL(12, 4)"),
        (DecimalType(38, 0), "DECIMAL(38, 0)"),
        (BoolType(), "BOOLEAN"),
        (DateType(), "DATE"),
        (TimestampType(), "TIMESTAMP"),
        (VariantType(), "JSON"),  # Trino has a first-class JSON type
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_render_lowers_neutral_json_extraction_to_trino() -> None:
    node = exp.JSONExtractScalar(
        this=exp.column("customer"), expression=exp.Literal.string("$.id")
    )
    assert DIALECT.render(node) == "JSON_EXTRACT_SCALAR(customer, '$.id')"


def test_render_quotes_reserved_relation_names() -> None:
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    assert DIALECT.render(node) == 'SELECT\n  x\nFROM silver."order"'


def test_render_is_the_trino_generator() -> None:
    assert DIALECT.name == "trino"
    assert DIALECT.sqlglot_dialect == "trino"
    node = exp.JSONExtract(this=exp.column("payload"), expression=exp.Literal.string("$.a"))
    assert DIALECT.render(node) == "JSON_EXTRACT(payload, '$.a')"


def test_zone_interpretation_uses_with_timezone_not_at_timezone() -> None:
    """``to_utc`` means *interpret this zoneless timestamp as being in zone*
    (RFC 0004 §5.1) — the only door into the always-UTC ``timestamp`` type.

    Trino's ``AT TIME ZONE`` does not mean that. Given a zoneless timestamp it
    promotes the value using the **session** zone first and only then converts
    to the named one, so the instant comes out unchanged and the zone argument
    changes nothing but the display. Verified against trinodb/trino with the
    session on UTC: ``CAST('2026-01-06 12:00:00' AS TIMESTAMP) AT TIME ZONE
    'Europe/Berlin'`` is ``2026-01-06 13:00:00 Europe/Berlin`` — instant
    12:00Z — while ``with_timezone`` of the same value is ``2026-01-06
    12:00:00 Europe/Berlin``, instant 11:00Z. DuckDB and PostgreSQL both give
    11:00Z for their own ``AT TIME ZONE``, so Trino was the one port that read
    the transform backwards.
    """
    node = exp.AtTimeZone(
        this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
        zone=exp.Literal.string("Europe/Paris"),
    )
    rendered = DIALECT.render(node)
    assert "WITH_TIMEZONE(CAST(x AS TIMESTAMP), 'Europe/Paris')" in rendered
    # ... and normalized to a zoneless UTC value, because `timestamp` is always
    # UTC and a zone-aware value makes every derived date read its display rule
    # rather than its instant (RFC 0028).
    assert rendered.startswith("CAST(AT_TIMEZONE(")
    assert rendered.rstrip().endswith("AS TIMESTAMP)")


def test_a_nested_zone_interpretation_is_rewritten_too() -> None:
    """The rewrite walks the tree, and the interesting case is the one a
    mapping actually produces: the interpretation is a *column* of a SELECT,
    never the root node the unit above hands it."""
    node = exp.select(
        exp.alias_(
            exp.AtTimeZone(
                this=exp.cast(exp.column("placed_at"), exp.DataType.build("TIMESTAMP")),
                zone=exp.Literal.string("Europe/Berlin"),
            ),
            "ordered_at",
        )
    ).from_("bronze.woo")
    rendered = DIALECT.render(node)
    assert "WITH_TIMEZONE(CAST(placed_at AS TIMESTAMP), 'Europe/Berlin')" in rendered
    assert "AT TIME ZONE" not in rendered  # the neutral spelling, which Trino reads differently


def test_several_zone_interpretations_in_one_tree_are_all_rewritten() -> None:
    node = exp.select(
        exp.alias_(
            exp.AtTimeZone(this=exp.column("a"), zone=exp.Literal.string("Europe/Berlin")), "a"
        ),
        exp.alias_(
            exp.AtTimeZone(this=exp.column("b"), zone=exp.Literal.string("Asia/Kolkata")), "b"
        ),
    )
    rendered = DIALECT.render(node)
    assert rendered.count("WITH_TIMEZONE") == 2
    assert rendered.count("AT_TIMEZONE") == 2  # each interpretation normalized to UTC
    assert "AT TIME ZONE" not in rendered


@pytest.mark.parametrize("nested", [False, True])
def test_rendering_a_zone_interpretation_does_not_mutate_the_input(nested: bool) -> None:
    """The port contract shares one neutral AST across every dialect, so a
    rewrite that edited in place would leave the next dialect rendering
    Trino's spelling — and the in-place branch is the *nested* one, since a
    root node is replaced by rebinding a local.

    Both parameters matter: the root case exercises the rebind, the nested one
    exercises ``replace()``, and only the second can corrupt the caller's tree.
    """
    interpretation = exp.AtTimeZone(this=exp.column("x"), zone=exp.Literal.string("Europe/Paris"))
    node: Expression = (
        exp.select(exp.alias_(interpretation, "t")) if nested else interpretation
    )
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before
    assert "AT TIME ZONE" in before
    # The shared AST still renders the neutral spelling for the next port.
    assert "AT TIME ZONE" in node.sql(dialect="duckdb")


def _iso_cast(to: str = "TIMESTAMP") -> Expression:
    """What `{parse_ts: ISO8601}` lowers to: a cast over a marked operand."""
    return exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build(to),
    )


@pytest.mark.parametrize(("to", "expected"), [("TIMESTAMP", "TIMESTAMP"), ("DATE", "DATE")])
def test_the_iso_text_marker_becomes_a_separator_rewrite(to: str, expected: str) -> None:
    """Trino's cast takes only the space-separated spelling and returns NULL
    for `2026-01-06T12:00:00` — measured, and the same for `AS DATE`. The
    rewrite accepts both spellings and is a no-op on a value that never had a
    `T` (RFC 0027).
    """
    assert (
        DIALECT.render(_iso_cast(to))
        == f"CAST(REPLACE(REPLACE(CAST(x AS VARCHAR), 'T', ' '), 't', ' ') AS {expected})"
    )


def test_the_marker_is_rewritten_inside_a_try_cast() -> None:
    """The shape an entity in the quality system actually emits.

    The marker wraps the *operand*, so `_try_cast_shape`'s Cast → TryCast
    rewrite still reaches the cast, and this port's rewrite still reaches the
    text. Had the marker replaced the cast, this would be a plain produce-or-
    raise call and the `coercible` rule would have stopped marking anything.
    """
    node = exp.TryCast(
        this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("created_at")]),
        to=exp.DataType.build("TIMESTAMP"),
    )
    assert DIALECT.render(node) == (
        "TRY_CAST(REPLACE(REPLACE(CAST(created_at AS VARCHAR), 'T', ' '), 't', ' ') "
        "AS TIMESTAMP)"
    )


def test_both_iso_separators_are_normalized() -> None:
    """ISO 8601 permits `T` and `t`, and Trino takes neither.

    Measured on trinodb/trino:483: `TRY_CAST('2026-01-06T12:00:00' AS
    TIMESTAMP)` is NULL and so is the lowercase form, while DuckDB and
    Postgres read both. A port that normalized only the uppercase spelling left
    the lowercase one as a NULL projection here and nowhere else — a
    quarantined row, or a blocking audit, on data the other two ports read.
    """
    rendered = DIALECT.render(_iso_cast())
    assert "'T', ' '" in rendered
    assert "'t', ' '" in rendered


def test_the_rewrite_survives_an_operand_that_is_not_text() -> None:
    """The marked operand is text in a transform chain, by `parse_ts`'s declared
    input type — and is whatever the project landed when the marker is on a
    **bronze column**, which is where RFC 0016 D21's metadata audit puts it.

    Trino's `replace` takes varchar and nothing else, so the unguarded spelling
    did not plan at all against a project that lands `_ingested_at` typed:
    *Unexpected parameters (timestamp(6), varchar, varchar) for function
    replace*. The inner `CAST(… AS VARCHAR)` is a no-op on the chain's text and
    is what makes the port's spelling total over what it may be handed.
    """
    node = exp.TryCast(
        this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("_ingested_at")]),
        to=exp.DataType.build("TIMESTAMP"),
    )
    assert "CAST(_ingested_at AS VARCHAR)" in DIALECT.render(node)
