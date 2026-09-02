"""Currency conversion, executed (RFC 0023 §5.4, RFC 0009 §5.2 tier 4).

The compile-time checks prove a rate subquery is *emitted*; this proves it
converts at the rate that was current when the payment was made, which is the
claim the feature exists for and a different one.

The specimen: EUR→USD moved from 1.10 to 1.20 on 2024-06-01, and back to 1.05
on 2024-09-01. Three payments of €100 straddle those boundaries.

- ``p1`` (2024-03-10) converts at 1.10 → $110
- ``p2`` (2024-07-04) converts at 1.20 → $120
- ``p3`` (2024-10-20) converts at 1.05 → $105

Converting all three at today's rate is the defect this refuses: $315 against
the correct $335 is not a crash, it is revenue restated at a price that was
never paid, and every row count stays right.

``p4`` is the miss: a payment dated before the feed begins. With both interval
ends declared it matches no rate and converts to NULL (D11) — the alternative,
extending the oldest or newest rate to cover it, prices a payment at a rate
that did not exist and says nothing.

All money is ``Decimal`` — floats never appear (RFC 0003 D5).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest

from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.execution

FIXTURE = "currency_convert"

#: ``(from_ccy, to_ccy, rate, valid_from, valid_to)`` — the half-open intervals
#: the emitted predicate reads. ``valid_to`` NULL is the live rate.
RATES = [
    ("EUR", "USD", Decimal("1.10"), "2024-01-01", "2024-06-01"),
    ("EUR", "USD", Decimal("1.20"), "2024-06-01", "2024-09-01"),
    ("EUR", "USD", Decimal("1.05"), "2024-09-01", None),
    # A pair nothing converts through: the predicate must not pick it up.
    ("GBP", "USD", Decimal("9.99"), "2024-01-01", None),
]

#: ``(id, amount, fee, paid_at)`` as bronze holds them — text, like every payload.
PAYMENTS = [
    ("p1", "100.00", "1.50", "2024-03-10"),
    ("p2", "100.00", "2.50", "2024-07-04"),
    ("p3", "100.00", "3.00", "2024-10-20"),
    # Before the feed begins: no interval contains it.
    ("p4", "100.00", "4.00", "2023-11-30"),
]


@pytest.fixture(scope="module")
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    conn.execute("CREATE SCHEMA bronze")
    conn.execute("CREATE SCHEMA silver")
    conn.execute(
        "CREATE TABLE silver.fx_rate (from_ccy VARCHAR, to_ccy VARCHAR, "
        "rate DECIMAL(12, 4), valid_from DATE, valid_to DATE)"
    )
    conn.executemany("INSERT INTO silver.fx_rate VALUES (?, ?, ?, ?, ?)", RATES)
    conn.execute("CREATE TABLE bronze.psp__payments (id VARCHAR, amount VARCHAR, fee VARCHAR, paid_at VARCHAR)")
    conn.executemany("INSERT INTO bronze.psp__payments VALUES (?, ?, ?, ?)", PAYMENTS)

    artifact = next(
        a for a in compile_fixture(FIXTURE, dialect="duckdb") if a.path.endswith("payment.sql")
    )
    conn.execute(f"CREATE TABLE silver.payment AS {extract_select(artifact.content)}")
    yield conn
    conn.close()


def test_each_payment_converts_at_the_rate_that_was_current_when_it_was_paid(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The feature, in one assertion. Three identical €100 payments become
    three different dollar amounts, because the rate moved between them."""
    rows = warehouse.execute(
        "SELECT payment_id, amount_usd FROM silver.payment "
        "WHERE amount_usd IS NOT NULL ORDER BY payment_id"
    ).fetchall()

    assert rows == [
        ("p1", Decimal("110.0000")),
        ("p2", Decimal("120.0000")),
        ("p3", Decimal("105.0000")),
    ]


def test_the_source_amount_is_untouched(warehouse: duckdb.DuckDBPyConnection) -> None:
    """Conversion writes a second column; it never rewrites the amount that was
    actually paid."""
    rows = warehouse.execute(
        "SELECT DISTINCT amount_eur FROM silver.payment"
    ).fetchall()

    assert rows == [(Decimal("100.0000"),)]


def test_the_conversion_keeps_the_row_count(warehouse: duckdb.DuckDBPyConnection) -> None:
    """A scalar subquery converts; it does not fan out. Three rate versions for
    EUR→USD would each match a payment under a one-ended interval — which is
    the multiplication D11 refuses to allow."""
    count = warehouse.execute("SELECT COUNT(*) FROM silver.payment").fetchone()
    assert count is not None
    assert count[0] == len(PAYMENTS)


def test_a_payment_outside_every_interval_converts_to_null(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """D11's miss: a gap in the feed is a miss, not the nearest rate. NULL
    propagates and stays visible; a neighbouring rate would be a number nobody
    could tell from a real one."""
    rows = warehouse.execute(
        "SELECT payment_id FROM silver.payment WHERE amount_usd IS NULL"
    ).fetchall()

    assert rows == [("p4",)]


def test_the_other_currency_pair_is_not_read(warehouse: duckdb.DuckDBPyConnection) -> None:
    """The GBP→USD rate of 9.99 overlaps every payment date. It is excluded by
    the two currency equalities, not by luck of the interval."""
    total = warehouse.execute(
        "SELECT SUM(amount_usd) FROM silver.payment"
    ).fetchone()
    assert total is not None
    assert total[0] == Decimal("335.0000")


def test_without_the_validity_predicate_the_same_conversion_multiplies(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """Why both interval ends are required, executed rather than argued (D11).

    The emitted SQL is re-run with the interval conditions stripped — which is
    what a one-ended `valid_from`-only declaration would produce — and the
    scalar subquery now matches three rate rows per payment.

    DuckDB raises here, which is the *lucky* outcome and not the one to rely
    on: its own message offers `SET scalar_subquery_error_on_multiple_rows=
    false` "to revert to previous behavior of returning a random row", so this
    same spec converted at an arbitrary one of the three rates on an older
    engine. Written as a join instead of a subquery it would not raise at all —
    it would return three rows per payment and triple the revenue. Either way
    the declared upper bound is what stops it, which is why D11 requires it
    rather than deriving it.
    """
    artifact = next(
        a for a in compile_fixture(FIXTURE, dialect="duckdb") if a.path.endswith("payment.sql")
    )
    select = extract_select(artifact.content)
    unguarded = re.sub(
        r"\s+AND CAST\(paid_at AS DATE\) >= fx\.valid_from\s+AND \(\s*fx\.valid_to IS NULL "
        r"OR CAST\(paid_at AS DATE\) < fx\.valid_to\s*\)",
        "",
        select,
    )
    assert unguarded != select, "the interval predicate was not found to strip"

    with pytest.raises(duckdb.InvalidInputException, match="(?i)more than one row"):
        warehouse.execute(f"SELECT * FROM ({unguarded})").fetchall()


def test_the_metric_the_ceiling_made_unexpressible(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """A converted amount added to one that was already USD — the whole point.

    Before §5.4 this had no spelling. `convert` was refused at emit, so
    `amount_usd` could not be produced at all; and adding the EUR column to the
    USD one is a `CurrencyMismatch`, correctly. A multi-currency business had
    no third option.

    110 + 1.50, 120 + 2.50, 105 + 3.00 = 342.00. `p4` converts to NULL and
    drops out of the sum, which is what a miss should do to a total rather than
    quietly contributing a made-up rate.
    """
    total = warehouse.execute(
        "SELECT SUM(amount_usd + fee_usd) FROM silver.payment"
    ).fetchone()
    assert total is not None
    assert total[0] == Decimal("342.0000")
