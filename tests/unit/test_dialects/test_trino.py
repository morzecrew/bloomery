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
    node = exp.AtTimeZone(
        this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
        zone=exp.Literal.string("Europe/Paris"),
    )
    # UNNEST-in-FROM territory and AT_TIMEZONE are where trino diverges.
    assert DIALECT.render(node) == "AT_TIMEZONE(CAST(x AS TIMESTAMP), 'Europe/Paris')"
