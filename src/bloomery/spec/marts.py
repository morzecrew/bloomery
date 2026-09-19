"""The ``MartSet`` spec kind (S-0027/spec-kind; S-0019/D-9).

The wide-mart gold layer: one mart per (grain × subject area), flattened at
build time. ``flatten`` steps are a discriminated union on ``via`` vs ``date``:
a ``via:`` step names a declared relationship and a mandatory column prefix; a
``date:`` step declares a role-playing time dimension expanded into
``<role>_<bucket>`` columns. Shape-only at parse — relationship existence,
cardinality, grain equality, and collision checks are compile-stage validation
(S-0027/validation-compile-errors-batched-with-guardrails).
"""

from __future__ import annotations

from collections.abc import Mapping as AbcMapping
from typing import Annotated, Literal, Self

from pydantic import Discriminator, Field, Tag, model_validator

from bloomery.spec.common import (
    Grants,
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
    flattened column with ``prefix`` (S-0027/D-3 — prefixes mandatory,
    so an empty prefix is a parse error, not a silent no-op).

    ``as_of`` names the **anchor**: a date or timestamp column of the mart's
    base entity, and the instant the joined entity is read *as of* (S-0040
    §5.3, D8). It is required to flatten an ``scd: type2`` entity and refused
    on any other, because a historical relation joined without one matches
    every version of each key and multiplies the base grain, while a
    current-view relation has no version to choose between.

    Declared, never inferred: which date history is read on is intent, and
    S-0038 closed inference. The anchor sits here rather than on the mart
    because it qualifies *this* join — two historical dimensions in one mart
    can legitimately be read as of different dates.

    ``role_of`` names the **dimension this prefixed column family is a role
    of** (S-0007/roles-for-any-dimension): two steps declaring ``role_of:
    address`` say that ``billing_region`` and ``shipping_region`` are two roles
    of one dimension, which is what the prefix never carried. Optional and
    additive — a step without one is exactly the step that compiled before
    (S-0007/D-5) — and it does not replace the prefix, which stays mandatory
    because it is what keeps the emitted columns distinct.

    A :class:`~bloomery.spec.common.MemberName` rather than a free string: it
    reaches the emitted artifacts as a dimension name, so it is guarded like
    every other name that does.

    There is no ``same_as:`` beside it (S-0007/D-8). Naming another mart's role
    that draws from the same value set says, within one project, exactly what
    two ``role_of:`` steps already say, and R021 is the rule that reads them;
    across a project boundary it has no consumer until a reference is emitted
    over one. A fact whose rule never reaches ``RULES`` is dropped rather than
    landed (S-0007/D-2), so the relation is retired rather than pending.
    """

    via: str
    prefix: str = Field(min_length=1)
    as_of: str | None = None
    role_of: MemberName | None = None


# ....................... #


class DateRoleStep(SpecModel):
    """Declare a role-playing time dimension: ``{date: order_date, role:
    ordered}`` expands to ``ordered_day`` … ``ordered_year`` (S-0027/D-4).
    ``metric_time`` is reserved as a role name (S-0019/D-10)."""

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
"""Discriminated union on ``via`` vs ``date`` (S-0027/spec-kind)."""


#: The aggregates a mart assertion may take. Deliberately the **same** closed
#: vocabulary the ``reconcile`` grammar uses (S-0033/spec-schema): both compute one
#: number over a column so a human can be told it is wrong, and two lists that
#: mean the same thing drift.
MartAggregate = Literal["avg", "count", "max", "min", "sum"]


class MartAssert(SpecModel):
    """One aggregate assertion over a mart (S-0033/D-89) — §10's "no month has
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
    ``range`` does — a YAML float never reaches the IR (S-0020/D-5).

    **What it cannot see, stated:** a group with no rows produces no row to
    aggregate, so an assertion over a mart cannot notice a month that is
    entirely *missing* — only one whose total is out of bounds. Closing that
    needs a join against the date spine, which is a different check with a
    different dependency (S-0033/D-89).
    """

    name: RuleName
    measure: str
    agg: MartAggregate
    by: tuple[str, ...] = ()
    min: RangeBound | None = None
    max: RangeBound | None = None
    #: ``fail`` blocks the run; ``flag`` emits a non-blocking audit — the same
    #: two readings ``reconcile.on_fail`` carries (S-0033/D-38). ``quarantine``
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
    meaningful — chains flatten transitively, S-0027/spec-kind), measures,
    partitioning, aggregate assertions, and the tie-breaking ``cost_hint``
    (S-0027/D-8)."""

    grain: str
    base: str
    flatten: tuple[FlattenStep, ...] = ()
    measures: tuple[str, ...] = ()
    #: The weakest evidence this consumer accepts under its measures
    #: (S-0070/the-annotation). ``assumed`` is the default and is what every project
    #: does today, so absence is byte-identical to not having the key (D3).
    #:
    #: There is no ``open``: it would mean "accept anything", which is the
    #: absence of the annotation rather than a third setting.
    #:
    #: A plain literal rather than :class:`~bloomery.semantic.EvidenceGrade`,
    #: because the spec layer sits below ``semantic`` in the import contract.
    #: The guardrail maps the string; the two are pinned equal by a test, the
    #: way every other spelled-out vocabulary in this package is.
    requires_evidence: Literal["locked", "assumed"] = "assumed"
    partition_by: tuple[PartitionSpecString, ...] = ()
    materialization: MaterializationName | None = None
    assert_: tuple[MartAssert, ...] = Field(default=(), alias="assert")
    cost_hint: int = Field(default=1, ge=1)
    #: Who is responsible for this, as a free string (S-0062/owner). Reaches
    #: every target's owner slot and changes no SQL.
    #:
    #: **A declaration bloomery does not verify.** Nobody is paged, the name is
    #: not checked against a directory, and an owner who has left reads exactly
    #: like one who has not. Not validated as an email, a handle or a team name
    #: either (D8): every project spells this differently, and a format rule
    #: would refuse spellings that are correct for their reader.
    owner: str | None = None
    #: Who may read the relation this becomes (S-0062/grants). Unlike the two
    #: annotations above, this one is **applied** — by the framework, on the
    #: engine — so being wrong changes who can read data.
    grants: Grants | None = None


# ....................... #


class RollupMart(SpecModel):
    """A mart at a coarser grain than one this project already builds
    (S-0065/the-shape), declared under the document's ``rollups:`` key.

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
    write, which is not what a source path is (S-0019/source-paths). Two keys in one
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
    #: canonicalizes a repeat rather than refusing it (S-0065 row 16), which
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
    #: Who may read the relation this rollup becomes (S-0062/D-12).
    #:
    #: Its own, not the parent mart's. D2's rule is that authored nodes do not
    #: inherit, and a rollup is authored — so a rollup over a restricted mart is
    #: **not** restricted until it says so, and one that says nothing is the
    #: advisory of row 11 rather than a silent hole. That is the opposite of an
    #: entity's ``<entity>__reject`` table, which does inherit, because a reject
    #: table is generated rather than authored.
    grants: Grants | None = None

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
    (S-0027/D-7)."""

    #: Pinned to the one version bloomery implements (S-0035/D-7). It was
    #: ``int`` with ``ge=1``, which accepted a document written for a future
    #: bloomery and silently applied v1 semantics to it — the exact misreading
    #: a version key exists to refuse. This key is also the document-kind
    #: discriminator, so it stays required: a document without one cannot be
    #: identified at all.
    marts_version: Literal[1]
    marts: dict[RelationName, Mart]
    #: Rollups of the marts above (S-0065/the-obligation). A second key of the same
    #: document rather than a document of its own: a rollup is meaningless
    #: without the mart it names, and the two are authored together.
    rollups: dict[RelationName, RollupMart] = Field(default_factory=dict)

    # ....................... #

    @model_validator(mode="after")
    def _rollups_name_a_mart(self) -> Self:
        """A rollup's parent is a mart of this document, and its own name is
        not one (S-0065/D-10).

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
                    "gold layer, so the two would build one table (S-0027/martir). Fix: name "
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
