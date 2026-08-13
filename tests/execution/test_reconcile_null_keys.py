"""A reconcile check over a NULL key, executed (RFC 0016 §5.3).

``GROUP BY`` and ``=`` disagree about NULL, and a reconcile model contains
both. The aggregate side groups every NULL key into one group — SQL's
``GROUP BY`` treats NULLs as equal — and the join then used an ordinary ``=``,
which does not. One query, two rules for the same column.

The consequence is not a conservative failure. It is a **wrong number**: a
NULL-keyed group whose two sides *agree* came back as two rows, one per side,
both keyed NULL, both ``within_tolerance = FALSE``, both with a NULL
``difference``. A check whose data was correct reported two failures and named
neither of them.

This module runs the emitted SQL rather than reading it, because that is the
only way to state the claim as a row count. It also pins the case the null-safe
join must *not* soften: a key genuinely present on one side only is still the
loudest disagreement there is, and must still fail.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.execution

#: Two entities and one reconcile between them: the sum of a line-level amount
#: by ``order_id`` against the order-level total. ``line.order_id`` is not
#: ``required``, which is the whole point — nothing in the spec layer forces a
#: key or a ``by`` column to be non-nullable, so a NULL group is reachable from
#: an ordinary, valid project.
SOURCES = {
    "entity_model": """\
spec_version: 1
entities:
  line:
    grain: one row per order line
    key: [line_id]
    fields:
      line_id: {type: string, required: true}
      order_id: {type: string}
      amount: {type: "decimal(12,2)"}
  order_total:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12,2)"}
reconcile:
  - {name: lines_match_total, left: "sum(line.amount) by order_id",
     right: "order_total.amount", tolerance: "0.01", on_fail: flag}
""",
    "mapping_line": """\
mapping_version: 1
source: src__lines
target: line
key: {line_id: {from: "$.id", transform: [to_string]}}
fields:
  order_id: {from: "$.order_id", transform: [to_string]}
  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}
""",
    "mapping_order": """\
mapping_version: 1
source: src__orders
target: order_total
key: {order_id: {from: "$.id", transform: [to_string]}}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}
""",
}

#: Four groups, one per case the join has to get right.
#:
#: - ``o1`` — matched and agreeing.
#: - ``o2`` — left only (lines with no order row).
#: - ``o3`` — right only (an order with no lines).
#: - ``NULL`` — matched *and agreeing*, through a key that is NULL on both
#:   sides. The case that was reported as two failures.
LINES = [
    ("l1", "o1", Decimal("10.00")),
    ("l2", "o1", Decimal("5.00")),
    ("l3", "o2", Decimal("3.00")),
    ("l4", None, Decimal("7.00")),
]
ORDERS = [
    ("o1", Decimal("15.00")),
    ("o3", Decimal("9.00")),
    (None, Decimal("7.00")),
]


@pytest.fixture(scope="module")
def run() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    connection.execute(
        "CREATE TABLE bronze.src__lines (id VARCHAR, order_id VARCHAR, amount DECIMAL(12, 2))"
    )
    connection.executemany("INSERT INTO bronze.src__lines VALUES (?, ?, ?)", LINES)
    connection.execute("CREATE TABLE bronze.src__orders (id VARCHAR, amount DECIMAL(12, 2))")
    connection.executemany("INSERT INTO bronze.src__orders VALUES (?, ?)", ORDERS)
    materialize(connection, compile_project(load_project(SOURCES), target=Target.SQLMESH, dialect="duckdb"))
    yield connection
    connection.close()


def _rows(conn: duckdb.DuckDBPyConnection) -> dict[str | None, tuple[object, ...]]:
    return {
        order_id: (left, right, difference, within)
        for order_id, left, right, difference, within in conn.execute(
            "SELECT order_id, left_value, right_value, difference, within_tolerance "
            "FROM silver.lines_match_total__reconcile"
        ).fetchall()
    }


def test_a_null_key_compares_once_rather_than_failing_twice(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The defect, as a row count.

    Before the null-safe join this was two rows, both keyed NULL and both
    failing. It is one row, and it passes — because the two sides agree.
    """
    null_rows = run.execute(
        "SELECT left_value, right_value, difference, within_tolerance "
        "FROM silver.lines_match_total__reconcile WHERE order_id IS NULL"
    ).fetchall()
    assert null_rows == [(Decimal("7.00"), Decimal("7.00"), Decimal("0.00"), True)]


def test_a_null_key_that_disagrees_still_fails(run: duckdb.DuckDBPyConnection) -> None:
    """The other half, and the one a fix could quietly break: matching the NULL
    group must not stop it being *checked*. Re-run against a right side moved
    outside the tolerance, in a second warehouse so the module's own run stays
    the clean one."""
    connection = warehouse()
    connection.execute(
        "CREATE TABLE bronze.src__lines (id VARCHAR, order_id VARCHAR, amount DECIMAL(12, 2))"
    )
    connection.executemany("INSERT INTO bronze.src__lines VALUES (?, ?, ?)", LINES)
    connection.execute("CREATE TABLE bronze.src__orders (id VARCHAR, amount DECIMAL(12, 2))")
    connection.executemany(
        "INSERT INTO bronze.src__orders VALUES (?, ?)",
        [*ORDERS[:-1], (None, Decimal("99.00"))],
    )
    materialize(
        connection,
        compile_project(load_project(SOURCES), target=Target.SQLMESH, dialect="duckdb"),
    )
    try:
        assert connection.execute(
            "SELECT left_value, right_value, within_tolerance "
            "FROM silver.lines_match_total__reconcile WHERE order_id IS NULL"
        ).fetchall() == [(Decimal("7.00"), Decimal("99.00"), False)]
    finally:
        connection.close()


def test_one_sided_keys_are_still_the_loudest_disagreement(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """A FULL join exists so that a key on one side only fails rather than
    vanishing. Null-safe equality matches NULL *to NULL*, not to absence, so
    both one-sided cases are untouched."""
    rows = _rows(run)
    assert rows["o2"] == (Decimal("3.00"), None, None, False)
    assert rows["o3"] == (None, Decimal("9.00"), None, False)


def test_the_matched_case_is_unchanged(run: duckdb.DuckDBPyConnection) -> None:
    """The control. Every assertion above is about NULLs; this is the ordinary
    row, and it would be the first casualty of a join written wrong."""
    assert _rows(run)["o1"] == (Decimal("15.00"), Decimal("15.00"), Decimal("0.00"), True)


def test_every_group_produces_exactly_one_row(run: duckdb.DuckDBPyConnection) -> None:
    """The property underneath all four cases: a reconcile model is one row per
    compared key. The defect was a violation of exactly this — NULL produced
    two — and stating it as a count is what would catch a different key type
    regressing the same way."""
    total, distinct = run.execute(
        "SELECT COUNT(*), COUNT(DISTINCT COALESCE(order_id, '<null>')) "
        "FROM silver.lines_match_total__reconcile"
    ).fetchone() or (0, 0)
    assert total == distinct == 4
