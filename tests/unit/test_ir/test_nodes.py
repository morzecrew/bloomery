"""IR node semantics (RFC 0003 §5.1–§5.2; RFC 0010 §5.3; RFC 0016 §5.3–§5.6):
value equality, immutability, SqlExpr AST caching contract, DimensionRef
qualification, and the data-quality nodes' shape and canonical order."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlglot import exp

from bloomery.ir import (
    DedupeIR,
    DimensionRef,
    OnFail,
    PartitionSpec,
    ProjectIR,
    QualityRuleIR,
    QuarantineIR,
    ReconcileIR,
    SqlExpr,
    quality_sort_key,
)

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


# ....................... #
# Data quality (RFC 0016 §5.3–§5.6)


def test_ir_version_is_four() -> None:
    # RFC 0016 M12, RFC 0017 M13, and now `ProjectIR.coverage` + `MartIR.asserts`
    # each change the IR shape; RFC 0003 D3 makes the version part of the
    # fingerprint, so each bump is deliberate and loud. This wave nearly shipped
    # without one: the fingerprints moved anyway (the encoder covers field names
    # and count), so nothing failed — but `plan()` would have diffed a
    # coverage-carrying IR against one without, both calling themselves v3.
    assert ProjectIR().bloomery_ir_version == 4


def test_on_fail_is_the_disposition_set() -> None:
    # RFC 0016 §5.1/D2: deliberately no `drop`. `repair` joined in D87, once
    # RFC 0017's registry supplied the recipe contract D17 gated it on — and it
    # is last because it is the one member that resolves to another.
    assert [member.value for member in OnFail] == ["flag", "quarantine", "fail", "repair"]


def test_field_rule_carries_its_column_and_params() -> None:
    rule = QualityRuleIR(
        name="unit_price_range_min",
        kind="range",
        column="unit_price",
        on_fail=OnFail.QUARANTINE,
        params=(("min", "0"),),
    )
    assert rule.column == "unit_price"
    assert rule.params == (("min", "0"),)
    with pytest.raises(AttributeError):
        rule.on_fail = OnFail.FLAG  # type: ignore[misc]


def test_row_rule_has_no_target_column() -> None:
    rule = QualityRuleIR(
        name="discount_not_exceeding_gross",
        kind="expression",
        column=None,
        on_fail=OnFail.FLAG,
        params=(("expr", "discount <= unit_price * quantity"),),
    )
    assert rule.column is None


def test_referential_disposition_lives_in_params_not_on_fail() -> None:
    # `unknown_member` is not an OnFail: the row passes with its fk rewritten
    # to the reserved member — neither flagged nor diverted (RFC 0016 D19).
    rule = QualityRuleIR(
        name="item_of_order",
        kind="referential",
        column=None,
        on_fail=None,
        params=(("on_missing", "unknown_member"), ("via", "item_of_order")),
    )
    assert rule.on_fail is None
    assert dict(rule.params)["on_missing"] == "unknown_member"


def test_quality_sort_key_is_total_over_the_whole_value() -> None:
    # §5.3's worked example: two `range` rules on one column, distinguished
    # only by their bounds — permuting them must not change the IR.
    low = QualityRuleIR("r", "range", "unit_price", OnFail.QUARANTINE, (("min", "0"),))
    high = QualityRuleIR("r", "range", "unit_price", OnFail.FLAG, (("max", "1000000"),))
    assert sorted((low, high), key=quality_sort_key) == sorted((high, low), key=quality_sort_key)
    assert quality_sort_key(low) != quality_sort_key(high)


def test_quality_sort_key_orders_row_rules_before_a_named_column() -> None:
    row = QualityRuleIR("x", "expression", None, OnFail.FLAG)
    field = QualityRuleIR("x", "expression", "amount", OnFail.FLAG)
    assert quality_sort_key(row) < quality_sort_key(field)  # "" sorts first


def test_dedupe_tie_break_keeps_authored_order() -> None:
    dedupe = DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id", "_batch"))
    assert dedupe.tie_break == ("_load_id", "_batch")  # a sort order is semantic
    assert dedupe != DedupeIR(
        keep="latest_by", field="_ingested_at", tie_break=("_batch", "_load_id")
    )


def test_dedupe_tie_break_defaults_to_empty() -> None:
    # empty means the compile stage has yet to refuse it, never that ties are
    # allowed (DedupeTieBreakMissing, RFC 0016 §5.3)
    assert DedupeIR(keep="latest_by", field="_ingested_at").tie_break == ()


def test_quarantine_holds_the_retention_string_and_redact_paths() -> None:
    quarantine = QuarantineIR(retention="90d", redact=("$.a.email", "$.b.phone"))
    assert quarantine.retention == "90d"
    assert quarantine.redact == ("$.a.email", "$.b.phone")


def test_reconcile_tolerance_is_a_decimal() -> None:
    block = ReconcileIR(
        name="order_total_matches_lines",
        left="sum(order_item.line_total) by order_id",
        right="order.total_amount",
        tolerance=Decimal("0.01"),
        on_fail=OnFail.FLAG,
    )
    assert block.tolerance == Decimal("0.01")
    assert not isinstance(block.tolerance, float)
    # exact by construction: 0.01 and 0.010 are the same number, distinct text
    assert block.tolerance == Decimal("0.010")
