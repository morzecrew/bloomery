"""IR node semantics (RFC 0003 §5.1–§5.2; RFC 0010 §5.3): value equality,
immutability, SqlExpr AST caching contract, DimensionRef qualification."""

from __future__ import annotations

import pytest
from sqlglot import exp

from bloomery.ir import DimensionRef, PartitionSpec, SqlExpr

pytestmark = pytest.mark.unit


def test_sql_expr_equality_is_by_string() -> None:
    assert SqlExpr("a + b") == SqlExpr("a + b")
    assert SqlExpr("a + b") != SqlExpr("a+b")  # the canonical string is the value
    assert hash(SqlExpr("a + b")) == hash(SqlExpr("a + b"))


def test_sql_expr_ast_parses() -> None:
    ast = SqlExpr("unit_price * quantity").ast()
    assert isinstance(ast, exp.Expression)
    assert ast.sql() == "unit_price * quantity"


def test_sql_expr_ast_returns_fresh_copies() -> None:
    expr = SqlExpr("a + b")
    first = expr.ast()
    second = expr.ast()
    assert first is not second  # mutating one caller's AST cannot leak
    first.set("this", exp.column("mutated"))
    assert second.sql() == "a + b"
    assert expr.ast().sql() == "a + b"


def test_ir_nodes_are_frozen() -> None:
    ref = DimensionRef(dimension="date", role="ordered")
    with pytest.raises(AttributeError):
        ref.role = "shipped"  # type: ignore[misc]


def test_dimension_ref_qualified() -> None:
    assert DimensionRef(dimension="date", role="ordered").qualified == "ordered_date"
    assert DimensionRef(dimension="customer_region").qualified == "customer_region"


def test_partition_spec_identity_transform() -> None:
    assert PartitionSpec(transform=None, column="region").column == "region"
    assert PartitionSpec(transform="days", column="d") != PartitionSpec(transform=None, column="d")
