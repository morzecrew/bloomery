"""The resolve stage (RFC 0005): the single dependency DAG, recorded-recipe
validation, reachability with specific missing leaves, cycle detection, the
deterministic topological emission order — and the IR builder that lowers a
resolved, typechecked project into :class:`~bloomery.ir.ProjectIR`."""

from bloomery.resolve.build import Stage, StageProgress, build_project_ir, pipeline
from bloomery.resolve.graph import Edge, Graph, Node, NodeKind, step_node
from bloomery.resolve.lineage import Direction, Lineage, lineage
from bloomery.resolve.resolution import FieldProvenance, Provenance, Resolution, resolve
from bloomery.resolve.timeline import (
    MatchedBy,
    SpecVersion,
    Timeline,
    TimelineChange,
    TimelineEntry,
    timeline,
)

# ----------------------- #

__all__ = [
    "Direction",
    "Edge",
    "FieldProvenance",
    "Graph",
    "Lineage",
    "MatchedBy",
    "Node",
    "NodeKind",
    "step_node",
    "Provenance",
    "Resolution",
    "SpecVersion",
    "Stage",
    "StageProgress",
    "Timeline",
    "TimelineChange",
    "TimelineEntry",
    "build_project_ir",
    "lineage",
    "pipeline",
    "resolve",
    "timeline",
]
