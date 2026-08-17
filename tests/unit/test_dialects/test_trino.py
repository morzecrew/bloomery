"""The Trino dialect (RFC 0008 D5, M10): physical types for all seven
logical types and dialect-specific rendering of neutral ASTs."""

from __future__ import annotations

import pytest
from sqlglot import exp

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
    assert DIALECT.render(node) == "WITH_TIMEZONE(CAST(x AS TIMESTAMP), 'Europe/Paris')"


def test_rendering_a_zone_interpretation_does_not_mutate_the_input() -> None:
    """The port contract shares one neutral AST across every dialect, so a
    rewrite that edited in place would leave the next dialect rendering
    Trino's spelling."""
    node = exp.AtTimeZone(this=exp.column("x"), zone=exp.Literal.string("Europe/Paris"))
    DIALECT.render(node)
    assert isinstance(node, exp.AtTimeZone)
    assert node.sql() == "x AT TIME ZONE 'Europe/Paris'"
