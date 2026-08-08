"""The resolve stage (RFC 0005): the single dependency DAG, recorded-recipe
validation, reachability with specific missing leaves, cycle detection, the
deterministic topological emission order — and the IR builder that lowers a
resolved, typechecked project into :class:`~bloomery.ir.ProjectIR`."""

from bloomery.resolve.build import build_project_ir
from bloomery.resolve.graph import Edge, Graph, Node, NodeKind, step_node
from bloomery.resolve.resolution import FieldProvenance, Provenance, Resolution, resolve

__all__ = [
    "Edge",
    "FieldProvenance",
    "Graph",
    "Node",
    "NodeKind",
    "step_node",
    "Provenance",
    "Resolution",
    "build_project_ir",
    "resolve",
]
