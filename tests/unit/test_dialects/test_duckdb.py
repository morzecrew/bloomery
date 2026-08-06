"""The DuckDB dialect (RFC 0008 D5): physical types for all seven logical
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
