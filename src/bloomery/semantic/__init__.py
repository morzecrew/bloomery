"""The semantic grain model (RFC 0037): grain as structural identity,
functional dependencies carrying the basis that justifies them, and a
directional rollup question answered with a proof or a reason.

Vocabulary, not a stage. Nothing in the compile pipeline consults it yet —
RFC 0040's planner is the first consumer, and RFC 0037 §7 is explicit that the
mart's existing ``GrainViolation`` keeps its own implementation until an RFC
amends it. What this package owes the documents built on it (0038's measure
types, 0039's proof IR, 0040's planner, 0041's multi-grain queries) is one
grain comparison rather than four.

It sits below every consumer and above nothing but the IR: it reads
:class:`~bloomery.ir.ProjectIR` and knows nothing of SQLMesh, dbt, Cube,
MetricFlow or SQL syntax (§8), which the import contract enforces rather than
this docstring promising.
"""

from bloomery.semantic.closure import can_roll_up, closure, dependencies, prove_rollup
from bloomery.semantic.historical import AsOfState, qualify_as_of
from bloomery.semantic.nodes import (
    NO_CONTEXT,
    BlockedEdge,
    ColumnRef,
    DependencyBasis,
    DependencySet,
    Derivation,
    Determined,
    FunctionalDependency,
    GrainRef,
    RefusalReason,
    RollupContext,
    RollupProof,
    RollupRefusal,
    grain_of,
)
from bloomery.semantic.proof import (
    RULES,
    SUPERSEDED,
    Obligation,
    Proof,
    Provenance,
    Refutation,
    Rule,
    SemanticFact,
    SemanticJudgement,
)

# ----------------------- #

__all__ = [
    "prove_rollup",
    "SemanticJudgement",
    "SemanticFact",
    "SUPERSEDED",
    "Rule",
    "Refutation",
    "RULES",
    "Provenance",
    "Proof",
    "Obligation",
    "NO_CONTEXT",
    "AsOfState",
    "BlockedEdge",
    "ColumnRef",
    "DependencyBasis",
    "DependencySet",
    "Derivation",
    "Determined",
    "FunctionalDependency",
    "GrainRef",
    "RefusalReason",
    "RollupContext",
    "RollupProof",
    "RollupRefusal",
    "can_roll_up",
    "closure",
    "dependencies",
    "grain_of",
    "qualify_as_of",
]
