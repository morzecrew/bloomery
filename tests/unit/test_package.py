"""Package-surface smoke test: the public API is exactly what spec §8 and the
stage RFCs promise (M2–M3 adds compile/resolve/build and the extension
points; M7–M8 add the planner port types, the MetricFlow planner, and
hydration — RFC 0011/0013/0014; M9 adds the plan stage — RFC 0007), and
``__all__`` stays sorted."""

from __future__ import annotations

import pytest

import bloomery

pytestmark = pytest.mark.unit


def test_public_api_surface() -> None:
    assert bloomery.__all__ == [
        "BackfillScope",
        "BloomeryError",
        "Change",
        "ChangeClass",
        "ColumnDescriptor",
        "FilterExpr",
        "HydrationKey",
        "LruManifestHydrator",
        "MetricFlowPlanner",
        "MetricRequest",
        "OrderSpec",
        "Plan",
        "QueryPlan",
        "Resolution",
        "RowPolicy",
        "Target",
        "TimeGrain",
        "build_project_ir",
        "compile_project",
        "load_catalog",
        "load_project",
        "plan",
        "project_fingerprint",
        "register_emitter",
        "register_transform",
        "resolve",
    ]


def test_all_is_sorted_and_resolvable() -> None:
    assert bloomery.__all__ == sorted(bloomery.__all__)
    for name in bloomery.__all__:
        assert getattr(bloomery, name) is not None
