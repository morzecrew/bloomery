"""The plan-stage value objects (RFC 0007 §5.1, amended by RFC 0016 §5.7):
the five-member :class:`ChangeClass`, the :class:`Change` record,
:class:`BackfillScope`, :class:`ReplayScope`, and the :class:`Plan` a diff
returns.

Frozen slotted stdlib dataclasses, like the IR they describe (RFC 0003 D1):
plans are value-like, hashable, and byte-comparable — every collection is a
tuple in a deterministic lexicographic order (RFC 0007 D6).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# ----------------------- #

__all__ = [
    "BackfillScope",
    "Change",
    "ChangeClass",
    "Plan",
    "ReplayScope",
]


class ChangeClass(StrEnum):
    """The closed classification vocabulary (RFC 0007 D1 — spec §5.5):
    every diffable difference maps to exactly one class."""

    #: New optional column / metric — metadata-only, nothing existing moves.
    ADDITIVE = "additive"
    #: Type widened per the RFC 0004 lattice (e.g. decimal(10,2) → (12,4)).
    WIDENING = "widening"
    #: Field identity preserved via an explicit ``renamed_from`` (RFC 0007 D3).
    RENAME = "rename"
    #: Same shape, different meaning — history must be recomputed (D4).
    RESTATING = "restating"
    #: Drop / narrow / grain / key / scd / materialization — classified and
    #: returned, never raised (D5): the caller decides.
    BREAKING = "breaking"


# ....................... #


@dataclass(frozen=True, slots=True)
class Change:
    """One classified difference between two IRs (RFC 0007 §5.1).

    ``subject`` follows the fixed grammar ``<kind>:<name>`` with kinds
    ``entity``, ``field``, ``metric``, ``mart``, ``relationship``,
    ``date_dimension`` and — since RFC 0016 §5.7 — the data-quality kinds
    ``quality`` (named by the rule), ``dedupe`` and ``quarantine`` (named by
    the owning entity) and ``reconcile`` (named by the check). ``entity`` is
    the owning entity for entity- and field-level subjects and ``None`` for
    project-level ones (``reconcile`` included: a check relates two entities,
    so it belongs to neither). ``detail`` is deterministic human-readable
    wording; ``old``/``new`` carry compact value reprs where meaningful.
    """

    entity: str | None
    subject: str
    change_class: ChangeClass
    detail: str
    old: str | None = None
    new: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class BackfillScope:
    """Which stored rows a plan invalidates (RFC 0007 §5.1): the sorted
    entities whose rows must be recomputed, and whether any RESTATING change
    is present — i.e. whether historical numbers change meaning."""

    entities: tuple[str, ...]
    restates_history: bool


# ....................... #


@dataclass(frozen=True, slots=True)
class ReplayScope:
    """Which entities' ``<entity>__reject`` tables a plan invalidates
    (RFC 0016 §5.7, D11) — sorted, like every other plan collection.

    Distinct from :class:`BackfillScope` because the two name different
    *storage*. A backfill recomputes an entity from bronze; a replay re-runs
    the current mapping against rows that are **not in bronze's incremental
    window at all** — they sit in the reject table, quarantined by a rule the
    new spec has since relaxed. Relaxing ``quarantine`` to ``flag`` and
    backfilling would leave those rows quarantined forever: the backfill reads
    bronze, and bronze's window has long since moved past them.

    Populated only where a change can actually free rows (RFC 0016 D52): the
    rule's **old** disposition was ``quarantine`` — otherwise nothing sits in
    the reject table on its account — *and* it is now gone, now disposes as
    ``flag``, or has relaxed parameters. Two shapes deliberately do **not**
    replay although they restate: ``flag → quarantine`` (nothing was diverted
    to begin with) and any *tightening* of a still-quarantining rule — a
    narrowed bound, or ``quarantine → fail`` — because every row in the reject
    table still fails the rule, so the replay drains nothing and, under
    ``fail``, halts the pipeline on the new blocking audit. Where relaxation is
    undecidable from the parameters alone (an unorderable ``pattern`` regex or
    ``expression``) the replay is reported: a no-op MERGE is cheaper than a
    row stranded in quarantine. bloomery emits the replay merge artifact;
    *executing* it is the caller's (§5.6).
    """

    entities: tuple[str, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class Plan:
    """The product of :func:`bloomery.plan.plan` (RFC 0007 D6): classified
    changes sorted by ``(entity, subject, class, detail)``, the backfill
    scope, the quarantine replay scope (RFC 0016 §5.7), and the affected
    metric names computed from the IR's own ``depends_on`` edges — no
    external lineage."""

    changes: tuple[Change, ...]
    backfill_scope: BackfillScope
    downstream_impact: tuple[str, ...]
    replay_scope: ReplayScope = ReplayScope(entities=())

    # ....................... #

    @property
    def has_changes(self) -> bool:
        """Whether the diff found anything at all — ``plan(ir, ir)`` is the
        empty plan (RFC 0007 D2)."""

        return bool(self.changes)

    # ....................... #

    @property
    def breaking(self) -> tuple[Change, ...]:
        """The BREAKING subset, in plan order — the changes a caller must
        explicitly accept before applying."""

        return tuple(
            change for change in self.changes if change.change_class is ChangeClass.BREAKING
        )
