"""A declared field no mapping produces, read by a step, run as emitted (#404).

The step's ``requires`` is checked against the entity's declared fields, so it
compiled; the silver model left the field out, so the step's model failed on
DuckDB's binder. The field is now a typed NULL column of the silver model.
"""

from __future__ import annotations

import pytest
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_project
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.execution

ENTITY_MODEL = """spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      state: {type: string}
      delivery_cost_kop: {type: int}
"""

MAPPING = (
    "mapping_version: 1\nsource: shop__orders\ntarget: order\n"
    'key:\n  order_id: {from: "$.id"}\n'
    'fields:\n  state: {from: "$.state"}\n'
)

STEPS = (
    "steps_version: 1\nsteps:\n  - use: economics@1\n"
    "    inputs: {orders: silver.order}\n"
    "    outputs: {out: silver.order_economics}\n"
)

MANIFEST: dict[str, object] = {
    "ref": "economics",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "inputs": {"orders": {"grain": "order", "requires": ["order_id", "delivery_cost_kop"]}},
    "outputs": {
        "out": {
            "grain": "one row per order",
            "key": ["order_id"],
            "produces": {"order_id": {"type": "string"}, "cost": {"type": "int"}},
        }
    },
}

BODY = 'SELECT o.order_id, o.delivery_cost_kop AS cost FROM silver."order" AS o'


def test_a_step_reads_the_field_as_null() -> None:
    registry = StepRegistry(
        {("economics", 1): StepManifest.model_validate(MANIFEST)},
        sql_bodies={("economics", 1): BODY},
    )
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING, "steps": STEPS})
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", steps=registry)

    conn = warehouse()
    conn.execute("CREATE TABLE bronze.shop__orders (id VARCHAR, state VARCHAR)")
    conn.execute("INSERT INTO bronze.shop__orders VALUES ('o1', 'paid'), ('o2', 'new')")
    materialize(conn, artifacts)

    assert conn.execute(
        "SELECT order_id, cost FROM silver.order_economics ORDER BY order_id"
    ).fetchall() == [("o1", None), ("o2", None)]
    # Typed, not a bare NULL: the column has the field's declared type.
    assert conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = 'silver' AND table_name = 'order' "
        "AND column_name = 'delivery_cost_kop'"
    ).fetchall() == [("BIGINT",)]
