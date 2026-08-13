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
from support.reconcile import LINES, ORDERS, SOURCES

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.execution


@pytest.fixture(scope="module")
def run() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    connection.execute(
        "CREATE TABLE bronze.src__lines (id VARCHAR, order_id VARCHAR, amount DECIMAL(12, 2))"
    )
    connection.executemany("INSERT INTO bronze.src__lines VALUES (?, ?, ?)", LINES)
    connection.execute("CREATE TABLE bronze.src__orders (id VARCHAR, amount DECIMAL(12, 2))")
    connection.executemany("INSERT INTO bronze.src__orders VALUES (?, ?)", ORDERS)
    materialize(
        connection,
        compile_project(load_project(SOURCES), target=Target.SQLMESH, dialect="duckdb"),
    )
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


def test_a_null_key_that_disagrees_still_fails() -> None:
    """The other half, and the one a fix could quietly break: matching the NULL
    group must not stop it being *checked*.

    Builds its own warehouse rather than taking the module's — the seed differs
    on purpose, and a test that mutated the shared run would leave every
    assertion after it describing a run nobody declared.
    """
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
