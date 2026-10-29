"""A metric reads a per-unit field of a many-to-one parent (#366, S-0023/D-15,
S-0022/D-12).

Cost of goods at order-line grain is the line's quantity times its product's
unit cost. The cost lives on `product`, and the grain guard refused it, as it
refuses order shipping read per line (the `fanout_trap`): a many-to-one join
copies the parent's value onto every child row, and a SUM of an *amount* copied
that way overstates it. A unit cost is not an amount of its product but a rate
that holds for each unit sold, so the catalog says so (`per_unit: true`), and
the metric's canonical reads the column each mart flattens it into.
"""

from __future__ import annotations

import json

import pytest
import yaml
from support.planning import make_planner

from bloomery import (
    MetricRequest,
    Project,
    Target,
    build_project_ir,
    compile_project,
    load_catalog,
    load_project,
)
from bloomery.errors import GrainMismatch, GuardrailError, InvalidMetricShape
from bloomery.guardrails.grain import check_grain
from bloomery.guardrails.operands import Derivation
from bloomery.spec import Catalog

pytestmark = pytest.mark.unit

ENTITY_MODEL = """spec_version: 1
entities:
  order_line:
    grain: one row per order line
    key: [line_id]
    fields:
      line_id: {type: string, required: true}
      product_id: {type: string}
      quantity: {type: int, canonical: line_quantity}
      ordered_at: {type: timestamp}
  product:
    grain: one row per product
    key: [product_id]
    fields:
      product_id: {type: string, required: true}
      buy_price_kop: {type: int, canonical: product_cost}
      shipping_kop: {type: int, canonical: product_shipping}
relationships:
  - name: line_of_product
    from: order_line
    to: product
    via: {product_id: product_id}
    cardinality: many_to_one
"""

LINES = (
    "mapping_version: 1\nsource: shop__lines\ntarget: order_line\n"
    'key:\n  line_id: {from: "$.id"}\n'
    'fields:\n  product_id: {from: "$.product"}\n'
    '  quantity: {from: "$.qty", transform: [to_int]}\n'
    '  ordered_at: {from: "$.at", transform: [{parse_ts: ISO8601}], zone_in: UTC}\n'
)

PRODUCTS = (
    "mapping_version: 1\nsource: shop__products\ntarget: product\n"
    'key:\n  product_id: {from: "$.id"}\n'
    'fields:\n  buy_price_kop: {from: "$.cost", transform: [to_int]}\n'
    '  shipping_kop: {from: "$.ship", transform: [to_int]}\n'
)

CATALOG = """catalog_version: 1
vertical: v
canonical_fields:
  line_quantity:
    entity: order_line
    type: int
    unit: count{line_per_unit}
    recipes: [{{id: direct, requires: [line_quantity]}}]
  product_cost:
    entity: product
    type: int
    unit: currency
    tax_basis: net{per_unit}
    recipes: [{{id: direct, requires: [product_cost]}}]
  product_shipping:
    entity: product
    type: int
    unit: currency
    tax_basis: net
    recipes: [{{id: direct, requires: [product_shipping]}}]
date_dimension: {{name: dim_date, grain: day, start_year: 2020, end_year: 2030}}
metric_templates:
  cost_of_goods:
    requires: [line_quantity, product_cost]
    grain: order_line
    additivity: additive
    agg: sum
    expr: product_cost * line_quantity
  shipping_per_line:
    requires: [line_quantity, product_shipping]
    grain: order_line
    additivity: additive
    agg: sum
    expr: product_shipping * line_quantity
"""

METRICS = "metrics_version: 1\nmetrics:\n{metrics}"


def _mart(name: str, prefix: str, measures: str) -> str:
    return (
        f"  {name}:\n    grain: order_line\n    base: order_line\n"
        f"    flatten:\n      - {{via: line_of_product, prefix: {prefix}}}\n"
        f"      - {{date: ordered_at, role: ordered}}\n    measures: [{measures}]\n"
    )


def _project(
    metrics: str = "  cost_of_goods: {template: cost_of_goods}\n",
    marts: str = "",
) -> Project:
    return load_project(
        {
            "entity_model": ENTITY_MODEL,
            "mapping_lines": LINES,
            "mapping_products": PRODUCTS,
            "metrics": METRICS.format(metrics=metrics),
            "marts": "marts_version: 1\nmarts:\n"
            + (marts or _mart("order_lines", "product_", "cost_of_goods")),
        }
    )


def _catalog(*, per_unit: bool = True, line_per_unit: bool = False) -> Catalog:
    flag = "\n    per_unit: true"
    return load_catalog(
        CATALOG.format(
            per_unit=flag if per_unit else "", line_per_unit=flag if line_per_unit else ""
        )
    )


def _artifacts(target: Target, **kwargs: str) -> dict[str, str]:
    return {
        artifact.path: artifact.content
        for artifact in compile_project(
            _project(**kwargs), target=target, dialect="duckdb", catalog=_catalog()
        )
    }


# ....................... #
# The grain guard


def test_undeclared_the_parent_s_field_is_still_a_fan_out() -> None:
    """Nothing about the guard changes for a field the catalog does not
    declare per unit: an amount of the parent, copied onto each line."""
    with pytest.raises(GuardrailError) as refused:
        build_project_ir(_project(), _catalog(per_unit=False))

    assert any(isinstance(leaf, GrainMismatch) for leaf in refused.value.collected)


def test_a_per_unit_field_of_a_many_to_one_parent_compiles() -> None:
    ir = build_project_ir(_project(), _catalog())

    (metric,) = (metric for metric in ir.metrics if metric.name == "cost_of_goods")
    assert metric.expr is not None
    assert metric.expr.sql == "product_cost * quantity"  # the IR keeps the canonical


def test_shipping_on_the_same_parent_is_still_refused() -> None:
    """The fanout trap, beside the declared field and in the same shape: an
    amount of the product copied onto each line. Only the declaration tells
    the two apart, which is why it is one."""
    metrics = (
        "  cost_of_goods: {template: cost_of_goods}\n"
        "  shipping_per_line: {template: shipping_per_line}\n"
    )
    marts = _mart("order_lines", "product_", "cost_of_goods, shipping_per_line")
    with pytest.raises(GuardrailError) as refused:
        build_project_ir(_project(metrics, marts), _catalog())

    (leaf,) = (leaf for leaf in refused.value.collected if isinstance(leaf, GrainMismatch))
    assert "'product_shipping'" in str(leaf)
    assert "per_unit" in str(leaf)


def test_the_parent_reading_a_child_s_per_unit_field_is_still_refused() -> None:
    """Only the many-to-one direction copies one value per row. From the parent
    a child's field has many values per row, declared per unit or not, and the
    expression must aggregate it."""
    metrics = (
        "  cost_per_product:\n    requires: [line_quantity, product_cost]\n"
        "    grain: product\n    additivity: additive\n    agg: sum\n"
        "    expr: product_cost * line_quantity\n"
    )
    marts = (
        "  products:\n    grain: product\n    base: product\n    measures: []\n"
    )
    with pytest.raises(GuardrailError) as refused:
        build_project_ir(_project(metrics, marts), _catalog(line_per_unit=True))

    (leaf,) = (leaf for leaf in refused.value.collected if isinstance(leaf, GrainMismatch))
    assert "'line_quantity'" in str(leaf)
    assert "per_unit" not in str(leaf)  # the declaration would not help here


# ....................... #
# The mart reads the column it flattened


def test_metricflow_measures_the_flattened_column() -> None:
    manifest = json.loads(_artifacts(Target.METRICFLOW)["semantic_manifest.json"])
    (model,) = manifest["semantic_models"]
    (measure,) = model["measures"]

    assert measure["expr"] == "product_buy_price_kop * quantity"


def test_each_cube_reads_its_own_prefix() -> None:
    """Two marts flatten the product under different prefixes, each owning one
    instance of the template: one expression shape, one column per mart."""
    metrics = (
        "  cost_of_goods: {template: cost_of_goods}\n"
        "  item_cost: {template: cost_of_goods}\n"
    )
    marts = _mart("order_lines", "product_", "cost_of_goods") + _mart(
        "lines_by_item", "item_", "item_cost"
    )
    artifacts = _artifacts(Target.CUBE, metrics=metrics, marts=marts)
    sql = {}
    for path, name in (
        ("model/cubes/order_lines.yml", "cost_of_goods"),
        ("model/cubes/lines_by_item.yml", "item_cost"),
    ):
        (cube,) = yaml.safe_load(artifacts[path])["cubes"]
        (measure,) = (m for m in cube["measures"] if m["name"] == name)
        sql[name] = measure["sql"]

    assert sql == {
        "cost_of_goods": "product_buy_price_kop * quantity",
        "item_cost": "item_buy_price_kop * quantity",
    }


def test_a_rollup_aggregates_the_parent_mart_s_column() -> None:
    marts = _mart("order_lines", "product_", "cost_of_goods")
    rollups = (
        "rollups:\n  cost_by_product:\n    of: order_lines\n"
        "    keep: [product_product_id]\n    measures: [cost_of_goods]\n"
    )
    artifacts = _artifacts(Target.SQLMESH, marts=marts + rollups)
    (model,) = (text for path, text in artifacts.items() if "cost_by_product" in path)

    assert "SUM(product_buy_price_kop * quantity)" in model
    assert "product_cost" not in model


def test_a_mart_that_does_not_flatten_the_parent_is_refused() -> None:
    marts = (
        "  bare_lines:\n    grain: order_line\n    base: order_line\n"
        "    flatten:\n      - {date: ordered_at, role: ordered}\n    measures: [cost_of_goods]\n"
    )
    with pytest.raises(GuardrailError) as refused:
        build_project_ir(_project(marts=marts), _catalog())

    (leaf,) = (leaf for leaf in refused.value.collected if isinstance(leaf, InvalidMetricShape))
    assert "'product_cost'" in str(leaf)
    assert "bare_lines" in str(leaf)


def test_the_planner_explains_and_queries_the_flattened_column() -> None:
    """The plan's SQL is MetricFlow's, over the manifest's measure, and its
    explanation names the column it summed rather than the canonical."""
    ir = build_project_ir(_project(), _catalog())
    plan = make_planner().plan(ir, MetricRequest(metrics=("cost_of_goods",)), dialect="duckdb")

    (measure,) = plan.explanation.measures
    assert measure.expr == "SUM(product_buy_price_kop * quantity)"
    assert "product_buy_price_kop" in plan.sql


# ....................... #
# A derivation reads the same rule


def _derive(entity: str, expr: str, *, per_unit: bool) -> list[Exception]:
    project = _project()
    draft = build_project_ir(project, _catalog())
    derivation = Derivation(
        source_path=f"mapping[s->{entity}]: fields.f",
        source="s",
        cleaned=False,
        entity=entity,
        field="f",
        expr=expr,
        operands=("line_quantity", "product_cost"),
        direct=None,
    )
    violations = check_grain((derivation,), draft, project, _catalog(per_unit=per_unit))
    # The draft's own metric is checked too; only the derivation's leaves count here.
    return [one for one in violations if one.source_path == derivation.source_path]


def test_a_derivation_reads_a_per_unit_parent_field() -> None:
    assert _derive("order_line", "product_cost * line_quantity", per_unit=True) == []


def test_a_derivation_reading_an_undeclared_parent_field_is_refused() -> None:
    (violation,) = _derive("order_line", "product_cost * line_quantity", per_unit=False)

    assert isinstance(violation, GrainMismatch)
    assert "declare per_unit: true" in str(violation)


def test_a_derivation_on_the_parent_still_aggregates_the_child() -> None:
    (violation,) = _derive("product", "product_cost * line_quantity", per_unit=True)

    assert isinstance(violation, GrainMismatch)
    assert "'line_quantity'" in str(violation)
    assert "per_unit" not in str(violation)
