"""Filter-vocabulary execution acceptance (RFC 0015 §6, RFC 0009 §5.10):
run the SQL the planner renders for the CNF vocabulary against DuckDB marts
built from the emitted SQLMesh artifacts —

- an ``AnyOf`` clause returns exactly the rows of the two single-predicate
  queries UNIONed;
- row policy + ``AnyOf``: the policy predicate reaches every scan and the
  policy is never disjoined with the ``AnyOf`` branches, asserted on the
  parsed AST, plus the numeric leak check;
- ``like`` pattern behavior: caller-owned wildcards match, a ``\\%``-escaped
  literal matches literally, ``ilike`` is case-insensitive.

**Scope honesty (defense in depth, not the detection layer):** this tier
verifies end-to-end behavior *through* MetricFlow, and MetricFlow itself
parenthesizes each ``where_constraints`` entry it receives — so these tests
cannot detect a dropped-parens regression in bloomery's own ``AnyOf``
renderer. The merge-blocking parenthesization guarantee (RFC 0015 D11)
rests on the unit rendering tests in
``tests/unit/test_planner/test_filters.py``:
``test_any_of_renders_as_one_parenthesized_or_constraint``,
``test_single_member_any_of_is_still_parenthesized``,
``test_mixed_dimension_any_of_renders_each_member_typed``, and
``test_policy_with_any_of_keeps_the_group_parenthesized``. The assertions
below are kept as defense in depth over the full stack.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest
import sqlglot
from sqlglot import expressions as exp

from bloomery import AnyOf, MetricRequest, Op, OrderSpec, Predicate, RowPolicy
from support.compiling import compile_fixture
from support.planning import audit_scans, fixture_ir, make_planner

from .test_marts import materialize

pytestmark = pytest.mark.execution

PLANNER = make_planner()


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    connection.execute("SET TimeZone = 'UTC'")
    for schema in ("bronze", "silver", "gold"):
        connection.execute(f"CREATE SCHEMA {schema}")
    yield connection
    connection.close()


def _seed(conn: duckdb.DuckDBPyConnection) -> None:
    """Stores chosen to distinguish case sensitivity and wildcard escaping:
    ``Acme`` vs ``acme``, and ``50%off`` vs ``50xoff`` (the pair an
    unescaped ``%`` would conflate)."""
    conn.execute(
        "CREATE TABLE bronze.pos__orders ("
        "id VARCHAR, store VARCHAR, amount DECIMAL(12, 4), order_date VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.pos__orders VALUES (?, ?, ?, ?)",
        [
            ("o1", "Acme", Decimal("100.00"), "2024-01-15"),
            ("o2", "acme", Decimal("10.00"), "2024-01-16"),
            ("o3", "50%off", Decimal("7.00"), "2024-01-17"),
            ("o4", "50xoff", Decimal("3.00"), "2024-01-18"),
        ],
    )
    materialize(conn, compile_fixture("non_additive_aov"))


def _run(
    conn: duckdb.DuckDBPyConnection,
    request: MetricRequest,
    *,
    policy: RowPolicy | None = None,
) -> list[tuple[object, ...]]:
    plan = PLANNER.plan(fixture_ir("non_additive_aov"), request, dialect="duckdb", policy=policy)
    return conn.execute(plan.sql).fetchall()


def _by_store(*filters: Predicate | AnyOf) -> MetricRequest:
    return MetricRequest(
        metrics=("revenue",),
        dimensions=("store",),
        filters=filters,
        order_by=(OrderSpec("store"),),
    )


# ....................... #
# AnyOf ≡ UNION of the single-predicate queries (RFC 0015 §6)


def test_any_of_equals_the_union_of_single_predicate_queries(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """OR semantics hold through the full stack. Defense in depth: MetricFlow
    parenthesizes each constraint entry itself, so this cannot catch a
    dropped-parens regression in bloomery's renderer — the unit rendering
    tests (see the module docstring) are the detection layer."""
    _seed(conn)
    any_of = AnyOf((Predicate("store", Op.EQ, ("Acme",)), Predicate("store", Op.EQ, ("acme",))))
    combined = _run(conn, _by_store(any_of))
    first = _run(conn, _by_store(Predicate("store", Op.EQ, ("Acme",))))
    second = _run(conn, _by_store(Predicate("store", Op.EQ, ("acme",))))
    assert set(combined) == set(first) | set(second)
    assert len(combined) == 2  # both branches actually contributed


# ....................... #
# Policy + AnyOf: every scan scoped, the group parenthesized — on the AST


def _policy_inside_a_disjunction(sql: str, column: str, value: str) -> bool:
    """True when the policy comparison sits *inside* an OR — the parse shape
    of the unparenthesized ``policy AND a OR b`` bug. Parenthesized
    rendering keeps the policy a sibling of the OR, never a descendant."""
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    for disjunction in tree.find_all(exp.Or):
        for eq in disjunction.find_all(exp.EQ):
            left, right = eq.left, eq.right
            if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
                left, right = right, left
            if (
                isinstance(left, exp.Column)
                and left.name.endswith(column)
                and isinstance(right, exp.Literal)
                and right.this == value
            ):
                return True
    return False


def test_policy_with_any_of_scopes_every_scan_and_stays_outside_the_or(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The policy scopes every scan and is never disjoined with the AnyOf
    branches — asserted end-to-end, through MetricFlow. Defense in depth
    only: MetricFlow parenthesizes each ``where_constraints`` entry it
    receives, so this test would still pass if bloomery's renderer dropped
    its own parens — the merge-blocking guarantee rests on the unit
    rendering tests named in the module docstring, which assert on the
    rendered constraint strings directly."""
    _seed(conn)
    policy = RowPolicy("store", Op.EQ, "Acme")
    any_of = AnyOf(
        (Predicate("amount", Op.GT, (Decimal("5"),)), Predicate("store", Op.EQ, ("acme",)))
    )
    plan = PLANNER.plan(
        fixture_ir("non_additive_aov"),
        MetricRequest(metrics=("revenue",), filters=(any_of,)),
        dialect="duckdb",
        policy=policy,
    )
    # The policy predicate reaches every scan of the mart (RFC 0013 §5.9d).
    verdicts = audit_scans(plan.sql, "gold.mart_orders", "store", "Acme")
    assert verdicts and all(protected for _scan, protected in verdicts)
    # And it is never disjoined with the AnyOf branches (RFC 0015 D11).
    assert not _policy_inside_a_disjunction(plan.sql, "store", "Acme")
    # The numeric leak check: unparenthesized rendering would let the
    # store='acme' branch bypass the policy and return 110.
    rows = conn.execute(plan.sql).fetchall()
    assert [Decimal(str(v)) for (v,) in rows] == [Decimal("100.00")]


# ....................... #
# like / ilike behavior (RFC 0015 D-Q2, decision 13)


def _revenue(conn: duckdb.DuckDBPyConnection, clause: Predicate) -> Decimal:
    rows = _run(conn, MetricRequest(metrics=("revenue",), filters=(clause,)))
    (value,) = rows[0]
    return Decimal("0") if value is None else Decimal(str(value))


def test_like_wildcards_are_caller_owned(conn: duckdb.DuckDBPyConnection) -> None:
    _seed(conn)
    # `A%` matches `Acme` only — like is case-sensitive.
    assert _revenue(conn, Predicate("store", Op.LIKE, ("A%",))) == Decimal("100.00")
    # No auto-%-wrapping survives from the removed `contains`: a bare
    # needle matches nothing.
    assert _revenue(conn, Predicate("store", Op.LIKE, ("cme",))) == Decimal("0")


def test_escaped_percent_matches_literally(conn: duckdb.DuckDBPyConnection) -> None:
    _seed(conn)
    # Escaped: `50\%off` is the literal string — only the `50%off` store.
    assert _revenue(conn, Predicate("store", Op.LIKE, ("50\\%off",))) == Decimal("7.00")
    # Unescaped: `%` is a wildcard — both `50%off` and `50xoff` match.
    assert _revenue(conn, Predicate("store", Op.LIKE, ("50%off",))) == Decimal("10.00")


def test_ilike_is_case_insensitive(conn: duckdb.DuckDBPyConnection) -> None:
    _seed(conn)
    assert _revenue(conn, Predicate("store", Op.ILIKE, ("acme",))) == Decimal("110.00")
    assert _revenue(conn, Predicate("store", Op.LIKE, ("acme",))) == Decimal("10.00")


def test_multi_pattern_like_is_an_or_match(conn: duckdb.DuckDBPyConnection) -> None:
    _seed(conn)
    assert _revenue(conn, Predicate("store", Op.LIKE, ("Acme", "50\\%off"))) == Decimal(
        "107.00"
    )
