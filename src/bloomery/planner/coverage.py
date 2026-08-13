"""Mart-coverage precheck (RFC 0013 §5.4, R3 — RFC 0011's refusal policy,
preserved): every request is checked against the IR **before** anything is
delegated to MetricFlow. MetricFlow would happily plan a multi-hop join
across semantic models; the mart design (RFC 0010) says a cross-grain
request is *refused*, not silently answered — refuse-don't-guess, enforced
twice (here first, MetricFlow's resolver second).

Rules, in order:

1. every requested metric exists (``UnknownMember`` with a did-you-mean);
   a non-additive ratio requires its component measures;
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
from typing import TYPE_CHECKING

from bloomery.emit.lower import measure_owners
from bloomery.errors import (
    AmbiguousDimension,
    InvalidRequest,
    PlannerError,
    UnknownMember,
    UnreachableAtGrain,
    guaranteed,
)
from bloomery.ir import Additivity, Layer
from bloomery.marts import DATE_BUCKETS
from bloomery.planner.names import ResolvedDimension
from bloomery.planner.request import TimeGrain, clause_predicates

if TYPE_CHECKING:
    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.naming import NamingPolicy
    from bloomery.planner.policy import RowPolicy
    from bloomery.planner.request import MetricRequest

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


def _did_you_mean(name: str, known: list[str]) -> str:
    matches = difflib.get_close_matches(name, known, n=1)
    return f"; did you mean {matches[0]!r}?" if matches else f"; known: {known}"


def _gold_relation(mart: MartIR, naming: NamingPolicy) -> str:
    namespace, relation = naming.relation(mart.name, Layer.GOLD)
    return f"{namespace}.{relation}"


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
        raise UnknownMember(f"unknown metric {name!r}{_did_you_mean(name, known)}")
    if metric.additivity is Additivity.NON_ADDITIVE:
        if metric.ratio is None:  # pragma: no cover — guardrails refuse this at compile
            msg = (
                f"non-additive metric {name!r} carries no ratio decomposition — "
                "the guardrail stage should have refused it (RFC 0006 D6)"
            )
            raise PlannerError(msg)
        return metric, (metric.ratio.numerator, metric.ratio.denominator)
    return metric, (name,)


def _covering_mart(ir: ProjectIR, request: MetricRequest, naming: NamingPolicy) -> MartIR:
    """One mart carrying every required measure, or ``UnreachableAtGrain``
    with the per-metric grain/mart table (RFC 0011 §5.3)."""
    owners = measure_owners(ir)
    metrics_by_name = {m.name: m for m in ir.metrics}
    entries: dict[str, tuple[str, MartIR]] = {}  # measure -> (grain, owner)
    for requested in request.metrics:
        _metric, required = _required_measures(ir, requested)
        for measure in required:
            owner = owners.get(measure)
            if owner is None:
                grain = metrics_by_name[measure].grain if measure in metrics_by_name else "?"
                suffix = (
                    ""
                    if measure == requested
                    else f" (a component of the requested ratio {requested!r})"
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
        raise UnreachableAtGrain("\n".join(lines))
    return guaranteed(
        iter(entries.values()),
        expected="at least one covering mart",
        by="MetricRequest.__post_init__, which refuses a request with no metrics",
    )[1]


def _resolve_dimension(
    mart: MartIR, name: str, *, apply_grain: TimeGrain | None
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
                return _resolve_dimension(mart, f"{roles[0]}_{name}", apply_grain=apply_grain)
        known = sorted(refs)
        msg = f"unknown dimension {name!r} on mart {mart.name!r}{_did_you_mean(name, known)}"
        raise UnknownMember(msg)
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
        _resolve_dimension(mart, name, apply_grain=request.time_grain)
        for name in request.dimensions
    )
    filter_dimensions = tuple(
        tuple(
            _resolve_dimension(mart, predicate.dimension, apply_grain=None)
            for predicate in clause_predicates(clause)
        )
        for clause in request.filters
    )
    policy_dimension = (
        _resolve_dimension(mart, policy.dimension, apply_grain=None) if policy is not None else None
    )
    return Coverage(
        mart=mart,
        dimensions=dimensions,
        filter_dimensions=filter_dimensions,
        policy_dimension=policy_dimension,
    )


def check(ir: ProjectIR, request: MetricRequest, *, naming: NamingPolicy) -> str:
    """The R3 entry point: the name of the single mart able to answer
    ``request``, or a typed refusal (RFC 0013 D6 — refuse before delegating)."""
    return resolve_request(ir, request, naming=naming).mart.name
