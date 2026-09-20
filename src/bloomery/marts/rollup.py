"""Rollup lowering: ``lower_rollups(mart_set, draft) -> RollupLowering``
(S-0065/the-obligation, S-0065/phasing (P-2)).

A rollup is a mart at a coarser grain than one this project already builds.
This module resolves each declared one against the parent it names and, for
every measure it would carry, asks the obligation R013 states — and refuses
where the obligation does not discharge (D5, `LOCKED`).

Total, like :mod:`bloomery.marts.flatten`: it never raises. A rollup with any
violation contributes no :class:`~bloomery.ir.RollupIR` and its leaves batch
into the guardrail stage's single aggregate, so an author fixes a marts
document in one round-trip.

**Nothing here decides whether a rollup is *used*.** Row 14 (`LOCKED`) says a
rollup is never a measure owner and never a covering mart, and it holds because
:class:`~bloomery.ir.RollupIR` lands in ``ProjectIR.rollups`` rather than in
``ProjectIR.marts`` — the collection ``measure_owners`` and the planner's
covering-mart search both walk. There is no filter to keep in step here;
choosing to read a rollup instead of the detail is S-0054's job (§4).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from bloomery.errors import UnprovableRollup
from bloomery.ir import GrantsIR, Materialization, RollupIR, partition_specs
from bloomery.semantic import Refutation, prove_mart_rollup

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.ir import MartIR, MetricIR, ProjectIR
    from bloomery.spec.marts import MartSet, RollupMart

# ----------------------- #

__all__ = [
    "RollupLowering",
    "lower_rollups",
]


@dataclass(frozen=True, slots=True)
class RollupLowering:
    """The rollup resolver's product: cleanly lowered rollups (sorted by name)
    and every violation found, as guardrail leaves for the stage aggregate."""

    rollups: tuple[RollupIR, ...]
    violations: tuple[GuardrailError, ...]


# ....................... #


def _not_on_the_parent(
    name: str, rollup: RollupMart, parent: MartIR, path: str
) -> UnprovableRollup | None:
    """A measure the parent does not carry.

    Asked here rather than left to R013, because the obligation is asked with
    the rollup's own measure list and would therefore find every one of them
    "carried". A rollup aggregates the rows of one relation, and a measure that
    relation does not store is not one of them.
    """

    absent = tuple(sorted(set(rollup.measures) - set(parent.measures)))

    if not absent:
        return None

    msg = (
        f"rollup {name!r} carries {', '.join(absent)}, which mart {parent.name!r} does not. "
        "A rollup aggregates the rows of the mart it names, so it can only carry measures "
        f"that mart stores (S-0065/the-obligation). Fix: name the measure among {parent.name!r}'s "
        "measures, or drop it from the rollup"
    )

    return UnprovableRollup(msg, source_path=f"{path}.measures")


# ....................... #


def _refused(name: str, answer: Refutation, path: str) -> UnprovableRollup:
    """R013's refutation, as the guardrail leaf an author reads.

    The rendered proof form is not used: a refutation renders over several
    lines and every other leaf in this stage is one sentence, so the aggregate
    would read as two formats. What is kept is everything the four lines carry — the
    obligation, the reason code and the fix — in the shape
    ``resolve.build`` already uses for R009's refusal.
    """

    obligation = answer.obligations[0]
    fix = f" Fix: {answer.remediation}" if answer.remediation else ""

    msg = (
        f"rollup {name!r} is not provable: {obligation.found} (required: "
        f"{obligation.required}). A rollup is read instead of the detail table, so an "
        "unprovable one answers quickly and plausibly rather than failing (S-0065/D-5, "
        f"R013, {answer.reason}).{fix}"
    )

    return UnprovableRollup(msg, source_path=path)


# ....................... #


def _dropped_declaration(
    name: str, measure: str, metric: MetricIR, path: str
) -> UnprovableRollup | None:
    """A measure whose declaration a rollup's aggregate would silently drop.

    R013 asks the aggregation-class question and gets it right; two other
    declarations reach the same measure and neither is a class. A ``filter:``
    restricts the rows a metric aggregates, and a rollup's ``SUM(expr)`` over
    the parent aggregates all of them — the unrestricted number, under the
    restricted metric's name. A ``cumulative:`` window accumulates across rows
    at query time and is not an aggregate a ``GROUP BY`` can stand in for.

    Refused here rather than folded into R013 because both are questions about
    what an emitted aggregate can *carry*, and R013 is about whether the
    arithmetic is sound. Supporting the first means a third rendering of the
    metric-filter grammar — after Cube's and MetricFlow's — and
    ``metric_filter_sql`` says in its own docstring that two copies of an
    escaping rule is the defect this project keeps finding in itself
    (logs/T-0034.md).
    """

    dropped = (
        "a filter:, which restricts the rows it aggregates"
        if metric.filter
        else "a cumulative: window, which accumulates across rows at query time"
        if metric.cumulative is not None
        else ""
    )

    if not dropped:
        return None

    msg = (
        f"rollup {name!r} carries {measure!r}, which declares {dropped}. A rollup builds its "
        "measure with one aggregate over the parent's rows, so the declaration would be "
        "dropped and the column would hold a number that is not the metric it is named after "
        f"(S-0065/D-5). Fix: leave {measure!r} off the rollup and request it at the grain it "
        "is declared for"
    )

    return UnprovableRollup(msg, source_path=f"{path}.measures")


# ....................... #


def _determinations(mart: MartIR, project: ProjectIR) -> dict[str, tuple[str, ...]]:
    """What the entities' ``determines:`` declarations say in *this mart's*
    namespace, keyed by dimension name, for R020 (S-0079/D-4).

    Derived at the call and stored nowhere: a mapping could not reach an IR
    node in any case (``_canon_bytes`` raises on a ``dict``), so carrying it
    would mean a second statement of a fact ``EntityIR.columns`` and
    ``MartIR.columns`` already hold between them — one that can disagree.

    A column is matched to its **join family**, never to its source entity
    alone (S-0079/D-5): it belongs to ``(prefix, entity)`` when its source
    entity is ``entity`` and its name is ``prefix + source_column``, the base
    entity taking the empty prefix. One entity flattened under two prefixes
    relates ``billing_city`` to ``billing_state`` and to nothing of the
    shipping family; matching on the source column alone would relate them
    across families and prove a coarsening that does not hold. What enforces
    that is the keeper lookup below, which spells the determined column with
    the *matched* family's prefix.

    The ``len(matched) != 1`` guard is not that enforcement and only its
    ``== 0`` half fires — an emitted column with no family behind it, a date
    bucket for instance. Two families cannot match one column: the column's
    own ``source_column`` fixes the prefix to one string, so a second match
    needs a second join carrying that prefix for that entity, and such a mart
    never lowers — every column the second join flattens collides with the
    first's, and :func:`~bloomery.marts.flatten.lower_marts` returns
    violations rather than a :class:`~bloomery.ir.MartIR`. It stays as the
    belt on a total function: a column matching two families contributes no
    edge, and the ambiguous case fails by proving less, which is the only
    direction R020 may fail in.

    Only the **direct** declarations are translated (S-0079/D-6). The
    transitive step stays inside R020, whose ``determination_closure`` runs
    over whatever mapping it is handed: closing it here would make every
    witness read ``DECLARED`` and the provenance R020 reports stop meaning
    anything.
    """

    declared = {
        (entity.name, column.name): column.determines
        for entity in project.entities
        for column in entity.columns
        if column.determines
    }

    if not declared:
        return {}

    families = ((mart.base, ""), *((join.entity, join.prefix) for join in mart.joins))
    dimension_of = {dimension.column: dimension.ref.qualified for dimension in mart.dimensions}
    traced = {(column.source_entity, column.source_column, column.name) for column in mart.columns}
    edges: dict[str, tuple[str, ...]] = {}

    for column in mart.columns:
        targets = declared.get((column.source_entity, column.source_column), ())
        source = dimension_of.get(column.name)
        matched = [
            prefix
            for entity, prefix in families
            if entity == column.source_entity and column.name == prefix + column.source_column
        ]

        if not targets or source is None or len(matched) != 1:
            continue

        # The determined column of the *same* family: same source entity, the
        # declared column, and the family's prefix on the name — so a base
        # column that happens to be spelled like a prefixed one earns nothing.
        keepers = tuple(
            qualified
            for target in targets
            if (column.source_entity, target, matched[0] + target) in traced
            and (qualified := dimension_of.get(matched[0] + target)) is not None
        )

        if keepers:
            edges[source] = keepers

    return edges


# ....................... #


def lower_rollups(mart_set: MartSet | None, draft: ProjectIR) -> RollupLowering:
    """Resolve every declared rollup against the parent it names (S-0065/phasing (P-2)).

    Total — never raises. A project with no marts document, or one whose marts
    are all wide, lowers to the empty tuple.

    A rollup whose parent is absent from ``draft.marts`` is **skipped in
    silence**, and that is not a hole: the spec layer already refuses a
    ``rollup_of`` naming a mart this document does not declare, so the only way
    to arrive here is a parent that failed to lower. Its own violation is in
    the same aggregate and is the actionable one; a second leaf saying the
    rollup could not be checked would send an author to the rollup.
    """

    if mart_set is None:
        return RollupLowering(rollups=(), violations=())

    parents = {mart.name: mart for mart in draft.marts}
    rollups: list[RollupIR] = []
    violations: list[GuardrailError] = []

    for name in sorted(mart_set.rollups):
        rollup = mart_set.rollups[name]
        parent = parents.get(rollup.of)

        if parent is None:
            continue

        # `rollups.<name>`, not `marts.<name>`: a source path addresses the
        # authored document (S-0019/source-paths), and a rollup is authored under its
        # own key. Sending an author to `marts.monthly` when they wrote
        # `rollups: monthly` is the same defect that ruled out putting a rollup
        # in `marts:` as a discriminated union — a path naming a key nobody
        # wrote (logs/T-0034.md).
        path = f"marts: rollups.{name}"
        missing = _not_on_the_parent(name, rollup, parent, path)

        if missing is not None:
            violations.append(missing)
            continue

        # The parent restricted to the measures this rollup takes. A rollup may
        # carry a subset — that is the point of declaring `measures:` at all,
        # since a mart with one `distinct_count` would otherwise have no
        # provable rollup — and R013 is asked about what the rollup carries
        # (§5.2), not about what the parent does.
        carried = replace(parent, measures=tuple(sorted(rollup.measures)))
        answer = prove_mart_rollup(carried, rollup.keep, draft, _determinations(parent, draft))

        if isinstance(answer, Refutation):
            violations.append(_refused(name, answer, path))
            continue

        by_name = {metric.name: metric for metric in draft.metrics}
        dropped = tuple(
            leaf
            for measure in sorted(rollup.measures)
            if (leaf := _dropped_declaration(name, measure, by_name[measure], path)) is not None
        )

        if dropped:
            violations.extend(dropped)
            continue

        rollups.append(
            RollupIR(
                name=name,
                of=rollup.of,
                keep=tuple(sorted(set(rollup.keep))),
                measures=tuple(sorted(rollup.measures)),
                partition_by=partition_specs(rollup.partition_by),
                materialization=(
                    Materialization.FULL
                    if rollup.materialization is None
                    else Materialization(rollup.materialization)
                ),
                grants=GrantsIR(select=rollup.grants.select) if rollup.grants is not None else None,
            )
        )

    return RollupLowering(rollups=tuple(rollups), violations=tuple(violations))
