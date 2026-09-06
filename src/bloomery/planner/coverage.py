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
from bloomery.ir import Additivity, Cardinality, Layer
from bloomery.marts import DATE_BUCKETS
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import TimeGrain, clause_predicates
from bloomery.semantic import Proof, RefusalReason, grain_of, prove_rollup

if TYPE_CHECKING:
    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.policy import RowPolicy
    from bloomery.planner.request import MetricRequest

# ----------------------- #

__all__ = [
    "Coverage",
    "check",
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

    if metric.additivity is Additivity.NON_ADDITIVE:
        if metric.ratio is None:  # pragma: no cover — guardrails refuse this at compile
            msg = (
                f"non-additive metric {metric.name!r} carries neither a ratio nor a derived "
                "decomposition — the guardrail stage should have refused it (RFC 0006 D6)"
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


def _covering_mart(ir: ProjectIR, request: MetricRequest, naming: NamingPolicy) -> MartIR:
    """One mart carrying every required measure, or ``UnreachableAtGrain``
    with the per-metric grain/mart table (RFC 0011 §5.3)."""
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

    marts = {owner.name for _grain, owner in entries.values()}

    if len(marts) > 1:
        listed = sorted(entries.items())
        width = max(len(measure) for measure, _ in listed)
        names = ", ".join(measure for measure, _ in listed)
        lines = [f"metrics {{{names}}} live on different grains"]
        lines.extend(
            f"  {measure:<{width}} → grain: {grain} (mart: {_gold_relation(owner, naming)})"
            for measure, (grain, owner) in listed
        )
        lines.append(f"  {_REMEDIATION}")
        # The same table the message renders, as data (RFC 0020 §5.4): one
        # entry per required measure, naming the mart that *does* serve it and
        # the grain it does so at. ``mart`` is the logical name rather than the
        # gold relation the sentence quotes — that is the identity a caller
        # acts on, and the one ``QueryPlan.mart`` already reports.
        raise UnreachableAtGrain(
            "\n".join(lines),
            covering_marts=tuple(
                MartCoverage(mart=owner.name, metric=measure, grain=grain)
                for measure, (grain, owner) in listed
            ),
        )

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
        (candidate.source_entity, candidate.source_column)
        for candidate in other.columns
        if candidate.name == column
    }
    # Requestable names only. A mart may flatten a column without exposing it
    # as a dimension — join keys never double as one — and naming one of those
    # would answer a refusal with a request that is refused too.
    requestable = {dimension.column for dimension in mart.dimensions}

    return next(
        (
            candidate.name
            for candidate in sorted(mart.columns, key=lambda item: item.name)
            if candidate.name in requestable
            and (candidate.source_entity, candidate.source_column) in origin
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
    )


# ....................... #


def check(ir: ProjectIR, request: MetricRequest, *, naming: NamingPolicy) -> str:
    """The R3 entry point: the name of the single mart able to answer
    ``request``, or a typed refusal (RFC 0013 D6 — refuse before delegating)."""

    return resolve_request(ir, request, naming=naming).mart.name
