"""The ``_quality_flags`` / ``failed_rules`` physical contract (RFC 0016 D23)
and its single-pass shape (§5.4).

The contract is what makes the two lowerings comparable, so it is asserted as
a contract: never NULL, empty collection for a clean row, lexicographic order,
``_quality_ok`` generated per shape — and, for the array/string pair, the same
flag *set* out of both. The single-pass property is asserted structurally: one
expression, each predicate appearing exactly once.
"""

from __future__ import annotations

import duckdb
import pytest
from sqlglot import exp

from bloomery.ir import OnFail
from bloomery.quality import (
    DELIMITER,
    empty_flags,
    flag_member,
    flags_expression,
    quality_ok,
    violation,
)
from support.quality_rules import rule_of_kind

pytestmark = pytest.mark.unit


def _pairs() -> list[tuple[str, exp.Expression]]:
    """Two rules, deliberately handed over in reverse-lexicographic order —
    the builder must impose D23's order, not inherit the caller's."""
    return [
        ("zeta_rule", violation(rule_of_kind("range", OnFail.FLAG))),
        ("alpha_rule", violation(rule_of_kind("not_null", OnFail.FLAG))),
    ]


def _evaluate(node: exp.Expression, row: dict[str, object]) -> object:
    columns = ", ".join(f"? AS {name}" for name in row) or "1"
    sql = f"SELECT ({node.sql(dialect='duckdb')}) FROM (SELECT {columns})"
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(sql, list(row.values())).fetchone()
    assert result is not None
    return result[0]


# ....................... #
# The physical contract (D23)


@pytest.mark.parametrize("arrays", [True, False])
def test_a_clean_row_carries_the_empty_collection_never_null(arrays: bool) -> None:
    node = flags_expression(_pairs(), arrays=arrays)
    assert _evaluate(node, {"amount": 5}) == ([] if arrays else "")
    assert _evaluate(empty_flags(arrays=arrays), {}) == ([] if arrays else "")


@pytest.mark.parametrize("arrays", [True, False])
def test_flags_are_lexicographic_regardless_of_input_order(arrays: bool) -> None:
    node = flags_expression(_pairs(), arrays=arrays)
    fired = _evaluate(node, {"amount": None})  # not_null fires, range stays UNKNOWN
    assert fired == (["alpha_rule"] if arrays else "alpha_rule")
    both = _evaluate(flags_expression(_pairs(), arrays=arrays), {"amount": -1})
    # ``-1`` violates range; ``not_null`` does not fire, so only one name.
    assert both == (["zeta_rule"] if arrays else "zeta_rule")


def test_the_two_lowerings_agree_on_the_flag_set() -> None:
    """D23's whole point: the array and the delimited string carry the same
    set, in the same order, so a comparison across them is an equality."""
    pairs = [
        ("alpha_rule", violation(rule_of_kind("not_null", OnFail.FLAG))),
        ("zeta_rule", violation(rule_of_kind("not_null", OnFail.FLAG))),
    ]
    row: dict[str, object] = {"amount": None}
    as_array = _evaluate(flags_expression(pairs, arrays=True), row)
    as_string = _evaluate(flags_expression(pairs, arrays=False), row)
    assert as_array == ["alpha_rule", "zeta_rule"]
    assert isinstance(as_string, str)
    assert as_string.split(DELIMITER) == as_array


@pytest.mark.parametrize("arrays", [True, False])
def test_quality_ok_is_generated_per_shape(arrays: bool) -> None:
    node = quality_ok(arrays=arrays)
    rendered = node.sql(dialect="duckdb")
    assert rendered == ("ARRAY_LENGTH(_quality_flags) = 0" if arrays else "_quality_flags = ''")


def test_quality_ok_never_spells_cardinality_on_duckdb() -> None:
    """DuckDB's ``CARDINALITY`` operates on MAPs only — the neutral
    ``ArraySize`` node is what keeps one AST legal on all three."""
    node = quality_ok(arrays=True)
    assert node.sql(dialect="trino") == "CARDINALITY(_quality_flags) = 0"
    assert node.sql(dialect="postgres") == "ARRAY_LENGTH(_quality_flags, 1) = 0"


def test_quality_ok_can_be_qualified() -> None:
    assert quality_ok(table="_evaluated", arrays=True).sql() == (
        "ARRAY_LENGTH(_evaluated._quality_flags) = 0"
    )


# ....................... #
# One pass, never N (RFC 0016 §5.4)


def test_flag_construction_is_a_single_expression_per_row() -> None:
    node = flags_expression(_pairs(), arrays=True)
    # One expression; each rule contributes exactly one CASE, so each
    # predicate is evaluated once — never a scan per rule.
    cases = list(node.find_all(exp.Case))
    assert len(cases) == len(_pairs())
    assert node.find(exp.Select) is None  # no correlated subquery anywhere


def test_no_rules_collapses_to_the_empty_constant() -> None:
    for arrays in (True, False):
        assert flags_expression([], arrays=arrays).sql() == empty_flags(arrays=arrays).sql()


def test_rule_names_never_need_escaping() -> None:
    """Names are ``[a-z0-9_]+`` by construction (D23), so the delimited
    fallback can be split on ``,`` without a quoting rule: the only commas in
    the rendered SQL are the separators the builder itself emits."""
    rendered = flags_expression(_pairs(), arrays=False).sql(dialect="duckdb")
    assert "',alpha_rule'" in rendered
    assert "',zeta_rule'" in rendered
    assert rendered.endswith(", ',')")  # the LTRIM argument
    assert rendered.count(DELIMITER) == len(_pairs()) + 2  # two names, the trim, its separator


# ....................... #
# Reading a stored collection back (the quality mart's per-rule counts, §5.8)


def test_flag_membership_reads_both_shapes_the_same_way() -> None:
    """One rule name, two stored shapes, one answer — the read side of the D23
    contract. Executed rather than string-matched: what matters is that both
    lowerings agree on the *set*, which is exactly what the dialect-matrix tier
    asserts for the write side."""
    stored = ("alpha_rule", "zeta_rule")
    connection = duckdb.connect(":memory:")
    try:
        for name, expected in (("alpha_rule", True), ("zeta_rule", True), ("beta_rule", False)):
            array_sql = flag_member(
                exp.cast(
                    exp.Array(expressions=[exp.Literal.string(flag) for flag in stored]),
                    exp.DataType.build("TEXT[]"),
                ),
                name,
                arrays=True,
            ).sql(dialect="duckdb")
            string_sql = flag_member(
                exp.Literal.string(DELIMITER.join(stored)), name, arrays=False
            ).sql(dialect="duckdb")
            assert connection.execute(f"SELECT {array_sql}").fetchone() == (expected,)
            assert connection.execute(f"SELECT {string_sql}").fetchone() == (expected,)
    finally:
        connection.close()


def test_the_delimited_shape_is_not_fooled_by_underscores_or_prefixes() -> None:
    """Rule names contain ``_``, which is ``LIKE``'s single-character wildcard
    — matching by position instead is what keeps ``stock_level`` from being
    reported present when the row carries ``stockXlevel``. And delimiting both
    sides is what keeps ``,a,`` out of ``,ab,``."""
    connection = duckdb.connect(":memory:")
    try:
        for stored, name, expected in (
            ("stockXlevel", "stock_level", False),
            ("alpha_rule_two", "alpha_rule", False),
            ("two_alpha_rule", "alpha_rule", False),
            ("alpha_rule", "alpha_rule", True),
        ):
            sql = flag_member(exp.Literal.string(stored), name, arrays=False).sql(dialect="duckdb")
            assert connection.execute(f"SELECT {sql}").fetchone() == (expected,), (stored, name)
    finally:
        connection.close()
