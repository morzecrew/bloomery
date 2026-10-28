"""Shared planner-path helpers (S-0026/layout-and-markers ``tests/support/``): fixture
IR construction, a process-wide planner over one LRU hydrator (hydration is
~10 ms per fixture — one shared L1 keeps the suites fast), and the
row-policy AST audit the M4.5 verification spike arrived at (S-0030
§5.9d: assert the predicate in EVERY scan, never a substring)."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from decimal import Decimal
from functools import lru_cache

import duckdb
import sqlglot
from sqlglot import expressions as exp

from bloomery import (
    AnyOf,
    MetricFlowPlanner,
    MetricRequest,
    Op,
    OrderSpec,
    Predicate,
    RowPolicy,
    TimeGrain,
    build_project_ir,
    load_catalog,
    load_project,
)
from bloomery.ir import MartIR, ProjectIR
from bloomery.naming import DefaultNaming
from bloomery.runtime import LruManifestHydrator
from support.compiling import FIXTURES, compile_fixture, fixture_sources, load_fixture
from support.execution import materialize, warehouse

__all__ = [
    "BIND_FIXTURE",
    "BIND_REQUESTS",
    "BIND_SALES",
    "audit_scans",
    "bind_warehouse",
    "fixture_ir",
    "fixture_mart",
    "make_planner",
    "normalize_month",
    "quantized",
    "variant_ir",
]


#: The fixture bound plans run against on every engine (S-0097/D-4, D-7): it
#: has a dimension of each type a filter value takes.
BIND_FIXTURE = "period_over_period"

#: ``(id, amount, units, is_test, status, channel, sold_at, booked_at)``, as
#: bronze lands them: the execution tier's `period_over_period` seed.
BIND_SALES = [
    ("s01", "100.00", "1", "false", "paid", "web", "2023-03-15", "2023-03-15T09:00:00"),
    ("s02", "100.00", "1", "false", "paid", "web", "2024-03-01", "2024-03-01T09:00:00"),
    ("s03", "7.00", "1", "false", "paid", "store", "2024-03-04", "2024-03-04T09:00:00"),
    ("s04", "50.00", "2", "false", "refunded", "web", "2024-03-05", "2024-03-05T09:00:00"),
    ("s05", "100.00", "1", "false", "paid", "store", "2024-03-11", "2024-03-11T09:00:00"),
    ("s06", "40.00", "1", "false", "paid", "store", "2023-04-10", "2023-04-10T09:00:00"),
    ("s07", "40.00", "1", "false", "paid", "store", "2024-04-10", "2024-02-28T09:00:00"),
    ("s08", "60.00", "3", "false", "paid", "web", "2024-05-02", "2024-05-02T09:00:00"),
]


def _by_month(*filters: Predicate | AnyOf, metrics: tuple[str, ...] = ("revenue",)) -> MetricRequest:
    return MetricRequest(
        metrics=metrics,
        dimensions=("sold_month",),
        time_grain=TimeGrain.MONTH,
        filters=filters,
        order_by=(OrderSpec("sold_month"),),
    )


#: Each request bound and inline must answer alike: one filter per type, the
#: membership and pattern operators, a disjunction, a policy, and a metric
#: whose own filter stays text beside a bound one.
BIND_REQUESTS: dict[str, tuple[MetricRequest, RowPolicy | None]] = {
    "date": (_by_month(Predicate("sold_at", Op.GTE, (datetime.date(2024, 3, 4),))), None),
    "timestamp": (
        _by_month(Predicate("booked_at", Op.LT, (datetime.datetime(2024, 3, 5, 9, 0),))),
        None,
    ),
    # The same instant as `timestamp`, zoned: s04, booked at 09:00 UTC, is out.
    "zoned timestamp": (
        _by_month(Predicate("booked_at", Op.LT, ("2024-03-05T11:00:00+02:00",))),
        None,
    ),
    "decimal": (_by_month(Predicate("amount", Op.GT, (Decimal("40.00"),))), None),
    "int in": (_by_month(Predicate("units", Op.IN, (2, 3))), None),
    "bool": (_by_month(Predicate("is_test", Op.EQ, (False,))), None),
    "like": (_by_month(Predicate("channel", Op.LIKE, ("w%",))), None),
    "any of": (
        _by_month(
            AnyOf((Predicate("status", Op.EQ, ("refunded",)), Predicate("amount", Op.GTE, ("100",))))
        ),
        None,
    ),
    "policy": (
        _by_month(Predicate("sold_at", Op.LT, (datetime.date(2024, 5, 1),))),
        RowPolicy("channel", Op.EQ, "store"),
    ),
    "metric filter": (
        _by_month(Predicate("channel", Op.EQ, ("web",)), metrics=("revenue", "paid_revenue")),
        None,
    ),
}


def bind_warehouse() -> duckdb.DuckDBPyConnection:
    """A DuckDB warehouse holding :data:`BIND_FIXTURE`'s marts over
    :data:`BIND_SALES`: the rows every engine's bound plan is held to."""
    connection = warehouse()
    connection.execute(
        "CREATE TABLE bronze.shop__sales (id VARCHAR, amount VARCHAR, units VARCHAR, "
        "is_test VARCHAR, status VARCHAR, channel VARCHAR, sold_at VARCHAR, booked_at VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.shop__sales VALUES (?, ?, ?, ?, ?, ?, ?, ?)", BIND_SALES
    )
    materialize(connection, compile_fixture(BIND_FIXTURE, dialect="duckdb"))
    return connection


@lru_cache(maxsize=None)
def fixture_ir(name: str) -> ProjectIR:
    project, catalog = load_fixture(name)
    return build_project_ir(project, catalog)


def fixture_mart(fixture: str, name: str) -> MartIR:
    """One mart of a fixture, **by name**.

    Never by index: every quality-carrying fixture also carries the
    bloomery-owned ``data_quality`` mart (S-0033/the-quality-mart), which sorts first
    among ``ProjectIR.marts`` — so ``marts[0]`` silently means something else
    there than it did before M12.
    """
    return next(mart for mart in fixture_ir(fixture).marts if mart.name == name)


def variant_ir(name: str, **edits: tuple[str, ...]) -> ProjectIR:
    """One fixture's sources with substitutions applied, built into IR.

    A variant rather than a fixture directory: what a test needs is often a
    *shape* the corpus does not otherwise contain, and adding a fixture for
    each would move parity rows for a reason unrelated to what is asserted
    (logs/T-0026.md, D-167). Each keyword names a document and gives the
    ``(old, new)`` pair to substitute, or several such pairs; the anchor must
    be present.

    Several pairs per document because one edit can make a *second* one
    necessary: turning a counting measure into one over a nullable column
    leaves the ratio above it needing a row-set declaration (R019), and that
    declaration belongs in the variant rather than in the shared fixture,
    which does not need it.
    """
    sources = dict(fixture_sources(name))
    for document, edit in edits.items():
        pairs = (edit,) if isinstance(edit[0], str) else edit
        for old, new in pairs:
            assert old in sources[document], f"{document}: anchor not found"
            sources[document] = sources[document].replace(old, new)
    catalog_path = FIXTURES / name / "catalog.yaml"

    return build_project_ir(
        load_project(sources), load_catalog(catalog_path.read_text(encoding="utf-8"))
    )


def make_planner(**kwargs: object) -> MetricFlowPlanner:
    """A planner over a fresh default-naming LRU hydrator."""
    return MetricFlowPlanner(LruManifestHydrator(DefaultNaming()), **kwargs)  # type: ignore[arg-type]


def normalize_month(value: object) -> datetime.date:
    """DuckDB returns month-grain keys as TIMESTAMPs (``DATE_TRUNC('month',
    DATE)`` → TIMESTAMP) — normalize to a date before comparing (S-0026
    §5.10)."""
    if isinstance(value, datetime.datetime):
        return value.date()
    assert isinstance(value, datetime.date)
    return value


def quantized(value: object) -> Decimal:
    """A numeric result as a 2-dp Decimal — engines may hand ratios back as
    floats; assertions stay Decimal (S-0020/D-5)."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ....................... #
# Row-policy AST audit (M4.5 spike V4's logic, verbatim). The spike and its
# write-up are retired — `git log --diff-filter=D -- spikes/` finds the commit,
# `git show <commit>^:spikes/metricflow/VERIFICATION.md` prints the finding.


def _where_has_policy(
    select: exp.Select, column: str, value: str, params: Mapping[str, object]
) -> bool:
    """True when this SELECT's WHERE compares a ``*column`` to ``value``,
    inline or as a named placeholder ``params`` binds to it (S-0097/D-3)."""
    where = select.args.get("where")
    if where is None:
        return False
    for eq in where.find_all(exp.EQ):
        left, right = eq.left, eq.right
        if isinstance(right, exp.Column) and isinstance(left, (exp.Literal, exp.Placeholder)):
            left, right = right, left
        if not (isinstance(left, exp.Column) and left.name.endswith(column)):
            continue
        if isinstance(right, exp.Literal) and right.this == value:
            return True
        if isinstance(right, exp.Placeholder) and str(params.get(right.name)) == value:
            return True
    return False


def _select_aggregates(select: exp.Select) -> bool:
    if select.args.get("group"):
        return True
    return any(
        isinstance(node, exp.AggFunc)
        for projection in select.expressions
        for node in projection.walk()
    )


def audit_scans(
    sql: str,
    mart_relation: str,
    column: str,
    value: str,
    params: Mapping[str, object] | None = None,
) -> list[tuple[str, bool]]:
    """For every scan of ``mart_relation`` in the parsed AST: is the policy
    predicate applied at or below the first aggregation over that scan?
    Under the ``named`` paramstyle, ``params`` is ``dict(plan.params)`` and
    the predicate's placeholder must be bound to the policy value.
    A predicate applied only above an aggregation means the aggregate (the
    MAX-date subquery of a semi-additive plan, say) was computed over
    unscoped rows — the security defect V4 ruled out (S-0030/row-policy, S-0030/what-is-superseded-and-the-boundary-that-makes-it-reversible (§5.9d))."""
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    verdicts: list[tuple[str, bool]] = []
    for table in tree.find_all(exp.Table):
        qualified = ".".join(
            part.name for part in (table.args.get("db"), table.this) if part is not None
        )
        if qualified != mart_relation:
            continue
        protected = False
        node: exp.Expression = table
        while True:
            select = node.find_ancestor(exp.Select)
            if select is None:
                break
            if _where_has_policy(select, column, value, params or {}):
                protected = True
                break
            if _select_aggregates(select):
                break  # aggregation over rows the policy never filtered
            node = select
        alias = table.args.get("alias")
        verdicts.append((f"{qualified} AS {alias.name if alias else '?'}", protected))
    return verdicts
