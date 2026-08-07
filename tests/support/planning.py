"""Shared planner-path helpers (RFC 0009 §5.1 ``tests/support/``): fixture
IR construction, a process-wide planner over one LRU hydrator (hydration is
~10 ms per fixture — one shared L1 keeps the suites fast), and the
row-policy AST audit adapted from ``spikes/metricflow/v4_row_policy.py``
(RFC 0013 §5.9d: assert the predicate in EVERY scan, never a substring)."""

from __future__ import annotations

import datetime
from decimal import Decimal
from functools import lru_cache

import sqlglot
from sqlglot import expressions as exp

from bloomery import MetricFlowPlanner, build_project_ir
from bloomery.ir import ProjectIR
from bloomery.naming import DefaultNaming
from bloomery.runtime import LruManifestHydrator
from support.compiling import load_fixture

__all__ = [
    "audit_scans",
    "fixture_ir",
    "make_planner",
    "normalize_month",
    "quantized",
]


@lru_cache(maxsize=None)
def fixture_ir(name: str) -> ProjectIR:
    project, catalog = load_fixture(name)
    return build_project_ir(project, catalog)


def make_planner(**kwargs: object) -> MetricFlowPlanner:
    """A planner over a fresh default-naming LRU hydrator."""
    return MetricFlowPlanner(LruManifestHydrator(DefaultNaming()), **kwargs)  # type: ignore[arg-type]


def normalize_month(value: object) -> datetime.date:
    """DuckDB returns month-grain keys as TIMESTAMPs (``DATE_TRUNC('month',
    DATE)`` → TIMESTAMP) — normalize to a date before comparing (RFC 0009
    §5.10)."""
    if isinstance(value, datetime.datetime):
        return value.date()
    assert isinstance(value, datetime.date)
    return value


def quantized(value: object) -> Decimal:
    """A numeric result as a 2-dp Decimal — engines may hand ratios back as
    floats; assertions stay Decimal (RFC 0003 D5)."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ....................... #
# Row-policy AST audit (spikes/metricflow/v4_row_policy.py, verbatim logic)


def _where_has_policy(select: exp.Select, column: str, value: str) -> bool:
    """True when this SELECT's WHERE compares a ``*column`` to ``value``."""
    where = select.args.get("where")
    if where is None:
        return False
    for eq in where.find_all(exp.EQ):
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


def _select_aggregates(select: exp.Select) -> bool:
    if select.args.get("group"):
        return True
    return any(
        isinstance(node, exp.AggFunc)
        for projection in select.expressions
        for node in projection.walk()
    )


def audit_scans(sql: str, mart_relation: str, column: str, value: str) -> list[tuple[str, bool]]:
    """For every scan of ``mart_relation`` in the parsed AST: is the policy
    predicate applied at or below the first aggregation over that scan?
    A predicate applied only above an aggregation means the aggregate (the
    MAX-date subquery of a semi-additive plan, say) was computed over
    unscoped rows — the security defect V4 ruled out (RFC 0013 §5.7/§5.9d)."""
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
            if _where_has_policy(select, column, value):
                protected = True
                break
            if _select_aggregates(select):
                break  # aggregation over rows the policy never filtered
            node = select
        alias = table.args.get("alias")
        verdicts.append((f"{qualified} AS {alias.name if alias else '?'}", protected))
    return verdicts
