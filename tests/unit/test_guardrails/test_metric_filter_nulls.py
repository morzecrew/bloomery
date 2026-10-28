"""A metric filter's ``ne`` or ``not_in`` states what NULL means
(S-0050/D-17, #357).

Under three-valued logic ``status <> 'refunded'`` is NULL, not true, for a
NULL ``status``, so the filter drops the rows it reads as keeping. The
author says which they mean, ``nulls: include`` or ``nulls: exclude``, on any
dimension that can be NULL, and the metric is refused until they do.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.emit.lower import metric_filter_sql
from bloomery.errors import BloomeryError, GuardrailError, MetricFilterInvalid
from bloomery.ir import MetricFilterIR, ProjectIR
from bloomery.typing import StringType
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit

FIXTURE = "period_over_period"
PAID = "- {dimension: status, op: eq, values: [paid]}"


def _compiled(clause: str, *, required: str | None = None) -> ProjectIR:
    """The fixture with ``paid_revenue`` filtered by ``clause`` instead, and
    ``required`` declared required on the entity."""
    _project, catalog = load_fixture(FIXTURE)
    sources = dict(fixture_sources(FIXTURE))
    assert sources["metrics"].count(PAID) == 1
    sources["metrics"] = sources["metrics"].replace(PAID, clause)
    if required is not None:
        field = f"      {required}: {{type: string}}"
        assert sources["entity_model"].count(field) == 1
        sources["entity_model"] = sources["entity_model"].replace(
            field, f"      {required}: {{type: string, required: true}}"
        )
    return build_project_ir(load_project(sources), catalog)


def _refusal(clause: str) -> GuardrailError:
    with pytest.raises(GuardrailError) as excinfo:
        _compiled(clause)
    (leaf,) = excinfo.value.collected
    return leaf


# ....................... #
# The refusal


@pytest.mark.parametrize(
    "clause",
    [
        "- {dimension: status, op: ne, values: [refunded]}",
        "- {dimension: status, op: not_in, values: [refunded, void]}",
    ],
)
def test_a_negation_on_a_dimension_that_can_be_null_is_refused_naming_both_choices(
    clause: str,
) -> None:
    leaf = _refusal(clause)

    assert isinstance(leaf, MetricFilterInvalid)
    assert "'status'" in str(leaf)
    assert "nulls: include" in str(leaf)
    assert "nulls: exclude" in str(leaf)


@pytest.mark.parametrize("nulls", ["include", "exclude"])
def test_either_choice_compiles(nulls: str) -> None:
    ir = _compiled(f"- {{dimension: status, op: ne, values: [refunded], nulls: {nulls}}}")

    (clause,) = next(metric for metric in ir.metrics if metric.name == "paid_revenue").filter
    assert clause.nulls == nulls


def test_a_required_dimension_needs_no_choice() -> None:
    _compiled("- {dimension: status, op: ne, values: [refunded]}", required="status")


def test_a_key_needs_no_choice() -> None:
    """A key need not be declared required, and is never NULL in silver: a
    row with no key is not a row of the entity (S-0033)."""
    _project, catalog = load_fixture(FIXTURE)
    sources = dict(fixture_sources(FIXTURE))
    sources["entity_model"] = sources["entity_model"].replace(
        "sale_id: {type: string, required: true}", "sale_id: {type: string}"
    )
    sources["metrics"] = sources["metrics"].replace(PAID, "- {dimension: sale_id, op: ne, values: [s01]}")

    build_project_ir(load_project(sources), catalog)


#: A self-join: the manager is an employee, flattened under a prefix.
SELF_JOIN = {
    "entity_model": """spec_version: 1
entities:
  employee:
    grain: one row per employee
    key: [employee_id]
    fields:
      employee_id: {type: string, required: true}
      name: {type: string, required: true}
      manager_id: {type: string}
      salary: {type: "decimal(12,4)"}
      hired_on: {type: date}
relationships:
  - name: employee_manager
    from: employee
    to: employee
    via: {manager_id: employee_id}
    cardinality: many_to_one
""",
    "mapping_employees": """mapping_version: 1
source: src__employees
target: employee
key:
  employee_id: {from: "$.id", transform: [to_string]}
fields:
  name: {from: "$.name"}
  manager_id: {from: "$.manager", transform: [to_string]}
  salary: {from: "$.salary"}
  hired_on: {from: "$.hired", transform: [{parse_date: ISO8601}]}
""",
    "metrics": """metrics_version: 1
metrics:
  payroll:
    grain: employee
    additivity: additive
    agg: sum
    expr: "salary"
    filter: [{dimension: manager_name, op: ne, values: [Ann]}]
""",
    "marts": """marts_version: 1
marts:
  employees:
    grain: employee
    base: employee
    flatten:
      - {via: employee_manager, prefix: manager_}
      - {date: hired_on, role: hired}
    measures: [payroll]
""",
}


def test_a_self_join_s_column_is_told_from_the_base_by_its_name() -> None:
    """The manager's `name` is required on `employee`, the mart's base, but an
    employee with no manager has none: the joined column carries the prefix,
    and that, not the entity, is what says it was joined."""
    with pytest.raises(GuardrailError) as excinfo:
        load_and_build(SELF_JOIN)

    (leaf,) = excinfo.value.collected
    assert "'manager_name' can be NULL" in str(leaf)


def test_a_joined_column_can_be_null_whatever_its_own_entity_declares() -> None:
    """`address_id` is the address entity's key, so it is never NULL there,
    but the mart reaches it through a LEFT JOIN and an order with no billing
    address has none."""
    from golden.roles_of_one_dimension import DOCUMENTS

    filtered = "    filter: [{dimension: billing_address_id, op: ne, values: [a1]}]\n"
    with pytest.raises(GuardrailError) as excinfo:
        load_and_build({**DOCUMENTS, "metrics": DOCUMENTS["metrics"] + filtered})

    (leaf,) = excinfo.value.collected
    assert "'billing_address_id' can be NULL" in str(leaf)


def test_a_column_comparison_names_every_side_that_can_be_null() -> None:
    from golden.roles_of_one_dimension import DOCUMENTS

    compared = "    filter: [{dimension: billing_region, op: ne, column: shipping_region}]\n"
    with pytest.raises(GuardrailError) as excinfo:
        load_and_build({**DOCUMENTS, "metrics": DOCUMENTS["metrics"] + compared})

    (leaf,) = excinfo.value.collected
    assert "'billing_region' and 'shipping_region' can be NULL" in str(leaf)


def load_and_build(documents: dict[str, str]) -> ProjectIR:
    return build_project_ir(load_project(documents))


def test_nulls_on_another_operator_is_refused_at_parse() -> None:
    with pytest.raises(BloomeryError, match="only ne and not_in take"):
        _compiled("- {dimension: status, op: eq, values: [paid], nulls: include}")


# ....................... #
# The rendering, one copy for MetricFlow and Cube


def _sql(op: str, values: tuple[str, ...], nulls: str | None, column: str | None = None) -> str:
    clause = MetricFilterIR(dimension="status", op=op, values=values, column=column, nulls=nulls)
    return metric_filter_sql(
        clause, ref="status", declared=StringType(), column_ref=None if column is None else column
    )


def test_include_keeps_the_null_rows_and_exclude_is_sql_s_answer() -> None:
    assert _sql("ne", ("refunded",), "include") == "(status IS NULL OR status <> 'refunded')"
    assert _sql("not_in", ("a", "b"), "include") == "(status IS NULL OR status NOT IN ('a', 'b'))"
    assert _sql("ne", ("refunded",), "exclude") == _sql("ne", ("refunded",), None)
    assert _sql("ne", (), "include", column="channel") == (
        "(status IS NULL OR channel IS NULL OR status <> channel)"
    )


@pytest.mark.parametrize(("nulls", "kept"), [("include", ["paid", None]), ("exclude", ["paid"])])
def test_the_rendered_clause_keeps_what_it_says_on_duckdb(nulls: str, kept: list[str | None]) -> None:
    duckdb = pytest.importorskip("duckdb")

    rows = duckdb.connect().execute(
        "SELECT status FROM (VALUES ('paid'), ('refunded'), (NULL)) AS t(status) "
        f"WHERE {_sql('ne', ('refunded',), nulls)} ORDER BY status NULLS LAST"
    ).fetchall()

    assert [row[0] for row in rows] == kept


def test_the_metricflow_manifest_and_the_explanation_carry_it() -> None:
    from bloomery.emit.metricflow import emit_manifest
    from bloomery.naming import DefaultNaming
    from support.planning import make_planner

    from bloomery import MetricRequest

    ir = _compiled("- {dimension: status, op: ne, values: [refunded], nulls: include}")
    manifest = emit_manifest(ir, naming=DefaultNaming())
    (metric,) = [metric for metric in manifest.metrics if metric.name == "paid_revenue"]
    (where,) = metric.filter.where_filters
    assert "IS NULL OR" in where.where_sql_template

    plan = make_planner().plan(ir, MetricRequest(metrics=("paid_revenue",)), dialect="duckdb")
    assert "IS NULL OR" in plan.sql
    assert "(NULL kept)" in str(plan.explanation)
