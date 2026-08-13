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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, InvariantViolated
from bloomery.ir import Materialization, UnreachableMetric, project_fingerprint
from bloomery.resolve import Resolution, Stage, StageProgress, pipeline

# Imported at run time rather than under ``TYPE_CHECKING``: both appear in
# ``evaluate``'s signature, and the signature-closure test resolves every
# public annotation for real (RFC 0018 D10).
from bloomery.spec import Catalog, Project
from bloomery.steps import EMPTY_REGISTRY, StepRegistry

if TYPE_CHECKING:
    from bloomery.ir import MartIR, ProjectIR

__all__ = [
    "MartSummary",
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
    :attr:`unreachable`                     ``(name, missing)``
    :attr:`marts`                           ``(name, grain)``
    :attr:`refusals`                        ``(source_path or "", class, str)``
    ======================================  ==================================

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
    fingerprint: str | None = field(default=None)


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


def _from_ir(
    stage: Stage,
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
    return SpecEvidence(
        stage_reached=stage,
        reachable=tuple(sorted(resolution.reachable_metrics)),
        unreachable=tuple(sorted(resolution.unreachable_metrics, key=_unreachable_key)),
        refusals=refusals,
        marts=tuple(
            sorted(
                (_mart_summary(mart) for mart in ir.marts),
                key=lambda summary: (summary.name, summary.grain),
            )
        ),
        entities=tuple(sorted(entity.name for entity in ir.entities)),
        fingerprint=fingerprint,
    )


def _unreachable_key(metric: UnreachableMetric) -> tuple[str, tuple[str, ...]]:
    return (metric.name, metric.missing)


def _partial(stage: Stage, progress: StageProgress, raised: BloomeryError) -> SpecEvidence:
    """The prefix that survived a refusal at ``stage`` (RFC 0022 D3).

    Three widths, one per how far the pipeline got: a draft IR carries
    everything, a bare :class:`Resolution` carries reachability alone, and a
    refusal at the first stage carries nothing but itself. Each is what was
    genuinely computed — an empty tuple here means "not computed", which is why
    :attr:`SpecEvidence.stage_reached` has to be read first.
    """
    refusals = _refusals(raised)
    resolution = progress.resolution
    if resolution is None:
        return SpecEvidence(stage_reached=stage, refusals=refusals)
    if progress.ir is not None:
        return _from_ir(stage, progress.ir, resolution, refusals)
    return SpecEvidence(
        stage_reached=stage,
        reachable=tuple(sorted(resolution.reachable_metrics)),
        unreachable=tuple(sorted(resolution.unreachable_metrics, key=_unreachable_key)),
        refusals=refusals,
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
        return _partial(stage, progress, refusal)
    ir, resolution = progress.ir, progress.resolution
    if ir is None or resolution is None:  # pragma: no cover — COMPLETE carries both
        msg = "the pipeline reached COMPLETE without an IR"
        raise InvariantViolated(msg)
    return _from_ir(Stage.COMPLETE, ir, resolution, (), project_fingerprint(ir))
