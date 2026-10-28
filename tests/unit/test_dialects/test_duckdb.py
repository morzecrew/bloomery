"""The DuckDB dialect (S-0025/D-5): physical types for all seven logical
types and dialect-specific rendering of neutral ASTs."""

from __future__ import annotations

import pytest
from sqlglot import exp

from bloomery.dialects import DuckDBDialect
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

DIALECT = DuckDBDialect()


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
        (VariantType(), "JSON"),
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_render_lowers_neutral_json_extraction_to_duckdb() -> None:
    node = exp.JSONExtractScalar(
        this=exp.column("customer"), expression=exp.Literal.string("$.id")
    )
    assert DIALECT.render(node) == "customer ->> '$.id'"


def test_render_is_the_duckdb_generator() -> None:
    assert DIALECT.name == "duckdb"
    assert DIALECT.sqlglot_dialect == "duckdb"
    node = exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP"))
    assert DIALECT.render(node) == "CAST(x AS TIMESTAMP)"


def _iso_cast() -> exp.Expression:
    """What `{parse_ts: ISO8601}` lowers to: a cast over a marked operand."""
    return exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )


def test_the_iso_text_marker_becomes_a_separator_rewrite() -> None:
    """DuckDB's cast takes `2026-01-06T12:00:00` and the space-separated
    spelling — and **raises** on `2026-01-06t12:00:00`, which ISO 8601 permits
    and the other two ports read. So this port normalizes both separators, as
    Trino does and through the same function, and carries the offset guard
    every port carries (S-0052/D-3).

    A port that left the marker in place would emit `BLM_ISO_TEXT(x)`, which no
    engine defines — deliberately louder than silently NULL data (S-0044).
    """
    assert DIALECT.render(_iso_cast()) == (
        "CAST(CASE\n"
        "  WHEN SUBSTRING(CAST(x AS TEXT), 11) LIKE '%+%'\n"
        "  OR SUBSTRING(CAST(x AS TEXT), 11) LIKE '%-%'\n"
        "  THEN NULL\n"
        "  ELSE REPLACE(REPLACE(CAST(x AS TEXT), 'T', ' '), 't', ' ')\n"
        "END AS TIMESTAMP)"
    )


@pytest.mark.parametrize(("fmt", "scale"), [("UNIX_SECONDS", "1000000"), ("UNIX_MILLIS", "1000")])
def test_an_epoch_count_is_arithmetic_from_1970_never_to_timestamp(fmt: str, scale: str) -> None:
    """`to_timestamp` returns a `TIMESTAMPTZ` whose cast reads the session zone;
    `make_timestamp` over microseconds is zoneless (S-0096/D-6)."""
    from bloomery.transforms import DEFAULT_REGISTRY

    rendered = DuckDBDialect().render(DEFAULT_REGISTRY["parse_ts"].builder(exp.column("x"), fmt))

    assert rendered.startswith("MAKE_TIMESTAMP(")
    assert f"END * {scale}" in rendered
    assert "TO_TIMESTAMP" not in rendered.upper()
