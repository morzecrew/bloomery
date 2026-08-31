"""The total ``BloomeryError`` hierarchy (RFC 0002 §5.4).

Every failure the package can raise derives from :class:`BloomeryError` and
carries a human message plus an optional ``source_path`` — a dotted/bracketed
address into the authored spec document (RFC 0002 §5.3). All leaf classes are
declared here, in one module importable without pulling in any pipeline stage,
so callers can write a single ``except BloomeryError`` (RFC 0002 D3).

Batched stages (parse — RFC 0002 D6; resolution — RFC 0005 D7; guardrails —
RFC 0006 D2) collect their individual failures and raise one aggregate error
listing every path: authors fix a spec in one round-trip, not one error at a
time. The aggregation surface is :attr:`BloomeryError.collected` plus the
:meth:`BloomeryError.from_collected` constructor.

**Fix suggestions** (RFC 0020 §5.4, D7). Five refusals carry a structured next
action beside the prose, because a human reads a message and a proposal loop
reads a *structure*. Each field exposes a value bloomery already computed on
its way to writing the message, and until now threw away there —
:attr:`UnknownMember.did_you_mean`, :attr:`UnreachableAtGrain.covering_marts`,
:attr:`GrainViolation.offending_measures`,
:attr:`UnknownStep.available_versions`,
:attr:`UnsupportedFilter.nearest_supported`. Every one is always present and
carries a default (``()`` or ``None``): absence has one representation per
surface, and "the attribute is missing" is not it. An empty suggestion is a
*fact* — genuinely nothing covers the request — never a search that was
skipped, and nothing is discoverable only through a suggestion (D8): the
primary contract stays the message and, for :class:`UnsupportedFilter`, the
``reason`` code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Iterable

# ----------------------- #

__all__ = [
    "BloomeryError",
    "MartCoverage",
    "MeasureRef",
    "SpecParseError",
    "UnknownTransformError",
    "TypeCheckError",
    "TransformRegistrationError",
    "ResolutionError",
    "CircularDerivation",
    "MissingReference",
    "GuardrailError",
    "InvariantViolated",
    "UnitMismatch",
    "TaxBasisMismatch",
    "CurrencyMismatch",
    "GrainMismatch",
    "AdditivityViolation",
    "AssertLoweringError",
    "GrainViolation",
    "guaranteed",
    "FanoutRisk",
    "HistoricalFanout",
    "NonAdditiveWithoutComponents",
    "UnsupportedCumulative",
    "MartMissingTimeDimension",
    "QuarantineRetentionMissing",
    "DedupeTieBreakMissing",
    "DedupeDispositionConflict",
    "IngestionMetadataMissing",
    "RedactionConflict",
    "StepError",
    "UnknownStep",
    "StepDeterminismError",
    "StepContractViolation",
    "PlanError",
    "ContractViolation",
    "RenameTargetMissing",
    "EmitError",
    "UnsupportedByTarget",
    "PlannerError",
    "UnknownMember",
    "UnreachableAtGrain",
    "AmbiguousDimension",
    "InvalidRequest",
    "FilterTypeMismatch",
    "UnsupportedFilter",
    "UnsupportedSetRelation",
    "UnsupportedHierarchy",
    "UnsupportedTextOperator",
    "FilterTooComplex",
    "UnsupportedNegation",
    "InvalidLiteral",
    "UnsupportedSortNulls",
    "UnsupportedPagination",
    "UnsupportedFieldCompare",
    "UnsupportedQuantifier",
]


# ....................... #
# Suggestion payloads — RFC 0020 §5.4, D11.
#
# Typed values rather than encoded strings. A ``tuple[str, ...]`` could name
# the marts but not say which metric each covers at which grain, which is the
# entire content of the conflict; encoding the triple into
# ``"orders_daily:revenue:day"`` would put a parse step and an undocumented
# format between bloomery and its caller — exactly the machine-readability
# these fields exist to add, so shipping it inside the fix would be
# self-defeating.
#
# They live here, in the bottom layer, because that is where the errors that
# carry them live: nothing under ``src/bloomery/`` may import upward. RFC 0020
# §5.4's table typed both grains as ``TimeGrain``, which cannot be right for
# either — ``TimeGrain`` is the planner's *time bucket* vocabulary
# (``day``/``month``/…), while a mart's and a metric's grain is an **entity**
# name (``order_item``). The field is the entity grain, spelled as the IR
# spells it.


@dataclass(frozen=True, slots=True)
class MartCoverage:
    """One mart's offer of one metric, at the entity grain it serves it at.

    Carried by :attr:`UnreachableAtGrain.covering_marts`. ``mart`` is the
    logical mart name — the spec-level identity a caller acts on, the same one
    :attr:`bloomery.QueryPlan.mart` reports — not the rendered gold relation
    the message quotes.
    """

    mart: str
    metric: str
    grain: str


# ....................... #


@dataclass(frozen=True, slots=True)
class MeasureRef:
    """A mart measure and its own entity grain.

    Carried by :attr:`GrainViolation.offending_measures`: the measure whose
    grain is at odds with the mart's, so a caller can act on the pair without
    parsing the sentence that describes it.
    """

    measure: str
    grain: str


# ....................... #


class BloomeryError(Exception):
    """Base of every error bloomery raises (RFC 0002 §5.4).

    Carries the human message (``str(exc)``), the ``source_path`` into the
    authored document that caused the failure (always set by the parse stage,
    best-effort elsewhere), and — for the batched stages — the ``collected``
    tuple of individual failures this aggregate reports.
    """

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
    ) -> None:
        super().__init__(message)
        self.source_path = source_path
        self.collected = collected

    # ....................... #

    @classmethod
    def from_collected(cls, errors: tuple[BloomeryError, ...]) -> Self:
        """Build one aggregate error whose message lists every collected path.

        Used by the batched stages (RFC 0002 D6): the individual failures stay
        machine-readable on :attr:`collected`; the message enumerates each one
        in collection order (callers pre-sort where determinism demands it).
        """
        lines = [f"{len(errors)} error(s):"]

        for err in errors:
            prefix = f"{err.source_path}: " if err.source_path else ""
            lines.append(f"  - {prefix}{err}")

        return cls("\n".join(lines), collected=errors)


# ....................... #
# Parse stage — RFC 0002


# ....................... #


class InvariantViolated(BloomeryError):
    """A guarantee an earlier stage was supposed to have established did not
    hold (RFC 0003 D11).

    Never an authored spec's fault. Every lookup that raises this is total
    *because a guardrail already refused the case that would break it*, so
    reaching here means the guardrail and the lookup have drifted apart — and
    the message names which guardrail was relied on, because that is the thing
    a reader needs and the traceback cannot supply.
    """


# ....................... #


def guaranteed[T](candidates: Iterable[T], *, expected: str, by: str) -> T:
    """The first candidate, or :class:`InvariantViolated` naming its guarantor.

    ``next(x for x in xs if …)`` over a set an earlier stage validated is the
    idiom this replaces. It is correct and it fails terribly: a bare
    ``StopIteration`` carries no message, no source path and no hint about
    which stage was supposed to prevent it — one escaped from a coverage check
    on an unmapped entity and read as a crash rather than as a missing
    refusal.

    Writing the guarantor at each call site is the point. The invariant was
    real and held everywhere but one, and what it never had was a place to be
    stated where drift would be visible.
    """

    for candidate in candidates:
        return candidate

    msg = (
        f"expected {expected}, which {by} is supposed to guarantee — reaching here means "
        "that check and this lookup disagree. This is a bug in bloomery, not in the spec"
    )
    raise InvariantViolated(msg)


# ....................... #


class SpecParseError(BloomeryError):
    """Raised by the parse stage (loaders, RFC 0002): YAML failures, duplicate
    keys, shape/unknown-key validation failures — batched per document (D6)."""


# ....................... #
# Typing and transforms — RFC 0004


# ....................... #


class UnknownTransformError(BloomeryError):
    """Raised by the typecheck stage (RFC 0004) when a transform chain names a
    transform absent from the registry; the message names the closest match."""


# ....................... #


class TypeCheckError(BloomeryError):
    """Raised by the type layer (RFC 0004): unparsable type strings and
    transform chains whose terminal type is not assignable to the declared."""


# ....................... #


class TransformRegistrationError(BloomeryError):
    """Raised by ``register_transform`` (RFC 0004) when a transform spec is
    invalid or collides with an already-registered name."""


# ....................... #
# Resolution — RFC 0005


# ....................... #


class ResolutionError(BloomeryError):
    """Raised by the resolution stage (RFC 0005): cross-spec reference and
    recipe failures over the dependency DAG — batched per stage (D7)."""


# ....................... #


class CircularDerivation(ResolutionError):
    """Raised by the resolution stage (RFC 0005 D4) on any cycle in the
    dependency DAG; the message names the full cycle path."""


# ....................... #


class MissingReference(ResolutionError):
    """Raised by the resolution stage (RFC 0005 D7) when a spec references a
    nonexistent entity, field, canonical field, template, or relationship end."""


# ....................... #
# Guardrails — RFC 0006 (mart-level leaves: RFC 0010; MetricFlow: RFC 0013)


# ....................... #


class GuardrailError(BloomeryError):
    """Raised by the guardrail stage (RFC 0006): the aggregate whose
    ``collected`` violations are sorted by ``(source_path, type name)``."""


# ....................... #


class UnitMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.2): operands of ``+``/``-`` with differing
    *declared* ``unit`` metadata (currency + count is the bug)."""


# ....................... #


class TaxBasisMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.2, worked example §5.7): ``net`` and
    ``gross`` — or an unknown basis alongside a monetary operand — meeting in
    additive arithmetic (unknown poisons, D3)."""


# ....................... #


class CurrencyMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.2): two operands with distinct declared
    ISO-4217 currency codes.

    Unconditional. A ``convert`` step in the chain used to satisfy the rule and
    no longer does (RFC 0023 D5): the transform has no lowering on any dialect,
    so the marker bought a compile-time pass whose only outcome was a run-time
    failure.
    """


# ....................... #


class GrainMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.3): expression combining columns of
    different grains without an explicit aggregation."""


# ....................... #


class AdditivityViolation(GuardrailError):
    """Guardrail stage (RFC 0006 §5.4): an aggregation that contradicts the
    metric's declared additivity."""


# ....................... #


class AssertLoweringError(GuardrailError):
    """Guardrail stage (RFC 0006 D8): an ``assert:`` clause ill-typed against
    the field's logical type."""


# ....................... #


class GrainViolation(GuardrailError):
    """Guardrail stage, mart-level (RFC 0010 D2): a mart measure whose grain
    does not strictly equal the mart grain.

    ``offending_measures`` names the measure and its own grain (RFC 0020
    §5.4). It is empty for the sibling violation this class also carries — a
    mart whose *declared* grain differs from its base entity — where no
    measure is at fault and the mart header is.
    """

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
        offending_measures: tuple[MeasureRef, ...] = (),
    ) -> None:
        super().__init__(message, source_path=source_path, collected=collected)
        self.offending_measures = offending_measures


# ....................... #


class FanoutRisk(GuardrailError):
    """Guardrail stage, mart-level (RFC 0010 D3): a mart ``via:`` flatten step
    over a ``one_to_many`` relationship."""


# ....................... #


class HistoricalFanout(GuardrailError):
    """Guardrail stage, mart-level (RFC 0023 D1/D2): a mart that flattens — or
    is based on — an entity declared ``scd: type2``.

    Distinct from :class:`FanoutRisk` on purpose. That one reports a *declared
    cardinality* the author can go and correct; here the cardinality is
    typically right and the relation is the thing that holds more rows than it
    claims, one per version per key. Pointing one error at both would send the
    reader to a ``cardinality:`` that is already correct.
    """


# ....................... #


class NonAdditiveWithoutComponents(GuardrailError):
    """Guardrail stage (RFC 0006 §5.4, RFC 0011 D5): a non-additive metric
    without a ratio / additive decomposition to recompute it from."""


# ....................... #


class UnsupportedCumulative(GuardrailError):
    """Guardrail stage: a metric declaring ``cumulative:``, which is reserved
    spec surface (RFC 0002 D10) that no stage lowers.

    Refused rather than dropped: until the lowering ships, a ``cumulative:``
    metric would compile as a plain simple metric and every artifact would
    aggregate per period instead of cumulatively — a wrong number with no
    signal, which the compiler exists to refuse.
    """


# ....................... #


class MartMissingTimeDimension(GuardrailError):
    """Guardrail stage (RFC 0010 §5.5 rule 6, RFC 0013 R1): a measure-carrying
    mart that declares no date role."""


# ....................... #
# Guardrails, data-quality leaves — RFC 0016 §5.9. A guardrail says the
# *model* is wrong (compile time, decidable from the spec alone); a quality
# rule says the *data* is wrong (run time, a disposition per row). Everything
# this RFC can decide without data is therefore a ``GuardrailError``.


# ....................... #


class QuarantineRetentionMissing(GuardrailError):
    """Guardrail stage (RFC 0016 §5.6, D10): an entity with a ``quarantine``
    disposition and no ``quarantine.retention`` — reject tables hold raw
    payloads, so retention is required, never defaulted."""


# ....................... #


class DedupeTieBreakMissing(GuardrailError):
    """Guardrail stage (RFC 0016 §5.3, D6): ``dedupe.keep: latest_by`` without
    ``tie_break`` — rows sharing a timestamp would make the winner arbitrary,
    and a nondeterministic model violates the core invariant (RFC 0003)."""


# ....................... #


class DedupeDispositionConflict(GuardrailError):
    """Guardrail stage (RFC 0016 §5.4, D6): a weaker declared ``coercible``
    disposition on a field named by ``dedupe.field``/``tie_break``, where the
    fixed pipeline order forces ``fail`` — an uncastable recency field leaves
    dedupe ordering undefined."""


# ....................... #


class IngestionMetadataMissing(GuardrailError):
    """Guardrail stage (RFC 0016 §5.6, D21): an entity using ``quarantine`` or
    ``dedupe`` whose bronze source lacks ``_load_id``/``_ingested_at``/
    ``_source_row_id``. Their NOT NULL/uniqueness properties are data facts no
    compiler can check — those become a generated blocking audit; *absence* is
    decidable from the spec, so it is this guardrail."""


# ....................... #


class RedactionConflict(GuardrailError):
    """Guardrail stage (RFC 0016 §5.6, D10): a ``quarantine.redact`` JSONPath
    intersecting a path the entity's mappings read (``from`` paths, recipe
    aliases included) — you cannot both require a field and destroy it at
    write time; the message names both sides."""


# ....................... #
# Steps — RFC 0017. Two compile-time refusals and one raised only by
# generated code, at target runtime, which is why it is a sibling of the
# compile hierarchy rather than a GuardrailError: nothing in bloomery ever
# raises it, and nothing in bloomery ever catches it.


# ....................... #


class StepError(BloomeryError):
    """Raised for the referenced-implementation escape hatch (RFC 0017)."""


# ....................... #


class UnknownStep(StepError):
    """Compile stage (RFC 0017 §5.3, D3): a spec references a ``ref@version``
    the :class:`~bloomery.steps.StepRegistry` does not hold. The message names
    the versions that *are* available — there is no dynamic loading path to
    fall back on, by design, so the registry is the whole world.

    ``available_versions`` is that same list as data, ascending (RFC 0020
    §5.4). Empty means the registry holds no version of this ``ref`` at all,
    which is a different repair from pinning a different one.
    """

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
        available_versions: tuple[int, ...] = (),
    ) -> None:
        super().__init__(message, source_path=source_path, collected=collected)
        self.available_versions = available_versions


# ....................... #


class StepDeterminismError(StepError):
    """Compile stage (RFC 0017 §5.5, D5): a step declaring
    ``determinism: nondeterministic``, or a ``seeded`` step wired without a
    seed. A nondeterministic step makes a backfill disagree with the original
    run, which destroys restatement — the capability the architecture is
    organized around, so this is the load-bearing refusal, not caution."""


# ....................... #


class StepContractViolation(StepError):
    """**Run time**, raised only by generated wrapper code (RFC 0017 §5.4,
    D4): the step's actual output contradicts its manifest — a missing or
    undeclared output, a column set that differs, an unassignable type, a null
    in a ``required`` column, or a duplicated grain key. Non-optional and
    non-configurable by construction: a claim that is checked is a commitment,
    a claim that is not is a comment."""


# ....................... #
# Plan — RFC 0007


# ....................... #


class PlanError(BloomeryError):
    """Raised by the plan stage (RFC 0007) when a spec diff cannot produce a
    safe migration plan."""


# ....................... #


class ContractViolation(PlanError):
    """Plan stage (RFC 0007 D5): dropping or narrowing a field still
    referenced by a reachable metric — expand/contract enforced."""


# ....................... #


class RenameTargetMissing(PlanError):
    """Plan stage (RFC 0007 D3): a ``renamed_from`` annotation whose old name
    is absent from the old IR (stale one-shot annotation)."""


# ....................... #
# Emit — RFC 0008


# ....................... #


class EmitError(BloomeryError):
    """Raised by the emit stage (RFC 0008) when the IR cannot be lowered to a
    target artifact."""


# ....................... #


class UnsupportedByTarget(EmitError):
    """Emit stage (RFC 0008 D3): an IR construct the selected target or
    dialect cannot express — fail loud, never approximate."""


# ....................... #
# Planner — RFC 0011 (backend: RFC 0013). Deliberately NOT batched (0011 D9).


# ....................... #


class PlannerError(BloomeryError):
    """Raised by the query planner (RFC 0011) on malformed or unanswerable
    requests; planner errors are not batched (D9)."""


# ....................... #


class UnknownMember(PlannerError):
    """Planner stage (RFC 0011 D3): a request names a metric or dimension that
    does not exist.

    ``did_you_mean`` is the closest known name, or ``None`` when nothing is
    close enough (the message then lists what *is* known). The docstring has
    promised this field since RFC 0011 while the match was computed and
    rendered into prose; RFC 0020 §5.4 makes the sentence true.
    """

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
        did_you_mean: str | None = None,
    ) -> None:
        super().__init__(message, source_path=source_path, collected=collected)
        self.did_you_mean = did_you_mean


# ....................... #


class UnreachableAtGrain(PlannerError):
    """Planner stage (RFC 0011 D3): no single mart can answer the request at
    the requested grain — refuse, never join at plan time.

    ``covering_marts`` is the conflict as data (RFC 0020 §5.4): one
    :class:`MartCoverage` per required measure, naming the mart that *does*
    serve it and the grain it serves it at. Empty means genuinely no mart
    lists the metric as a measure — a different repair (define a mart) from a
    split across grains (request them separately).
    """

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
        covering_marts: tuple[MartCoverage, ...] = (),
    ) -> None:
        super().__init__(message, source_path=source_path, collected=collected)
        self.covering_marts = covering_marts


# ....................... #


class AmbiguousDimension(PlannerError):
    """Planner stage (RFC 0011 D6): an unqualified reference to a dimension
    with multiple roles; the message names the available roles."""


# ....................... #


class InvalidRequest(PlannerError):
    """Planner stage (RFC 0011 D9): bad filter/order/limit shapes or raw SQL
    where a structured request member is required."""


# ....................... #


class FilterTypeMismatch(PlannerError):
    """Planner stage (RFC 0013 D8): a filter value whose type contradicts the
    dimension's logical type — refused before any SQL is rendered."""


# ....................... #
# Query vocabulary — RFC 0015 §5.3: the closed refusal list. Every leaf
# carries a stable ``reason`` code; the union of codes the three parse
# functions can raise is exported as ``bloomery.planner.KNOWN_UNSUPPORTED``.


# ....................... #


class UnsupportedFilter(PlannerError):
    """Planner stage (RFC 0015 §5.3): a query-vocabulary construct bloomery
    deliberately refuses — a *reviewed* gap, never drift.

    Carries ``reason`` (the stable string code adapters key refusal handling
    on), the inherited ``source_path``, and — where the refusal happened
    after normalization — ``normalized``, the post-normalization form, so the
    error is actionable rather than merely correct.

    ``nearest_supported`` (RFC 0020 §5.4) names the operator that would have
    worked, where one exists: ``$regex`` refuses with ``"like"``. It is the
    :class:`~bloomery.Op` *value*, not the member, because this module is the
    bottom layer and the planner's vocabulary sits at the top —
    :class:`~bloomery.Op` is a ``StrEnum``, so ``Op(err.nearest_supported)``
    round-trips and ``err.nearest_supported == Op.LIKE`` holds. ``None`` is
    the common case and is a fact rather than a gap: a set relation has no
    scalar counterpart at all, and ``$empty`` refuses *because* ``eq ""`` and
    ``is_null true`` are different questions — naming one of them here would
    fabricate the choice the refusal exists to make the author state.
    """

    reason: str = "unsupported_filter"

    # ....................... #

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
        normalized: str | None = None,
        nearest_supported: str | None = None,
    ) -> None:
        super().__init__(message, source_path=source_path, collected=collected)
        self.normalized = normalized
        self.nearest_supported = nearest_supported


# ....................... #


class UnsupportedSetRelation(UnsupportedFilter):
    """RFC 0015 §5.3: ``$superset``/``$subset``/``$disjoint``/``$overlaps`` —
    marts are flattened and scalar by construction; no array columns exist
    to relate."""

    reason = "unsupported_set_relation"


# ....................... #


class UnsupportedHierarchy(UnsupportedFilter):
    """RFC 0015 §5.3: ``$descendant_of``/``$ancestor_of`` — backend-specific
    (``ltree``), capability-gated even upstream; model hierarchy as
    flattened level columns on the mart."""

    reason = "unsupported_hierarchy"


# ....................... #


class UnsupportedTextOperator(UnsupportedFilter):
    """RFC 0015 §5.3: ``$regex`` (dialect-divergent, unbounded cost) and
    ``$empty`` (ambiguous across types) — express as ``like``/``ilike``,
    ``eq ""``, or ``is_null true`` explicitly."""

    reason = "unsupported_text_operator"


# ....................... #


class FilterTooComplex(UnsupportedFilter):
    """RFC 0015 §5.2 step 3: CNF expansion exceeded the clause cap — refused
    *during* distribution, before the expansion is ever materialized."""

    reason = "filter_too_complex"


# ....................... #


class UnsupportedNegation(UnsupportedFilter):
    """RFC 0015 §5.2 step 2: a negated leaf with no complement operator
    (e.g. ``$not $like``) — ``not_like`` is added only on demonstrated
    need."""

    reason = "unsupported_negation"


# ....................... #


class InvalidLiteral(UnsupportedFilter):
    """RFC 0015 D5: a non-finite numeric operand (``NaN``/``Infinity``/
    ``-Infinity``, float or string form) or an invalid ``like`` pattern
    (unpaired trailing ``\\``, NUL) — fails open if permitted."""

    reason = "invalid_literal"


# ....................... #


class UnsupportedSortNulls(UnsupportedFilter):
    """RFC 0015 D-Q6: a ``nulls`` placement other than the canonical default
    (``first`` for asc, ``last`` for desc) — accepting-and-dropping would be
    worse than refusing."""

    reason = "unsupported_sort_nulls"


# ....................... #


class UnsupportedPagination(UnsupportedFilter):
    """RFC 0015 D-Q7: a non-zero ``offset`` or cursor pagination — paging
    aggregates belongs to the serving layer (materialize, then page)."""

    reason = "unsupported_pagination"


# ....................... #


class UnsupportedFieldCompare(UnsupportedFilter):
    """Adapter-owned (RFC 0015 §5.3): ``$fields`` field-to-field compare.
    Declared here so adapters can raise it; **never raised by bloomery** and
    its code is not part of ``KNOWN_UNSUPPORTED`` — it belongs to the
    adapter's ``APP_UNSUPPORTED`` set."""

    reason = "unsupported_field_compare"


# ....................... #


class UnsupportedQuantifier(UnsupportedFilter):
    """Adapter-owned (RFC 0015 §5.3): ``$any``/``$all``/``$none`` element
    quantifiers. Declared here so adapters can raise it; **never raised by
    bloomery** and its code is not part of ``KNOWN_UNSUPPORTED`` — it
    belongs to the adapter's ``APP_UNSUPPORTED`` set."""

    reason = "unsupported_quantifier"
