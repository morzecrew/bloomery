"""Mart-coverage precheck (RFC 0013 §5.4, R3 — RFC 0011's refusal policy,
preserved): every request is checked against the IR **before** anything is
delegated to MetricFlow. MetricFlow would happily plan a multi-hop join
across semantic models; the mart design (RFC 0010) says a cross-grain
request is *refused*, not silently answered — refuse-don't-guess, enforced
twice (here first, MetricFlow's resolver second).

Rules, in order:

1. every requested metric exists (``UnknownMember`` with a did-you-mean);
   a non-additive ratio requires its component measures, and a derived metric
   requires whatever its inputs need, transitively (RFC 0034 §8);
2. all required measures live on **one** mart — ownership by the exact rule
   the emitter placed measures with (cheapest ``cost_hint``, ties
   lexicographic — :func:`bloomery.emit.metricflow.measure_owners`), so
   emitter and planner cannot disagree; zero candidates or a split is
   ``UnreachableAtGrain`` naming the per-metric grain/mart conflict
   (RFC 0011 §5.3's exact message shape);
3. every requested, filtered, and policy dimension is flattened on the
   covering mart: bare column names resolve directly, an unqualified bucket
   (``month``) resolves through the mart's single date role or refuses with
   ``AmbiguousDimension`` naming the roles (D3 shape), and the request
   ``time_grain`` re-buckets date-role dimensions (``ordered_day`` +
   ``MONTH`` → ``ordered_month``).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from bloomery.emit.lower import measure_owners
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    MartCoverage,
    PlannerError,
    UnknownMember,
    UnreachableAtGrain,
    guaranteed,
)
from bloomery.ir import COMPUTED, Additivity, Cardinality, Layer, SqlExpr
from bloomery.marts import DATE_BUCKETS
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import TimeGrain, clause_predicates
from bloomery.semantic import Proof, RefusalReason, grain_of, prove_rollup

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.policy import RowPolicy
    from bloomery.planner.request import MetricRequest

# ----------------------- #

__all__ = [
    "Coverage",
    "Projected",
    "check",
    "composed_keys",
    "composed_projection",
    "resolve_branches",
    "resolve_request",
]

_REMEDIATION = (
    "Summing across grains would double-count. Request them separately,\n"
    "  or define a mart at the shared grain."
)


@dataclass(frozen=True, slots=True)
class Coverage:
    """The precheck's product: the single covering mart and every dimension
    reference resolved against it (request order preserved).

    ``filter_dimensions`` holds one inner tuple per filter *clause*
    (RFC 0015 D-Q3), pairing positionally with that clause's predicates —
    a bare ``Predicate`` clause yields a 1-tuple, an ``AnyOf`` group one
    entry per member."""

    mart: MartIR
    dimensions: tuple[ResolvedDimension, ...]
    filter_dimensions: tuple[tuple[ResolvedDimension, ...], ...]
    policy_dimension: ResolvedDimension | None
    #: The metrics this mart is asked for, in request order. One coverage is
    #: one branch (RFC 0041 D11), and a branch that did not carry its own
    #: metrics would leave the planner re-deriving the partition it was just
    #: handed — two answers to "which mart serves this measure" is the
    #: divergence D11 exists to prevent.
    #:
    #: These are the request's own metrics wherever a metric is a stored
    #: measure, and its **components** where it is computed above the join
    #: (RFC 0041 D3): a branch is asked for `revenue`, never for the
    #: `revenue_per_item` the wrapper divides to get.
    metrics: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class Projected:
    """One requested metric, and where the composed statement gets it from.

    A stored measure is projected from the branch that carries it and has no
    ``expr``. Anything else is computed **above** the join (RFC 0041 D3), from
    components each branch aggregated on its own — which is the whole reason
    the ordering in D1 is locked: `SUM(a)/SUM(b)` and a row-level `a/b`
    aggregated afterwards are different numbers.

    ``inputs`` pairs the alias ``expr`` references with the component metric a
    branch was asked for. For a ratio the two are the same name; for an
    RFC 0034 ``derived:`` metric they differ, because the expression was
    authored against aliases.
    """

    name: str
    inputs: tuple[tuple[str, str], ...] = ()
    expr: SqlExpr | None = None

    # ....................... #

    @property
    def components(self) -> tuple[str, ...]:
        """The component metrics a branch has to produce.

        A stored measure has no ``inputs`` and answers with its own name,
        because that is what a branch is asked for. The empty case is decided
        here rather than inherited: a computed metric always has inputs — a
        ratio has two and RFC 0034 gives ``inputs:`` a ``min_length=1`` — so
        ``inputs`` being empty means "stored" and nothing else, and the day
        that stops being true this reads as a branch asked for the metric it
        was supposed to compute.
        """

        if not self.inputs:
            return (self.name,)

        return tuple(metric for _alias, metric in self.inputs)


# ....................... #


def _closest(name: str, known: list[str]) -> str | None:
    """The one known name close enough to be worth suggesting, or ``None``."""
    matches = difflib.get_close_matches(name, known, n=1)
    return matches[0] if matches else None


# ....................... #


def _did_you_mean(closest: str | None, known: list[str]) -> str:
    """The message suffix for a match :func:`_closest` already found.

    Takes the match rather than searching for it, so the sentence and
    :attr:`~bloomery.errors.UnknownMember.did_you_mean` are one computation
    read twice (RFC 0020 §5.4) rather than two searches that happen to agree.
    """

    return f"; did you mean {closest!r}?" if closest else f"; known: {known}"


# ....................... #


def _gold_relation(mart: MartIR, naming: NamingPolicy) -> str:
    namespace, relation = naming.relation(mart.name, Layer.GOLD)
    return f"{namespace}.{relation}"


# ....................... #


def _measures_of(ir: ProjectIR, metric: MetricIR, seen: set[str]) -> tuple[str, ...]:
    """The measures one metric needs, following decompositions (RFC 0011 D5).

    A ratio needs both components; a derived metric needs whatever its inputs
    need, transitively — a derived metric over a ratio over two simple metrics
    needs the two simple measures (RFC 0034 §8). ``seen`` bounds the walk: the
    resolution DAG is acyclic, so it can only be reached twice by a diamond,
    but a cycle that somehow arrived here would hang rather than refuse, and a
    planner that hangs is worse than one that is wrong.
    """

    if metric.name in seen:
        return ()

    seen.add(metric.name)

    if metric.derived is not None:
        return tuple(
            measure
            for input_ in metric.derived.inputs
            for measure in _measures_of(
                ir,
                guaranteed(
                    (m for m in ir.metrics if m.name == input_.metric),
                    expected=f"derived input {input_.metric!r} of metric {metric.name!r}",
                    by="reachability, which drops a metric whose inputs are unreachable",
                ),
                seen,
            )
        )

    if metric.additivity in COMPUTED:
        if metric.ratio is None:  # pragma: no cover — guardrails refuse this at compile
            msg = (
                f"{metric.additivity.value} metric {metric.name!r} carries neither a ratio "
                "nor a derived decomposition — the guardrail stage should have refused it "
                "(RFC 0006 D6)"
            )
            raise PlannerError(msg)
        return (metric.ratio.numerator, metric.ratio.denominator)

    return (metric.name,)


# ....................... #


def _required_measures(ir: ProjectIR, name: str) -> tuple[MetricIR, tuple[str, ...]]:
    """The metric named in the request and the measure names a mart must
    carry to serve it (a ratio needs both components — RFC 0011 D5)."""
    metric = next((m for m in ir.metrics if m.name == name), None)

    if metric is None:
        unreachable = next((u for u in ir.unreachable if u.name == name), None)
        if unreachable is not None:
            msg = (
                f"metric {name!r} is unreachable: leaves {list(unreachable.missing)} have "
                "no mapped derivation path (RFC 0005 §5.3) — map them before requesting it"
            )
            raise UnknownMember(msg)
        known = sorted(m.name for m in ir.metrics)
        closest = _closest(name, known)
        raise UnknownMember(
            f"unknown metric {name!r}{_did_you_mean(closest, known)}", did_you_mean=closest
        )

    return metric, _measures_of(ir, metric, set())


# ....................... #


def _owner_entries(
    ir: ProjectIR, request: MetricRequest, naming: NamingPolicy
) -> dict[str, tuple[str, MartIR]]:
    """Every measure this request needs, with its grain and the mart that owns
    it — ownership by the exact rule the emitter placed measures with.

    Split out of :func:`_covering_mart` so the partition RFC 0041 D11 asks for
    reads the same answer the single-mart precheck does. Two computations of
    "which mart serves this measure" is precisely the divergence D11 names,
    and it would appear here first as a plan whose branches disagree with the
    emitter about where a measure lives.
    """
    owners = measure_owners(ir)
    metrics_by_name = {m.name: m for m in ir.metrics}
    entries: dict[str, tuple[str, MartIR]] = {}  # measure -> (grain, owner)

    for requested in request.metrics:
        metric, required = _required_measures(ir, requested)
        shape = "derived metric" if metric.derived is not None else "ratio"
        for measure in required:
            owner = owners.get(measure)
            if owner is None:
                grain = metrics_by_name[measure].grain if measure in metrics_by_name else "?"
                suffix = (
                    ""
                    if measure == requested
                    else f" (a component of the requested {shape} {requested!r})"
                )
                msg = (
                    f"metric {measure!r}{suffix} (grain: {grain}) is served by no mart — "
                    "no mart lists it as a measure.\n"
                    f"  Define a mart at grain {grain!r} carrying it."
                )
                raise UnreachableAtGrain(msg)
            entries[measure] = (metrics_by_name[measure].grain, owner)

    return entries


# ....................... #


def _split_refusal(
    entries: dict[str, tuple[str, MartIR]], naming: NamingPolicy
) -> UnreachableAtGrain:
    """The cross-grain refusal, unchanged from RFC 0011 §5.3.

    Reached whenever the composed path declines — so a request that RFC 0041
    P1 cannot answer keeps the refusal and the class it had before this phase
    existed, which is what leaves the parity baseline able to say what P1
    actually converted (D16).
    """
    listed = sorted(entries.items())
    width = max(len(measure) for measure, _ in listed)
    names = ", ".join(measure for measure, _ in listed)
    lines = [f"metrics {{{names}}} live on different grains"]
    lines.extend(
        f"  {measure:<{width}} → grain: {grain} (mart: {_gold_relation(owner, naming)})"
        for measure, (grain, owner) in listed
    )
    lines.append(f"  {_REMEDIATION}")

    # The same table the message renders, as data (RFC 0020 §5.4): one entry
    # per required measure, naming the mart that *does* serve it and the grain
    # it does so at. ``mart`` is the logical name rather than the gold relation
    # the sentence quotes — that is the identity a caller acts on, and the one
    # ``QueryPlan.mart`` already reports.
    return UnreachableAtGrain(
        "\n".join(lines),
        covering_marts=tuple(
            MartCoverage(mart=owner.name, metric=measure, grain=grain)
            for measure, (grain, owner) in listed
        ),
    )


# ....................... #


def _covering_mart(ir: ProjectIR, request: MetricRequest, naming: NamingPolicy) -> MartIR:
    """One mart carrying every required measure, or ``UnreachableAtGrain``
    with the per-metric grain/mart table (RFC 0011 §5.3)."""
    entries = _owner_entries(ir, request, naming)

    if len({owner.name for _grain, owner in entries.values()}) > 1:
        raise _split_refusal(entries, naming)

    return guaranteed(
        iter(entries.values()),
        expected="at least one covering mart",
        by="MetricRequest.__post_init__, which refuses a request with no metrics",
    )[1]


# ....................... #


def _origin(mart: MartIR, column: str) -> str:
    """The entity a flattened column came from — which is not the carrying
    mart's grain whenever that mart flattened a join to reach it.

    `order_items` carries `order_customer_id` from `order`, so a rollup
    question about that column is a question about reaching `order`, and
    asking it about the carrier's grain would prove the wrong thing: a second
    mart at the *same* grain as the requester carries a foreign dimension, the
    reflexive rollup succeeds, and the refusal reports "safe, just flatten it"
    about a hop nobody proved (logs/T-0022.md, D-139).
    """

    return guaranteed(
        (candidate.source_entity for candidate in mart.columns if candidate.name == column),
        expected=f"a column backing dimension {column!r} of mart {mart.name!r}",
        by="the mart flattener, which builds every dimension from a column it flattened",
    )


# ....................... #


def _carried_elsewhere(ir: ProjectIR, mart: MartIR, name: str) -> tuple[MartIR, str] | None:
    """The first other mart flattening ``name``, with the entity that column
    came from, or ``None``.

    Sorted by mart name rather than taken in IR order: this decides which mart
    a refusal message names, and a message that depends on iteration order is
    one two runs can disagree about (RFC 0003).
    """

    return next(
        (
            (candidate, _origin(candidate, name))
            for candidate in sorted(ir.marts, key=lambda m: m.name)
            if candidate.name != mart.name
            and any(dimension.column == name for dimension in candidate.dimensions)
        ),
        None,
    )


# ....................... #


#: What a mart may flatten. `one_to_many` is refused by the mart flattener —
#: "flattening it multiplies the mart's own rows once per row" — so naming one
#: in a remediation would send an author to write a line the compiler rejects.
_FLATTENABLE: Final = (Cardinality.MANY_TO_ONE, Cardinality.ONE_TO_ONE)


def _same_source(mart: MartIR, other: MartIR, column: str) -> str | None:
    """What ``mart`` calls the column ``other`` calls ``column``, when both
    trace to one source column, or ``None``.

    A flattened join prefixes what it brings, so the same underlying column can
    sit on two marts under two names — `customer_id` on the mart based at
    `order`, `order_customer_id` on the one that joined to it. Naming the local
    spelling turns a refusal into a corrected request (logs/T-0022.md, D-142).
    """

    origin = {
        (candidate.source_entity, candidate.source_column, candidate.ref)
        for candidate in other.columns
        if candidate.name == column
    }
    # The `ref` and not the source column alone. A date role expands to six
    # columns over one source — `order_date`, `ordered_day`, `ordered_month`
    # and the rest — so provenance alone would answer a request for
    # `ordered_month` with `order_date`, which is a different grain and a
    # different number (logs/T-0022.md, D-144).
    #
    # Requestable names only. A mart may flatten a column without exposing it
    # as a dimension — join keys never double as one — and naming one of those
    # would answer a refusal with a request that is refused too.
    return next(
        (name for triple in sorted(origin, key=str) if (name := _column_with(mart, triple))),
        None,
    )


# ....................... #


def _column_with(mart: MartIR, triple: tuple[str, str, object]) -> str | None:
    """What ``mart`` calls the column with this provenance, or ``None``.

    Requestable names only. A mart may flatten a column without exposing it as
    a dimension — join keys never double as one — and naming one of those
    would answer a refusal with a request that is refused too.
    """

    requestable = {dimension.column for dimension in mart.dimensions}

    return next(
        (
            candidate.name
            for candidate in sorted(mart.columns, key=lambda item: item.name)
            if candidate.name in requestable
            and (candidate.source_entity, candidate.source_column, candidate.ref) == triple
        ),
        None,
    )


# ....................... #


#: How many routes are worth keeping. The question is "exactly one or not", so
#: a second witness answers it and every further one is a route nobody reads.
#: Keeping them all is the textbook way to turn a breadth-first search into an
#: exponential one: a diamond in the relationship graph doubles the paths held
#: at each level, and `seen` only prevents revisiting *between* levels
#: (logs/T-0022.md, D-143).
_WITNESSES: Final = 2


def _witness(paths: list[tuple[str, ...]], path: tuple[str, ...]) -> None:
    """Keep ``path`` while fewer than :data:`_WITNESSES` are held."""

    if len(paths) < _WITNESSES:
        paths.append(path)


# ....................... #


def _hops(ir: ProjectIR, source: str, target: str) -> tuple[str, ...]:
    """The relationships a mart based at ``source`` would flatten to reach
    ``target``, in the order they must be authored.

    A chain rather than an edge: marts flatten transitively, so
    `order_item -> order -> customer` is two `flatten:` lines and not a missing
    relationship. Telling an author to declare a direct edge they can already
    reach by composition is prescribing redundant modelling
    (logs/T-0022.md, D-141).

    Empty where no flattenable route exists, or where two shortest routes do —
    picking one of two sends the author to write the wrong line. Only
    `many_to_one` and `one_to_one` are walked: a rollup can be provable across
    the *inverse* of a `one_to_many` (RFC 0037 admits that direction, and only
    that one) while the mart flattener refuses to flatten it at all. Provable
    and flattenable are different questions, and a remediation answers the
    second (D-140).
    """

    edges: dict[str, list[tuple[str, str]]] = {}
    for relationship in sorted(ir.relationships, key=lambda item: item.name):
        if relationship.cardinality in _FLATTENABLE:
            edges.setdefault(relationship.from_entity, []).append(
                (relationship.name, relationship.to_entity)
            )

    reached: list[tuple[str, ...]] = []
    frontier: dict[str, list[tuple[str, ...]]] = {source: [()]}
    seen = {source}

    while frontier and not reached:
        following: dict[str, list[tuple[str, ...]]] = {}
        for entity, paths in frontier.items():
            for name, to_entity in edges.get(entity, ()):
                for path in paths:
                    step = (*path, name)
                    if to_entity == target:
                        _witness(reached, step)
                    elif to_entity not in seen:
                        _witness(following.setdefault(to_entity, []), step)
        seen.update(following)
        frontier = following

    return reached[0] if len(reached) == 1 else ()


# ....................... #


def _not_here(
    ir: ProjectIR, mart: MartIR, name: str, other: MartIR, origin: str
) -> UnreachableAtGrain:
    """The refusal for a dimension another mart carries and this one does not
    (RFC 0040 §11a P2, logs/T-0022.md D-135).

    The name is not unknown, so `UnknownMember` would be false about the one
    thing an author acts on: it would send them to declare a dimension that is
    already declared. What decides the message is whether the rollup from this
    mart's grain to that one's is provable — one line of spec fixes the first
    case, and nothing in the spec fixes the second the same way.

    Refuses either way. This phase adds no capability (D9); what it adds is a
    refusal that says which of the two situations the author is in.
    """

    keys = {entity.name: entity.key for entity in ir.entities}
    source, target = mart.grain, origin
    answer = (
        prove_rollup(grain_of(source, keys[source]), grain_of(target, keys[target]), ir)
        if source in keys and target in keys
        else None
    )
    carried = (
        f"at grain {target!r}"
        if other.grain == target
        else f"at grain {other.grain!r}, flattened from {target!r}"
    )
    lead = (
        f"dimension {name!r} is not on mart {mart.name!r}, which serves this request; "
        f"mart {other.name!r} carries it {carried}"
    )

    if isinstance(answer, Proof) and not answer.closed:  # pragma: no cover
        # A proof resting on a leaf nothing closes — a heuristic or an
        # unverified import — does not authorize "safe, just flatten it", which
        # is why this is tested before the branch that says so rather than
        # folded into it. Unreachable today and deliberately still written: every
        # basis a rollup rests on is `DECLARED` or `DERIVED`, which
        # `test_no_rollup_basis_carries_a_provenance_that_leaves_a_proof_open`
        # asserts, and RFC 0044's imported provenance is what makes it
        # reachable. The code is its own, because the repair is to verify the
        # imported fact rather than to edit a mart.
        msg = (
            f"{lead}, and the rollup from {source!r} to {target!r} rests on facts bloomery "
            f"cannot close, so it is not authorization for flattening the hop."
        )
        return UnreachableAtGrain(msg, refusal_reason="unverified")

    if isinstance(answer, Proof) and source == target:
        # The identity rollup, which proves trivially and involves no
        # relationship at all. Reaching the chain logic here asked the author
        # to declare an edge from an entity to itself (logs/T-0022.md, D-142).
        local = _same_source(mart, other, name)
        remedy = (
            f"ask for {local!r} instead — the same column, under the name this mart flattens it as"
            if local is not None
            else f"expose it on mart {mart.name!r}, which is built from {target!r} already"
        )
        msg = (
            f"{lead}, and {target!r} is this mart's own grain, so no relationship is "
            f"involved.\n  {remedy}."
        )
        return UnreachableAtGrain(msg, refusal_reason="not_flattened")

    if isinstance(answer, Proof):
        chain = _hops(ir, source, target)
        steps = " then ".join(f"`flatten: {{via: {step}}}`" for step in chain)
        via = (
            f"add {steps} to mart {mart.name!r}"
            + (" — chains flatten transitively, in authored order" if len(chain) > 1 else "")
            if chain
            else (
                f"declare a many_to_one or one_to_one relationship from {source!r} to "
                f"{target!r} and flatten it onto mart {mart.name!r} — no relationship this "
                f"mart could flatten reaches {target!r} today, so ask mart {other.name!r} "
                f"for the measure instead if it serves one"
            )
        )
        msg = (
            f"{lead}.\n"
            f"  Values at {source!r} roll up to {target!r} safely, so the column can be "
            f"flattened onto this mart at build time: {via}.\n"
            f"  bloomery does not join at plan time (RFC 0040 D3) — the join belongs to the "
            f"mart, where it is proven once instead of per request."
        )
        return UnreachableAtGrain(msg, refusal_reason="not_flattened")

    if answer is None:
        msg = (
            f"{lead}, and this project maps no entity for one of those grains, so no rollup "
            f"between them can be stated."
        )
        return UnreachableAtGrain(msg, refusal_reason=str(RefusalReason.UNKNOWN_GRAIN))

    obligations = "\n".join(
        f"  required: {obligation.required}"
        + (f"\n  found:    {obligation.found}" if obligation.found else "")
        for obligation in answer.obligations
    )
    remedy = f"\n  Fix: {answer.remediation}" if answer.remediation else ""
    msg = (
        f"{lead}, and values at {source!r} cannot be rolled up to {target!r} "
        f"({answer.reason}).\n{obligations}{remedy}"
    )

    return UnreachableAtGrain(msg, refusal_reason=str(answer.reason))


# ....................... #


def _resolve_dimension(
    mart: MartIR, name: str, *, apply_grain: TimeGrain | None, ir: ProjectIR
) -> ResolvedDimension:
    """One dimension reference against the covering mart's flattened columns
    (RFC 0011 D6 — role-playing needs no planner logic beyond naming)."""
    refs = {dimension.column: dimension.ref for dimension in mart.dimensions}
    ref = refs.get(name)

    if ref is None:
        if name in DATE_BUCKETS:
            roles = sorted({r.role for r in refs.values() if r.role is not None})
            if len(roles) > 1:
                options = " or ".join(f"'{role}_{name}'" for role in roles)
                msg = f"{name!r} has roles {roles}. Use {options}."
                raise AmbiguousDimension(msg)
            if len(roles) == 1:
                return _resolve_dimension(
                    mart, f"{roles[0]}_{name}", apply_grain=apply_grain, ir=ir
                )
        elsewhere = _carried_elsewhere(ir, mart, name)
        if elsewhere is not None:
            raise _not_here(ir, mart, name, *elsewhere)

        known = sorted(refs)
        closest = _closest(name, known)
        msg = f"unknown dimension {name!r} on mart {mart.name!r}{_did_you_mean(closest, known)}"
        raise UnknownMember(msg, did_you_mean=closest)

    if ref.role is None:
        return ResolvedDimension(name=name)

    grain = TimeGrain(ref.dimension)

    if apply_grain is not None and apply_grain is not grain:
        rebucketed = f"{ref.role}_{apply_grain.value}"
        if rebucketed not in refs:
            msg = (
                f"time_grain {apply_grain.value!r} has no flattened bucket on mart "
                f"{mart.name!r} — date roles expand to {list(DATE_BUCKETS)} (RFC 0010 D4)"
            )
            raise InvalidRequest(msg)
        return ResolvedDimension(name=rebucketed, role=ref.role, grain=apply_grain)

    return ResolvedDimension(name=name, role=ref.role, grain=grain)


# ....................... #


def resolve_request(
    ir: ProjectIR,
    request: MetricRequest,
    *,
    naming: NamingPolicy,
    policy: RowPolicy | None = None,
) -> Coverage:
    """The full precheck: covering mart plus every dimension reference —
    requested, filtered, and policy — resolved against it.

    The request ``time_grain`` re-buckets *requested* date-role dimensions
    only; filter and policy dimensions keep the bucket they name (a filter on
    ``ordered_day`` stays daily under a monthly grouping).
    """
    mart = _covering_mart(ir, request, naming)
    dimensions = tuple(
        _resolve_dimension(mart, name, apply_grain=request.time_grain, ir=ir)
        for name in request.dimensions
    )
    filter_dimensions = tuple(
        tuple(
            _resolve_dimension(mart, predicate.dimension, apply_grain=None, ir=ir)
            for predicate in clause_predicates(clause)
        )
        for clause in request.filters
    )
    policy_dimension = (
        _resolve_dimension(mart, policy.dimension, apply_grain=None, ir=ir)
        if policy is not None
        else None
    )
    return Coverage(
        mart=mart,
        dimensions=dimensions,
        filter_dimensions=filter_dimensions,
        policy_dimension=policy_dimension,
        metrics=tuple(request.metrics),
    )


# ....................... #


def _candidate_triples(ir: ProjectIR, name: str) -> list[tuple[str, str, object]]:
    """Every provenance any mart publishes under ``name``, sorted.

    Sorted by the triple's text rather than left as a set: the order decides
    which candidate wins a tie below, and a set's iteration order would make
    that depend on the hash seed (RFC 0003).
    """

    return sorted(
        {
            triple
            for mart in ir.marts
            if any(dimension.column == name for dimension in mart.dimensions)
            if (triple := _provenance(mart, name)) is not None
        },
        key=str,
    )


# ....................... #


def _shared_provenance(
    ir: ProjectIR, marts: Sequence[MartIR], name: str
) -> tuple[str, str, object] | None:
    """The one provenance every branch can reach under ``name``, or ``None``.

    Every mart that publishes a dimension called ``name`` offers a candidate —
    `region` may be `order.region` on one mart and `customer.region` on another
    — and a branch can reach a candidate when it holds a requestable column of
    that provenance under any spelling. The answer is the candidate **all**
    branches reach, and only if exactly one does.

    Computed across the branches rather than read off whichever mart sorts
    first. The first-mart reading let a mart that is not in the request decide
    what the request meant: with `region` published by an unrelated mart from
    `customer.region`, one branch translated to its customer column while
    another kept its own `order.region` column, and the two were joined on
    different things until the identity check refused the pair. None is
    returned where the candidates disagree, and the ordinary per-branch
    resolution then raises the ordinary refusal.
    """

    reachable = [
        triple
        for triple in _candidate_triples(ir, name)
        if all(_column_with(mart, triple) is not None for mart in marts)
    ]
    # A branch that publishes the requested *spelling* is the caller's most
    # likely meaning, and preferring it is what keeps `region` meaning what the
    # mart serving the request means by it when an unrelated mart publishes a
    # `region` of its own. Where two branches publish the name and disagree
    # about it, there is no such preference — that is the collision D12
    # refuses, and it is left to the identity check to say so.
    published = [
        triple for triple in reachable if any(_provenance(mart, name) == triple for mart in marts)
    ]

    if len(published) == 1:
        return published[0]

    return reachable[0] if len(reachable) == 1 else None


# ....................... #


def _resolve_branch_dimension(
    mart: MartIR,
    name: str,
    *,
    target: tuple[str, str, object] | None,
    apply_grain: TimeGrain | None,
    ir: ProjectIR,
) -> ResolvedDimension:
    """One requested dimension against **a branch's** mart, by identity rather
    than by name (RFC 0041 D12).

    A flattened join prefixes what it brings, so one dimension has one name per
    mart that reaches it: `region` on the mart based at `order`, and
    `order_region` on the one that flattened its way there. Asking each branch
    for the requested spelling would refuse every branch but the one the caller
    happened to name — and answering with the wrong column would be worse.

    Identity is the provenance triple :func:`_same_source` already compares for
    P2's remediations, so the same rule decides "these are one dimension" here
    and "ask for this name instead" there. Where no branch-local column shares
    that provenance, the ordinary resolution runs and raises the ordinary
    refusal: this function widens what resolves, never what is accepted
    unproven.

    ``target`` is the provenance **every** branch agreed on, computed once by
    :func:`_shared_provenance` rather than discovered per branch. Discovering
    it per branch meant asking the first *other* mart carrying the requested
    name what it meant by it, and an unrelated mart that sorts earlier then
    decided the answer for everybody: two branches resolved to columns of
    different origins and only the identity check downstream noticed. Anchored
    on one triple, the branches cannot disagree in the first place.
    """

    if target is not None and (local := _column_with(mart, target)) is not None:
        return _resolve_dimension(mart, local, apply_grain=apply_grain, ir=ir)

    return _resolve_dimension(mart, name, apply_grain=apply_grain, ir=ir)


# ....................... #


def _provenance(mart: MartIR, column: str) -> tuple[str, str, object] | None:
    """The provenance triple behind one of a mart's columns, or ``None``.

    The same triple :func:`_same_source` compares — source entity, source
    column, and the ref that separates a date role's six buckets from each
    other and from the column they expand.
    """

    return next(
        (
            (candidate.source_entity, candidate.source_column, candidate.ref)
            for candidate in mart.columns
            if candidate.name == column
        ),
        None,
    )


# ....................... #


def _not_one_dimension(
    name: str, resolved: Sequence[tuple[MartIR, ResolvedDimension]]
) -> UnreachableAtGrain:
    """The refusal for a name every branch has and no two branches mean the
    same thing by (RFC 0041 D12, D5).

    The dangerous case, and the reason identity is checked on every branch
    rather than only where a name had to be translated: `order_id` is a column
    of the mart based at `order` and *also* of the mart based at `order_item`,
    where it is the foreign key pointing at the first. Joining branch
    aggregates on those two would group one measure by an order and the other
    by the order its line belongs to — plausible, sometimes even equal, and
    not something anybody proved.
    """

    listed = "\n".join(
        f"  {mart.name:<20} → {dimension.name} (from "
        f"{(_provenance(mart, dimension.name) or ('?', '?', None))[0]}."
        f"{(_provenance(mart, dimension.name) or ('?', '?', None))[1]})"
        for mart, dimension in resolved
    )
    msg = (
        f"dimension {name!r} is carried by every mart this request needs, and they do not "
        f"mean the same column by it:\n{listed}\n"
        "  Two columns are the same dimension when they come from the same source column, "
        "not when they share a name (RFC 0041 D12).\n"
        "  Request the measures separately, or flatten one shared dimension onto both marts."
    )

    return UnreachableAtGrain(msg)


# ....................... #


def _projected(ir: ProjectIR, name: str) -> Projected | None:
    """How a composed statement would produce one requested metric, or
    ``None`` where it could not produce it at all.

    Shape only — nothing here knows which mart owns anything. Three forms come
    back with an expression the wrapper evaluates above the join (D3), and one
    stored measure comes back bare:

    * an RFC 0034 ``derived:`` metric carries its own expression over its
      inputs' aliases, and is the general case P2 admits (logs/T-0027.md,
      D-179);
    * a ratio is that with the expression fixed — ``num / NULLIF(den, 0)``,
      which is what the Cube emitter already writes for the same metric;
    * a stored additive measure needs no expression, and the branch that
      carries it projects it under its own name.

    ``None`` for everything else, and the request then keeps the cross-grain
    refusal it had. A **cumulative** metric is a window rather than a rollup;
    a metric with its own ``filter`` narrows one branch and the composed
    statement has no way to say that it did; and a derived input carrying a
    time **offset** names a shifted grain no branch produced, so evaluating
    the expression over the unshifted column would label the wrong number with
    the right name (logs/T-0027.md, D-180).
    """

    metric = next((candidate for candidate in ir.metrics if candidate.name == name), None)

    if metric is None or metric.cumulative is not None or metric.filter:
        return None

    if metric.derived is not None:
        if any(
            input_.offset_window is not None or input_.offset_to_grain is not None
            for input_ in metric.derived.inputs
        ):
            return None

        return Projected(
            name=name,
            inputs=tuple((input_.alias, input_.metric) for input_ in metric.derived.inputs),
            expr=metric.derived.expr,
        )

    if metric.additivity in COMPUTED:
        if metric.ratio is None:  # pragma: no cover — the additivity guardrail refuses it
            return None

        numerator, denominator = metric.ratio.numerator, metric.ratio.denominator

        return Projected(
            name=name,
            inputs=((numerator, numerator), (denominator, denominator)),
            expr=SqlExpr(f"{numerator} / NULLIF({denominator}, 0)"),
        )

    if metric.additivity is not Additivity.ADDITIVE:
        return None

    return Projected(name=name)


# ....................... #


def _homes(
    ir: ProjectIR, entries: dict[str, tuple[str, MartIR]], component: str
) -> set[str | None]:
    """The marts a component metric's leaf measures live on.

    One element means one branch answers the component whole, which is what
    the composed path requires: the wrapper's expression reads a component as
    a single column, and a component needing two branches would be a join
    inside a join (logs/T-0027.md, D-181). ``None`` in the set is a leaf no
    mart serves, which :func:`_owner_entries` has already refused for a
    requested metric and can still reach here through a component of one.
    """

    metric = next((candidate for candidate in ir.metrics if candidate.name == component), None)

    if metric is None:  # pragma: no cover — a component always names a real metric
        # `_projected` reads components off `metric.ratio` and
        # `metric.derived.inputs`, and both are checked against the metric set
        # when the project compiles — `_measures_of` asserts the same thing
        # with `guaranteed` on the way down. Kept because what holds it up is a
        # guardrail rather than anything here, and `{None}` refuses where a
        # `KeyError` two frames later would not say what went wrong.
        return {None}

    leaves = _measures_of(ir, metric, set())

    if not leaves:  # pragma: no cover — a decomposition always reaches a leaf
        return {None}

    return {None if (entry := entries.get(leaf)) is None else entry[1].name for leaf in leaves}


# ....................... #


def _not_on_every_branch(
    ir: ProjectIR, name: str, marts: Sequence[MartIR], *, kind: str
) -> UnreachableAtGrain:
    """The refusal for a restriction one branch can evaluate and another cannot
    (RFC 0041 D4, D5; logs/T-0027.md, D-176).

    Placing it on the branches that can is the outcome that returns a number:
    with a restriction on the orders mart alone, restricted revenue and
    unrestricted quantity meet at one key and the row reads as one filter
    applied throughout. So the whole request refuses, and the message names
    every branch and what it has, because the fix is a mart change rather than
    a request change.
    """

    candidates = _candidate_triples(ir, name)
    width = max(len(mart.name) for mart in marts)
    listed = "\n".join(
        f"  {mart.name:<{width}} → "
        + (
            local
            if (
                local := next(
                    (
                        found
                        for triple in candidates
                        if (found := _column_with(mart, triple)) is not None
                    ),
                    None,
                )
            )
            is not None
            else "not carried"
        )
        for mart in marts
    )

    msg = (
        f"{kind} dimension {name!r} is not carried by every mart this request needs:\n"
        f"{listed}\n"
        "  A restriction placed on some branches and not others narrows one measure and "
        "not the other, and the join reports the two side by side as though one "
        "restriction applied throughout (RFC 0041 D4, D5).\n"
        f"  Request the measures separately, or flatten {name!r} onto every mart above."
    )

    return UnreachableAtGrain(msg)


# ....................... #


def _composable(
    ir: ProjectIR,
    request: MetricRequest,
    entries: dict[str, tuple[str, MartIR]],
) -> bool:
    """Whether RFC 0041 P2 may answer this cross-mart request by composing
    branches, rather than refusing it as before.

    Two conditions now, where P1 had five. Filters, the row policy,
    ``order_by`` and ``limit`` are no longer among them — each has a place on
    the composed statement, and where a restriction cannot reach every branch
    the refusal is :func:`_not_on_every_branch`, which says which dimension
    rather than which grains.

    * **every requested metric has a projection** — it is a stored additive
      measure, or it decomposes into components the wrapper computes over
      (:func:`_projected`);
    * **every component is answered whole by one branch**, and is itself
      additive, unrestricted and non-cumulative. A component's own restriction
      would narrow one branch with nothing in the composed statement saying so,
      which is P1's rule applied one level down.

    The two halves of the second condition are not independent today, and the
    branch that says so is unreachable rather than merely untaken: a component
    needing two marts has to decompose, and a metric that decomposes is never
    ``ADDITIVE`` — the additivity guardrail refuses ``additivity: additive``
    beside a ``derived:`` block, and ``ratio`` beside anything else. So the
    additivity test above catches every spanning component first
    (logs/T-0027.md, finding 1).

    It stays, and :func:`_home` refuses the same shape loudly, because what
    holds it up is a rule in another package. Were that rule relaxed, dropping
    this line would not fail a test — it would place a component on whichever
    of its marts sorts first, and answer.
    """

    metrics_by_name = {metric.name: metric for metric in ir.metrics}

    for name in request.metrics:
        projection = _projected(ir, name)

        if projection is None:
            return False

        for component in projection.components:
            metric = metrics_by_name.get(component)

            if metric is None or metric.cumulative is not None or metric.filter:
                return False
            if metric.additivity is not Additivity.ADDITIVE:
                return False
            homes = _homes(ir, entries, component)

            if len(homes) != 1 or None in homes:  # pragma: no cover — see below
                return False

    return True


# ....................... #


def composed_projection(ir: ProjectIR, request: MetricRequest) -> tuple[Projected, ...]:
    """Every requested metric's projection, in request order.

    Public because the planner needs it and must not compute it a second way:
    :func:`resolve_branches` accepted the request on exactly these projections,
    so a planner deriving its own would be the second opinion RFC 0041 D11
    exists to prevent — one level up from the partition D11 is about.
    """

    return tuple(
        guaranteed(
            (found for found in (_projected(ir, name),) if found is not None),
            expected=f"a projection for requested metric {name!r}",
            by="resolve_branches, which keeps the cross-grain refusal for a metric with none",
        )
        for name in request.metrics
    )


# ....................... #


def composed_keys(request: MetricRequest, branches: Sequence[Coverage]) -> tuple[str, ...]:
    """What the composed statement calls each joined key.

    One dimension has one name per mart that reaches it — `tier` on the mart
    based at `customer`, `customer_tier` one hop away, `order_customer_tier`
    two — and the composed projection has to choose one (logs/T-0026.md,
    D-165). It takes **the name the caller asked for**: every branch's column
    is the same dimension by D12, so no branch's spelling is more the answer
    than another's, and the request's own name is the one the caller can
    predict.

    The exception is a date-role dimension, which is answered under its
    *effective* name — `ordered_month` for `ordered_day` under a monthly
    ``time_grain``, exactly as a single-mart plan answers it. Every branch
    agrees on that name when the composed path opens at all, since two marts
    reaching one date column through different roles have different
    provenance and D12 refuses them (logs/T-0026.md, D-169).

    Read from the resolutions rather than from the rendered columns: they are
    the same name — the bridge round-trips, which `test_names` pins — and
    computing it here is what lets the collision check below see the name the
    result will actually carry.
    """

    # The date-role arm cannot be taken by a composed request as the mart
    # grammar stands: a role may only name a column of its mart's base entity,
    # so two marts at different grains never publish one date column as a role,
    # and two roles of different origin are refused by D12 before they reach
    # here (logs/T-0027.md, finding 3). Kept because what forbids it is a rule
    # in the mart grammar rather than anything about this function, and because
    # its absence would answer under the wrong name rather than fail.
    return tuple(
        branches[0].dimensions[position].name
        if branches[0].dimensions[position].role is not None
        else name
        for position, name in enumerate(request.dimensions)
    )


# ....................... #


def _home(ir: ProjectIR, entries: dict[str, tuple[str, MartIR]], component: str) -> str:
    """The one mart answering a component whole, after :func:`_composable`.

    Exactly one, checked rather than taken. The obvious spelling — the first of
    the sorted names — answers for a component whose leaves span two marts by
    silently choosing one of them, and the composed statement would then read
    that component's column off a branch that computed half of it. Nothing
    downstream could tell (logs/T-0027.md, finding 1).
    """

    homes = sorted(name for name in _homes(ir, entries, component) if name is not None)

    if len(homes) != 1:
        msg = (
            f"component {component!r} is served by {homes or 'no mart'} — a component the "
            "composed statement reads as one column has to be aggregated by one branch "
            "(RFC 0041 D4)"
        )
        raise PlannerError(msg)

    return homes[0]


# ....................... #


def _one_dimension(name: str, resolved: Sequence[tuple[MartIR, ResolvedDimension]]) -> None:
    """Refuse unless every branch resolved the *same* dimension for one name.

    Run over every **requested** dimension, including the ones where the
    requested name resolved locally and no translation was needed. Checking
    only where a name had to be translated is the asymmetry that let
    `order_id` — a key on one mart and a foreign key on another — join two
    branches on different things (RFC 0041 D12).

    The restrictions are not run through it, and that is a difference in what
    is *known* rather than in what matters: a restriction whose provenance no
    branch shares is refused before any branch resolves it, so every branch
    takes the anchored path and there is nothing left to disagree about
    (logs/T-0027.md, finding 2).
    """

    provenances = {_provenance(mart, dimension.name) for mart, dimension in resolved}

    if len(provenances) > 1 or None in provenances:
        raise _not_one_dimension(name, resolved)


# ....................... #


def resolve_branches(
    ir: ProjectIR,
    request: MetricRequest,
    *,
    naming: NamingPolicy,
    policy: RowPolicy | None = None,
) -> tuple[Coverage, *tuple[Coverage, ...]]:
    """The precheck, widened to N branches (RFC 0041 D9, D11).

    One coverage for a request every measure of which lives on one mart —
    which is every request this planner answered before RFC 0041 — and one per
    owning mart otherwise, sorted by mart name so a composed plan and the SQL
    built from it read the branches in one order (RFC 0003).

    Each branch carries the restrictions the composed request applies, resolved
    against **its own** mart by provenance identity: a filter and the row
    policy reach every branch or the whole request refuses (RFC 0041 D4, D5;
    logs/T-0027.md, D-176). The policy reaching every branch is the merge
    -blocking half — a branch left unscoped answers from rows the caller may
    not read, and the join puts that number beside a scoped one.

    A cross-mart request the composed path cannot take keeps the refusal it
    had: :func:`_split_refusal` is the same message, the same class and the
    same ``covering_marts`` table as before this phase, so what these phases
    converted is a diff in the parity baseline rather than a number that moved
    (D16).
    """
    entries = _owner_entries(ir, request, naming)

    if len({owner.name for _grain, owner in entries.values()}) == 1:
        return (resolve_request(ir, request, naming=naming, policy=policy),)

    if not _composable(ir, request, entries):
        raise _split_refusal(entries, naming)

    by_mart: dict[str, MartIR] = {owner.name: owner for _grain, owner in entries.values()}
    ordered = [by_mart[name] for name in sorted(by_mart)]
    projections = composed_projection(ir, request)
    # Components rather than requested metrics: a branch is asked for `revenue`
    # and never for the ratio the wrapper divides to get (D3). Deduplicated in
    # request order, since a component may also be requested on its own.
    served: dict[str, tuple[str, ...]] = {
        name: tuple(
            dict.fromkeys(
                component
                for projection in projections
                for component in projection.components
                if _home(ir, entries, component) == name
            )
        )
        for name in sorted(by_mart)
    }

    # One provenance per requested dimension, agreed across the branches before
    # any of them resolves — see :func:`_shared_provenance`.
    targets = [_shared_provenance(ir, ordered, dimension) for dimension in request.dimensions]
    # The same, for every dimension a restriction names. Refused up front where
    # no one provenance reaches every branch, because unlike a requested
    # dimension there is no per-branch resolution worth attempting: a filter
    # one branch cannot evaluate is not a filter placed elsewhere, it is a
    # request with no consistent meaning.
    restrictions: dict[str, tuple[str, str, object]] = {}

    for kind, name in [
        *(
            ("filter", predicate.dimension)
            for clause in request.filters
            for predicate in clause_predicates(clause)
        ),
        *((("row policy", policy.dimension),) if policy is not None else ()),
    ]:
        if name in restrictions:
            # A repeat, not a conflict: `_shared_provenance` is pure in its
            # arguments, so the second lookup would return the first's answer.
            # What the skip decides is which `kind` the refusal names when a
            # dimension both a filter and the policy mention reaches no branch
            # — the first mention, which is the filter.
            continue
        target = _shared_provenance(ir, ordered, name)
        if target is None:
            raise _not_on_every_branch(ir, name, ordered, kind=kind)
        restrictions[name] = target

    def _restricted(mart: MartIR, name: str) -> ResolvedDimension:
        return _resolve_branch_dimension(
            mart, name, target=restrictions[name], apply_grain=None, ir=ir
        )

    branches = tuple(
        Coverage(
            mart=by_mart[name],
            dimensions=tuple(
                _resolve_branch_dimension(
                    by_mart[name],
                    dimension,
                    target=target,
                    apply_grain=request.time_grain,
                    ir=ir,
                )
                for dimension, target in zip(request.dimensions, targets, strict=True)
            ),
            filter_dimensions=tuple(
                tuple(
                    _restricted(by_mart[name], predicate.dimension)
                    for predicate in clause_predicates(clause)
                )
                for clause in request.filters
            ),
            policy_dimension=(
                _restricted(by_mart[name], policy.dimension) if policy is not None else None
            ),
            metrics=served[name],
        )
        for name in sorted(by_mart)
    )

    # Identity is checked on **every** branch, including the ones where the
    # requested name resolved locally and no translation was needed. A name
    # two marts both carry is the case that most needs the check rather than
    # the case that can skip it (RFC 0041 D12).
    for position, requested in enumerate(request.dimensions):
        _one_dimension(
            requested, [(branch.mart, branch.dimensions[position]) for branch in branches]
        )

    # The restrictions need no such check, and one was written and removed
    # rather than left reading as protection. Their provenance is agreed
    # *before* resolution — a restriction with no triple every branch reaches
    # was already refused above — so `_resolve_branch_dimension` takes the
    # anchored path on every branch and cannot produce two origins. The
    # requested dimensions differ precisely because their anchor may be `None`,
    # and the per-branch fallback is then what can disagree (logs/T-0027.md,
    # finding 2).

    # A composed statement projects a key under the name the result will carry
    # (logs/T-0026.md, D-165), so a name that is also a requested metric would
    # be projected twice under one alias and `ColumnDescriptor.sql_alias` — the
    # binding contract since RFC 0018 D4 — would name two columns.
    # `MetricRequest` refuses duplicates within each tuple and cannot see
    # across them. Compared against the **effective** key names rather than the
    # requested ones, because a date role is answered under its re-bucketed
    # name: `ordered_day` under a monthly `time_grain` comes back as
    # `ordered_month`, and a metric of that name collides with a request that
    # never mentions it. A single-mart plan is unaffected, because there the
    # dimension keeps its entity-qualified alias.
    collisions = sorted(set(request.metrics) & set(composed_keys(request, branches)))

    if collisions:
        msg = (
            f"{collisions} would name both a metric and a dimension of this answer: a "
            "cross-grain answer projects a dimension under the name the result carries, "
            "so it would hold two columns with one name and binding by `sql_alias` could "
            "not tell them apart.\n  Rename one, or request them separately."
        )
        raise InvalidRequest(msg)

    # Rebuilt as a non-empty tuple rather than returned as-is: the return type
    # says a branch always comes back, which is what lets a caller read
    # `branches[0]` without a guard for a case `by_mart` cannot produce.
    return (branches[0], *branches[1:])


# ....................... #


def check(ir: ProjectIR, request: MetricRequest, *, naming: NamingPolicy) -> str:
    """The R3 entry point: the name of the single mart able to answer
    ``request``, or a typed refusal (RFC 0013 D6 — refuse before delegating)."""

    return resolve_request(ir, request, naming=naming).mart.name
