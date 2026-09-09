"""The ``MartSet`` spec kind (RFC 0010 §5.1; RFC 0002 D9).

The wide-mart gold layer: one mart per (grain × subject area), flattened at
build time. ``flatten`` steps are a discriminated union on ``via`` vs ``date``:
a ``via:`` step names a declared relationship and a mandatory column prefix; a
``date:`` step declares a role-playing time dimension expanded into
``<role>_<bucket>`` columns. Shape-only at parse — relationship existence,
cardinality, grain equality, and collision checks are compile-stage validation
(RFC 0010 §5.5).
"""

from __future__ import annotations

from collections.abc import Mapping as AbcMapping
from typing import Annotated, Literal, Self

from pydantic import Discriminator, Field, Tag, model_validator

from bloomery.spec.common import (
    MaterializationName,
    MemberName,
    PartitionSpecString,
    RelationName,
    SpecModel,
)
from bloomery.spec.quality import RangeBound, RuleName

# ----------------------- #

__all__ = [
    "DateRoleStep",
    "FlattenStep",
    "Mart",
    "MartAggregate",
    "MartAssert",
    "MartSet",
    "RollupMart",
    "ViaStep",
]


class ViaStep(SpecModel):
    """Flatten one declared relationship into the mart, prefixing every
    flattened column with ``prefix`` (RFC 0010 D3 — prefixes mandatory,
    so an empty prefix is a parse error, not a silent no-op).

    ``as_of`` names the **anchor**: a date or timestamp column of the mart's
    base entity, and the instant the joined entity is read *as of* (RFC 0023
    §5.3, D8). It is required to flatten an ``scd: type2`` entity and refused
    on any other, because a historical relation joined without one matches
    every version of each key and multiplies the base grain, while a
    current-view relation has no version to choose between.

    Declared, never inferred: which date history is read on is intent, and
    RFC 0021 closed inference. The anchor sits here rather than on the mart
    because it qualifies *this* join — two historical dimensions in one mart
    can legitimately be read as of different dates.
    """

    via: str
    prefix: str = Field(min_length=1)
    as_of: str | None = None


# ....................... #


class DateRoleStep(SpecModel):
    """Declare a role-playing time dimension: ``{date: order_date, role:
    ordered}`` expands to ``ordered_day`` … ``ordered_year`` (RFC 0010 D4).
    ``metric_time`` is reserved as a role name (RFC 0002 D10)."""

    date: str
    role: MemberName


# ....................... #


def _flatten_tag(value: object) -> str:
    if isinstance(value, AbcMapping) and "via" in value:
        return "via"

    if isinstance(value, ViaStep):
        return "via"

    return "date"


# ....................... #


FlattenStep = Annotated[
    Annotated[ViaStep, Tag("via")] | Annotated[DateRoleStep, Tag("date")],
    Discriminator(_flatten_tag),
]
"""Discriminated union on ``via`` vs ``date`` (RFC 0010 §5.1)."""


#: The aggregates a mart assertion may take. Deliberately the **same** closed
#: vocabulary the ``reconcile`` grammar uses (RFC 0016 §5.3): both compute one
#: number over a column so a human can be told it is wrong, and two lists that
#: mean the same thing drift.
MartAggregate = Literal["avg", "count", "max", "min", "sum"]


class MartAssert(SpecModel):
    """One aggregate assertion over a mart (RFC 0016 D89) — §10's "no month has
    zero revenue", made declarable.

    **Why this is an assertion and not a quality rule.** §5.9 draws the line at
    what a verdict *does*: a quality rule disposes of a row. A mart row is
    derived — it has no ``_source_row_id``, no bronze payload, no reject table
    and no replay — so there is nothing to quarantine, nothing to repair, and
    nothing to bring back. What is left is D4's other half, "alert me", which
    is `assert:`. §10 asked whether mart-level rules were reconcile-shaped or a
    new surface; they are neither, and the disposition model is what separates
    them from both.

    ``by`` groups the aggregate; empty means one group over the whole mart.
    Bounds carry the exact-decimal/ISO string form for the same reason
    ``range`` does — a YAML float never reaches the IR (RFC 0003 D5).

    **What it cannot see, stated:** a group with no rows produces no row to
    aggregate, so an assertion over a mart cannot notice a month that is
    entirely *missing* — only one whose total is out of bounds. Closing that
    needs a join against the date spine, which is a different check with a
    different dependency (RFC 0016 D89).
    """

    name: RuleName
    measure: str
    agg: MartAggregate
    by: tuple[str, ...] = ()
    min: RangeBound | None = None
    max: RangeBound | None = None
    #: ``fail`` blocks the run; ``flag`` emits a non-blocking audit — the same
    #: two readings ``reconcile.on_fail`` carries (RFC 0016 D38). ``quarantine``
    #: and ``repair`` are absent rather than lowered to something weaker:
    #: neither has a meaning without a row to route.
    on_fail: Literal["flag", "fail"]

    # ....................... #

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> Self:
        if self.min is None and self.max is None:
            msg = "a mart assertion needs at least one of min / max"
            raise ValueError(msg)

        return self

    # ....................... #

    @model_validator(mode="after")
    def _by_is_a_set(self) -> Self:
        if len(set(self.by)) != len(self.by):
            msg = f"assertion {self.name!r} repeats a by: column — each names one grouping level"
            raise ValueError(msg)

        return self


# ....................... #


class Mart(SpecModel):
    """One wide mart: base entity, authored-order flatten steps (order is
    meaningful — chains flatten transitively, RFC 0010 §5.1), measures,
    partitioning, aggregate assertions, and the tie-breaking ``cost_hint``
    (RFC 0010 D8)."""

    grain: str
    base: str
    flatten: tuple[FlattenStep, ...] = ()
    measures: tuple[str, ...] = ()
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None
    assert_: tuple[MartAssert, ...] = Field(default=(), alias="assert")
    cost_hint: int = Field(default=1, ge=1)


# ....................... #


class RollupMart(SpecModel):
    """A mart at a coarser grain than one this project already builds
    (RFC 0058 §5.1), declared under the document's ``rollups:`` key.

    It names a parent and the dimensions it keeps; what it **drops** is derived
    — every column of the parent not listed — because listing what you keep and
    what you drop is two statements of one fact that will disagree (D4).

    **Its own key rather than a member of `marts:`**, which is where row 9 put
    it. Row 9's deciding argument was that ``measure_owners`` already
    arbitrates between marts and a second shape would have to be taught that
    arbitration again; row 14 then removed the arbitration entirely — a rollup
    is never a measure owner — so the argument no longer reaches. What decided
    it in the end was smaller and more concrete: a discriminated union inside
    ``marts:`` puts its tag into every mart's error path, and
    ``marts.m.wide.flatten[0].via.prefix`` names a ``wide`` the author did not
    write, which is not what a source path is (RFC 0002 §5.3). Two keys in one
    document mirror ``ProjectIR.marts`` and ``ProjectIR.rollups``, which is the
    same separation row 14 is built on (logs/T-0034.md).

    It declares no ``base:`` and no ``grain:`` (row 11): those name an *entity*,
    and a rollup's rows are identified by ``keep``. Nor ``cost_hint:`` or
    ``assert:``, which row 9 expected it to reuse — ``cost_hint`` breaks the tie
    in ``measure_owners``, which a rollup never reaches, and ``assert:`` is out
    of this phase rather than refused on principle: the audit body reads a
    :class:`~bloomery.ir.MartIR` for its bound types, and teaching it a second
    node is work this phase does not need.
    """

    of: RelationName
    #: The parent's columns this rollup groups by. At least one, and each named
    #: once: a repeat is one grouping level stated twice, refused here the way
    #: :class:`MartAssert` refuses a repeated ``by:``. The obligation itself
    #: canonicalizes a repeat rather than refusing it (RFC 0058 row 16), which
    #: is the right answer for a library caller and the wrong one for a
    #: document a person wrote.
    keep: tuple[str, ...] = Field(min_length=1)
    #: The parent's measures this rollup carries. At least one, and each named
    #: once. A repeat is not a harmless restatement here the way it might be in
    #: a list of names: every entry becomes one aggregate column, so a measure
    #: stated twice emits ``SUM(expr) AS m, SUM(expr) AS m`` and neither engine
    #: accepts a relation with two columns of one name.
    measures: tuple[str, ...] = Field(min_length=1)
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None

    # ....................... #

    @model_validator(mode="after")
    def _keep_is_a_set(self) -> Self:
        if len(set(self.keep)) != len(self.keep):
            msg = "a rollup repeats a keep: column — each names one grouping level"
            raise ValueError(msg)

        return self

    # ....................... #

    @model_validator(mode="after")
    def _measures_are_a_set(self) -> Self:
        if len(set(self.measures)) != len(self.measures):
            msg = "a rollup repeats a measure — each names one column it carries"
            raise ValueError(msg)

        return self


# ....................... #


class MartSet(SpecModel):
    """The per-project marts document (``marts_version``), at most one per
    project, optional — a project without marts compiles silver only
    (RFC 0010 D7)."""

    #: Pinned to the one version bloomery implements (RFC 0018 D7). It was
    #: ``int`` with ``ge=1``, which accepted a document written for a future
    #: bloomery and silently applied v1 semantics to it — the exact misreading
    #: a version key exists to refuse. This key is also the document-kind
    #: discriminator, so it stays required: a document without one cannot be
    #: identified at all.
    marts_version: Literal[1]
    marts: dict[RelationName, Mart]
    #: Rollups of the marts above (RFC 0058 §5.2). A second key of the same
    #: document rather than a document of its own: a rollup is meaningless
    #: without the mart it names, and the two are authored together.
    rollups: dict[RelationName, RollupMart] = Field(default_factory=dict)

    # ....................... #

    @model_validator(mode="after")
    def _rollups_name_a_mart(self) -> Self:
        """A rollup's parent is a mart of this document, and its own name is
        not one (RFC 0058 D10).

        **Chaining is refused rather than resolved**, and the separate key is
        what makes that trivially true: ``of:`` names a member of ``marts:``,
        so a rollup of a rollup cannot be spelled. The obligation would
        compose — a monthly rollup of a daily one is the same arithmetic twice
        — but its *premise* does not: R008 says a measure is embedded in a
        mart at that mart's grain, and a rollup's measures do not originate at
        its grain, they arrive there.

        **A rollup may not take a mart's name.** Both become one relation in
        the gold layer, so a collision is two models writing one table — which
        the emitters would report as a duplicate artifact path at best and
        silently order-dependently at worst. Refused here because both names
        are in this document and nothing downstream has a better view of them.
        """

        for name, rollup in self.rollups.items():
            if name in self.marts:
                msg = (
                    f"rollup {name!r} takes the name of a mart. Both are relations of the "
                    "gold layer, so the two would build one table (RFC 0010 §5.4). Fix: name "
                    "the rollup for the grain it holds"
                )
                raise ValueError(msg)

            if rollup.of not in self.marts:
                msg = (
                    f"rollup {name!r} is a rollup of {rollup.of!r}, which this document does "
                    f"not declare as a mart. Marts: {sorted(self.marts)}"
                )
                raise ValueError(msg)

        return self
