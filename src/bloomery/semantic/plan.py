"""The semantic plan (RFC 0040): what a request computes, decided by bloomery
before any target sees it.

Today's planner resolves a covering mart and hands the request to MetricFlow,
which produces the SQL. That works and says nothing: the evidence that the
answer is right is that no precheck objected, and the reasoning is spread
across a coverage function and an embedded engine. §6 asks for the other shape
— bloomery decides, targets lower — and this is the value it decides *into*.

**Nothing lowers from it yet, and that is still true.** The plan is built
beside the SQL and consumed by no target: MetricFlow still plans from the
request exactly as it did, so a reader should not take a plan's presence as
evidence that it produced the query beside it. Wiring a target to the plan
would change what the SQL is generated from, which is the one thing every
phase here has had to avoid if the parity suite is to mean anything — and
RFC 0066 §4 keeps it a non-goal for the same reason.

**A plan is not a rendering.** It names logical operators over grains, and a
target may choose any syntax for them, but it may not introduce a
multiplicity-changing join the plan does not carry (D4). Where a node makes a
semantic claim it references the proof that authorizes it, and a plan whose
such nodes do not is **invalid IR rather than merely unexplained** (D2) —
:meth:`SemanticPlan.check` is where that distinction stops being a sentence.

D2's own sentence names the multiplicity-changing node, and **there is still
no such node**: the mart is already flattened, so every kind here reduces, adds
a column, or names one. Read literally, the rule would hold over an empty set.
It does not, because a node that *claims* is checked too — the aggregate claims
these measures may be rolled to this grain, and five more have joined it since
(logs/T-0021.md, D-124).

`PreservingJoin` was once expected to arrive and bring the other half. It has
not, and RFC 0041 D10 keeps it refused rather than deferred: joining
unaggregated rows is the fan-out the wide-mart design removes, so the half of
D2 about multiplication stays vacuous **by construction** rather than by phase.
That is a stronger position than the one this paragraph originally described,
and it is why the check asks a node whether it claims rather than whether it
multiplies (RFC 0041 D14).

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
    "Compute",
    "Filter",
    "JoinAggregates",
    "JoinBranch",
    "Offset",
    "PlanNode",
    "Project",
    "Reduce",
    "Scan",
    "SemanticPlan",
    "Window",
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

    @property
    def claims(self) -> bool:
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
    invents none, so it needs no authorization.

    It must, however, name **every** predicate the query applies — a row
    policy and a metric's own restriction narrow the answer exactly as a
    request filter does, and a plan that omits one is a plan a target lowers
    into a broader result than the one bloomery decided.
    """

    #: Every predicate that restricts the scanned rows, in the order the query
    #: applies them — policy first, then the request's filters in request
    #: order, then each metric's own restriction. Rendered as prose: this is a
    #: plan, not a SQL string, and the target chooses how to spell them.
    #:
    #: Not sorted. Sorting them canonicalized a tuple whose source is already
    #: deterministic and, in doing so, made the plan disagree with the
    #: explanation beside it about the order of the same predicates — an
    #: invariant the no-filter case could never catch.
    predicates: tuple[str, ...] = ()
    #: The measures these predicates restrict; empty means **every** measure
    #: beneath (RFC 0066 §5.5).
    #:
    #: A metric's own `filter:` narrows that measure alone, so a request pairing
    #: `paid_revenue` with `revenue` restricts one and not the other. One
    #: unscoped node covering both would say each predicate restricts every
    #: measure beneath it — a broader claim than the query makes, and the reason
    #: such a request had no plan at all before this. Scoped here rather than on
    #: :class:`Aggregate` because this is the node that makes the claim.
    measures: tuple[str, ...] = ()

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    @property
    def claims(self) -> bool:
        return False

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.measures))
        if canonical != self.measures:
            object.__setattr__(self, "measures", canonical)

        if self.measures and not self.predicates:
            msg = (
                "a filter scoped to measures with no predicates restricts nothing while "
                "naming what it restricts, which reads as a narrowed measure and is not "
                "one (RFC 0066 §5.5)"
            )
            raise ValueError(msg)

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "filter",
            "predicates": list(self.predicates),
            "measures": list(self.measures),
        }

    # ....................... #

    def render(self) -> str:
        scope = f" on {', '.join(self.measures)}" if self.measures else ""
        return f"Filter({'; '.join(self.predicates) or 'none'}{scope})"


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
    #: caller may build a node before it has one — but a
    #: :class:`SemanticPlan` containing an unproven aggregate does not
    #: construct. Every aggregate the P1 builder produces carries R008, the
    #: mart contract that lets a measure be embedded at this grain at all.
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

    @property
    def claims(self) -> bool:
        return True

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

    @property
    def claims(self) -> bool:
        return False

    # ....................... #

    def document(self) -> dict[str, object]:
        return {"node": "project", "columns": list(self.columns)}

    # ....................... #

    def render(self) -> str:
        return f"Project({', '.join(self.columns) or 'none'})"


# ....................... #


@dataclass(frozen=True, slots=True)
class Compute:
    """A column computed from other columns of the same relation, **after**
    they were aggregated (RFC 0066 §5.2).

    The node RFC 0040 §4 never had and `compose` names by its absence: "none of
    them states arithmetic, so naming the metric in ``Project.columns`` would
    claim the join produced a column the join does not produce". A ratio and an
    RFC 0034 ``derived:`` expression are both this shape — a metric with no
    measure of its own, rebuilt from measures that have one.

    **The claim is the ordering, not the arithmetic.** Division needs no
    authorization. What needs it is computing the expression *here* rather than
    per row before the aggregate: ``SUM(a)/SUM(b)`` and a row-level ``a/b``
    aggregated afterwards are different numbers, and only one of them is what
    the metric declares. R014 is that rule, and it premises on the aggregate
    beneath — which is why an unaggregated `Compute` cannot construct.
    """

    #: Output column → the expression producing it, as prose. Sorted by output
    #: name: a plan states what is computed, and two orders of one set of
    #: definitions are one plan.
    outputs: tuple[tuple[str, str], ...]
    #: What the expressions reference, so a reader can check them against
    #: columns the plan actually produces. Sorted for the same reason.
    inputs: tuple[str, ...] = ()
    proof: Proof | None = None

    # ....................... #

    def __post_init__(self) -> None:
        for name in ("outputs", "inputs"):
            canonical = tuple(sorted(getattr(self, name)))
            if canonical != getattr(self, name):
                object.__setattr__(self, name, canonical)

        if not self.outputs:
            msg = (
                "a compute node with no outputs computes nothing, and `check` would "
                "report it authorized — the same shape as a proof resting on no facts "
                "(RFC 0066 §5.2)"
            )
            raise ValueError(msg)

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    @property
    def claims(self) -> bool:
        return True

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "compute",
            "outputs": [[name, expr] for name, expr in self.outputs],
            "inputs": list(self.inputs),
            "proof": self.proof.document() if self.proof is not None else None,
        }

    # ....................... #

    def render(self) -> str:
        # Semicolons, not commas: each output carries its own alias list, and
        # comma-joining two of them reads as one expression with four aliases.
        computed = "; ".join(f"{name} = {expr}" for name, expr in self.outputs)
        return f"Compute({computed})"


# ....................... #


@dataclass(frozen=True, slots=True)
class Reduce:
    """One named dimension collapsed by a declared rule (RFC 0066 §5.3).

    What a semi-additive measure is lowered as before anything else touches it:
    the ``over:`` dimension reduced away, leaving one value per group, so that
    aggregating across the *other* dimensions is legitimate afterwards. RFC 0040
    P1 declined these because "one ``Aggregate`` cannot say" it, and a plan that
    said `Aggregate` would have named the operation it is not.

    **`Reduce` rather than `Pick`, and the whole vocabulary rather than two of
    it.** ``SemiAdditiveRule`` is ``last``, ``first``, ``avg``, ``min``,
    ``max`` — three of which select no row at all, so a node named for picking
    would have been right about two members of five and would have needed a
    comment arguing its own name away.

    It differs from :class:`Aggregate` in what licenses it rather than in what
    it does to rows. An `Aggregate` reduces by the metric's own declared
    aggregation and is licensed by the mart contract; a `Reduce` collapses one
    *named* dimension by the semi-additive rule, and is licensed by that
    declaration. Two nodes because two different facts authorize them.
    """

    #: The grain a row is identified by once ``over`` is gone.
    output_grain: str
    #: The dimension reduced away — the metric's declared ``over:``.
    over: str
    #: The declared rule along it, as its own word.
    rule: str
    measures: tuple[str, ...] = ()
    proof: Proof | None = None

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.measures))
        if canonical != self.measures:
            object.__setattr__(self, "measures", canonical)

        if not self.measures:
            msg = (
                "a reduce node with no measures reduces nothing, and `check` would report "
                "it authorized — the same shape as a proof resting on no facts "
                "(RFC 0066 §5.3)"
            )
            raise ValueError(msg)

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    @property
    def claims(self) -> bool:
        return True

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "reduce",
            "output_grain": self.output_grain,
            "over": self.over,
            "rule": self.rule,
            "measures": list(self.measures),
            "proof": self.proof.document() if self.proof is not None else None,
        }

    # ....................... #

    def render(self) -> str:
        return (
            f"Reduce({', '.join(self.measures)} : {self.rule} over {self.over} "
            f"-> {self.output_grain})"
        )


# ....................... #


@dataclass(frozen=True, slots=True)
class Window:
    """Accumulation across rows at query time (RFC 0066 §5.4).

    A ``cumulative:`` metric keeps its own measure and its own additivity —
    those describe the measure, this describes the accumulation. RFC 0040 P1
    declined these because "a window and a ``period_agg`` are not a rollup at
    all", and a plan reading as a plain sum per day would have been the
    operation this is not.

    **Its output is not re-aggregable, and that is the part worth stating.** A
    reader seeing an :class:`Aggregate` beneath must not conclude the window's
    result can be rolled further: a trailing 7-day total summed across weeks
    counts each day up to seven times. R016 records the frame so that any later
    transformation has something to refuse against, rather than a column that
    looks like every other measure.
    """

    measures: tuple[str, ...]
    #: The ordering the window runs along.
    over: str
    #: ``trailing <n> <grain>`` or ``grain_to_date <grain>`` — the two forms a
    #: metric may declare, rendered as prose because a plan is not SQL.
    frame: str
    #: What a request *coarser* than the accumulation collapses the series
    #: with. Declared on the metric and applied by the engine, so it is stated
    #: here for the same reason the frame is: it decides the number, and a plan
    #: silent about it would be silent about a collapse that changes the answer.
    period_agg: str
    proof: Proof | None = None

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.measures))
        if canonical != self.measures:
            object.__setattr__(self, "measures", canonical)

        if not self.measures:
            msg = (
                "a window node with no measures accumulates nothing, and `check` would "
                "report it authorized — the same shape as a proof resting on no facts "
                "(RFC 0066 §5.4)"
            )
            raise ValueError(msg)

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    @property
    def claims(self) -> bool:
        return True

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "window",
            "measures": list(self.measures),
            "over": self.over,
            "frame": self.frame,
            "period_agg": self.period_agg,
            "proof": self.proof.document() if self.proof is not None else None,
        }

    # ....................... #

    def render(self) -> str:
        return (
            f"Window({', '.join(self.measures)} : {self.frame} over {self.over}, "
            f"coarser requests take {self.period_agg})"
        )


# ....................... #


@dataclass(frozen=True, slots=True)
class Offset:
    """The same measure read at a shifted range (RFC 0066 §5.6).

    A ``derived:`` input may carry an ``offset_window`` or ``offset_to_grain``,
    so ``revenue_yoy`` reads `revenue` now and `revenue` a year earlier and
    subtracts. The second read is not a column of the relation the expression
    runs over, which is why :class:`Compute` alone could not state it and the
    request had no plan at all.

    **What this node states is the declared shift, not the join that renders
    it.** MetricFlow lowers an offset by joining the measure to the time spine
    at a shifted date under a full outer join; a plan naming that would be
    stating how the SQL is spelled rather than what is computed, which RFC 0040
    D4 refuses. The target chooses the mechanism; the plan says which measure
    is read, over which ordering, and how far back.

    **The gap question is the whole of R017.** A shifted read is sound when the
    shifted range aggregates the same way the current one does — and a period
    with no rows must read as *absent* rather than as zero, because a missing
    prior period and a prior period that really summed to nothing are different
    answers and only one of them is a defensible denominator.
    """

    #: ``(metric, alias, measure, shift)`` — whose expression references the
    #: alias, the alias itself, the measure it reads, and how far back, as
    #: prose. Sorted.
    #:
    #: The metric is not decoration. An alias is scoped to the metric that
    #: declares it (RFC 0034 D1), so two ``derived:`` metrics may both call
    #: their offset input ``prior`` and mean different measures; flattening
    #: them into one namespace produced a plan naming one alias twice, which no
    #: target can lower because the expressions above reference ``prior`` and
    #: there is no longer one answer to which.
    reads: tuple[tuple[str, str, str, str], ...]
    #: The ordering the shift runs along.
    over: str
    proof: Proof | None = None

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.reads))
        if canonical != self.reads:
            object.__setattr__(self, "reads", canonical)

        if not self.reads:
            msg = (
                "an offset node with no reads shifts nothing, and `check` would report it "
                "authorized — the same shape as a proof resting on no facts (RFC 0066 §5.6)"
            )
            raise ValueError(msg)

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    @property
    def claims(self) -> bool:
        return True

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "offset",
            "reads": [
                [metric, alias, measure, shift] for metric, alias, measure, shift in self.reads
            ],
            "over": self.over,
            "proof": self.proof.document() if self.proof is not None else None,
        }

    # ....................... #

    def render(self) -> str:
        shifted = "; ".join(
            f"{metric}.{alias} = {measure} {shift}" for metric, alias, measure, shift in self.reads
        )
        return f"Offset({shifted} over {self.over})"


# ....................... #


@dataclass(frozen=True, slots=True)
class JoinBranch:
    """One branch of a join, and what *it* calls the join keys.

    The pair, and not the plan alone. Two marts spell one dimension
    differently, so a join node holding only plans cannot tell whether a
    branch aggregated to the keys or to something else with the same number of
    columns — and "each side is unique at the key" is the whole content of
    R010. Carrying the branch's own names is what makes that sentence
    checkable rather than asserted (logs/T-0026.md, D-174).
    """

    plan: SemanticPlan
    #: This branch's names for the join keys, in the join's key order.
    keys: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class JoinAggregates:
    """Branch plans joined on the key their aggregates already reduced them to
    (RFC 0041 D1, D9).

    Each branch is a whole :class:`SemanticPlan` rather than a node list,
    because a branch *is* a plan: it scans, restricts, aggregates and carries
    its own proof, and it was checked when it was constructed. Nesting them
    keeps that so — a branch that could not stand alone cannot enter a join.

    ``keys`` are the result-grain columns in the caller's vocabulary, one name
    for every branch: two marts spell a flattened column differently, and D12
    settles that they are the same dimension by provenance, so the join names
    it once and each branch's own spelling stays inside that branch.

    **Never multiplies, and still carries a proof.** A join of relations each
    unique at ``keys`` returns at most one row per key — that is D2, and it is
    structural, from the aggregate beneath each branch rather than from
    anything the warehouse holds. R010 states it. The alternative, a join node
    exempt from proof because its inputs obviously cannot fan out, is how the
    fan-out returns the first time a branch stops ending in an aggregate.
    """

    keys: tuple[str, ...]
    branches: tuple[JoinBranch, ...]
    proof: Proof | None = None

    # ....................... #

    def __post_init__(self) -> None:
        # Sorted like every other IR collection (RFC 0003) — and the branches
        # are reordered *with* the keys, because entry `i` of a branch is that
        # branch's name for key `i`. Sorting one side alone breaks the pairing
        # silently: `keys` reads `('signed_up', 'tier')` while every branch
        # still lists its tier column first, and a target lowering the plan
        # joins the wrong columns (logs/T-0026.md, D-175).
        order = sorted(range(len(self.keys)), key=lambda index: self.keys[index])

        if order != list(range(len(self.keys))):
            object.__setattr__(self, "keys", tuple(self.keys[index] for index in order))
            object.__setattr__(
                self,
                "branches",
                tuple(
                    JoinBranch(plan=branch.plan, keys=tuple(branch.keys[index] for index in order))
                    if len(branch.keys) == len(order)
                    else branch
                    for branch in self.branches
                ),
            )

        # One branch is a single-mart plan, which needs no join node at all,
        # and zero is a join over nothing that `check` would then report as
        # authorized — the same shape as a proof resting on no facts.
        if len(self.branches) < 2:
            msg = (
                f"a branch join needs at least two branches, got {len(self.branches)} — "
                "one branch is a plan, not a join (RFC 0041 §3)"
            )
            raise ValueError(msg)

        # R010's content is *structural*: one row per key because of the
        # aggregate beneath. A branch that does not end in an aggregate over
        # the join keys makes that sentence false while the proof beside it
        # still reads as closed — the node has to require the structure it
        # claims, or the claim is decoration (RFC 0041 D2).
        #
        # The **last** aggregate, and its column *names*. An earlier one says
        # nothing about the branch's output: an aggregate to the keys followed
        # by one to a coarser grain leaves a relation unique at neither. And a
        # count of columns is not identity — a branch grouped by two unrelated
        # columns counts the same as one grouped by the keys, and the join
        # would then match rows that share nothing (logs/T-0026.md, D-174).
        unaggregated = [
            index for index, branch in enumerate(self.branches) if not self._ends_at(branch)
        ]

        if unaggregated:
            msg = (
                f"branch(es) {unaggregated} do not end in an aggregate to their own names "
                f"for the {len(self.keys)} join key(s), so they are not unique at the "
                "result grain and R010 would be asserting it about a plan that does not "
                "do it (RFC 0041 D2)"
            )
            raise ValueError(msg)

    # ....................... #

    def _ends_at(self, branch: JoinBranch) -> bool:
        """Whether ``branch`` is unique at its own names for the join keys."""

        aggregates = [node for node in branch.plan.nodes if isinstance(node, Aggregate)]

        return (
            len(branch.keys) == len(self.keys)
            and bool(aggregates)
            and aggregates[-1].dimensions == tuple(sorted(branch.keys))
        )

    # ....................... #

    @property
    def multiplies(self) -> bool:
        return False

    # ....................... #

    @property
    def claims(self) -> bool:
        return True

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "node": "join_aggregates",
            "keys": list(self.keys),
            "branches": [
                {"keys": list(branch.keys), **branch.plan.document()} for branch in self.branches
            ],
            "proof": self.proof.document() if self.proof is not None else None,
        }

    # ....................... #

    def render(self) -> str:
        joined = ", ".join(self.keys) or "total"
        return f"JoinAggregates({len(self.branches)} branches on {joined})"


# ....................... #

#: The node vocabulary, closed. RFC 0040 §4 also lists `PreservingJoin` and
#: `ConvertUnit`; neither exists yet — the first would join *unaggregated*
#: rows, which RFC 0041 D10 keeps refused, and the second has no owner since
#: RFC 0038 retired without it (RFC 0066 §8). :class:`Compute` is the sixth
#: kind, :class:`Reduce` the seventh, :class:`Window` the eighth and
#: :class:`Offset` the ninth (RFC 0066 §5.2-§5.6).
PlanNode = Scan | Filter | Aggregate | Project | JoinAggregates | Compute | Reduce | Window | Offset


@dataclass(frozen=True, slots=True)
class SemanticPlan:
    """A validated plan: what to compute, and on what authority.

    Constructed only after every obligation is proven — a list that grew from
    one node to six as the vocabulary did, and that still contains nothing
    multiplicity-changing, since a pre-joined mart introduces none. :meth:`check`
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
        """D2: every node that makes a semantic claim carries a **closed**
        proof of it.

        Two kinds of node do. A multiplicity-changing one, because it can
        invent rows — that is D2 as written, and it is vacuous here, since no
        node type in this vocabulary can multiply. And a node that *claims*:
        an :class:`Aggregate`, because rolling measures up to a grain is the
        claim this compiler exists to get right, and a
        :class:`JoinAggregates`, because "each side is unique at the key" is
        the whole reason its output is not a fan-out. D2's sentence names the
        first; the second is the same rule reaching the nodes a plan actually
        builds, rather than a rule that waits for a phase to become true
        (logs/T-0021.md, D-124).

        Asked of the node as a property rather than by listing node types
        here. A membership test over a closed vocabulary is right until the
        vocabulary gains a member, and the member it silently exempts is the
        one nobody remembered to add — which for a join node is the fan-out
        itself (RFC 0041 D14).

        **Closed, not merely present.** A proof resting on a heuristic or
        unknown leaf is a derivation nobody stands behind, and accepting one
        because it is not ``None`` reads the field for its existence instead
        of its content — the same shape as trusting a refusal because an
        exception object was constructed.

        The emptiness check is not vacuous and is not decoration: an empty
        sequence satisfies every "for all nodes" rule perfectly, so without it
        a plan that computes nothing is a plan this method calls valid.
        """
        if not self.nodes:
            msg = (
                "a plan with no nodes computes nothing — `check` would pass over an empty "
                "sequence and report it valid, which is the same shape as a proof resting "
                "on no facts (RFC 0040 D2)"
            )
            raise ValueError(msg)

        # R014 premises on the aggregate beneath, so a `Compute` with nothing
        # aggregated above it is claiming an ordering that did not happen —
        # the same reason `JoinAggregates` requires its branches to end in an
        # aggregate rather than trusting the proof beside it (RFC 0041 D2).
        reduced = False

        for node in self.nodes:
            if isinstance(node, Aggregate | JoinAggregates):
                reduced = True
            elif isinstance(node, Compute | Window | Offset) and not reduced:
                msg = (
                    f"{node.render()} runs before anything is aggregated, so the ordering "
                    "it is authorized for did not happen — a row-level expression or "
                    "window aggregated afterwards is a different number, and a shifted "
                    "read of unaggregated rows is not the measure it names "
                    "(RFC 0066 §5.2, §5.4, §5.6)"
                )
                raise ValueError(msg)

        unauthorized = [
            node.render()
            for node in self.nodes
            if node.multiplies or node.claims
            if not ((proof := getattr(node, "proof", None)) is not None and proof.closed)
        ]

        if unauthorized:
            msg = (
                f"plan node(s) claim without a closed proof: {unauthorized} — an aggregate "
                "or a duplicating join whose authorization is missing, or rests on a leaf "
                "nothing closes, is invalid IR rather than merely unexplained (RFC 0040 D2)"
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
        """Every proof this plan rests on, in node order — a branch join's
        own first, then each branch's, depth first.

        Reaching into branches rather than stopping at the top level: a
        composed plan's authorization is mostly *inside* it, and a reader
        counting the proofs of a two-branch plan and finding one has been told
        the branches rest on nothing.
        """

        found: list[Proof] = []

        for node in self.nodes:
            if (proof := getattr(node, "proof", None)) is not None:
                found.append(proof)
            for branch in getattr(node, "branches", ()):
                found.extend(branch.plan.proofs)

        return tuple(found)

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
