"""Package-surface smoke test: the public API is exactly what spec §8, the
stage RFCs and **signature closure** (RFC 0018 D1) promise (M2–M3 adds compile/resolve/build and the extension
points; M7–M8 add the planner port types, the MetricFlow planner, and
hydration — RFC 0011/0013/0014; M9 adds the plan stage — RFC 0007), and
``__all__`` stays sorted."""

from __future__ import annotations

import pytest

import bloomery

pytestmark = pytest.mark.unit


def test_public_api_surface() -> None:
    assert bloomery.__all__ == [
        "AnyOf",
        "ArgKind",
        "ArtifactKind",
        "BackfillScope",
        "BloomeryError",
        "Builder",
        "Catalog",
        "Change",
        "ChangeClass",
        "Clause",
        "ColumnDescriptor",
        "ColumnRole",
        "DefaultNaming",
        "Direction",
        "EMPTY_REGISTRY",
        "Edge",
        "EmittedArtifact",
        "Explanation",
        "FieldProvenance",
        "Gap",
        "Graph",
        "HydrationKey",
        "JsonDict",
        "Lineage",
        "LogicalType",
        "LruManifestHydrator",
        "MartCoverage",
        "MartSummary",
        "Materialization",
        "MeasureExplanation",
        "MeasureRef",
        "MetricFlowPlanner",
        "MetricRequest",
        "NamingPolicy",
        "Node",
        "NodeKind",
        "Op",
        "OpenDecision",
        "OrderDirection",
        "OrderSpec",
        "OutputType",
        "Plan",
        "Predicate",
        "Project",
        "ProjectIR",
        "Provenance",
        "QueryPlan",
        "RecipeOption",
        "ReplayScope",
        "Resolution",
        "RowPolicy",
        "Scalar",
        "SpecEvidence",
        "SpecKind",
        "Stage",
        "StepManifest",
        "StepRegistry",
        "Target",
        "TargetEmitter",
        "TimeGrain",
        "TransformSpec",
        "UnreachableMetric",
        "all_spec_schemas",
        "build_project_ir",
        "compile_project",
        "evaluate",
        "lineage",
        "load_catalog",
        "load_project",
        "plan",
        "project_fingerprint",
        "register_emitter",
        "register_transform",
        "resolve",
        "spec_json_schema",
    ]


def test_all_is_sorted_and_resolvable() -> None:
    assert bloomery.__all__ == sorted(bloomery.__all__)
    for name in bloomery.__all__:
        assert getattr(bloomery, name) is not None
