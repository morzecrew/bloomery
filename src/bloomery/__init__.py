"""Entity-first spec compiler: declarative entity/mapping/metric specs compiled
deterministically into SQLMesh, dbt, and Cube artifacts.

Public API (spec §8): the pure loaders (``load_catalog``, ``load_project``),
compilation (``compile_project`` with ``Target``), analysis without emission
(``resolve`` / ``Resolution``, ``build_project_ir``, ``project_fingerprint``),
spec-diff planning (``plan`` with ``Plan`` / ``Change`` / ``ChangeClass`` /
``BackfillScope`` — RFC 0007), the request-time planner (``MetricFlowPlanner`` with the ``MetricRequest`` /
``QueryPlan`` port types and ``RowPolicy`` — RFC 0011/0013), manifest
hydration (``LruManifestHydrator``, ``HydrationKey`` — RFC 0014), the
extension points (``register_transform``, ``register_emitter``), and the
total error hierarchy rooted at ``BloomeryError`` (import leaves from
:mod:`bloomery.errors`).
"""

from bloomery.compile import Target, compile_project
from bloomery.emit import register_emitter
from bloomery.errors import BloomeryError
from bloomery.ir import project_fingerprint
from bloomery.plan import BackfillScope, Change, ChangeClass, Plan, plan
from bloomery.planner import (
    AnyOf,
    ColumnDescriptor,
    MetricFlowPlanner,
    MetricRequest,
    Op,
    OrderSpec,
    Predicate,
    QueryPlan,
    RowPolicy,
    TimeGrain,
)
from bloomery.resolve import Resolution, build_project_ir, resolve
from bloomery.runtime import HydrationKey, LruManifestHydrator
from bloomery.spec import load_catalog, load_project
from bloomery.transforms import register_transform

__all__ = [
    "AnyOf",
    "BackfillScope",
    "BloomeryError",
    "Change",
    "ChangeClass",
    "ColumnDescriptor",
    "HydrationKey",
    "LruManifestHydrator",
    "MetricFlowPlanner",
    "MetricRequest",
    "Op",
    "OrderSpec",
    "Plan",
    "Predicate",
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
