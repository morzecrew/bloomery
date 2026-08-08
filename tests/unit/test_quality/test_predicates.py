"""Violation predicates (RFC 0016 §5.4, D18/D19).

Three things are asserted here, and RFC 0016 §6 names all three:

- the **exhaustive** rule × disposition lowering matrix — ``product(ALL_RULES,
  ALL_DISPOSITIONS)``, every pair lowering to SQL that parses under DuckDB,
  because "a missing pair is exactly the gap that ships";
- **three-valued logic** per rule: a NULL-involved comparison evaluates to SQL
  ``UNKNOWN`` and must not fire. This is asserted by *executing* the predicate
  against a null row in DuckDB and requiring ``NULL``, not ``TRUE`` — reading
  the AST would only prove the shape, not the semantics;
- **disposition precedence** ``fail > quarantine > flag``, and the rule that a
  quarantined row records all its failures, flag-level ones included.
"""

from __future__ import annotations

from itertools import product

import duckdb
import pytest
from sqlglot import exp, parse_one

from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import (
    ALL_DISPOSITIONS,
    ALL_ON_MISSING,
    ALL_RULES,
    FIELD_RULES,
    ROW_RULES,
    UNKNOWN_MEMBER,
    disposition,
    failed_rule_names,
    ref_alias,
    source_alias,
    unknown_member_case,
    violation,
    window_alias,
    windowed,
    worst,
)
from support.quality_rules import ON_MISSING_RULES, referential_rule, rule_of_kind

pytestmark = pytest.mark.unit


# ....................... #
# The exhaustive matrix (RFC 0016 §6)


def test_the_catalogue_is_the_union_of_the_two_levels() -> None:
    """``ALL_RULES`` is what the matrix iterates, so it must not drift from
    the field/row split the pipeline order separates."""
    assert set(ALL_RULES) == set(FIELD_RULES) | set(ROW_RULES)
    assert tuple(sorted(ALL_RULES)) == ALL_RULES


@pytest.mark.parametrize(("kind", "on_fail"), list(product(ALL_RULES, ALL_DISPOSITIONS)))
def test_every_rule_disposition_pair_lowers_and_parses(kind: str, on_fail: OnFail) -> None:
    rule = rule_of_kind(kind, on_fail)
    rendered = violation(rule).sql(dialect="duckdb")
    assert parse_one(f"SELECT 1 WHERE {rendered}", dialect="duckdb") is not None


def test_a_predicate_carrying_a_window_declares_itself_windowed() -> None:
    """The catalogue's own statement of where its predicates are legal.

    SQL allows a window function in a projection and forbids it in a ``WHERE``
    clause, and the lowering reads a violation predicate from *both* — routing
    filters on it, an audit body filters on it, the conservation audit sums
    over it. A kind whose predicate contains a window must therefore be
    computed once as a column and referenced by name
    (:func:`~bloomery.quality.window_alias`), and this is the assertion that
    keeps the declaration and the predicate from drifting: a rule that grows a
    window later fails here rather than at the first engine that binds it.
    """
    for kind in ALL_RULES:
        rule = rule_of_kind(kind)
        carries = violation(rule).find(exp.Window) is not None
        assert carries is windowed(rule), kind


def test_the_window_alias_is_derived_from_the_rule_name() -> None:
    """Two windowed rules on one entity each need their own column."""
    assert window_alias(rule_of_kind("unique")) == "_win_amount_unique"


@pytest.mark.parametrize("on_missing", ALL_ON_MISSING)
def test_referential_lowers_once_per_on_missing(on_missing: str) -> None:
    """``referential`` contributes its own axis (RFC 0016 §6), one row per
    ``on_missing`` — each asserting its §5.4 lowering."""
    rule = ON_MISSING_RULES[on_missing]
    probe = violation(rule).sql(dialect="duckdb")
    # Every disposition shares the same LEFT JOIN probe (§5.4's table).
    assert probe == "_ref_item_of_order.order_id IS NULL AND (NOT order_id IS NULL)"
    if on_missing == "unknown_member":
        rewrite = unknown_member_case(rule).sql(dialect="duckdb")
        assert rewrite.startswith("CASE WHEN _ref_item_of_order.order_id IS NULL")
        assert f"THEN '{UNKNOWN_MEMBER}'" in rewrite
        assert rewrite.endswith("ELSE order_id END")


def test_ref_alias_is_derived_from_the_relationship_not_the_entity() -> None:
    """Two relationships may point at the same entity; each needs its own
    probe."""
    assert ref_alias("item_of_order") == "_ref_item_of_order"
    assert ref_alias("item_of_parent_order") == "_ref_item_of_parent_order"


# ....................... #
# Three-valued logic (RFC 0016 D19) — executed, not merely inspected


def _evaluate(rule: QualityRuleIR, row: dict[str, object]) -> bool | None:
    """Evaluate a violation predicate against one row in DuckDB."""
    columns = ", ".join(f"? AS {name}" for name in row)
    sql = f"SELECT ({violation(rule).sql(dialect='duckdb')}) FROM (SELECT {columns})"
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(sql, list(row.values())).fetchone()
    assert result is not None
    return result[0]


#: Rules whose violation predicate must stay ``UNKNOWN`` on a null operand
#: (D19: ``not_null`` and ``coercible`` are the two that own nulls).
_NULL_SILENT = ("range", "length", "pattern", "in_enum", "in_set", "unique", "expression")


@pytest.mark.parametrize("kind", _NULL_SILENT)
def test_a_null_operand_never_fires(kind: str) -> None:
    rule = rule_of_kind(kind)
    row: dict[str, object] = {"amount": None, "order_date": "2024-01-01"}
    if kind == "expression":
        row = {"discount": None, "unit_price": 10, "quantity": 2}
    assert _evaluate(rule, row) is not True


@pytest.mark.parametrize("kind", _NULL_SILENT)
def test_a_definite_violation_does_fire(kind: str) -> None:
    """The mirror of the test above: silence on NULL must not be silence on
    everything."""
    violations: dict[str, dict[str, object]] = {
        "range": {"amount": -1, "order_date": "2024-01-01"},
        "length": {"amount": "123456789", "order_date": "2024-01-01"},
        "pattern": {"amount": "abc", "order_date": "2024-01-01"},
        "in_enum": {"amount": "z", "order_date": "2024-01-01"},
        "in_set": {"amount": "z", "order_date": "2024-01-01"},
        "unique": {"amount": "a", "order_date": "2024-01-01"},
        "expression": {"discount": 100, "unit_price": 10, "quantity": 2},
    }
    if kind == "unique":
        pytest.skip("a window predicate needs more than one row; covered below")
    assert _evaluate(rule_of_kind(kind), violations[kind]) is True


def test_unique_counts_within_the_partition_slice_and_ignores_nulls() -> None:
    """The slice is the entity's partition (D5): duplicates in *different*
    slices are not this rule's business, and two null rows are nobody's."""
    rendered = violation(rule_of_kind("unique")).sql(dialect="duckdb")
    sql = f"SELECT amount, ({rendered}) AS fired FROM rows ORDER BY 1 NULLS LAST"
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE rows (amount VARCHAR, order_date VARCHAR)")
        connection.executemany(
            "INSERT INTO rows VALUES (?, ?)",
            [
                ("dup", "2024-01-01"),
                ("dup", "2024-01-01"),  # same slice — a duplicate
                ("dup", "2024-01-02"),  # different slice — not a duplicate
                (None, "2024-01-01"),
                (None, "2024-01-01"),  # two nulls are not_null's business
            ],
        )
        rows = connection.execute(sql).fetchall()
    # The null rows read FALSE rather than NULL — the explicit ``IS NOT NULL``
    # conjunct is definitively false, and "does not fire" is what D19 asks for.
    assert rows == [("dup", True), ("dup", True), ("dup", False), (None, False), (None, False)]


def test_not_null_owns_nulls() -> None:
    rule = rule_of_kind("not_null")
    assert _evaluate(rule, {"amount": None}) is True
    assert _evaluate(rule, {"amount": 1}) is False


def test_coercible_fires_only_when_the_source_was_present() -> None:
    """The marker is "the projection is NULL although every source it reads
    was not" — a genuinely null source is a legitimate null, not a coercion
    failure (RFC 0016 §5.2)."""
    rule = rule_of_kind("coercible")
    alias = source_alias(rule, 0)
    assert _evaluate(rule, {"amount": None, alias: "twelve"}) is True
    assert _evaluate(rule, {"amount": None, alias: None}) is False
    assert _evaluate(rule, {"amount": 12, alias: "12"}) is False


def test_a_null_fk_is_not_an_orphan() -> None:
    """D19's headline correction of Document 5's ``COALESCE`` sketch."""
    rule = referential_rule("quarantine")
    predicate = violation(rule, table="_extract").sql(dialect="duckdb")
    sql = (
        f"SELECT ({predicate}) FROM (SELECT NULL AS order_id) AS _extract, "
        "(SELECT NULL AS order_id) AS _ref_item_of_order"
    )
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(sql).fetchone() == (False,)


def test_composite_predicates_are_parenthesised() -> None:
    """SQLGlot adds no precedence parentheses of its own; a mis-parenthesised
    quality predicate is a silently wrong disposition."""
    rendered = violation(rule_of_kind("range")).sql()
    assert rendered == "amount < 0 OR amount > 1000000"
    nested = violation(rule_of_kind("coercible")).sql()
    assert nested == "amount IS NULL AND (NOT _src_amount_coercible_0000 IS NULL)"


def test_expression_bodies_are_qualified_and_negated_as_a_whole() -> None:
    rendered = violation(rule_of_kind("expression"), table="_extract").sql()
    assert rendered == ("NOT (_extract.discount <= _extract.unit_price * _extract.quantity)")


def test_qualification_never_mutates_the_input_ast() -> None:
    rule = rule_of_kind("range")
    first = violation(rule, table="_extract").sql()
    second = violation(rule).sql()
    assert first.startswith("_extract.")
    assert not second.startswith("_extract.")


# ....................... #
# Disposition precedence (RFC 0016 D18)


def test_severity_order_is_fail_over_quarantine_over_flag() -> None:
    flag = rule_of_kind("range", OnFail.FLAG)
    quarantine = rule_of_kind("length", OnFail.QUARANTINE)
    fail = rule_of_kind("not_null", OnFail.FAIL)
    assert worst([flag]) is OnFail.FLAG
    assert worst([flag, quarantine]) is OnFail.QUARANTINE
    assert worst([flag, quarantine, fail]) is OnFail.FAIL
    assert worst([quarantine, fail]) is OnFail.FAIL
    assert worst([]) is None


def test_a_quarantined_row_records_its_flag_level_failures_too() -> None:
    """D18: ``failed_rules`` is the full account of why a row is not in the
    entity, not merely the part that diverted it."""
    rules = [
        rule_of_kind("range", OnFail.FLAG),
        rule_of_kind("length", OnFail.QUARANTINE),
        rule_of_kind("not_null", OnFail.FLAG),
    ]
    assert failed_rule_names(rules) == ("amount_length", "amount_not_null", "amount_range")


def test_referential_dispositions_map_onto_the_three_value_model() -> None:
    """``unknown_member`` keeps the row, so it reads as ``FLAG`` — never
    ``QUARANTINE``, which would divert the row the reserved member exists to
    keep."""
    assert disposition(ON_MISSING_RULES["flag"]) is OnFail.FLAG
    assert disposition(ON_MISSING_RULES["quarantine"]) is OnFail.QUARANTINE
    assert disposition(ON_MISSING_RULES["unknown_member"]) is OnFail.FLAG


def test_every_pair_yields_a_deterministic_disposition() -> None:
    """No rule/disposition combination needs compile-time rejection (D18):
    the outcome is defined for all of them."""
    for kind, on_fail in product(ALL_RULES, ALL_DISPOSITIONS):
        rule = rule_of_kind(kind, on_fail)
        expected = OnFail.FLAG if kind == "referential" else on_fail
        assert disposition(rule) is expected


def test_an_unknown_rule_kind_is_a_loud_key_error() -> None:
    unknown = QualityRuleIR(name="x", kind="telepathy", column="amount", on_fail=OnFail.FLAG)
    with pytest.raises(KeyError, match="telepathy"):
        violation(unknown)


def test_predicates_render_on_every_shipped_dialect() -> None:
    """One neutral AST, per-dialect legal rendering (RFC 0008 doctrine)."""
    for kind in ALL_RULES:
        node = violation(rule_of_kind(kind))
        for dialect in ("duckdb", "postgres", "trino"):
            assert isinstance(parse_one(node.sql(dialect=dialect), dialect=dialect), exp.Expression)
