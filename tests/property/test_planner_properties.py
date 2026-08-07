"""Planner properties (RFC 0013 §6, RFC 0009 §5.10) — three merge-blocking
invariants:

- **Filter fuzz** (RFC 0013 D8): adversarial ``FilterExpr`` string values —
  quote breakers, ``' OR 1=1 --``, Jinja template syntax, unicode quotes,
  newlines, LIKE wildcards — always render to SQL that parses, scans exactly
  the expected mart, keeps the predicate structure of a benign baseline, and
  carries the adversarial value only as a string literal. NUL is refused.
- **Names round-trip** (RFC 0013 D7): every dimension the emitter produces
  maps through ``group_by_name`` and back to the original bloomery name and
  grain — emitter and bridge cannot drift apart.
- **Planner determinism** (RFC 0003, RFC 0009 §5.10): the same request twice
  yields an identical ``QueryPlan``, fingerprint included.
"""

from __future__ import annotations

import pytest
import sqlglot
from hypothesis import example, given, settings
from hypothesis import strategies as st
from sqlglot import expressions as exp

from bloomery import MetricRequest, OrderSpec, RowPolicy, TimeGrain
from bloomery.emit.metricflow import emit_manifest
from bloomery.errors import InvalidRequest
from bloomery.naming import DefaultNaming
from bloomery.planner import FilterExpr
from bloomery.planner.names import (
    ResolvedDimension,
    bloomery_dimension_name,
    group_by_name,
)
from support.planning import fixture_ir, make_planner

pytestmark = pytest.mark.property

PLANNER = make_planner()

ADVERSARIAL = [
    "' OR 1=1 --",
    "'; DROP TABLE gold.mart_orders; --",
    "{{ Dimension('order__store') }}",
    "{% raw %}x{% endraw %}",
    "{# comment #}",
    "’smart’ “quotes”",
    "line\nbreak",
    "100% _done_ \\ backslash",
    "🜚 unicode",
]

_value_strategy = st.one_of(
    st.sampled_from(ADVERSARIAL),
    st.text(min_size=1, max_size=40),
)


def _plan_sql(value: str, op: str) -> str:
    request = MetricRequest(
        metrics=("revenue",),
        dimensions=("store",),
        filters=(FilterExpr("store", op, (value,)),),  # type: ignore[arg-type]
    )
    return PLANNER.plan(fixture_ir("non_additive_aov"), request, dialect="duckdb").sql


def _normalized(sql: str) -> str:
    """The parsed tree with every string literal replaced by a placeholder —
    two plans differing only in literal content normalize identically."""
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    for literal in tree.find_all(exp.Literal):
        if literal.is_string:
            literal.set("this", "?")
    return tree.sql(dialect="duckdb")


def _scanned_relations(sql: str) -> set[str]:
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    return {
        ".".join(part.name for part in (table.args.get("db"), table.this) if part is not None)
        for table in tree.find_all(exp.Table)
    }


@settings(max_examples=60, deadline=None)
@given(value=_value_strategy, op=st.sampled_from(["eq", "contains"]))
@example(value="' OR 1=1 --", op="eq")
@example(value="{{ Dimension('order__store') }}", op="eq")
@example(value="100% _done_ \\ backslash", op="contains")
def test_adversarial_filter_values_stay_literals(value: str, op: str) -> None:
    if "\x00" in value:
        with pytest.raises(InvalidRequest):
            _plan_sql(value, op)
        return
    sql = _plan_sql(value, op)
    baseline = _plan_sql("baseline", op)
    # Parses under the requested dialect.
    tree = sqlglot.parse_one(sql, dialect="duckdb")
    # Scans exactly the expected mart — nothing else got smuggled in.
    assert _scanned_relations(sql) == {"gold.mart_orders"}
    # Predicate count/structure identical to the benign baseline.
    assert _normalized(sql) == _normalized(baseline)
    # The adversarial value appears only inside string literals. Jinja
    # normalizes newline sequences in the constraint template (\r\n and \r
    # become \n) — a rendering normalization, not an injection; assert on
    # the same normalization.
    if op == "eq":
        literals = {
            literal.this for literal in tree.find_all(exp.Literal) if literal.is_string
        }
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        assert normalized in literals


def test_nul_byte_is_refused() -> None:
    with pytest.raises(InvalidRequest, match="NUL"):
        _plan_sql("acme\x00corp", "eq")


# ....................... #
# Names round-trip (RFC 0013 D7) — over the emitted dimension set


FIXTURES = [
    "ecom_basic",
    "multi_mart_refusal",
    "non_additive_aov",
    "role_playing_dates",
    "semi_additive_inventory",
]


@settings(max_examples=20, deadline=None)
@given(
    name=st.sampled_from(FIXTURES),
    grain=st.sampled_from([g for g in TimeGrain if g is not TimeGrain.HOUR]),
)
def test_every_emitted_dimension_round_trips(name: str, grain: TimeGrain) -> None:
    ir = fixture_ir(name)
    manifest = emit_manifest(ir, naming=DefaultNaming())
    for model in manifest.semantic_models:
        mart = next(m for m in ir.marts if m.name == model.name)
        entity = mart.grain
        mart_dimensions = {d.column for d in mart.dimensions}
        for dimension in model.dimensions:
            if dimension.type.value == "time":
                role = dimension.name.removesuffix("_day")
                bloomery_name = f"{role}_{grain.value}"
                resolved = ResolvedDimension(name=bloomery_name, role=role, grain=grain)
                dunder = group_by_name(resolved, entity=entity)
                assert dunder == f"{entity}__{role}_day__{grain.value}"
                element, _, dunder_grain = dunder.removeprefix(f"{entity}__").rpartition("__")
                assert bloomery_dimension_name(element, TimeGrain(dunder_grain)) == bloomery_name
                assert bloomery_name in mart_dimensions  # every grain is flattened
            else:
                resolved = ResolvedDimension(name=dimension.name)
                dunder = group_by_name(resolved, entity=entity)
                assert dunder == f"{entity}__{dimension.name}"
                assert (
                    bloomery_dimension_name(dunder.removeprefix(f"{entity}__"), None)
                    == dimension.name
                )


# ....................... #
# Planner determinism (RFC 0009 §5.10)


DETERMINISM_REQUESTS = {
    "semi_additive_inventory": MetricRequest(
        metrics=("stock_on_hand",),
        dimensions=("warehouse_id", "snapshot_day"),
        filters=(FilterExpr("snapshot_day", "between", ("2024-01-01", "2024-03-31")),),
        time_grain=TimeGrain.MONTH,
        order_by=(OrderSpec("stock_on_hand", "desc"),),
        limit=10,
    ),
    "non_additive_aov": MetricRequest(
        metrics=("average_order_value", "revenue"),
        dimensions=("store",),
        filters=(FilterExpr("store", "ne", ("Z",)),),
        order_by=(OrderSpec("revenue", "desc"),),
        limit=25,
    ),
}


@pytest.mark.parametrize("fixture", sorted(DETERMINISM_REQUESTS))
def test_same_request_twice_yields_identical_plans(fixture: str) -> None:
    ir = fixture_ir(fixture)
    request = DETERMINISM_REQUESTS[fixture]
    policy = RowPolicy("store" if fixture == "non_additive_aov" else "warehouse_id", "eq", "A")
    first = PLANNER.plan(ir, request, dialect="duckdb", policy=policy)
    second = PLANNER.plan(ir, request, dialect="duckdb", policy=policy)
    assert first == second  # sql, columns, warnings, explanation — everything
    assert first.fingerprint == second.fingerprint
