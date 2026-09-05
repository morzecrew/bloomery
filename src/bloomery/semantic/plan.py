"""The semantic plan (RFC 0040): what a request computes, decided by bloomery
before any target sees it.

Today's planner resolves a covering mart and hands the request to MetricFlow,
which produces the SQL. That works and says nothing: the evidence that the
answer is right is that no precheck objected, and the reasoning is spread
across a coverage function and an embedded engine. §6 asks for the other shape
— bloomery decides, targets lower — and this is the value it decides *into*.

**Nothing lowers from it yet, and that is P1.** The plan is built beside the
SQL and consumed by no target: MetricFlow still plans from the request exactly
as it did, so a reader should not take a plan's presence as evidence that it
produced the query beside it. §11 makes P1 the IR alone, and D5 makes it a
re-expression with no capability change — wiring a target to the plan would
change what the SQL is generated from, which is the one thing this phase must
not do if §8's parity suite is to mean anything.

**A plan is not a rendering.** It names logical operators over grains, and a
target may choose any syntax for them, but it may not introduce a
multiplicity-changing join the plan does not carry (D4). Where a node can
duplicate a row it references the proof that authorizes it, and a plan whose
such nodes do not is **invalid IR rather than merely unexplained** (D2) —
:meth:`SemanticPlan.check` is where that distinction stops being a sentence.

At P1 there is nothing to authorize: the mart is already flattened, so the plan
is a scan, a filter and an aggregate that only ever reduces. D2 therefore holds
over an empty set here, and that is worth saying rather than presenting an
empty check as a passed one (logs/T-0021.md, D-116). The first
:class:`PreservingJoin` arrives with P2 and is what makes it bite.

Here rather than under ``planner`` because §6 hands this to target adapters,
and the emitters sit below the planner in the layer contract — a plan they
cannot import is a plan they cannot be handed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from bloomery.semantic.proof import Proof

# ----------------------- #

__all__ = [
    "Aggregate",
    "Filter",
    "PlanNode",
    "Project",
    "Scan",
    "SemanticPlan",
]


@dataclass(frozen=True, slots=True)
class Scan:
    """The relation a plan reads. ``grain`` is the grain of one of its rows.

    At P1 this is always a mart, which is pre-joined — so the plan starts at
    the grain the mart was built at rather than at an entity, and the joins
    that produced it were proven when the mart was built rather than here.
    """

    relation: str
    grain: str

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    def document(self) -> dict[str, object]:
        return {"node": "scan", "relation": self.relation, "grain": self.grain}

    # ....................... #

    def render(self) -> str:
        return f"Scan({self.relation} @ {self.grain})"


# ....................... #


@dataclass(frozen=True, slots=True)
class Filter:
    """Row restriction. Never multiplicity-changing: it removes rows and
    invents none, so it needs no authorization."""

    #: Rendered predicates, sorted — this is a plan, not a SQL string, and the
    #: target chooses how to spell them.
    predicates: tuple[str, ...] = ()

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.predicates))
        if canonical != self.predicates:
            object.__setattr__(self, "predicates", canonical)

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    def document(self) -> dict[str, object]:
        return {"node": "filter", "predicates": list(self.predicates)}

    # ....................... #

    def render(self) -> str:
        return f"Filter({'; '.join(self.predicates) or 'none'})"


# ....................... #


@dataclass(frozen=True, slots=True)
class Aggregate:
    """Measures rolled from ``input_grain`` to the grouping in ``dimensions``.

    ``output_grain`` is the *key* grain the result is identified by, and
    ``dimensions`` the columns projected from it. RFC 0040 §5 writes that pair
    as one name — ``output_grain=CustomerCountry`` — but ``country`` is not
    part of ``customer``'s key, and RFC 0037's grain is key identity, so no
    such grain exists to name. RFC 0039 §7 renders the same argument in the
    shape that does: roll up to the key grain, and the column is determined by
    that key (logs/T-0021.md, D-117).

    Reduces multiplicity and never raises it, so it carries a proof for what it
    *rolled up*, not for a duplication it might have caused.
    """

    input_grain: str
    output_grain: str
    measures: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    #: The proof authorizing this aggregate. Optional on the type because a
    #: caller may build a node before it has one; every aggregate the P1
    #: builder produces carries R008, the mart contract that lets a measure be
    #: embedded at this grain at all.
    proof: Proof | None = None

    # ....................... #

    def __post_init__(self) -> None:
        for name in ("measures", "dimensions"):
            canonical = tuple(sorted(getattr(self, name)))
            if canonical != getattr(self, name):
                object.__setattr__(self, name, canonical)

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "aggregate",
            "input_grain": self.input_grain,
            "output_grain": self.output_grain,
            "measures": list(self.measures),
            "dimensions": list(self.dimensions),
            "proof": self.proof.document() if self.proof is not None else None,
        }

    # ....................... #

    def render(self) -> str:
        grouped = ", ".join(self.dimensions) or "total"
        return (
            f"Aggregate({', '.join(self.measures)} : {self.input_grain} -> "
            f"{self.output_grain} by {grouped})"
        )


# ....................... #


@dataclass(frozen=True, slots=True)
class Project:
    """The output columns, in the order the caller asked for them.

    Order is *not* canonicalized here, unlike everywhere else in this package:
    a result's column order is part of the answer, and sorting it would change
    what the caller receives.
    """

    columns: tuple[str, ...] = ()

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    def document(self) -> dict[str, object]:
        return {"node": "project", "columns": list(self.columns)}

    # ....................... #

    def render(self) -> str:
        return f"Project({', '.join(self.columns) or 'none'})"


# ....................... #

#: The node vocabulary, closed. RFC 0040 §4 also lists `PreservingJoin` and
#: `ConvertUnit`; neither exists yet — the first arrives with P2's cross-entity
#: rollup and the second with RFC 0038's unit work — and inventing them now
#: would be two node types no plan can contain and no test can reach.
PlanNode = Scan | Filter | Aggregate | Project


@dataclass(frozen=True, slots=True)
class SemanticPlan:
    """A validated plan: what to compute, and on what authority.

    Constructed only after every obligation is proven — which at P1 is a short
    list, since a pre-joined mart introduces no multiplicity. :meth:`check`
    runs on construction rather than being offered to callers, because D2 makes
    an unauthorized plan *invalid* rather than undocumented, and a validity
    rule a caller has to remember to invoke is one that gets skipped exactly
    when the caller is in a hurry.
    """

    nodes: tuple[PlanNode, ...]

    # ....................... #

    def __post_init__(self) -> None:
        self.check()

    # ....................... #

    def check(self) -> None:
        """D2: every multiplicity-changing node references its proof.

        **The multiplicity half is vacuous at P1 and deliberately kept
        anyway.** No node type here can multiply — a mart is pre-joined and an
        aggregate reduces — so that loop runs and finds nothing. It exists
        because P2 adds `PreservingJoin`, and a rule written at the moment the
        first such node lands is a rule written under the pressure of making
        that node work.

        The emptiness check above it is not vacuous and is not decoration: an
        empty sequence satisfies "every multiplying node carries a proof"
        perfectly, so without it a plan that computes nothing is a plan this
        method calls valid.
        """
        if not self.nodes:
            msg = (
                "a plan with no nodes computes nothing — `check` would pass over an empty "
                "sequence and report it valid, which is the same shape as a proof resting "
                "on no facts (RFC 0040 D2)"
            )
            raise ValueError(msg)

        unauthorized = [
            node.render()
            for node in self.nodes
            if node.multiplies and getattr(node, "proof", None) is None
        ]

        if unauthorized:
            msg = (
                f"plan has multiplicity-changing node(s) with no proof: {unauthorized} — "
                "a plan whose duplicating joins carry no authorization is invalid IR, not "
                "merely unexplained (RFC 0040 D2)"
            )
            raise ValueError(msg)

    # ....................... #

    @property
    def shape(self) -> tuple[str, ...]:
        """The node kinds in order — what a test asserts instead of comparing
        whole nodes, so that adding a field to one does not rewrite every
        assertion about plans that contain it."""

        return tuple(str(node.document()["node"]) for node in self.nodes)

    # ....................... #

    @property
    def proofs(self) -> tuple[Proof, ...]:
        """Every proof this plan rests on, in node order."""

        return tuple(
            proof for node in self.nodes if (proof := getattr(node, "proof", None)) is not None
        )

    # ....................... #

    def document(self) -> dict[str, object]:
        return {"nodes": [node.document() for node in self.nodes]}

    # ....................... #

    def serialize(self) -> str:
        """Canonical JSON — deterministic under RFC 0003, like the proofs it
        carries. Node order is the plan's meaning and is never sorted."""

        return json.dumps(self.document(), separators=(",", ":"), ensure_ascii=False)

    # ....................... #

    def render(self) -> str:
        """The plan as a pipeline, one node per line, in execution order."""

        return "\n".join(
            f"{'  ' * index}-> {node.render()}" if index else node.render()
            for index, node in enumerate(self.nodes)
        )
