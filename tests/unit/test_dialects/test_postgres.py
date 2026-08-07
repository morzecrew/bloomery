"""The Postgres dialect (RFC 0008 D5, M10): physical types for all seven
logical types, dialect-specific rendering, and the reserved-identifier
quoting the sqlglot postgres generator does not perform itself."""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one

from bloomery.dialects import PostgresDialect
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

DIALECT = PostgresDialect()


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        (StringType(), "TEXT"),
        (IntType(), "BIGINT"),
        (DecimalType(12, 4), "DECIMAL(12, 4)"),
        (DecimalType(38, 0), "DECIMAL(38, 0)"),
        (BoolType(), "BOOLEAN"),
        (DateType(), "DATE"),
        (TimestampType(), "TIMESTAMP"),
        (VariantType(), "JSONB"),  # binary JSON is the idiomatic pg variant
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_render_lowers_neutral_json_extraction_to_postgres() -> None:
    # Parsed like an IR ``SqlExpr`` (canonical neutral text re-parsed at
    # emit), so the JSONPath is a structured node the generator can lower.
    # The ``->>`` operator is polymorphic over json AND jsonb — the function
    # form JSON_EXTRACT_PATH_TEXT exists only for json (verified live).
    node = parse_one("customer ->> '$.id'")
    assert DIALECT.render(node) == "customer ->> 'id'"


def test_render_casts_deep_json_paths_to_json() -> None:
    # Multi-key paths keep the function form, which requires the json type.
    node = parse_one("payload ->> '$.a.b'")
    assert DIALECT.render(node) == "JSON_EXTRACT_PATH_TEXT(CAST(payload AS JSON), 'a', 'b')"


def test_render_quotes_reserved_relation_names() -> None:
    # sqlglot's postgres generator leaves ``order`` bare (illegal live);
    # the dialect port quotes reserved identifiers itself.
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    assert DIALECT.render(node) == 'SELECT\n  x\nFROM silver."order"'


def test_render_never_mutates_the_shared_ast() -> None:
    # The same neutral AST renders on every dialect (RFC 0008 D1): quoting
    # for postgres must not leak into a later duckdb rendering.
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before


def test_render_is_the_postgres_generator() -> None:
    assert DIALECT.name == "postgres"
    assert DIALECT.sqlglot_dialect == "postgres"
    node = exp.RegexpLike(this=exp.column("sku"), expression=exp.Literal.string("^A-"))
    assert DIALECT.render(node) == "sku ~ '^A-'"
