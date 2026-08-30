"""The resolve stage (RFC 0005): the single dependency DAG, recorded-recipe
validation, reachability with specific missing leaves, cycle detection, the
deterministic topological emission order — and the IR builder that lowers a
resolved, typechecked project into :class:`~bloomery.ir.ProjectIR`."""

from bloomery.resolve.build import Stage, StageProgress, build_project_ir, pipeline
from bloomery.resolve.graph import Edge, Graph, Node, NodeKind, step_node
from bloomery.resolve.lineage import Direction, Lineage, lineage
from bloomery.resolve.resolution import FieldProvenance, Provenance, Resolution, resolve

# ----------------------- #

__all__ = [
    "Direction",
    "Edge",
    "FieldProvenance",
    "Graph",
    "Lineage",
    "Node",
    "NodeKind",
    "step_node",
    "Provenance",
    "Resolution",
    "Stage",
    "StageProgress",
    "build_project_ir",
    "lineage",
    "pipeline",
    "resolve",
]
