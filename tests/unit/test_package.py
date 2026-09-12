"""Package-surface smoke test: the public API is exactly what spec §8, the
stage RFCs and **signature closure** (RFC 0018 D1) promise (M2–M3 adds compile/resolve/build and the extension
points; M7–M8 add the planner port types, the MetricFlow planner, and
hydration — RFC 0011/0013/0014; M9 adds the plan stage — RFC 0007), and
``__all__`` stays sorted.

RFC 0040 adds the semantic plan and, with it, the proof vocabulary: a field on
``QueryPlan`` is a public signature, so signature closure promotes everything
reachable through it from ``bloomery.semantic`` to here (logs/T-0021.md,
D-120)."""

from __future__ import annotations

import pytest

import bloomery

pytestmark = pytest.mark.unit


def test_public_api_surface() -> None:
    assert bloomery.__all__ == [
        "Advisory",
        "AdvisoryCode",
        "AnyOf",
        "ArgKind",
        "ArtifactKind",
        "BackfillScope",
        "BloomeryError",
        "BranchSource",
        "Builder",
        "Catalog",
        "Change",
        "ChangeClass",
        "CheckedSurfaces",
        "Clause",
        "ColumnDescriptor",
        "ColumnRole",
        "DefaultNaming",
        "Direction",
        "EMPTY_REGISTRY",
        "Edge",
        "EmittedArtifact",
        "EvidenceGrade",
        "Explanation",
        "Facet",
        "FacetDelta",
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
        "MatchedBy",
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
        "PlanNode",
        "Predicate",
        "Project",
        "ProjectIR",
        "Proof",
        "Provenance",
        "QueryPlan",
        "RecipeOption",
        "ReplayScope",
        "Resolution",
        "RowPolicy",
        "Scalar",
        "SemanticFact",
        "SemanticJudgement",
        "SemanticPlan",
        "SpecEvidence",
        "SpecKind",
        "SpecVersion",
        "Stage",
        "StepManifest",
        "StepRegistry",
        "Target",
        "TargetEmitter",
        "TimeGrain",
        "Timeline",
        "TimelineChange",
        "TimelineEntry",
        "TransformSpec",
        "UnreachableMetric",
        "all_spec_schemas",
        "build_project_ir",
        "compile_project",
        "evaluate",
        "facets",
        "lineage",
        "load_catalog",
        "load_project",
        "node_labels",
        "plan",
        "project_fingerprint",
        "register_emitter",
        "register_transform",
        "resolve",
        "spec_json_schema",
        "timeline",
    ]


def test_all_is_sorted_and_resolvable() -> None:
    assert bloomery.__all__ == sorted(bloomery.__all__)
    for name in bloomery.__all__:
        assert getattr(bloomery, name) is not None
