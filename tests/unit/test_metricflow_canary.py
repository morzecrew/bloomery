"""Version-drift canary (RFC 0013 D11, §6): bloomery depends on MetricFlow
*internals* with no stability guarantee — this test asserts every surface the
emitter and (M7) planner rely on still exists at the pinned ``0.211.*``, so an
upgrade breaks loudly here instead of silently downstream. A failure means the
pin moved: regenerate goldens and review the diff as source (RFC 0013 §9)."""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys

import pytest
from metricflow.engine.metricflow_engine import (
    MetricFlowEngine,
    MetricFlowExplainResult,
    MetricFlowQueryRequest,
)
from metricflow.protocols.sql_client import SqlClient, SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow_semantic_interfaces.implementations.elements.measure import (
    PydanticMeasure,
    PydanticNonAdditiveDimensionParameters,
)
from metricflow_semantic_interfaces.implementations.metric import PydanticMetric
from metricflow_semantic_interfaces.implementations.node_relation import PydanticNodeRelation
from metricflow_semantic_interfaces.implementations.semantic_model import PydanticSemanticModel
from metricflow_semantic_interfaces.transformations.semantic_manifest_transformer import (
    PydanticSemanticManifestTransformer,
)
from metricflow_semantic_interfaces.type_enums.aggregation_type import AggregationType
from metricflow_semantic_interfaces.type_enums.entity_type import EntityType
from metricflow_semantic_interfaces.type_enums.metric_type import MetricType
from metricflow_semantic_interfaces.type_enums.time_granularity import TimeGranularity
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

pytestmark = pytest.mark.unit


def test_metricflow_api_surface() -> None:
    """The exact internal surfaces RFC 0013 builds on (§3, §5.9, D11)."""
    # The embedded-engine entry points.
    assert callable(MetricFlowQueryRequest.create)
    assert callable(MetricFlowEngine.explain)
    assert callable(SemanticManifestLookup)
    # explain() -> MetricFlowExplainResult with the rendered SQL statement.
    assert "sql_statement" in dir(MetricFlowExplainResult)
    # transform() is mandatory before hydration (RFC 0013 §3).
    assert callable(PydanticSemanticManifestTransformer.transform)


def test_sql_client_protocol_members() -> None:
    """RenderOnlySqlClient stubs exactly this Protocol (RFC 0013 §5.3)."""
    members = set(dir(SqlClient))
    assert {
        "sql_engine_type",
        "sql_plan_renderer",
        "query",
        "execute",
        "dry_run",
        "close",
        "render_bind_parameter_key",
    } <= members
    assert SqlEngine.DUCKDB is not None
    assert inspect.isclass(DuckDbSqlPlanRenderer)


def test_node_relation_has_no_sql_field() -> None:
    """RFC 0013 §5.9c: the (unbuilt) row-policy escape hatch is a per-view
    *name* swap — PydanticNodeRelation cannot carry an inline SQL body."""
    assert sorted(PydanticNodeRelation.__fields__) == [
        "alias",
        "database",
        "relation_name",
        "schema_name",
    ]


def test_manifest_model_fields_the_emitter_populates() -> None:
    assert "primary_entity" in PydanticSemanticModel.__fields__  # composite keys
    assert "non_additive_dimension" in PydanticMeasure.__fields__
    assert "agg_time_dimension" in PydanticMeasure.__fields__
    assert "description" in PydanticMetric.__fields__
    assert sorted(PydanticNonAdditiveDimensionParameters.__fields__) == [
        "name",
        "window_choice",
        "window_groupings",
    ]


def test_enum_members_the_mapping_tables_use() -> None:
    assert {AggregationType.SUM, AggregationType.MIN, AggregationType.MAX} <= set(
        AggregationType
    )
    assert {MetricType.SIMPLE, MetricType.RATIO} <= set(MetricType)
    assert {EntityType.PRIMARY, EntityType.FOREIGN} <= set(EntityType)
    assert TimeGranularity.DAY.value == "day"


def test_emitter_survives_being_the_first_msi_import() -> None:
    """RFC 0013 §5.9a: ``implementations.node_relation`` as the process's
    first metricflow_semantic_interfaces import raises a circular
    ImportError. The emitter orders its imports to finish ``protocols``
    first — this fresh-subprocess check keeps an import re-sort from
    silently breaking that."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import bloomery.emit.metricflow"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_top_level_pydantic_shim_module_exists() -> None:
    """RFC 0013 §5.9b: the wheel installs a top-level ``msi_pydantic_shim``
    module — deptry/vulture configuration accounts for it; its disappearance
    would signal a repackaged wheel."""
    assert importlib.import_module("msi_pydantic_shim") is not None


def test_pydantic_is_v2_only() -> None:
    """The environment carries exactly one pydantic: v2. MetricFlow's manifest
    models are v1-*style* only via the ``pydantic.v1`` compatibility namespace
    inside the v2 package (routed by ``msi_pydantic_shim``) — no legacy pydantic
    v1 distribution is installed, and bloomery's own models are pure v2. The
    v1-style surface is confined to two boundary call sites (``manifest_json``,
    ``hydrate_manifest``); pydantic 3 dropping the namespace is fenced by
    metricflow's own ``pydantic<3`` constraint."""
    import pydantic

    assert pydantic.VERSION.startswith("2.")
    shim = importlib.import_module("msi_pydantic_shim")
    assert shim.BaseModel.__module__.startswith("pydantic.v1")
