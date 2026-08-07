"""The plan-stage value objects (RFC 0007 §5.1): the five-member
:class:`ChangeClass`, the :class:`Change` record, :class:`BackfillScope`, and
the :class:`Plan` a diff returns.

Frozen slotted stdlib dataclasses, like the IR they describe (RFC 0003 D1):
plans are value-like, hashable, and byte-comparable — every collection is a
tuple in a deterministic lexicographic order (RFC 0007 D6).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "BackfillScope",
    "Change",
    "ChangeClass",
    "Plan",
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


@dataclass(frozen=True, slots=True)
class Change:
    """One classified difference between two IRs (RFC 0007 §5.1).

    ``subject`` follows the fixed grammar ``<kind>:<name>`` with kinds
    ``entity``, ``field``, ``metric``, ``mart``, ``relationship``, and
    ``date_dimension``; ``entity`` is the owning entity for entity- and
    field-level subjects and ``None`` for project-level ones. ``detail`` is
    deterministic human-readable wording; ``old``/``new`` carry compact value
    reprs where meaningful.
    """

    entity: str | None
    subject: str
    change_class: ChangeClass
    detail: str
    old: str | None = None
    new: str | None = None


@dataclass(frozen=True, slots=True)
class BackfillScope:
    """Which stored rows a plan invalidates (RFC 0007 §5.1): the sorted
    entities whose rows must be recomputed, and whether any RESTATING change
    is present — i.e. whether historical numbers change meaning."""

    entities: tuple[str, ...]
    restates_history: bool


@dataclass(frozen=True, slots=True)
class Plan:
    """The product of :func:`bloomery.plan.plan` (RFC 0007 D6): classified
    changes sorted by ``(entity, subject, class, detail)``, the backfill
    scope, and the affected metric names computed from the IR's own
    ``depends_on`` edges — no external lineage."""

    changes: tuple[Change, ...]
    backfill_scope: BackfillScope
    downstream_impact: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        """Whether the diff found anything at all — ``plan(ir, ir)`` is the
        empty plan (RFC 0007 D2)."""
        return bool(self.changes)

    @property
    def breaking(self) -> tuple[Change, ...]:
        """The BREAKING subset, in plan order — the changes a caller must
        explicitly accept before applying."""
        return tuple(
            change for change in self.changes if change.change_class is ChangeClass.BREAKING
        )
