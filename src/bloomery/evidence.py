"""Spec analysis as a value: ``evaluate(project) -> SpecEvidence`` (RFC 0022).

Everything knowable about a spec **without touching data** — which metrics are
computable, which are not and precisely which leaf is missing, what the
pipeline refused and where, and what shape the marts would have — returned as
one frozen value instead of assembled by the caller from three calls and two
exception handlers.

Two things make it worth a module rather than a recipe in a docstring.

**Refusal is a return value here.** :func:`~bloomery.compile_project` is
all-or-nothing by design and correctly so: it emits artifacts or it refuses.
But a refusal on a draft spec is a normal outcome, and a caller reviewing that
draft wants the refusal *alongside* the analysis that completed, which an
exception cannot carry.

**The prefix survives.** "Seven metrics reachable, two blocked on ``cogs``, one
refusal at ``mappings/crm.yaml``" is unavailable today at any price, and is the
most useful sentence bloomery can produce about a spec it will not compile.
:func:`evaluate` runs the pipeline to the first stage that refuses and reports
what the stages before it produced.

It adds no analysis. Every number here is one bloomery already computes on its
way to emitting or refusing, and the stages come from
:func:`~bloomery.resolve.pipeline` — the same generator
:func:`~bloomery.build_project_ir` is written as — so a third entry point
cannot drift from the second.

Pure, like everything under ``src/bloomery/``: no execution, no connection, no
data. That boundary is the point of the type and not an implementation detail —
see :class:`SpecEvidence`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, InvariantViolated
from bloomery.ir import Materialization, UnreachableMetric, project_fingerprint
from bloomery.resolve import FieldProvenance, Resolution, Stage, StageProgress, pipeline

# Imported at run time rather than under ``TYPE_CHECKING``: both appear in
# ``evaluate``'s signature, and the signature-closure test resolves every
# public annotation for real (RFC 0018 D10).
from bloomery.spec import Catalog, Project
from bloomery.steps import EMPTY_REGISTRY, StepRegistry

if TYPE_CHECKING:
    from bloomery.ir import MartIR, ProjectIR

__all__ = [
    "Gap",
    "MartSummary",
    "OpenDecision",
    "RecipeOption",
    "SpecEvidence",
    "evaluate",
]


@dataclass(frozen=True, slots=True)
class MartSummary:
    """One mart's shape, projected from :class:`~bloomery.ProjectIR`.

    A projection, never a recomputation: every field is read off ``MartIR``,
    so a summary cannot describe a mart the compiler would not build. What it
    drops is everything a reviewer does not read — the flattened columns, the
    build-time joins, the partition spec — because a summary that carries the
    whole mart is the mart.

    ``dimensions`` are **role-qualified** (``ordered_at``, ``shipped_at``), the
    names a request writes, rather than the underlying entity fields they
    flatten from. That is the whole reason role-playing dates exist (RFC 0010),
    and a summary naming the field twice would be describing a different mart
    than the planner serves.
    """

    name: str
    grain: str
    measures: tuple[str, ...]
    dimensions: tuple[str, ...]
    materialization: Materialization


class Gap(StrEnum):
    """Why a canonical field is unavailable — which decides the edit
    (RFC 0030 D3).

    The distinction is the report's reason to exist: both states arrive as the
    same :class:`~bloomery.UnreachableMetric` today, and they are closed by
    edits to two different documents.
    """

    #: No entity field carries ``canonical: <name>``. The edit is an
    #: entity-model one — declare the field and link it — and it does not close
    #: the decision, it turns it into :attr:`UNMAPPED` (RFC 0030 D10).
    UNLINKED = "unlinked"
    #: A field carries the link and no mapping produces it. The edit is a
    #: mapping field, and it is where the recipe choice is.
    UNMAPPED = "unmapped"


@dataclass(frozen=True, slots=True)
class RecipeOption:
    """One derivation the catalog declares, as a chooser needs it.

    A projection of :class:`~bloomery.spec.catalog.Recipe`, never an opinion
    about it: the report enumerates and does not rank (RFC 0030 D2). What it
    adds is proximity — ``requires`` names the alias slots a mapping's ``from:``
    must bind, which lives in the catalog under a different key from the
    canonical field a metric names, and a chooser that gets that join wrong
    records a ``recipe:`` the compiler refuses.
    """

    id: str
    #: The alias slots the mapping's ``from:`` must bind — **source paths**,
    #: never canonical fields, which is what makes the loop terminate
    #: (RFC 0030 D6).
    requires: tuple[str, ...]
    #: The recipe's expression; ``None`` is identity over a single requirement.
    expr: str | None = None


@dataclass(frozen=True, slots=True)
class OpenDecision:
    """One decision a spec leaves open, and the edit that would close it.

    **Not a recommendation.** :attr:`options` is what the catalog declares, in
    the order the catalog declares it, and bloomery neither ranks nor picks —
    not even when there is exactly one (RFC 0005 D2, RFC 0030 D2/D4). A caller
    that reads ``options[0]`` as advice has moved the compiler's refusal to
    choose into its own code without noticing.

    **Every entry names one edit** (RFC 0030 D9). An entry a caller cannot act
    on is worse than a gap — it is a worklist item that never clears — so a
    canonical whose entity is built by more than one mapping is left out
    entirely: its columns are per mapping (RFC 0024 D26), and an entry keyed on
    the canonical cannot say which document to edit. Nothing is hidden by that;
    the metric blocked on it is still in
    :attr:`~bloomery.SpecEvidence.unreachable`.
    """

    #: The unavailable canonical field, unprefixed (``net_revenue``).
    canonical: str
    gap: Gap
    #: The entity to edit: the one carrying the link, or — when nothing carries
    #: it — the one the catalog declares the canonical field for.
    entity: str
    #: The linked field, set iff :attr:`gap` is :attr:`Gap.UNMAPPED`.
    field: str | None
    #: The catalog's recipes for :attr:`canonical`, **in catalog order**
    #: (RFC 0030 D2) — the one collection on this type that is not sorted.
    #: May be empty, which says the catalog declares no derivation, and never
    #: that the data is absent: bloomery does no I/O and cannot know that.
    options: tuple[RecipeOption, ...]
    #: The metrics blocked on this decision, sorted. Never empty — a canonical
    #: nothing requires is not work — and it is what lets a caller set a
    #: priority bloomery deliberately does not.
    blocks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpecEvidence:
    """Everything knowable about a spec without touching data (RFC 0022 D1).

    **Read :attr:`stage_reached` before any other field.** An empty
    :attr:`unreachable` means "nothing is unreachable" only at
    :attr:`~bloomery.Stage.COMPLETE`; at :attr:`~bloomery.Stage.RESOLVE` it
    means reachability was never computed. Every tuple here is empty in both
    cases and they mean opposite things, which is the one way this type can be
    read into a wrong conclusion.

    Every tuple is sorted by a declared key, because determinism applies to an
    assessment as much as to an artifact — and because ``sorted()`` over these
    values does not merely order badly, it raises: neither
    :class:`~bloomery.BloomeryError` nor a frozen dataclass defines ``__lt__``,
    and Python has no lexicographic fallback for either.

    ======================================  ==================================
    Field                                   Sort key
    ======================================  ==================================
    :attr:`reachable`, :attr:`entities`     the string itself
    :attr:`unreachable`                     ``(name, missing, via)``
    :attr:`marts`                           ``(name, grain)``
    :attr:`refusals`                        ``(source_path or "", class, str)``
    :attr:`unresolved`                      ``canonical``
    :attr:`provenance`                      ``(entity, field)``
    ======================================  ==================================

    One collection escapes that rule, deliberately and in one place:
    :attr:`OpenDecision.options` is in **catalog order**, because the catalog's
    order is authored — recipes are "ordered by reliability" — and sorting it
    would destroy information rather than normalize it (RFC 0030 D2).

    ``source_path`` is optional on a refusal, so the empty string stands in for
    ``None``: a refusal with no source path sorts first, deterministically,
    rather than the sort failing on a mixed tuple.

    **This is deliberately half of what a reviewer needs.** The other half —
    coercion rates, null deltas, sample rows — requires running the emitted SQL
    against data, which is outside the library (RFC 0022 D6). A platform
    composes this with its own dry-run into one review payload. The temptation
    to add "and also run it against a sample" here is real and permanent, and
    taking it would put an engine connection inside a compiler whose test suite
    needs no infrastructure.

    It carries facts and never judgement — no score, no confidence, no
    approve/reject. The reviewer decides; bloomery reports (RFC 0022 D9).

    **It does not carry the compiled artifacts**, even at
    :attr:`~bloomery.Stage.COMPLETE`, where it could and where that would let a
    caller replace :func:`~bloomery.compile_project` outright. A type meaning
    "assessment" should not sometimes also mean "output" — and compilation is
    per *target* while an assessment is not, so the field would have to be
    either target-parameterized or wrong.
    """

    #: How far analysis got. Read first; see the class docstring.
    stage_reached: Stage
    #: Metric names computable from what the mappings supply, sorted.
    reachable: tuple[str, ...] = ()
    #: Metrics that are not, each with the specific missing leaves (RFC 0005 D3).
    unreachable: tuple[UnreachableMetric, ...] = ()
    #: The batched refusals of the stage that stopped analysis. Empty at
    #: :attr:`~bloomery.Stage.COMPLETE`, and never more than one batch: a stage
    #: batches within itself (RFC 0002/0006) and the pipeline stops at the
    #: first that refuses, so there is no second stage to collect from.
    refusals: tuple[BloomeryError, ...] = ()
    #: Shape of every mart that would be built, sorted by name.
    marts: tuple[MartSummary, ...] = ()
    #: Entity names in the IR, including step-produced ones, sorted.
    entities: tuple[str, ...] = ()
    #: The project fingerprint, or ``None`` when the IR never finished
    #: building — which is every stage before :attr:`~bloomery.Stage.COMPLETE`,
    #: since a fingerprint over a draft would name a project that does not
    #: exist.
    fingerprint: str | None = None
    # The two fields below are **appended after** ``fingerprint`` rather than
    # grouped with the analysis tuples they belong with, and that is a
    # compatibility decision rather than an ordering preference. Every field
    # here has a default, so inserting one mid-list does not raise for a
    # positional caller — it silently rebinds: `SpecEvidence(stage, reachable,
    # unreachable, refusals, marts, entities, fingerprint)` would land the
    # fingerprint in `unresolved` and leave `fingerprint` at `None`, producing
    # an evidence value that is wrong in two places and refuses nothing.
    # Appending is what keeps this addition additive (RFC 0018 D1); the
    # docstring's table above is the reading order, and this is the wire order.
    #: Every decision the spec leaves open, sorted by canonical field
    #: (RFC 0030). Read :attr:`stage_reached` first, as for every tuple here:
    #: empty means "nothing open" only where the resolve stage got far enough
    #: to compute it.
    unresolved: tuple[OpenDecision, ...] = ()
    #: How each mapped entity field is produced — the loop's memory of what it
    #: has already decided, and the recipe id it decided on (RFC 0030 D8).
    #: Computed on every ``resolve()``; carried here rather than discarded.
    #:
    #: One entry per ``(entity, field)``, so a **merged entity's** field appears
    #: once however many mappings build it — see
    #: :class:`~bloomery.FieldProvenance`, which carries the limit and where it
    #: is answered.
    provenance: tuple[FieldProvenance, ...] = ()


def _mart_summary(mart: MartIR) -> MartSummary:
    return MartSummary(
        name=mart.name,
        grain=mart.grain,
        measures=tuple(sorted(mart.measures)),
        # `ref` is the role-qualified name; `column` is the flattened storage
        # column serving it, which is the mart's business and not the summary's.
        dimensions=tuple(sorted(str(dimension.ref) for dimension in mart.dimensions)),
        materialization=mart.materialization,
    )


def _refusals(raised: BloomeryError) -> tuple[BloomeryError, ...]:
    """A raised refusal as the individual failures it reports.

    The batched stages raise **one** aggregate whose message enumerates the
    batch and whose :attr:`~bloomery.BloomeryError.collected` carries each
    failure with its own ``source_path`` (RFC 0002 D6). Reporting the aggregate
    alone would hand a caller a paragraph to re-parse for the paths it already
    has structured, so the batch is unwrapped and the aggregate dropped — it
    holds nothing its members do not.

    One level, not recursively: a stage batches its own leaves and nothing
    nests two deep, and flattening a hierarchy nobody builds would be guessing
    at a shape rather than reading one.
    """
    return tuple(sorted(raised.collected or (raised,), key=_refusal_key))


def _refusal_key(refusal: BloomeryError) -> tuple[str, str, str]:
    """Sort key for a refusal: source path, then class, then message.

    ``source_path`` is best-effort outside the parse stage, so the empty string
    stands in for ``None`` — a refusal with no path sorts first and
    deterministically, rather than the comparison failing on a mixed tuple.
    """
    return (refusal.source_path or "", type(refusal).__name__, str(refusal))


def _unresolved(
    project: Project, catalog: Catalog | None, resolution: Resolution
) -> tuple[OpenDecision, ...]:
    """Every open decision, joined from the resolution, the entity model and
    the catalog (RFC 0030 §5.2).

    **The open set is read off reachability, never recomputed.** An entry
    exists for each canonical field some unreachable metric names as a missing
    leaf — which is exactly "required by an effective metric, transitively, and
    not available", already computed by ``compute_reachability`` over the one
    shared DAG. A second notion of availability here is the drift §9's last
    risk names, and it is avoided by not having one rather than by testing for
    it.

    The rest is the three-document join a chooser would otherwise write: the
    entity model says whether anything links the canonical (the two gaps,
    RFC 0030 D3), and the catalog says what may be recorded once something
    does.
    """
    blocked_by: dict[str, list[str]] = {}
    for metric in resolution.unreachable_metrics:
        for canonical in metric.missing:
            blocked_by.setdefault(canonical, []).append(metric.name)
    if catalog is None:  # no canonical fields, so nothing requires one
        return ()

    # First in sort order where an entity carries the link twice: each of them
    # closes the gap when mapped, so naming one is naming the edit rather than
    # choosing between unequal options (`logs/T-0007.md` D-032).
    linked: dict[str, tuple[str, str]] = {}
    for entity_name, declared_entity in sorted(project.entity_model.entities.items()):
        for field_name, field in sorted(declared_entity.fields.items()):
            if field.canonical is not None:
                linked.setdefault(field.canonical, (entity_name, field_name))
    mappings_per_entity = Counter(mapping.target for mapping in project.mappings)

    decisions: list[OpenDecision] = []
    for canonical in sorted(blocked_by):
        declared = catalog.canonical_fields[canonical]
        link = linked.get(canonical)
        entity = link[0] if link is not None else declared.entity
        if mappings_per_entity[entity] > 1:
            # RFC 0030 D9: a merged entity's columns are per mapping, so no
            # single document is the edit. The blocked metric stays visible in
            # `unreachable`; only the un-actionable worklist entry is withheld.
            continue
        decisions.append(
            OpenDecision(
                canonical=canonical,
                gap=Gap.UNMAPPED if link is not None else Gap.UNLINKED,
                entity=entity,
                field=link[1] if link is not None else None,
                options=tuple(
                    RecipeOption(id=recipe.id, requires=recipe.requires, expr=recipe.expr)
                    for recipe in declared.recipes
                ),
                blocks=tuple(sorted(blocked_by[canonical])),
            )
        )
    return tuple(decisions)


def _from_ir(
    stage: Stage,
    project: Project,
    catalog: Catalog | None,
    ir: ProjectIR,
    resolution: Resolution,
    refusals: tuple[BloomeryError, ...],
    fingerprint: str | None = None,
) -> SpecEvidence:
    """Evidence read off a draft or a finished IR, plus its resolution.

    **Reachability comes from the resolution, not from ``ir.metrics``**, and
    the difference is not cosmetic: by the time the IR is finished it also
    carries the quality mart's bloomery-owned metrics (``quality_rows_deduped``
    and its siblings, RFC 0016 §5.8), which nobody authored and which
    ``resolve()`` has never heard of. Reading them as "reachable" would put
    five metrics in front of a reviewer that are not in their spec, and would
    make :attr:`SpecEvidence.reachable` and :attr:`SpecEvidence.unreachable`
    answer about two different populations. Reachability is the resolve stage's
    fact; the IR is asked only about shape.

    ``fingerprint`` defaults to ``None`` because a draft is not a project: it
    has not passed the guardrail stage, and fingerprinting it would mint an
    identity for something that may never be built. Only the caller that
    reached :attr:`~bloomery.Stage.COMPLETE` has one to pass.
    """
    reachable, unreachable = _reachability(resolution)
    return SpecEvidence(
        stage_reached=stage,
        reachable=reachable,
        unreachable=unreachable,
        refusals=refusals,
        unresolved=_unresolved(project, catalog, resolution),
        provenance=resolution.provenance,
        marts=tuple(
            sorted(
                (_mart_summary(mart) for mart in ir.marts),
                key=lambda summary: (summary.name, summary.grain),
            )
        ),
        entities=tuple(sorted(entity.name for entity in ir.entities)),
        fingerprint=fingerprint,
    )


def _reachability(
    resolution: Resolution,
) -> tuple[tuple[str, ...], tuple[UnreachableMetric, ...]]:
    """``(reachable, unreachable)``, sorted — the one definition of both.

    Both paths that build a :class:`SpecEvidence` from a resolution project it
    the same way, and this is where "the same way" is written down. The sort
    key gained a field in the change that added ``via``, and a projection
    written twice is one where the second copy is updated a release later.
    """
    return (
        tuple(sorted(resolution.reachable_metrics)),
        tuple(sorted(resolution.unreachable_metrics, key=_unreachable_key)),
    )


def _unreachable_key(metric: UnreachableMetric) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Every field, so the key is total rather than merely usually-unique.

    Names are unique within a project today, which makes the rest redundant —
    and a sort key that relies on a uniqueness it does not state is one
    refactor away from being unstable for a reason nobody looks for.
    """
    return (metric.name, metric.missing, metric.via)


def _partial(
    stage: Stage,
    project: Project,
    catalog: Catalog | None,
    progress: StageProgress,
    raised: BloomeryError,
) -> SpecEvidence:
    """The prefix that survived a refusal at ``stage`` (RFC 0022 D3).

    Three widths, one per how far the pipeline got: a draft IR carries
    everything, a bare :class:`Resolution` carries reachability alone, and a
    refusal at the first stage carries nothing but itself. Each is what was
    genuinely computed — an empty tuple here means "not computed", which is why
    :attr:`SpecEvidence.stage_reached` has to be read first.

    **The unresolved-work report travels with the resolution**, not with
    ``COMPLETE``. RFC 0030 D5 says a refusal empties it, and its argument is
    about a refusal *inside* the resolve stage — a malformed recipe id, where
    there is no graph and so nothing to project. A spec that resolved cleanly
    and was refused two stages later on a transform chain has open decisions
    that are computed and correct, and withholding them would make ``unresolved``
    the one field here that is empty for a reason ``stage_reached`` cannot
    explain (`logs/T-0007.md` D-031).
    """
    refusals = _refusals(raised)
    resolution = progress.resolution
    if resolution is None:
        return SpecEvidence(stage_reached=stage, refusals=refusals)
    if progress.ir is not None:
        return _from_ir(stage, project, catalog, progress.ir, resolution, refusals)
    reachable, unreachable = _reachability(resolution)
    return SpecEvidence(
        stage_reached=stage,
        reachable=reachable,
        unreachable=unreachable,
        refusals=refusals,
        unresolved=_unresolved(project, catalog, resolution),
        provenance=resolution.provenance,
    )


def evaluate(
    project: Project,
    *,
    catalog: Catalog | None = None,
    steps: StepRegistry = EMPTY_REGISTRY,
) -> SpecEvidence:
    """Everything knowable about ``project`` without touching data.

    **Read** :attr:`SpecEvidence.stage_reached` **before interpreting any other
    field** — an empty tuple means "nothing found" only at
    :attr:`~bloomery.Stage.COMPLETE`.

    Never raises for a spec-level refusal: refusals are the return value, and
    whatever analysis completed before them comes back alongside. A project
    refused by the guardrail stage still reports its reachability, because that
    was computed two stages earlier and there is no reason to throw it away.

    Two things do still raise, and the narrowness is the point.

    **Programming errors propagate.** A malformed ``steps`` registry, a
    ``MemoryError``, anything that is a bug rather than a judgement about a
    spec — a function that swallowed those would be worse than the exception
    path it replaces. The catch is :class:`~bloomery.BloomeryError` and nothing
    wider.

    **:class:`~bloomery.errors.InvariantViolated` propagates too**, and it is
    the one place that rule bites: it *is* a ``BloomeryError`` by inheritance
    and *is* a bloomery bug by meaning, so reporting it as a spec refusal would
    file our defect under the author's mistake. A narrow catch is only as good
    as the taxonomy beneath it, and this is the known soft spot — any future
    error meaning "bloomery is broken" has to join it here.

    Does not compile. Target-specific refusals (an
    :class:`~bloomery.errors.UnsupportedByTarget` from a target that will not
    emit a ``coverage:`` check, say) are invisible to this, because emission is
    per-target and evidence is not.
    """
    # The furthest point reached. Each yield names the stage *about to run*,
    # so when one refuses these hold that stage and everything before it —
    # which is exactly the partial answer.
    stage, progress = Stage.RESOLVE, StageProgress()
    try:
        for reached_stage, reached in pipeline(project, catalog, steps=steps):
            stage, progress = reached_stage, reached
    except InvariantViolated:
        raise
    except BloomeryError as refusal:
        return _partial(stage, project, catalog, progress, refusal)
    ir, resolution = progress.ir, progress.resolution
    if ir is None or resolution is None:  # pragma: no cover — COMPLETE carries both
        msg = "the pipeline reached COMPLETE without an IR"
        raise InvariantViolated(msg)
    return _from_ir(Stage.COMPLETE, project, catalog, ir, resolution, (), project_fingerprint(ir))
