"""The as-of fact, in one place (RFC 0037 §5.3, D4).

An ``scd: type2`` relation holds one row per version per key, so an equality
join on the relationship's columns matches every version and multiplies the
left side. An ``as_of:`` anchor is what narrows it back to one row — and an
anchor only does that if it names a **temporal column of the entity the join
reads from**, because that is where a fact's own date lives and only a date or
timestamp orders against a validity interval.

That is a single semantic fact with two consumers: the mart guard, which turns
it into :class:`~bloomery.errors.HistoricalFanout` leaves, and the grain
model, which admits a dependency across a historical relationship only when it
comes back qualified. RFC 0037 D4 requires them to read it here rather than
each holding its own reading — two interpretations of SCD2 validity in one
compiler is a divergence this project has paid for before.

The states are the fact; the messages are not. Each caller words its own
refusal, because a mart author and a rollup proof need to be told different
things about the same missing anchor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from bloomery.ir import SCDKind
from bloomery.typing import DateType, TimestampType

if TYPE_CHECKING:
    from bloomery.ir import EntityIR

# ----------------------- #

__all__ = [
    "AsOfState",
    "qualify_as_of",
]


class AsOfState(StrEnum):
    """How a join onto ``target`` reads, given the anchor it was handed.

    Only :attr:`CURRENT` and :attr:`QUALIFIED` are joins that preserve the
    reading side's grain. The other four are the ways the pairing is wrong,
    kept apart rather than collapsed into one falsehood because the repair
    differs for each: supply an anchor, drop one, name a column that exists,
    name one that is temporal.
    """

    #: Target is not historical and no anchor was given — an ordinary equality
    #: join, which is every join over a non-``type2`` entity.
    CURRENT = "current"
    #: Target is ``type2`` and a temporal anchor on the reading entity narrows
    #: it to one version. The as-of join.
    QUALIFIED = "qualified"
    #: Target is ``type2`` with no anchor: the join matches every version.
    UNANCHORED = "unanchored"
    #: An anchor onto a relation holding one row per key — there is no version
    #: to read as of, and the validity columns it compares against do not
    #: exist on the target.
    ANCHOR_ON_CURRENT = "anchor_on_current"
    #: The anchor names no column of the entity the join reads from.
    ANCHOR_UNKNOWN = "anchor_unknown"
    #: The anchor names a column that does not order against an interval.
    ANCHOR_NOT_TEMPORAL = "anchor_not_temporal"


# ....................... #


def qualify_as_of(*, reading: EntityIR, target: EntityIR, as_of: str | None) -> AsOfState:
    """Classify a join from ``reading`` onto ``target`` under ``as_of``.

    ``reading`` is the side the anchor is read from — the mart's base entity
    for a ``via:`` step, the determinant's entity for a functional dependency.
    Total: every pairing of historical-ness and anchor lands on exactly one
    :class:`AsOfState`.
    """
    historical = target.scd is SCDKind.TYPE2

    if as_of is None:
        return AsOfState.UNANCHORED if historical else AsOfState.CURRENT

    if not historical:
        return AsOfState.ANCHOR_ON_CURRENT

    column = next((c for c in reading.columns if c.name == as_of), None)

    if column is None:
        return AsOfState.ANCHOR_UNKNOWN

    if not isinstance(column.type, DateType | TimestampType):
        return AsOfState.ANCHOR_NOT_TEMPORAL

    return AsOfState.QUALIFIED
