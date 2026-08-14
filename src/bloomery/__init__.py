"""Entity-first spec compiler: declarative entity/mapping/metric specs compiled
deterministically into SQLMesh, dbt, and Cube artifacts.

Public API (spec §8): the pure loaders (``load_catalog``, ``load_project``),
compilation (``compile_project`` with ``Target``), analysis without emission
(``resolve`` / ``Resolution``, ``build_project_ir``, ``project_fingerprint``),
spec-diff planning (``plan`` with ``Plan`` / ``Change`` / ``ChangeClass`` /
``BackfillScope`` / ``ReplayScope`` — RFC 0007, RFC 0016), the request-time planner (``MetricFlowPlanner`` with the ``MetricRequest`` /
``QueryPlan`` port types and ``RowPolicy`` — RFC 0011/0013), manifest
hydration (``LruManifestHydrator``, ``HydrationKey`` — RFC 0014), the
JSON Schema export (``spec_json_schema`` / ``all_spec_schemas`` with
``SpecKind`` and ``JsonDict`` — RFC 0020), spec assessment as one value
(``evaluate`` with ``SpecEvidence`` / ``MartSummary`` / ``Stage`` — RFC 0022;
``Materialization`` comes with it, reached through ``MartSummary``), the
extension points (``register_transform``, ``register_emitter``), and the
total error hierarchy rooted at ``BloomeryError`` (import leaves from
:mod:`bloomery.errors`) — whose structured fix suggestions carry the two
payload types ``MartCoverage`` and ``MeasureRef`` (RFC 0020 D11), exported
here because D2's allowlist exempts the *errors*, not the values they hang.

The command line (``bloomery compile|plan|resolve|explain|schema|fingerprint``)
is a separate, one-directional shell over exactly this surface: it may import
the library, no library module may import it, and it is the only place in the
package that touches a filesystem (RFC 0020 D5).

**Signature closure** (RFC 0018 D1) is the rule that decides this list: a type
appearing in a public signature — parameter, return, generic argument, or field
of a returned dataclass — is exported here too, so a caller can always name what
the API hands them. ``tests/unit/test_signature_closure.py`` enforces it; the
walk stops at ``Catalog``, ``Project`` and ``ProjectIR``, which are handles
passed back rather than read (D9), and exempts ``bloomery.errors``, whose leaves
stay behind their own declared ``__all__`` (D2).
"""

from bloomery.compile import Target, compile_project
from bloomery.emit import ArtifactKind, EmittedArtifact, TargetEmitter, register_emitter
from bloomery.errors import BloomeryError, MartCoverage, MeasureRef
from bloomery.evidence import MartSummary, SpecEvidence, evaluate
from bloomery.ir import Materialization, ProjectIR, UnreachableMetric, project_fingerprint
from bloomery.naming import DefaultNaming, NamingPolicy
from bloomery.plan import BackfillScope, Change, ChangeClass, Plan, ReplayScope, plan
from bloomery.planner import (
    AnyOf,
    Clause,
    ColumnDescriptor,
    ColumnRole,
    Explanation,
    MeasureExplanation,
    MetricFlowPlanner,
    MetricRequest,
    Op,
    OrderDirection,
    OrderSpec,
    Predicate,
    QueryPlan,
    RowPolicy,
    Scalar,
    TimeGrain,
)
from bloomery.resolve import (
    FieldProvenance,
    Node,
    NodeKind,
    Provenance,
    Resolution,
    Stage,
    build_project_ir,
    resolve,
)
from bloomery.runtime import HydrationKey, LruManifestHydrator
from bloomery.schema import JsonDict, SpecKind, all_spec_schemas, spec_json_schema
from bloomery.spec import Catalog, Project, load_catalog, load_project
from bloomery.steps import EMPTY_REGISTRY, StepManifest, StepRegistry
from bloomery.transforms import Builder, OutputType, TransformSpec, register_transform
from bloomery.typing import ArgKind, LogicalType

__all__ = [
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
    "EMPTY_REGISTRY",
    "EmittedArtifact",
    "Explanation",
    "FieldProvenance",
    "HydrationKey",
    "JsonDict",
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
    "OrderDirection",
    "OrderSpec",
    "OutputType",
    "Plan",
    "Predicate",
    "Project",
    "ProjectIR",
    "Provenance",
    "QueryPlan",
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
    "load_catalog",
    "load_project",
    "plan",
    "project_fingerprint",
    "register_emitter",
    "register_transform",
    "resolve",
    "spec_json_schema",
]
