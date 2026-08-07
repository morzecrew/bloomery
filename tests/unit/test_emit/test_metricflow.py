"""The MetricFlow manifest emitter (RFC 0013 §5.2, R1): acceptance per mart
fixture (``SemanticManifestLookup`` accepts, ``explain`` renders — render-only,
never executed), the IR→MetricFlow mapping-table cases, and the emitter's
pinned deterministic choices (owning-mart measure selection, composite-key
handling, FK entities, day-only time dimensions, description carriage, the
reserved-name defense)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow_semantic_interfaces.type_enums.aggregation_type import AggregationType
from metricflow_semantic_interfaces.type_enums.dimension_type import DimensionType
from metricflow_semantic_interfaces.type_enums.entity_type import EntityType
from metricflow_semantic_interfaces.type_enums.metric_type import MetricType
from metricflow_semantic_interfaces.type_enums.time_granularity import TimeGranularity
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.emit import Feature
from bloomery.emit.metricflow import (
    METRICFLOW_PLANNER_CAPABILITIES,
    emit_manifest,
    manifest_json,
)
from bloomery.errors import EmitError, UnsupportedByTarget
from bloomery.ir import DimensionRef, MartColumnIR, ProjectIR, SemiAdditiveRule
from bloomery.naming import DefaultNaming, PrefixNaming
from bloomery.runtime import sql_client_for_dialect
from support.compiling import fixture_sources, load_fixture
from support.mart_permutations import MART_BLOCKS, sources_with_marts

if TYPE_CHECKING:
    from metricflow_semantic_interfaces.implementations.semantic_manifest import (
        PydanticSemanticManifest,
    )
    from metricflow_semantic_interfaces.implementations.semantic_model import (
        PydanticSemanticModel,
    )

pytestmark = pytest.mark.unit


def _fixture_ir(name: str) -> ProjectIR:
    project, catalog = load_fixture(name)
    return build_project_ir(project, catalog)


def _manifest(name: str) -> PydanticSemanticManifest:
    return emit_manifest(_fixture_ir(name), naming=DefaultNaming())


def _model(manifest: PydanticSemanticManifest, name: str) -> PydanticSemanticModel:
    return next(model for model in manifest.semantic_models if model.name == name)


# ....................... #
# Acceptance (pivot M6 gate): every mart fixture's manifest is accepted by
# SemanticManifestLookup and a simple metric query renders SQL, render-only.

_SMOKE_QUERIES = {
    "ecom_basic": ("gross_revenue", ["order_item__ordered_day__month"]),
    "role_playing_dates": ("revenue", ["order__shipped_day__month"]),
    "semi_additive_inventory": ("stock_on_hand", ["inventory_level__warehouse_id"]),
}


@pytest.mark.parametrize("fixture_name", sorted(_SMOKE_QUERIES))
def test_manifest_is_accepted_and_a_simple_query_explains(fixture_name: str) -> None:
    manifest = _manifest(fixture_name)
    engine = MetricFlowEngine(
        semantic_manifest_lookup=SemanticManifestLookup(manifest),
        sql_client=sql_client_for_dialect("duckdb"),
    )
    metric, group_by = _SMOKE_QUERIES[fixture_name]
    result = engine.explain(
        MetricFlowQueryRequest.create(metric_names=[metric], group_by_names=group_by)
    )
    assert "SELECT" in result.sql_statement.sql


def test_coarser_grains_derive_from_the_day_dimension() -> None:
    """Week/month/quarter/year bucket columns are not emitted as their own
    time dimensions; MetricFlow derives coarser grains from the day grain."""
    manifest = _manifest("role_playing_dates")
    model = _model(manifest, "orders")
    names = {dimension.name for dimension in model.dimensions}
    assert "ordered_day" in names
    assert "shipped_day" in names
    assert not names & {"ordered_week", "ordered_month", "ordered_quarter", "ordered_year"}
    engine = MetricFlowEngine(
        semantic_manifest_lookup=SemanticManifestLookup(manifest),
        sql_client=sql_client_for_dialect("duckdb"),
    )
    result = engine.explain(
        MetricFlowQueryRequest.create(
            metric_names=["revenue"], group_by_names=["order__ordered_day__week"]
        )
    )
    assert "SELECT" in result.sql_statement.sql


# ....................... #
# Semantic-model shape

def test_one_mart_is_exactly_one_semantic_model() -> None:
    ir = _fixture_ir("ecom_basic")
    manifest = _manifest("ecom_basic")
    assert [model.name for model in manifest.semantic_models] == [mart.name for mart in ir.marts]


def test_node_relation_agrees_with_the_sqlmesh_mart_naming() -> None:
    manifest = emit_manifest(_fixture_ir("role_playing_dates"), naming=PrefixNaming("acme"))
    model = _model(manifest, "orders")
    # NamingPolicy.relation("orders", GOLD) == ("acme_gold", "mart_orders")
    assert model.node_relation.schema_name == "acme_gold"
    assert model.node_relation.alias == "mart_orders"


def test_single_column_key_emits_a_primary_entity() -> None:
    model = _model(_manifest("role_playing_dates"), "orders")
    assert model.primary_entity is None
    (entity,) = model.entities
    assert entity.name == "order"
    assert entity.type is EntityType.PRIMARY
    assert entity.expr == "order_id"


def test_composite_key_sets_primary_entity_on_the_model() -> None:
    """order_item's key is (order_id, line_no): no single natural key column,
    so the primary entity is declared name-only on the model."""
    model = _model(_manifest("ecom_basic"), "order_items")
    assert model.primary_entity == "order_item"
    assert all(entity.type is not EntityType.PRIMARY for entity in model.entities)


def test_join_keys_become_foreign_entities_not_dimensions() -> None:
    model = _model(_manifest("ecom_basic"), "order_items")
    (foreign,) = [e for e in model.entities if e.type is EntityType.FOREIGN]
    assert foreign.name == "order"
    assert foreign.expr == "order_id"
    assert "order_id" not in {dimension.name for dimension in model.dimensions}


def test_foreign_entity_names_dedupe_and_composite_joins_emit_no_entity() -> None:
    ir = _fixture_ir("ecom_basic")
    mart = next(m for m in ir.marts)
    join = mart.joins[0]
    duplicate = replace(join, prefix="billing_")
    triplicate = replace(duplicate)  # same entity, same prefix -> skipped
    composite = replace(join, prefix="x_", on=(("line_no", "line_no"), ("order_id", "order_id")))
    patched = replace(mart, joins=(join, duplicate, triplicate, composite))
    manifest = emit_manifest(replace(ir, marts=(patched,)), naming=DefaultNaming())
    model = _model(manifest, "order_items")
    foreign = [e.name for e in model.entities if e.type is EntityType.FOREIGN]
    assert foreign == ["billing_order", "order"]


def test_dimensions_are_day_time_plus_categoricals() -> None:
    model = _model(_manifest("ecom_basic"), "order_items")
    by_name = {dimension.name: dimension for dimension in model.dimensions}
    assert by_name["ordered_day"].type is DimensionType.TIME
    assert by_name["ordered_day"].type_params.time_granularity is TimeGranularity.DAY
    categoricals = {n for n, d in by_name.items() if d.type is DimensionType.CATEGORICAL}
    assert categoricals == {
        "line_no",
        "order_customer_id",
        "order_date",
        "order_order_id",
        "quantity",
        "unit_price",
    }


# ....................... #
# Measures and metrics

def test_additive_measure_mapping() -> None:
    model = _model(_manifest("ecom_basic"), "order_items")
    (measure,) = model.measures
    assert measure.name == "gross_revenue"
    assert measure.agg is AggregationType.SUM
    assert measure.expr == "unit_price * quantity"
    assert measure.agg_time_dimension == "ordered_day"
    metric = next(m for m in _manifest("ecom_basic").metrics if m.name == "gross_revenue")
    assert metric.type is MetricType.SIMPLE


def test_unservable_ratio_is_absent_from_the_manifest() -> None:
    """average_order_value's denominator (order_count, grain order) is on no
    mart — the ratio is simply absent; the planner refuses it by name (M7)."""
    manifest = _manifest("ecom_basic")
    assert [metric.name for metric in manifest.metrics] == ["gross_revenue"]


_RATIO_SOURCES_METRICS = """\
metrics_version: 1
metrics:
  revenue:
    grain: order
    additivity: additive
    agg: sum
    expr: "amount"
    description: Total order amount, net.
  order_count:
    grain: order
    additivity: additive
    agg: count
    expr: "order_id"
  aov:
    grain: order
    requires_metrics: [revenue, order_count]
    additivity: non_additive
    ratio: {numerator: revenue, denominator: order_count}
    description: Average order value.
"""

_RATIO_SOURCES_MARTS = """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {date: order_date, role: ordered}
    measures: [aov, order_count, revenue]
"""


def _ratio_manifest() -> PydanticSemanticManifest:
    _project, catalog = load_fixture("role_playing_dates")
    docs = fixture_sources("role_playing_dates")
    docs["metrics"] = _RATIO_SOURCES_METRICS
    docs["marts"] = _RATIO_SOURCES_MARTS
    ir = build_project_ir(load_project(docs), catalog)
    return emit_manifest(ir, naming=DefaultNaming())


def test_ratio_is_a_metric_never_a_measure() -> None:
    manifest = _ratio_manifest()
    model = _model(manifest, "orders")
    assert [measure.name for measure in model.measures] == ["order_count", "revenue"]
    ratio = next(metric for metric in manifest.metrics if metric.name == "aov")
    assert ratio.type is MetricType.RATIO
    assert ratio.type_params.numerator.name == "revenue"
    assert ratio.type_params.denominator.name == "order_count"


def test_descriptions_are_carried_onto_metrics() -> None:
    manifest = _ratio_manifest()
    by_name = {metric.name: metric for metric in manifest.metrics}
    assert by_name["revenue"].description == "Total order amount, net."
    assert by_name["aov"].description == "Average order value."
    assert by_name["order_count"].description is None


_DESCRIBED_CATALOG = """\
catalog_version: 1
vertical: ecom_retail
canonical_fields:
  stock_level:
    entity: inventory_level
    type: int
    unit: count
    description: On-hand units at snapshot time.
    recipes:
      - {id: direct, requires: [stock_level]}
date_dimension: {name: dim_date, grain: day, start_year: 2020, end_year: 2030}
"""


def test_canonical_field_descriptions_are_carried_onto_dimensions() -> None:
    project, _catalog = load_fixture("semi_additive_inventory")
    ir = build_project_ir(project, load_catalog(_DESCRIBED_CATALOG))
    manifest = emit_manifest(ir, naming=DefaultNaming())
    model = _model(manifest, "inventory")
    dimension = next(d for d in model.dimensions if d.name == "stock_level")
    assert dimension.description == "On-hand units at snapshot time."


def test_a_shared_measure_lands_on_one_mart_only() -> None:
    """Both marts serve `revenue`; the measure lands on the mart the planner
    would select — cheapest cost_hint, ties lexicographic (RFC 0010 D8)."""
    _project, catalog = load_fixture("role_playing_dates")
    ir = build_project_ir(load_project(sources_with_marts(["by_shipped", "by_ordered"])), catalog)
    manifest = emit_manifest(ir, naming=DefaultNaming())
    assert [m.name for m in _model(manifest, "by_ordered").measures] == ["revenue"]
    assert [m.name for m in _model(manifest, "by_shipped").measures] == []


def test_a_cheaper_cost_hint_beats_the_lexicographic_tiebreak() -> None:
    blocks = dict(MART_BLOCKS)
    blocks["by_ordered"] = blocks["by_ordered"].replace(
        "measures: [revenue]", "measures: [revenue]\n    cost_hint: 5"
    )
    sources = sources_with_marts(sorted(blocks))
    sources["marts"] = "marts_version: 1\nmarts:\n" + "".join(blocks[n] for n in sorted(blocks))
    _project, catalog = load_fixture("role_playing_dates")
    ir = build_project_ir(load_project(sources), catalog)
    manifest = emit_manifest(ir, naming=DefaultNaming())
    assert [m.name for m in _model(manifest, "by_ordered").measures] == []
    assert [m.name for m in _model(manifest, "by_shipped").measures] == ["revenue"]


# ....................... #
# Semi-additive mapping (RFC 0013 D4)

def _with_rule(ir: ProjectIR, rule: SemiAdditiveRule) -> ProjectIR:
    metrics = tuple(
        replace(m, semi_additive=replace(m.semi_additive, rule=rule))
        if m.semi_additive is not None
        else m
        for m in ir.metrics
    )
    return replace(ir, metrics=metrics)


def test_semi_additive_last_maps_to_window_choice_max() -> None:
    model = _model(_manifest("semi_additive_inventory"), "inventory")
    (measure,) = model.measures
    assert measure.name == "stock_on_hand"
    assert measure.non_additive_dimension is not None
    assert measure.non_additive_dimension.name == "snapshot_day"
    assert measure.non_additive_dimension.window_choice is AggregationType.MAX
    assert list(measure.non_additive_dimension.window_groupings) == []


def test_semi_additive_first_maps_to_window_choice_min() -> None:
    ir = _with_rule(_fixture_ir("semi_additive_inventory"), SemiAdditiveRule.FIRST)
    model = _model(emit_manifest(ir, naming=DefaultNaming()), "inventory")
    assert model.measures[0].non_additive_dimension.window_choice is AggregationType.MIN


@pytest.mark.parametrize(
    "rule", [SemiAdditiveRule.AVG, SemiAdditiveRule.MIN, SemiAdditiveRule.MAX]
)
def test_inexpressible_semi_additive_rules_are_refused_naming_the_rule(
    rule: SemiAdditiveRule,
) -> None:
    ir = _with_rule(_fixture_ir("semi_additive_inventory"), rule)
    with pytest.raises(UnsupportedByTarget, match=rf"rule '{rule.value}'.*stock_on_hand"):
        emit_manifest(ir, naming=DefaultNaming())


def test_semi_additive_over_without_a_date_role_is_an_emit_error() -> None:
    ir = _fixture_ir("semi_additive_inventory")
    metrics = tuple(
        replace(m, semi_additive=replace(m.semi_additive, over=DimensionRef("warehouse_id")))
        if m.semi_additive is not None
        else m
        for m in ir.metrics
    )
    with pytest.raises(EmitError, match="declares no date role over"):
        emit_manifest(replace(ir, metrics=metrics), naming=DefaultNaming())


def test_semi_additive_without_a_policy_is_an_emit_error() -> None:
    ir = _fixture_ir("semi_additive_inventory")
    metrics = tuple(replace(m, semi_additive=None) for m in ir.metrics)
    with pytest.raises(EmitError, match="no {over, rule} policy"):
        emit_manifest(replace(ir, metrics=metrics), naming=DefaultNaming())


# ....................... #
# Refusals and defenses

def test_marts_without_a_date_dimension_are_an_emit_error() -> None:
    ir = replace(_fixture_ir("ecom_basic"), date_dimension=None)
    with pytest.raises(EmitError, match="declare catalog date_dimension"):
        emit_manifest(ir, naming=DefaultNaming())


def test_unknown_aggregation_is_refused_naming_it() -> None:
    ir = _fixture_ir("role_playing_dates")
    metrics = tuple(replace(m, agg="corr") for m in ir.metrics)
    with pytest.raises(UnsupportedByTarget, match="'corr'"):
        emit_manifest(replace(ir, metrics=metrics), naming=DefaultNaming())


def test_measure_backed_metric_without_an_expression_is_refused() -> None:
    ir = _fixture_ir("role_playing_dates")
    metrics = tuple(replace(m, expr=None) for m in ir.metrics)
    with pytest.raises(UnsupportedByTarget, match="no expression"):
        emit_manifest(replace(ir, metrics=metrics), naming=DefaultNaming())


def test_a_measure_carrying_mart_without_date_roles_is_an_emit_error() -> None:
    """Unreachable behind the MartMissingTimeDimension guardrail — the
    emitter re-checks (RFC 0013 D3 rule 2 defense)."""
    ir = _fixture_ir("role_playing_dates")
    mart = ir.marts[0]
    stripped = replace(mart, columns=tuple(c for c in mart.columns if c.ref is None))
    with pytest.raises(EmitError, match="no date role reached the emitter"):
        emit_manifest(replace(ir, marts=(stripped,)), naming=DefaultNaming())


def test_metric_time_in_the_emitted_surface_is_an_emit_error() -> None:
    """Defense in depth: the spec layer reserves metric_time (M1); a column
    smuggled past it (hand-built IR) is still refused at emit."""
    ir = _fixture_ir("role_playing_dates")
    mart = ir.marts[0]
    smuggled = MartColumnIR(
        name="metric_time",
        type=mart.columns[0].type,
        source_entity=mart.base,
        source_column=mart.columns[0].source_column,
    )
    patched = replace(mart, columns=(*mart.columns, smuggled))
    with pytest.raises(EmitError, match="reserved query-time dimension"):
        emit_manifest(replace(ir, marts=(patched,)), naming=DefaultNaming())


# ....................... #
# Time spine, martless projects, capabilities, serialization

def test_time_spine_points_at_the_gold_date_dimension() -> None:
    manifest = _manifest("ecom_basic")
    (spine,) = manifest.project_configuration.time_spines
    assert spine.node_relation.schema_name == "gold"
    assert spine.node_relation.alias == "dim_date"
    assert spine.primary_column.name == "date_day"
    assert spine.primary_column.time_granularity is TimeGranularity.DAY


def test_time_spine_namespace_follows_the_naming_policy() -> None:
    manifest = emit_manifest(_fixture_ir("ecom_basic"), naming=PrefixNaming("acme"))
    (spine,) = manifest.project_configuration.time_spines
    assert spine.node_relation.schema_name == "acme_gold"
    assert spine.node_relation.alias == "dim_date"


def test_a_martless_project_emits_an_empty_manifest() -> None:
    manifest = _manifest("minimal")
    assert list(manifest.semantic_models) == []
    assert list(manifest.metrics) == []
    assert list(manifest.project_configuration.time_spines) == []


def test_planner_capabilities_refuse_query_time_joins_by_policy() -> None:
    assert METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.SEMI_ADDITIVE)
    assert METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.NON_ADDITIVE)
    assert METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.CUMULATIVE)
    assert METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.DERIVED_METRIC)
    assert METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.ROLE_PLAYING_DIM)
    assert METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.ROW_LEVEL_SECURITY)
    assert not METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.QUERY_TIME_JOIN)
    assert not METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.MULTI_FACT)


def test_manifest_json_is_byte_stable_and_sorted() -> None:
    ir = _fixture_ir("ecom_basic")
    first = manifest_json(emit_manifest(ir, naming=DefaultNaming()))
    second = manifest_json(emit_manifest(ir, naming=DefaultNaming()))
    assert first == second
    assert first.startswith('{"metrics"')  # sorted keys: metrics < project_configuration
    assert "\n" in manifest_json(emit_manifest(ir, naming=DefaultNaming()), indent=2)


def test_transformed_input_measures_are_resorted() -> None:
    """transform()'s AddInputMetricMeasuresRule collects a ratio's
    input_measures through a builtin *set* — hash-seed-ordered until the
    emitter re-sorts them. Regression for the golden-flaking nondeterminism
    the non_additive_aov fixture surfaced (RFC 0013 R1: the manifest is
    hashed and cached; the subprocess determinism guard covers the
    cross-seed half)."""
    manifest = _manifest("non_additive_aov")
    for metric in manifest.metrics:
        names = [measure.name for measure in metric.type_params.input_measures]
        assert names == sorted(names)
    ratio = next(m for m in manifest.metrics if m.name == "average_order_value")
    assert [m.name for m in ratio.type_params.input_measures] == ["order_count", "revenue"]
