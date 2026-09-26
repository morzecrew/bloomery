"""Rung 4s (S-0026/tier-contracts, S-0012/D-2): the emitted Databricks SQL, executed
against a **local Spark session** — something engine-shaped, never the engine.

`surrogate("databricks_spark")` and never `engine("databricks")` (S-0016/D-3):
local Spark checks shared Spark semantics, and only a live warehouse checks
the Databricks dialect. A green run here may not be quoted as Databricks
conformance in a CI log or in prose, which is why the claim is kept out of the
test's name rather than only out of its body. Types in particular stay with
the live lane, where `DESCRIBE QUERY` asks the real analyzer (S-0016/D-4) —
type spellings are precisely where Spark and Databricks SQL are documented to
differ, so a surrogate assertion over them would report that difference as a
defect.

Hence the corpus below covers **only the shared subset**: joins, filters,
aggregates, windows, common casts, regexp, arrays, basic date and timestamp
expressions, null propagation, arithmetic. Every case's SQL is rendered
through the `databricks` port, so what runs is what an artifact would carry,
and every expectation is stated here rather than read back from the engine —
an engine agreeing with itself is not evidence.

**This lane is on probation** (S-0016/D-7). It is kept only if it catches
defects the offline rungs miss, measured over this port's work; if it returns
none, the outcome is to delete this module and `tests/support/spark.py` and
record why, which is a decision rather than neglect.

Opt-in: excluded from `just test`, skipped with a stated reason when PySpark
(the test-only `spark` dependency group, S-0016/D-2) or a JVM is absent.
"""

from __future__ import annotations

import pytest
import sqlglot
from support import spark

from bloomery.dialects import get_dialect

PORT = get_dialect("databricks")

_MISSING = spark.missing_reason()

pytestmark = [
    pytest.mark.surrogate(spark.SURROGATE),
    pytest.mark.skipif(_MISSING is not None, reason=_MISSING or ""),
]

# ....................... #
# The fixture the corpus reads

CUSTOMERS = (("id", "BIGINT"), ("name", "STRING"))
CUSTOMER_ROWS = (("1", "'ada'"), ("2", "'bo'"))

ORDERS = (
    ("id", "BIGINT"),
    ("customer_id", "BIGINT"),
    ("sku", "STRING"),
    ("amount", "DECIMAL(12, 4)"),
    ("placed_at", "TIMESTAMP_NTZ"),
    ("tags", "ARRAY<STRING>"),
)
#: Three rows, one of them with a NULL measure: null propagation is a case
#: here, and a corpus without a NULL in it cannot state one.
ORDER_ROWS = (
    ("1", "1", "'sku-42'", "10.2500", "'2024-01-15 08:30:00'", "ARRAY('a', 'b')"),
    ("2", "1", "'sku-7'", "20.0000", "'2024-02-01 00:00:00'", "ARRAY('b')"),
    ("3", "2", "'sku-9'", "NULL", "'2024-02-29 23:59:59'", "ARRAY('c')"),
)


@pytest.fixture(scope="module", autouse=True)
def fixture_relations() -> None:
    """The two relations, registered once for the module's session."""
    spark.relation("customers", CUSTOMERS, CUSTOMER_ROWS)
    spark.relation("orders", ORDERS, ORDER_ROWS)


# ....................... #
# The shared subset

#: `(id, neutral SQL, expected rows)`. The SQL is dialect-neutral and rendered
#: through the port before it runs, so a rewrite the port makes is in the
#: statement the session sees. Expected values are text: :func:`spark.rows`
#: canonicalizes, so a `Decimal` scale and a timestamp's wall clock are both
#: asserted as written.
CASES: tuple[tuple[str, str, tuple[tuple[object, ...], ...]], ...] = (
    (
        "join-and-aggregate",
        "SELECT c.name, SUM(o.amount) AS total, COUNT(*) AS n "
        "FROM orders AS o JOIN customers AS c ON o.customer_id = c.id "
        "WHERE o.amount > 10 GROUP BY c.name",
        (("ada", "30.2500", "2"),),
    ),
    (
        # A NULL measure is not `> 10` and not `<= 10` either: the row leaves
        # the result, and it is the filter that drops it.
        "filter-drops-the-null-measure",
        "SELECT id FROM orders WHERE amount > 10",
        (("1",), ("2",)),
    ),
    (
        "window-running-total",
        "SELECT id, SUM(amount) OVER (PARTITION BY customer_id ORDER BY id) AS running "
        "FROM orders",
        (("1", "10.2500"), ("2", "30.2500"), ("3", None)),
    ),
    (
        "arithmetic-keeps-the-declared-scale",
        "SELECT id, amount * 2 AS doubled FROM orders WHERE id = 1",
        (("1", "20.5000"),),
    ),
    (
        "null-propagates-through-arithmetic",
        "SELECT id, amount + 1 AS bumped, COALESCE(amount, 0) AS filled "
        "FROM orders WHERE id = 3",
        (("3", None, "0.0000"),),
    ),
    (
        "cast-round-trips-through-text",
        "SELECT id, CAST(CAST(amount AS STRING) AS DECIMAL(12, 4)) AS roundtrip "
        "FROM orders WHERE id = 1",
        (("1", "10.2500"),),
    ),
    (
        "regexp-returns-the-capture-group",
        "SELECT id, REGEXP_EXTRACT(sku, 'sku-([0-9]+)', 1) AS captured "
        "FROM orders WHERE id = 1",
        (("1", "42"),),
    ),
    (
        "array-membership-and-length",
        "SELECT id, ARRAY_CONTAINS(tags, 'b') AS tagged, SIZE(tags) AS n "
        "FROM orders WHERE id = 2",
        (("2", "True", "1"),),
    ),
    (
        # The zoneless-UTC invariant (S-0045) in the one place a session zone
        # could still reach it: a truncation and a date, over TIMESTAMP_NTZ.
        "timestamp-truncation-keeps-the-wall-clock",
        "SELECT id, DATE_TRUNC('MONTH', placed_at) AS month, CAST(placed_at AS DATE) AS day "
        "FROM orders WHERE id = 1",
        (("1", "2024-01-01T00:00:00", "2024-01-15"),),
    ),
)


@pytest.mark.parametrize(("case_id", "neutral", "expected"), CASES, ids=[case[0] for case in CASES])
def test_shared_subset_evaluates_as_declared(
    case_id: str,
    neutral: str,
    expected: tuple[tuple[object, ...], ...],
) -> None:
    """The port's SQL runs on Spark and returns what the case declares."""
    statement = PORT.render(sqlglot.parse_one(neutral))
    assert spark.rows(statement) == tuple(sorted(expected, key=repr)), (
        f"{case_id}: Spark disagrees with the declared result of\n{statement}"
    )
