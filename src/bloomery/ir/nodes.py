"""The frozen IR node tree (S-0020/ir-shape–S-0020/ordering-rules; S-0027/dimensionref–S-0027/martir).

Frozen slotted stdlib dataclasses — not Pydantic: the IR is compiler-internal;
it needs hashing and value semantics, its builder is its validator (S-0020
D1). Every collection is a tuple with an explicit lexicographic sort key,
except authored-order fields (``key``, transform chains, ``partition_by``,
mart flatten order — S-0020/D-4). Floats never appear (S-0020/D-5).

The IR *builder* (spec → IR) lands with M2+; in M1 the IR is constructed by
hand in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Final, cast

from sqlglot import parse_one
from sqlglot.expressions.core import Expression

from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
    "UpstreamIR",
    "with_imported",
    "StepParameterIR",
    "step_sort_key",
    "StepOutputIR",
    "StepKind",
    "StepIR",
    "StepColumnIR",
    "Lineage",
    "Determinism",
    "FLAGS_COLUMN",
    "NODE_ID_PREFIXES",
    "RESOLVABLE",
    "COMPUTED",
    "carries_quality_flags",
    "OK_COLUMN",
    "REJECT_SUFFIX",
    "REPAIRS_COLUMN",
    "Additivity",
    "AuditIR",
    "Cardinality",
    "CoverageIR",
    "ColumnIR",
    "DateDimensionIR",
    "DedupeIR",
    "DimensionRef",
    "FxRatesIR",
    "EntityIR",
    "ExportsIR",
    "ExposureIR",
    "ExposureKind",
    "Layer",
    "MartAssertIR",
    "MartColumnIR",
    "MartDimensionIR",
    "MartIR",
    "MartJoinIR",
    "Materialization",
    "CumulativeIR",
    "DerivedIR",
    "MetricFilterIR",
    "MetricIR",
    "MetricInputIR",
    "OnFail",
    "PartitionSpec",
    "ProjectIR",
    "QualityRuleIR",
    "QuarantineIR",
    "Ratio",
    "TimeWindow",
    "ReconcileIR",
    "RollupIR",
    "RelationshipIR",
    "SCDKind",
    "SemiAdditivePolicy",
    "SOURCE_COLUMN",
    "SemiAdditiveRule",
    "SourceColumnIR",
    "SourceFieldIR",
    "SourceIR",
    "SqlExpr",
    "TaxBasis",
    "TransformStepIR",
    "Unit",
    "UnreachableMetric",
    "VALIDITY_COLUMNS",
    "VALID_FROM",
    "VALID_TO",
    "quality_sort_key",
]

# ....................... #
# The physical names the data-quality nodes imply (S-0033/schema-additions-and-the-array-capability–S-0033/quarantine-one-reject-table-per-entity,
# D9/D23/D10). They live in the IR layer rather than in
# :mod:`bloomery.quality.catalogue` (which re-exports them, so every consumer
# keeps its shipped import path) because they are needed on *both* sides of a
# layer boundary: ``quality/`` builds the two generated columns, ``marts/``
# derives ``has_quality_flags`` from ``_quality_ok`` and refuses a mart based
# on a reject table — and the import contract forbids ``marts → quality``.

#: The generated silver flag collection; never NULL (empty array / empty
#: string per :attr:`~bloomery.dialects.DialectFeature.ARRAY`).
FLAGS_COLUMN = "_quality_flags"
#: The generated boolean, ``cardinality(_quality_flags) = 0`` per shape.
OK_COLUMN = "_quality_ok"
#: The **distinct** marker D17 required of ``repair`` before it could land: the
#: rules whose recipe rewrote this row's value (S-0033/D-87). Separate from
#: :data:`FLAGS_COLUMN` on purpose — "repaired, now correct" and "currently
#: suspect" are different facts, and folding the first into the second would
#: change what ``has_quality_flags`` means for every mart that already reads it.
#:
#: Emitted only on entities that carry a repair rule, unlike the two above.
#: §12 budgeted the silver-schema churn of ``_quality_flags`` once; a third
#: universal column would re-open every golden and fingerprint again to add a
#: column that is empty for every project not using the feature.
REPAIRS_COLUMN = "_quality_repairs"
#: One ``<entity>__reject`` per entity, never per mapping (D10).
REJECT_SUFFIX = "__reject"
#: The lineage node-id prefixes (S-0048/every-label-is-handled-and-the-vocabulary-is-closed-here, S-0059/the-node-id-collision-refused-at-its-cause; ``exposure``
#: added by S-0063/the-graph, ``mart`` by S-0072/the-node). Every node id but an
#: entity field's is ``<prefix>.<rest>``; an entity field is
#: ``<entity>.<field>`` bare, so an entity named after one of these mints
#: ids in another kind's namespace.
#: Reserved as entity names for that reason.
#:
#: Here rather than beside the node builders in ``resolve.graph`` because the
#: guardrail that refuses them sits *below* ``resolve`` in the layer contract
#: and cannot import it. ``tests/unit/test_resolve/test_graph.py`` pins the
#: two together: every builder's id must start with a member of this tuple,
#: so a node kind added with a new prefix fails there rather than silently
#: escaping the reservation.
NODE_ID_PREFIXES: Final = ("canonical", "exposure", "mart", "metric", "source", "step")
#: The provenance column a **merged** entity carries: which source relation a
#: row came from (S-0041/D-7). Load-bearing rather than diagnostic — the
#: collision audit reports *which* sources shared a key, and without it the
#: report is "this key is duplicated somewhere", which is not actionable on a
#: five-source entity.
#:
#: Emitted only on merged entities, like :data:`REPAIRS_COLUMN` and unlike the
#: two universal columns (D7): on a single-source entity it is a constant, and
#: putting a constant into every relation forever to spare one classified
#: change is how a schema move gets hidden from ``plan()``.
SOURCE_COLUMN = "_source"

#: The validity interval of an ``scd: type2`` relation (S-0040/phase-2-the-as-of-join, S-0040/D-7).
#:
#: Unlike every other name in this section these columns are not projected by
#: bloomery's own lowering — the target's snapshot machinery writes them. That
#: is exactly why they are named here: SQLMesh calls them ``valid_from`` /
#: ``valid_to`` and dbt calls them ``dbt_valid_from`` / ``dbt_valid_to``, each
#: privately, so before this pair existed bloomery did not know what the
#: interval was called and could emit no predicate against it. Both emitters
#: now *configure* their target to these names, which is what lets one as-of
#: predicate serve both.
#:
#: Deliberately not underscore-prefixed like the generated columns above: these
#: are written by the target under names it already treats as ordinary, and
#: renaming them to bloomery's convention would buy nothing but a diff. They
#: are refused as authored field names on a ``type2`` entity, where they would
#: collide.
VALID_FROM = "valid_from"
VALID_TO = "valid_to"

#: The two above, for membership tests and messages.
VALIDITY_COLUMNS = (VALID_FROM, VALID_TO)


# ....................... #
# Enums (values are the spec-layer vocabulary; fingerprint encodes by value)


class SCDKind(StrEnum):
    """Slowly-changing-dimension kind (original spec §3.3)."""

    TYPE1 = "type1"
    TYPE2 = "type2"


# ....................... #


class Materialization(StrEnum):
    """Resolved materialization strategy (S-0019/D-7 — explicit or derived)."""

    FULL = "full"
    INCREMENTAL_BY_KEY = "incremental_by_key"
    INCREMENTAL_BY_PARTITION = "incremental_by_partition"


# ....................... #


class StepKind(StrEnum):
    """The ladder tier a step occupies (S-0034/the-four-tier-ladder, S-0034/D-1). Tier 0 is the
    transform whitelist and is not a step: a step kind names a tier that needs
    a body somebody wrote."""

    SQL_MACRO = "sql_macro"
    SQL_MODEL = "sql_model"
    PYTHON_MODEL = "python_model"


# ....................... #


class Determinism(StrEnum):
    """S-0034/determinism-tiers, S-0034/D-5. ``NONDETERMINISTIC`` reaches the IR only in the
    sense that it is spellable in a manifest — the compile stage refuses it,
    because a step whose backfill disagrees with the original run destroys
    restatement, the capability the architecture is organized around."""

    PURE = "pure"
    SEEDED = "seeded"
    NONDETERMINISTIC = "nondeterministic"


# ....................... #


class Lineage(StrEnum):
    """Whether a step's outputs can be traced column by column (S-0034
    §5.1). Tier 3 loses it, and says so rather than letting a consumer infer
    it from the kind."""

    COARSE = "coarse"
    COLUMN = "column"


# ....................... #


class Layer(StrEnum):
    """Warehouse layer, consumed by naming policies (S-0025)."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


# ....................... #


class Unit(StrEnum):
    """Unit metadata driving the unit-coherence guardrail (S-0023/metadata-provenance-unit-tax-basis-currency);
    a column without catalog metadata is ``UNKNOWN``."""

    CURRENCY = "currency"
    COUNT = "count"
    UNKNOWN = "unknown"


# ....................... #


class TaxBasis(StrEnum):
    """Tax-basis metadata (S-0023/metadata-provenance-unit-tax-basis-currency): ``net`` and ``gross`` never meet
    in additive arithmetic; ``UNKNOWN`` poisons it."""

    NET = "net"
    GROSS = "gross"
    UNKNOWN = "unknown"


# ....................... #


class Additivity(StrEnum):
    """How a measure may be aggregated across a rollup dimension
    (S-0019/spec-model-surface; closed as a typed set by S-0053/D-1).

    Closed from the first commit that names it, which is what D1 locks: the
    planner, the proof rules and every emitter branch on this, and an open
    string set would make each target the authority for what a measure means.
    Staging the *lowering* of a member is allowed (§12) and staging the member
    itself is not.

    ``SNAPSHOT`` is therefore defined and **not minted by resolution** —
    :data:`RESOLVABLE` pins which members a project can produce. That pin is
    not decoration: a member that became reachable without each site being
    revisited would silently take a branch written for a different meaning,
    and mypy would say nothing. A snapshot's declaration is ``semi_additive``
    with a ``rule``: §4's "explicit time-selection before cross-time
    aggregation" is exactly ``{over, rule: first|last}``, and an authored
    ``snapshot`` beside it would give one fact two spellings (logs/T-0028.md).

    What most of those sites ask is not additivity at all but whether a metric
    is a *stored* measure or is computed at query time from its components, and
    that question now has a name of its own in :data:`COMPUTED`. Minting
    ``RATIO`` is what forced it: fifteen sites read ``NON_ADDITIVE``, and
    twelve of them meant something other than that member — nine "never emits
    a measure", three "a ratio specifically" — so splitting a second member out
    of the class narrowed every one of the twelve at once, with nothing in the
    tree failing (logs/T-0023.md, D-146). ``SNAPSHOT`` and ``DISTINCT_COUNT``
    are stored measures, so :data:`COMPUTED` is complete for all six members;
    minting ``DISTINCT_COUNT`` was the enum edit and a lowering D8 promised,
    not a second sweep (logs/T-0028.md).
    """

    ADDITIVE = "additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"
    #: Numerator and denominator semantics, never the materialized quotient:
    #: ``SUM(num)/SUM(den)`` and ``AVG(ratio)`` differ, and the second is what
    #: a numeric-looking column invites (S-0053/D-2).
    RATIO = "ratio"
    #: Carries the counted identity — ``agg: count_distinct`` over the column
    #: that names it. Computed from rows at the requested grain and never
    #: rolled up from a coarser result: additive across partitions only under a
    #: disjointness proof no rule yet supplies, so it stays out of branch
    #: planning (S-0055/D-8).
    DISTINCT_COUNT = "distinct_count"
    #: Point-in-time state, requiring explicit time-selection semantics
    #: (first/last/as-of) before any cross-time aggregation.
    SNAPSHOT = "snapshot"


#: The members a project can resolve to, and the canary that keeps ``SNAPSHOT``
#: — in the closed set by D1, declared through ``semi_additive`` rather than
#: by its own word — from becoming reachable by accident (S-0053/phasing).
#:
#: Minting a new one is a real change, not a widening. The commit that mints
#: one updates this tuple, and the test asserting it fails until then — which
#: is the point, since no other check in the tree can see the difference.
RESOLVABLE: Final = (
    Additivity.ADDITIVE,
    Additivity.SEMI_ADDITIVE,
    Additivity.NON_ADDITIVE,
    Additivity.RATIO,
    Additivity.DISTINCT_COUNT,
)

#: The members whose metrics are **recomputed at query time from components**
#: rather than emitted as a stored measure — the question nine of the fifteen
#: sites across the emitters, the planner and the guardrails were asking when
#: they read ``NON_ADDITIVE`` (S-0053/D-1; logs/T-0023.md, D-146).
#:
#: Membership is a property of the class, not a shape of the metric: a ratio
#: is recomputed from its operands, a `derived:` metric from its inputs, and
#: the expression-over-components form from its dependencies, and all three
#: are one answer to "does this emit a measure?". Testing the property rather
#: than a member is what keeps minting the remaining two an enum edit — every
#: site that means this asks it here, so a new member joins this tuple or does
#: not, once.
COMPUTED: Final = (
    Additivity.NON_ADDITIVE,
    Additivity.RATIO,
)


# ....................... #


class Cardinality(StrEnum):
    """Relationship cardinality (original spec §3.2)."""

    MANY_TO_ONE = "many_to_one"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"


# ....................... #


class OnFail(StrEnum):
    """A quality rule's row disposition (S-0033/the-disposition-model, S-0033/D-2) — explicit per
    rule, never a global default.

    Deliberately no ``DROP``: silently discarding rows is the fastest way for a
    BI product to lose trust permanently, and it is the disposition everyone
    reaches for first. ``QUARANTINE`` *is* drop plus recoverability — most
    quarantined rows return after a spec fix.

    ``REPAIR`` was deferred out of v1 (D17) and joined the vocabulary when
    S-0034's step registry supplied the recipe contract it was gated on
    (D87). It is the one member that is not a disposition on its own: a repair
    rule carries a ``fallback`` for the row its recipe did not fix, and
    :func:`~bloomery.quality.disposition` resolves it to that fallback — so
    severity, routing and precedence never see ``REPAIR`` at all.

    Severity order for a row failing several rules is ``FAIL > QUARANTINE >
    FLAG`` (D18), which makes every combination deterministic — so no
    rule/disposition pair needs compile-time rejection.
    """

    FLAG = "flag"  # row passes unchanged; recorded in _quality_flags
    QUARANTINE = "quarantine"  # row diverted to <entity>__reject; replayable
    FAIL = "fail"  # blocking audit; the run stops
    REPAIR = "repair"  # recipe rewrites the value; resolves to `fallback`


# ....................... #


class SemiAdditiveRule(StrEnum):
    """Rule applied along a semi-additive metric's ``over`` dimension
    (S-0028/D-5)."""

    LAST = "last"
    FIRST = "first"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


# ....................... #
# SQL expressions (S-0020/sql-expressions-in-the-ir-sqlexpr)


# ....................... #


@lru_cache(maxsize=512)
def _parse_sql(sql: str) -> Expression:
    """Parse canonical dialect-neutral SQL once per distinct string.

    The cached AST is never handed out directly — :meth:`SqlExpr.ast` returns
    a copy, so the cache can never be mutated through a caller.
    """

    # ``parse_one`` is annotated with the ``Expr`` base, but every node it can
    # return (including multi-statement ``Block``) is an ``Expression``.
    return cast("Expression", parse_one(sql))


# ....................... #


@dataclass(frozen=True, slots=True)
class SqlExpr:
    """A SQL expression held as its canonical dialect-neutral string — the
    string is the value (hashable, version-stable equality); dialect-specific
    rendering re-parses at emit (S-0020/D-2)."""

    sql: str

    # ....................... #

    def ast(self) -> Expression:
        """A fresh SQLGlot AST for this expression — always a copy; mutating
        the returned tree never affects other callers."""

        return _parse_sql(self.sql).copy()


# ....................... #
# Silver: entities (S-0020/ir-shape)


# ....................... #


@dataclass(frozen=True, slots=True)
class PartitionSpec:
    """One partition entry: an optional transform (``days``/``months``/
    ``years``/``hours``) over a column; ``transform=None`` is identity."""

    transform: str | None
    column: str


# ....................... #


@dataclass(frozen=True, slots=True)
class AuditIR:
    """A target-native audit lowered from an ``assert:`` clause (S-0023
    §5.6); ``params`` is a tuple of (name, value) pairs sorted by name."""

    kind: str
    column: str
    params: tuple[tuple[str, str], ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class TransformStepIR:
    """One resolved transform-chain step (authored order is semantic)."""

    name: str
    args: tuple[str | int, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class SourceColumnIR:
    """One column's **lowering**, for one source (S-0041/D-26).

    The half of the old ``ColumnIR`` that came from a mapping: the canonical
    lowered expression, and the recorded recipe id when the mapping derived
    the value rather than reading it. One of these per entity column per
    source, so several mappings can build one entity and each contributes its
    own projection to the ``UNION ALL``.

    **Column-grained, unlike :class:`SourceFieldIR`**, and the distinction is
    why this is a separate node rather than two more fields there. A recipe
    field mapping reads several bronze paths to produce one column, so it
    yields several ``SourceFieldIR`` and exactly one of these — hanging the
    expression on the path-grained node would store it once per path with no
    single place to read it from.

    ``name`` matches the :class:`ColumnIR` it lowers; the two collections are
    joined by name rather than by position, because a mapping's columns sort
    the same way but nothing enforces alignment.
    """

    name: str
    expr: SqlExpr
    recipe_id: str | None = None
    #: The canonical SQL of every raw extraction this branch reads for the
    #: column — what the ``coercible`` marker compares the produced value
    #: against (S-0041/D-32). Per source rather than on the rule, because the
    #: paths are one mapping's and the rule is evaluated once over the merged
    #: relation: carrying them on the rule would make source B's branch read
    #: source A's ``$.a.b`` off a bronze relation that need not have it.
    #: Empty for a column outside the quality system.
    sources: tuple[str, ...] = ()
    #: This branch's ``enum_map`` targets, deduplicated and sorted — the set
    #: ``in_enum`` admits for rows from this source (S-0041/D-32). Two
    #: mappings may map different spellings onto different vocabularies, so
    #: the admissible set is a branch fact exactly as ``sources`` is.
    enum_values: tuple[str, ...] = ()
    #: This branch's ``enum_map`` spellings, deduplicated and sorted. Carried
    #: for the same reason the rule used to carry them: a widening that points
    #: a new spelling at an existing target changes no target, and ``plan()``
    #: could not see it otherwise (S-0033/tests-rfc-0009-amendment).
    enum_spellings: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class SourceFieldIR:
    """One lowered (target field ← source path) entry with its chain."""

    target_field: str
    source_path: str
    transform: tuple[TransformStepIR, ...] = ()
    #: The zone this path's wall clocks were written in, as the mapping
    #: declared it (S-0076/zonein-is-how-a-utc-source-says-so) — ``None`` where nothing was declared,
    #: which is every project that predates the key.
    #:
    #: Here rather than on :class:`SourceColumnIR` because the declaration is a
    #: fact about *the path the value was read from*, and this is the node
    #: grained that way. A recipe field reads several paths to produce one
    #: column and carries no ``zone_in:`` at all, so nothing is stored twice.
    #:
    #: The chain beside it is the other half of the same question: R018 asks
    #: whether a value that reached a boundary was ever an undeclared wall
    #: clock, and ``transform`` already says whether ``parse_ts`` made it one.
    zone_in: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class FreshnessIR:
    """The declared staleness thresholds for one bronze relation (S-0064
    §5.1), carried verbatim from the mapping.

    Strings rather than a count and a unit, because the spec's grammar is the
    one vocabulary both halves already share (D3) and splitting it here would
    mean two representations of ``6h`` in one pipeline. The target's own
    vocabulary is the emitter's problem — dbt wants ``{count, period}`` and has
    no week, so ``_sources_artifact`` is where a week becomes seven days.

    Nothing measured lives here. A threshold is a declaration; the framework
    runs the query (D1).
    """

    warn_after: str
    error_after: str


# ....................... #


@dataclass(frozen=True, slots=True)
class SourceIR:
    """The bronze relation an entity is built from, with its field lowering
    entries sorted by target field (minimal M1 surface).

    ``mapping_version`` is the authored ``mapping_version:`` of the document
    that produced this entity. It reaches the IR because the reject table's
    schema carries it (S-0033/quarantine-one-reject-table-per-entity): a quarantined row records *which
    version of which mapping* rejected it, or replay cannot tell a row that
    still fails from a row the mapping has since learned to read.

    ``unmapped`` is the acknowledged tail — bronze paths the mapping declares
    exist and deliberately does not read, sorted. It reaches the IR for the
    same reason: the reject table's ``raw`` column is *the bronze payload*,
    not the mapped subset, and ``quarantine.redact`` only ever has something
    to remove there (a redacted path that the mapping reads is the compile
    error ``RedactionConflict``, S-0033/quarantine-one-reject-table-per-entity).
    """

    relation: str
    fields: tuple[SourceFieldIR, ...] = ()
    #: This source's projection of each entity column, sorted by name
    #: (S-0041/D-26). ``fields`` is what the reject payload and replay read;
    #: this is what the SELECT projects. The two answer different questions
    #: and are grained differently — see :class:`SourceColumnIR`.
    columns: tuple[SourceColumnIR, ...] = ()
    mapping_version: int = 1
    unmapped: tuple[str, ...] = ()
    #: The declared staleness thresholds for ``relation`` (S-0064/the-spec-surface), or
    #: ``None`` where the mapping declares none — never defaulted (D5).
    #:
    #: Per source rather than per entity because that is the grain the
    #: declaration has: a merged entity reads several relations and each has
    #: its own arrival schedule. Two mappings of *one* relation disagreeing is
    #: refused before this node is built
    #: (:mod:`bloomery.guardrails.quality`, D2a).
    freshness: FreshnessIR | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class ColumnIR:
    """One entity column's **schema**: declared type and catalog metadata.
    ``description`` comes from the canonical field, when one is bound — it is
    carried into semantic-layer emissions (S-0030 R1).

    **The lowered expression is not here** (S-0041/D-26). Every field on this
    node is derived from the EntityModel ``Field`` and the catalog, so it is
    identical for every mapping that targets the entity — by construction,
    not by convention. What comes from a *mapping* — the lowered ``expr`` and
    the recorded ``recipe_id`` — lives on :class:`SourceColumnIR`, one per
    source, which is what lets several mappings build one entity.

    The split follows a line the builder already drew: ``_column_ir`` took
    ``field``/``catalog`` for everything here and exactly two arguments from
    the mapping.
    """

    name: str
    type: LogicalType
    canonical: str | None
    unit: Unit | None
    tax_basis: TaxBasis | None
    #: Declared on the EntityModel ``Field``, not on a mapping — so it is
    #: schema like the rest of this node, and stays here (S-0041/D-26).
    renamed_from: str | None
    required: bool
    description: str | None = None
    #: What class of data this column holds (S-0062/classification), carried unchanged
    #: from the field. A plain string rather than an enum for the same reason
    #: the spec's vocabulary is a `Literal`: the value travels to metadata and
    #: nothing here branches on it.
    classification: str | None = None
    #: The entity's own columns each value of this one fixes (S-0079/D-1),
    #: carried unchanged from the field the way ``classification`` is. An
    #: authored fact that appears in no other IR field and that no compile can
    #: recover, so the IR stores it rather than deriving it; what follows from
    #: it — the transitive closure, the mart-namespace mapping a rollup proof
    #: reads — is derived at the point of use and stored nowhere.
    determines: tuple[str, ...] = ()


# ....................... #
# Silver: data quality (S-0033/spec-schema–S-0033/quarantine-one-reject-table-per-entity)


# ....................... #


@dataclass(frozen=True, slots=True)
class QualityRuleIR:
    """One lowered quality rule — field rule or row rule, one node either way
    (the fixed pipeline order, not the node type, is what separates them).

    ``column`` is the target column for a field rule and ``None`` for a row
    rule (``expression``, ``referential``), which is evaluated over the whole
    row. ``params`` carries the rule's kind-specific settings as (name, value)
    pairs sorted by name — the same shape as :class:`AuditIR`, values
    stringified so the canonical encoding never sees a float.

    ``on_fail`` is ``None`` for exactly one rule kind: ``referential`` carries
    its disposition as the ``on_missing`` param instead, because its
    ``unknown_member`` value is *not* an :class:`OnFail` — the row passes with
    its fk rewritten to the reserved member, neither flagged nor diverted
    (S-0033/fixed-pipeline-order-and-lowering, S-0033/D-19). Folding it into ``FLAG`` would misdescribe the
    lowering; widening ``OnFail`` would contradict §5.1's three-value model.
    """

    name: str
    kind: str
    column: str | None
    on_fail: OnFail | None
    params: tuple[tuple[str, str], ...] = ()


# ....................... #


def quality_sort_key(
    rule: QualityRuleIR,
) -> tuple[str, str, str, tuple[tuple[str, str], ...], str]:
    """The canonical order of :attr:`EntityIR.quality` — one function so no
    consumer can invent a second one. Total over the node's whole value, so
    two rules that would sort equal are the same rule (S-0020/ordering-rules).

    ``on_fail`` is the last component and it is **load-bearing**, not
    decoration (S-0033/D-50): name generation walks this order, so two rules
    differing only in their disposition sorting equal made the assignment fall
    through to authored order — swapping two YAML lines then compiled the same
    spec to two different IRs. It sorts last so it only ever breaks a tie
    nothing else could break.
    """

    return (rule.kind, rule.column or "", rule.name, rule.params, str(rule.on_fail or ""))


# ....................... #


@dataclass(frozen=True, slots=True)
class DedupeIR:
    """Entity-level dedupe (S-0033/fixed-pipeline-order-and-lowering, S-0033/D-20), lowered to a ``ROW_NUMBER``
    over ``PARTITION BY <entity key>``.

    The sort order is total by construction: ``field`` DESC, then each
    ``tie_break`` column DESC, then the stable source-row identity
    ``_source_row_id`` DESC — every key ``NULLS LAST``. ``tie_break`` keeps
    authored order (it is a sort order, therefore semantic — S-0020/D-4);
    empty here means the compile stage has yet to refuse it
    (``DedupeTieBreakMissing``), never that ties are allowed.
    """

    keep: str
    field: str
    tie_break: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class QuarantineIR:
    """The per-entity ``<entity>__reject`` policy (S-0033/quarantine-one-reject-table-per-entity, S-0033/D-10).

    ``retention`` is the grammar-validated duration string (``90d``) and is
    mandatory wherever a ``quarantine`` disposition exists — reject rows hold
    raw source payloads. ``redact`` is the JSONPath list applied to ``raw``
    and ``key_values`` at write time, sorted (it is a set of paths; authored
    order carries nothing).
    """

    retention: str
    redact: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class ReconcileIR:
    """One cross-entity reconciliation check (S-0033/spec-schema) — the check that
    catches a *correct formula over wrong data*. ``tolerance`` is a
    :class:`~decimal.Decimal`; floats never enter the IR (S-0020/D-5)."""

    name: str
    left: str
    right: str
    tolerance: Decimal
    on_fail: OnFail


# ....................... #


@dataclass(frozen=True, slots=True)
class CoverageIR:
    """One cross-entity coverage check (S-0033/D-90): every row of a
    relationship's referenced entity has at least ``minimum`` rows referencing
    it.

    Carries ``blocking`` rather than an :class:`OnFail`, for the reason
    :class:`MartAssertIR` does: an ``OnFail`` routes a *row*, and this check's
    verdict is about a row of the entity the audit is **not** attached to.
    """

    name: str
    relationship: str
    minimum: int
    blocking: bool


# ....................... #


@dataclass(frozen=True, slots=True)
class GrantsIR:
    """Who may read a relation (S-0062/grants).

    A record rather than a bare tuple so that "no role may select" and "no
    opinion" stay different values: ``GrantsIR(select=())`` is the first and
    ``None`` is the second (D6). A tuple alone would collapse them into an
    empty sequence that reads as both.
    """

    select: tuple[str, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class EntityIR:
    """One silver entity: key in authored order (it is meaningful), columns
    sorted by name, audits sorted by (kind, column).

    ``quality`` is sorted by :func:`quality_sort_key` —
    ``(kind, column or "", name, params, on_fail)``, a total key over the
    node's whole value, so permuting the authored rule order can never change
    the IR even before rule names are generated, and two rules of one kind on
    one column (``range min`` and ``range max``, §5.3's worked example) still
    order deterministically by their bounds. The trailing ``on_fail`` is not
    decoration: without it two rules differing only in disposition sort equal,
    and name generation falls through to authored order (S-0033/D-50). Read
    that function, not this sentence, for the authority.
    """

    name: str
    grain: str
    key: tuple[str, ...]
    scd: SCDKind
    materialization: Materialization
    partition_by: tuple[PartitionSpec, ...]
    columns: tuple[ColumnIR, ...]
    #: The bronze relations this entity is built from, sorted by ``relation``
    #: (S-0041/D-1, S-0041/D-3). More than one is a **union merge**: the silver model
    #: is a ``UNION ALL`` of one projection per source, in this order, so the
    #: emitted SQL is byte-identical across processes. Row order is not
    #: claimed — ``UNION ALL`` is a bag (D3).
    #:
    #: A step-produced entity has exactly one, naming its own output relation
    #: with identity projections — it is not a mapping, and D21 refuses mixing
    #: it with one: the union has nothing to order a step output by, and
    #: ``produced_by`` already means bloomery builds no SELECT for it.
    sources: tuple[SourceIR, ...]
    audits: tuple[AuditIR, ...] = ()
    quality: tuple[QualityRuleIR, ...] = ()
    dedupe: DedupeIR | None = None
    quarantine: QuarantineIR | None = None
    #: ``ref@version`` of the step that writes this entity, or ``None`` for an
    #: ordinary mapped one (S-0034/emission-and-the-dag).
    #:
    #: A step output *is* an entity — that is what lets marts, metrics and
    #: downstream mappings reference it "like any silver entity" — but it is
    #: not one bloomery builds a SELECT for: the step's generated wrapper
    #: writes the relation. Without this marker the emitter's entity loop
    #: would emit a second model at the same path, which is the collision D28
    #: refuses everywhere else.
    produced_by: str | None = None
    #: Who is responsible for this (S-0062/owner), carried unchanged to
    #: whichever targets have an owner slot. A declaration bloomery never
    #: verifies. Appended with a default so a positional construction keeps
    #: binding what it bound before.
    owner: str | None = None
    #: Who may read this relation (S-0062/grants), or ``None`` for "bloomery
    #: has no opinion and the warehouse's grants stand" (D6).
    grants: GrantsIR | None = None


# ....................... #
# Metrics (S-0020/ir-shape; policies per S-0028/D-5)


# ....................... #


@dataclass(frozen=True, slots=True)
class DimensionRef:
    """The single role-playing dimension model (S-0027/dimensionref), lowered per
    consumer (mart builder, planner, Cube emitter)."""

    dimension: str
    role: str | None = None

    # ....................... #

    @property
    def qualified(self) -> str:
        """``<role>_<dimension>`` when role-qualified, else the bare name."""

        return f"{self.role}_{self.dimension}" if self.role else self.dimension


# ....................... #


@dataclass(frozen=True, slots=True)
class SemiAdditivePolicy:
    """Typed semi-additive policy: the dimension the metric is not additive
    over, and the rule along it (S-0028/D-5)."""

    over: DimensionRef
    rule: SemiAdditiveRule


# ....................... #


@dataclass(frozen=True, slots=True)
class Ratio:
    """Additive decomposition of a non-additive metric (S-0028/D-5)."""

    numerator: str
    denominator: str
    #: The author's answer to "which rows is this ratio about" (S-0077/D-2),
    #: carried verbatim. Appended last so a positional construction keeps
    #: binding what it bound before.
    includes_zero_denominator: bool = False


# ....................... #


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A whole number of time units — ``(1, "year")``, ``(7, "day")``.

    One node for the two places a window appears (S-0050/D-2): a derived
    input's offset and a cumulative metric's trailing window. ``grain`` is
    singular and one of ``day|week|month|quarter|year``; the spec grammar
    accepts the plural and :func:`~bloomery.spec.metrics.parse_time_window`
    drops it, so the IR carries exactly one spelling of each grain.
    """

    count: int
    grain: str


# ....................... #


@dataclass(frozen=True, slots=True)
class MetricInputIR:
    """One input of a derived metric: the alias its expression references,
    the metric read, and the offset it is read at (S-0050/D-1).

    At most one of ``offset_window``/``offset_to_grain`` is set — the spec
    model refuses both and refuses neither-when-``offset``-is-written.
    """

    alias: str
    metric: str
    offset_window: TimeWindow | None = None
    offset_to_grain: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class DerivedIR:
    """A metric computed by an expression over other metrics (S-0050/D-1).

    ``inputs`` is sorted by alias, and the alias is what ``expr`` references.
    Like a :class:`Ratio`, this decomposes a metric that has no measure of
    its own — the planner recomputes it from the measures its inputs need
    (S-0028/D-5).
    """

    expr: SqlExpr
    inputs: tuple[MetricInputIR, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class CumulativeIR:
    """How a metric accumulates over time (S-0050/D-5): exactly one of a
    trailing ``window`` or a ``grain_to_date`` period start. The metric keeps
    its own measure and its own additivity — those describe the measure, this
    describes the accumulation (D6).

    ``period_agg`` is what a request *coarser* than the accumulation gets:
    ``first``, ``last`` or ``average`` of the period's series. It carries no
    default and comes first for that reason — the spec layer defaults it to
    ``last``, and a field meaning "collapse a series to one number" must not be
    answerable by omission anywhere downstream.
    """

    period_agg: str
    window: TimeWindow | None = None
    grain_to_date: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class MetricFilterIR:
    """One row-level restriction on a metric (S-0050/D-8).

    ``values`` carries text where the author wrote a date or timestamp — the
    same carrier :class:`AuditIR` params use, and for the same reason: a
    temporal literal reaches SQL as a quoted string compared in the column's
    own type, and the canonical encoder has no tag for a ``date``. The
    guardrail has already checked each value against the column's declared
    type, so the renderers quote by value type and never cast.
    """

    dimension: str
    op: str
    values: tuple[str | int | bool | Decimal, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class MetricIR:
    """One reachable metric; ``depends_on`` keeps the DAG edges sorted for
    ``plan()``'s downstream-impact computation (S-0020/ir-shape).
    ``description`` (authored or template-merged) is carried into semantic-
    layer emissions (S-0030 R1) — it grounds the Query Agent."""

    name: str
    grain: str
    additivity: Additivity
    agg: str | None
    expr: SqlExpr | None
    ratio: Ratio | None
    semi_additive: SemiAdditivePolicy | None
    #: The S-0050 forms. ``derived`` decomposes a metric with no measure of
    #: its own, like ``ratio`` and mutually exclusive with ``cumulative``,
    #: which accumulates a metric that has one. ``filter`` restricts the rows
    #: either aggregates.
    cumulative: CumulativeIR | None = None
    derived: DerivedIR | None = None
    filter: tuple[MetricFilterIR, ...] = ()
    description: str | None = None
    depends_on: tuple[str, ...] = ()
    #: Who is responsible for this (S-0062/owner), carried unchanged to
    #: whichever targets have an owner slot. A declaration bloomery never
    #: verifies. Appended with a default so a positional construction keeps
    #: binding what it bound before.
    owner: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class UnreachableMetric:
    """An unreachable metric with its specific missing leaves, sorted —
    product-facing IR output, not a log line (S-0020/D-6).

    ``missing`` names *leaves* and never intermediate metrics (S-0022/D-3),
    because the fix is always a mapping. ``via`` names the intermediates
    anyway, separately: a metric blocked through another — ``margin`` blocked
    because ``gross_profit`` is — reports the leaf, and without the chain the
    reader has to rediscover a walk the compiler already did. Empty when the
    metric's own requirements are what is missing.
    """

    name: str
    missing: tuple[str, ...]
    #: The blocked metrics between this one and ``missing``, sorted. Defaulted
    #: so every existing construction keeps working — but the default does not
    #: make the field free: the canonical encoder writes each dataclass's field
    #: *count* and names, so adding it re-fingerprints every project with an
    #: unreachable metric and moves ``bloomery_ir_version`` 4 → 5.
    via: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class RelationshipIR:
    """A declared relationship; ``via`` is (from-column, to-column) pairs
    sorted by from-column."""

    name: str
    from_entity: str
    to_entity: str
    via: tuple[tuple[str, str], ...]
    cardinality: Cardinality


# ....................... #
# Gold: marts (S-0027/martir)


# ....................... #


@dataclass(frozen=True, slots=True)
class MartColumnIR:
    """One flattened wide-schema column, traced to exactly one source entity
    column; ``ref`` is set for role/date-derived columns.

    ``role_of`` is the dimension this column's prefixed family is a role of
    (S-0007/roles-for-any-dimension), or ``None`` for a column that plays no
    declared role. It is deliberately *not* folded into ``ref``: a
    :class:`DimensionRef` with a role means a date bucket everywhere it is
    read, and a general role expands into no buckets (S-0007/D-5). Two columns
    are roles of one dimension when they agree on ``role_of`` **and**
    ``source_column`` — ``billing_region`` and ``shipping_city`` share a
    dimension and are still two different members of it.
    """

    name: str
    type: LogicalType
    source_entity: str
    source_column: str
    ref: DimensionRef | None = None
    role_of: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class MartDimensionIR:
    """A requestable dimension of a mart and the flattened column serving it."""

    ref: DimensionRef
    column: str


# ....................... #


@dataclass(frozen=True, slots=True)
class MartJoinIR:
    """One resolved build-time join of a mart (S-0027/validation-compile-errors-batched-with-guardrails, S-0025/D-11):
    the declared relationship, the joined entity, the column prefix (also the
    join alias), and the ``on`` pairs — (flattened from-side column in the
    mart's namespace, to-side entity column), sorted by from-side column.
    Consumed only by the mart-building emitter; the planner never joins.

    ``as_of`` is the anchor for an as-of join (S-0040/phase-2-the-as-of-join): the base-side
    column the joined entity's validity interval is read against, already in
    the mart's namespace like the left half of ``on``. ``None`` is an
    ordinary equality join, which is every join over a non-historical
    entity. The interval *column names* are not carried here — they are the
    same two names on every target by construction
    (:data:`~bloomery.ir.VALID_FROM` / :data:`~bloomery.ir.VALID_TO`), so a
    per-entity copy would be a constant wearing a field.

    ``role_of`` is the dimension this join's column family plays a role of
    (S-0007/roles-for-any-dimension), carried here as well as on each
    :class:`MartColumnIR` because the two are read at different grains: a
    consumer asking about one column has the column, and one asking about the
    join has only the prefix — and a prefix that is itself a prefix of another
    cannot say which family a column belongs to.
    """

    relationship: str
    entity: str
    prefix: str
    on: tuple[tuple[str, str], ...]
    as_of: str | None = None
    role_of: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class MartAssertIR:
    """One aggregate assertion over a mart (S-0033/D-89).

    Not a :class:`QualityRuleIR`, and the difference is the whole decision: a
    quality rule carries an ``OnFail`` that *routes a row*, and a mart row has
    no source identity to route. This carries a blocking flag instead — an
    audit either stops the run or reports beside it.

    ``by`` keeps its authored order (it is a ``GROUP BY``, and the emitted
    column order follows it); ``params`` is sorted, like every other params
    tuple in this module.
    """

    name: str
    column: str
    agg: str
    by: tuple[str, ...]
    params: tuple[tuple[str, str], ...]
    blocking: bool


# ....................... #


@dataclass(frozen=True, slots=True)
class MartIR:
    """One wide pre-joined mart — read by both the mart builder (joins at
    build) and the planner (no joins), so they cannot disagree (S-0027/D-1).
    ``joins`` keeps the authored flatten order (it is semantic: later joins
    may key off earlier-joined columns, S-0020/D-4)."""

    name: str
    grain: str
    base: str
    columns: tuple[MartColumnIR, ...]
    measures: tuple[str, ...]
    dimensions: tuple[MartDimensionIR, ...]
    joins: tuple[MartJoinIR, ...]
    partition_by: tuple[PartitionSpec, ...]
    materialization: Materialization
    #: Aggregate assertions over this mart (S-0033/D-89), sorted by name.
    #: Assertions rather than quality rules because a mart row has nothing to
    #: dispose of — no source identity, no reject table, no replay.
    asserts: tuple[MartAssertIR, ...] = ()
    cost_hint: int = 1
    #: Who is responsible for this (S-0062/owner), carried unchanged to
    #: whichever targets have an owner slot. A declaration bloomery never
    #: verifies. Appended with a default so a positional construction keeps
    #: binding what it bound before.
    owner: str | None = None
    #: Who may read this relation (S-0062/grants), or ``None`` for "bloomery
    #: has no opinion and the warehouse's grants stand" (D6).
    grants: GrantsIR | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class RollupIR:
    """A mart at a coarser grain than one this project builds (S-0065/the-obligation).

    Its own collection on :class:`ProjectIR` rather than a flag on
    :class:`MartIR`, and that is what makes S-0065 row 14 (`LOCKED`) true by
    construction. That row says a rollup is never a measure owner and never a
    covering mart; ``measure_owners`` and the planner's covering-mart search
    both walk ``ProjectIR.marts``, as do the Cube and MetricFlow emitters,
    which emit one surface per member. A rollup living there would be picked
    by every one of them by default, and the row would hold only for as long
    as three filters survived — while here nothing has to be excluded, because
    nothing that must not see a rollup is looking at this field
    (logs/T-0034.md).

    ``of`` names the parent mart and ``keep`` the parent columns this groups
    by; what it **drops** is derived (D4). There is no ``base`` or ``grain``:
    those name an entity, and a rollup's rows are identified by ``keep``.
    There is no ``cost_hint`` — it breaks ties in ``measure_owners``, which a
    rollup never reaches — and no ``joins``, because the parent is already
    flattened and that is the whole of what makes a rollup cheap.

    There is no ``columns`` either, and that one is worth a sentence.
    :class:`MartIR` carries its resolved schema because S-0027/martir does not
    want a consumer re-running the flatten recipe — joins in authored order,
    transitive prefixes, bucket expansion. A rollup has no recipe: ``keep``
    *is* the kept column set by name, ``measures`` is the rest, and the types
    come from the parent this names, which sits in the same
    :class:`ProjectIR`. A ``columns`` here would either duplicate that or
    carry half of it, and a field called ``columns`` holding some of them is
    worse than none (logs/T-0034.md).
    """

    name: str
    of: str
    keep: tuple[str, ...]
    measures: tuple[str, ...]
    partition_by: tuple[PartitionSpec, ...] = ()
    materialization: Materialization = Materialization.FULL
    #: Who may read this rollup (S-0062/D-12), or ``None`` for an undeclared
    #: audience. Not inherited from the parent mart: a rollup is an authored
    #: node, and D2 refuses inheritance between those.
    grants: GrantsIR | None = None


# ....................... #


class ExposureKind(StrEnum):
    """What a declared consumer *is* (S-0063/D-3).

    dbt's five exposure types verbatim, because dbt is the only framework with
    a consumer for these words and a bloomery-specific set would have to be
    mapped onto it anyway. ``report`` is not among them and ``analysis`` is,
    which is measurable rather than memorable — dbt's own schema was handed each
    one to find out.

    An enum rather than the ``str`` this first carried, for the reason every
    other closed vocabulary in this module is one: the IR's builder is its
    validator (S-0020/D-1), and a plain string leaves a hand-built node free to
    hold a type the dbt emitter would write out and dbt would refuse.
    """

    DASHBOARD = "dashboard"
    NOTEBOOK = "notebook"
    ANALYSIS = "analysis"
    ML = "ml"
    APPLICATION = "application"


# ....................... #


@dataclass(frozen=True, slots=True)
class ExportsIR:
    """What this project publishes for another project to read (S-0002 (§5.1),
    D1).

    The upstream half of the composition boundary, and in this phase the whole
    of it: nothing consumes an export yet. It is here rather than only in the
    authored document because **the IR is what crosses** (D2) — a downstream
    compile is handed the upstream's compiled IR, never its spec, so a surface
    that lived only in the document would be a surface the boundary could not
    see.

    Three collections rather than one, for the reason :class:`ExposureIR` keeps
    two: entity, mart and metric names are separate namespaces, so a single
    list would be names whose kind has to be guessed by looking each one up,
    and a name held by two kinds would resolve to whichever lookup ran first.

    Each is sorted. The order of an export list carries no meaning, so leaving
    it authored would let two spellings of one surface produce two fingerprints
    (S-0020/ir-shape).

    **Absence is the only spelling of "exports nothing".** An empty document is
    refused where it is authored, so this node is either present with something
    in it or absent entirely — which keeps "no boundary" and "a boundary that
    publishes nothing" from being two states that mean one thing.

    ``name`` is the producer's dbt project name (S-0002/D-10) — the one
    identity a project carries, carried across because a downstream's dbt
    target spells its cross-project ``ref()`` and its ``dependencies.yml``
    entry with it. ``None`` where the document names none, which is what the
    dbt target refuses an import against; every other target names a relation
    or reads a mart and never asks.
    """

    entities: tuple[str, ...] = ()
    marts: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    name: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class ExposureIR:
    """A declared consumer of what this project builds (S-0063/the-document).

    The one IR node with no artifact of its own on most targets and no
    contribution to any SELECT anywhere: an exposure is *read* — by the lineage
    graph, by ``plan()``'s impact report, and by the dbt emitter — and never
    built. That is what makes it a leaf rather than a stage.

    ``metrics`` and ``marts`` stay separate collections, as they are in the
    document. They are separate namespaces — one project may hold a metric and
    a mart of the same name — so a single list would be a list of names whose
    kind has to be guessed by looking each one up, and a name present in both
    would resolve to whichever lookup ran first.

    ``owner`` and ``url`` are carried verbatim and interpreted by nothing
    (S-0063/D-6). The URL in particular is never fetched: an exposure is a
    claim about a world this compiler cannot see, and validating it would need
    the network S-0020 forbids.
    """

    name: str
    kind: ExposureKind
    owner: str
    metrics: tuple[str, ...]
    marts: tuple[str, ...]
    url: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class DateDimensionIR:
    """The vertical-owned date dimension (S-0025/D-13, S-0030 R1 rule 4):
    one catalog definition emits both the gold ``dim_date`` model and, at M6,
    the MetricFlow time-spine declaration. Bounds are calendar years — the
    emitted table is a pure function of the spec, never of a clock."""

    name: str
    grain: str
    start_year: int
    end_year: int


# ....................... #


@dataclass(frozen=True, slots=True)
class FxRatesIR:
    """The dated exchange-rate relation ``convert`` reads (S-0040/phase-2-currency-as-a-declared-relation).

    Names only — the relation the operator supplies and the five columns it
    carries. ``relation`` is resolved through the naming policy at the silver
    layer at emit, the same way a mart's join target is: the IR holds names and
    emit holds the policy, so whatever scoping that policy applies reaches the
    rate relation as well.

    Both interval ends are here because one end is not an interval (D11): a
    fact row would match every rate at or before its anchor and the conversion
    would fan out instead of converting.
    """

    relation: str
    from_currency: str
    to_currency: str
    rate: str
    valid_from: str
    valid_to: str


# ....................... #
# Root


# ....................... #
# Steps — S-0034/runtime-pinning, S-0034/D-11, S-0034/D-15


# ....................... #


@dataclass(frozen=True, slots=True)
class StepColumnIR:
    """One column a step output declares it produces (S-0034/step-manifest).

    Trusted at compile — downstream models typecheck against this — and
    verified at run time by the generated wrapper's contract assertion (§5.4,
    D4). The type is a resolved :class:`LogicalType`, not the manifest's
    string, so downstream typechecking sees the same values it sees for a
    mapped column.
    """

    name: str
    type: LogicalType
    required: bool = False


# ....................... #


@dataclass(frozen=True, slots=True)
class StepOutputIR:
    """One relation a step produces, bound to a name (S-0034/step-manifest, S-0034/emission-and-the-dag).

    ``relation`` is where the wiring binds it; ``key`` is the grain's
    uniqueness columns, which is what the runtime assertion groups by. Each
    output gets its own generated wrapper model (D16), so this is also the
    unit of emission.
    """

    name: str
    relation: str
    grain: str
    key: tuple[str, ...]
    columns: tuple[StepColumnIR, ...]
    #: ``(column, sibling output)`` pairs this output references, sorted —
    #: declared in the manifest, never inferred from column names (D16).
    references: tuple[tuple[str, str], ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class StepParameterIR:
    """One resolved parameter: its name, its value as text, and the logical
    type the manifest declared for it (S-0034/step-manifest, S-0034/D-15).

    The value is text so the canonical encoding never meets a float (S-0020
    D5) — but text alone is not enough to *call* the step with. A generated
    wrapper has to hand the body a real ``Decimal``, ``int`` or ``str``, and
    the only thing that says which is the declared type, so it travels beside
    the value rather than being re-derived from how the digits look.
    """

    name: str
    value: str
    type: str


# ....................... #


@dataclass(frozen=True, slots=True)
class StepIR:
    """One wired step: the manifest's identity and contract, joined to what
    the spec asked of it (S-0034/runtime-pinning, S-0034/D-11, S-0034/D-15).

    **Everything that can change behaviour is a field here**, and that is the
    entire mechanism rather than an implementation detail. The canonical
    encoder walks dataclasses generically, so every field below is
    fingerprint-covered by construction: a ``runtime_lock`` bump, a changed
    parameter, a new seed, a rewired input — each shifts
    ``project_fingerprint``, and ``plan()`` reads an ordinary structural diff
    with no special-casing for steps anywhere (D6, D11).

    ``parameters`` are :class:`StepParameterIR` values sorted by name and the
    wiring is ``(name, relation)`` pairs, all stringified, so the canonical
    encoding never meets a float (D15, S-0020/D-5) — the same discipline
    :class:`QualityRuleIR.params` follows.

    ``body`` carries the SQL of a Tier 1 or Tier 2 step, canonicalized at
    lowering. It lives in the IR rather than being read from the registry at
    emit because emitters consume IR and never the spec or registry layer
    (S-0025); a Tier 3 step has no body here at all, since bloomery never
    sees its code.
    """

    ref: str
    version: int
    kind: StepKind
    determinism: Determinism
    runtime_lock: str
    lineage: Lineage
    outputs: tuple[StepOutputIR, ...]
    inputs: tuple[tuple[str, str], ...] = ()
    parameters: tuple[StepParameterIR, ...] = ()
    seed: int | None = None
    entrypoint: str | None = None
    body: SqlExpr | None = None


# ....................... #


def step_sort_key(step: StepIR) -> tuple[str, int]:
    """The canonical order of :attr:`ProjectIR.steps` — one function so no
    consumer invents a second one. ``(ref, version)`` is total over the
    collection because a spec may wire one ``ref@version`` at most once
    (S-0034/step-manifest)."""

    return (step.ref, step.version)


# ....................... #


@dataclass(frozen=True, slots=True)
class UpstreamIR:
    """One upstream project as this compile bound it (S-0002 (§5.1), S-0002/D-2).

    The upstream's **identity** is ``fingerprint``: a project carries no name
    of its own, so ``alias`` is the downstream's local spelling and says
    nothing about who the upstream is. The fingerprint is the value every
    upstream artifact header already carries, and it is what the next phase
    composes the downstream fingerprint from — which is why the identity has
    to reach the IR here rather than there.

    The three collections are the **nodes** that crossed, not names: a mart
    naming an imported entity as its base flattens over the entity itself, and
    a name with nothing behind it would leave the flattener to invent the
    columns. They are deliberately beside ``ProjectIR.entities`` rather than
    in it — an imported relation is built by the upstream, so a downstream
    that listed it among its own would emit a second build of somebody else's
    table. :func:`with_imported` is the view for the readers that resolve a
    reference; the collections themselves stay the local project's.

    What is here is what this compile **bound**: a name the upstream does not
    export, one a local declaration already claims, and one two upstreams both
    supply each bind nothing and are refused by
    :func:`~bloomery.guardrails.imports.check_imports` a stage later.

    Quality surfaces are stripped on the way over (S-0002/D-5): an upstream
    entity's rules, dedupe and quarantine describe how the upstream cleaned
    it, its reject table and quality mart are relations in the upstream's
    warehouse, and the downstream reads the entity.
    """

    alias: str
    fingerprint: str
    entities: tuple[EntityIR, ...] = ()
    marts: tuple[MartIR, ...] = ()
    metrics: tuple[MetricIR, ...] = ()
    #: Beside the alias and not instead of it (S-0002/D-10): what the upstream
    #: exports as its own dbt project name, or ``None`` where it exports none.
    #: The alias is still what keyed this bind and what every resolution goes
    #: through (D2); this is the name dbt's cross-project `ref()` needs, and
    #: the dbt target is the only reader — an import from an upstream that
    #: exports no name is refused there rather than emitted unresolvable.
    name: str | None = None


# ....................... #


def with_imported(draft: ProjectIR) -> ProjectIR:
    """The draft as a *resolver* must see it: local nodes plus imported ones.

    One view, built here rather than per reader, so that a mart flattener, a
    rollup obligation and a grain guard resolve an imported name through the
    same lookup a local one goes through — nothing downstream of here learns a
    second way to resolve a name (S-0002/D-2).

    Never the draft itself, and that is the whole point of the split: what the
    emitters walk is ``ProjectIR.entities``/``.marts``/``.metrics``, which stay
    this project's own. An imported relation already exists, built upstream
    under the naming policy both projects share (S-0002/D-7); a downstream
    that emitted a model for it would write the upstream's table from the
    upstream's bronze and, the quality surface having stayed behind
    (S-0002/D-5), would hard-code a verdict it never evaluated.

    A project with no imports gets itself back, identity-equal, so the
    single-project compile keeps its shape.
    """

    if not draft.upstream:
        return draft

    return replace(
        draft,
        entities=tuple(
            sorted(
                (*draft.entities, *(e for up in draft.upstream for e in up.entities)),
                key=lambda entity: entity.name,
            )
        ),
        marts=tuple(
            sorted(
                (*draft.marts, *(m for up in draft.upstream for m in up.marts)),
                key=lambda mart: mart.name,
            )
        ),
        metrics=tuple(
            sorted(
                (*draft.metrics, *(m for up in draft.upstream for m in up.metrics)),
                key=lambda metric: metric.name,
            )
        ),
    )


# ....................... #


@dataclass(frozen=True, slots=True)
class ProjectIR:
    """The compile pipeline's product: all collections sorted by name
    (S-0020/ir-shape). ``bloomery_ir_version`` is fingerprint-covered, so an IR
    shape change changes every fingerprint loudly (S-0020/fingerprint).

    Version 2 (S-0033 M12) adds the data-quality shape: ``reconcile`` here,
    ``quality``/``dedupe``/``quarantine`` on every :class:`EntityIR`. Version 3
    (S-0034 M13) adds ``steps``. Version 4 adds ``coverage`` here and
    ``asserts`` on every :class:`MartIR` (S-0033/D-89, S-0033/D-90). Version 5
    (S-0039 M19) adds ``via`` to every :class:`UnreachableMetric`. Version 6
    (S-0041/D-17, S-0041/D-26) moves each column's lowered expression off
    :class:`ColumnIR` onto a per-source :class:`SourceColumnIR`, so an entity
    can be built from more than one mapping. Version 7 (S-0040/phase-2-the-as-of-join) adds
    ``as_of`` to every :class:`MartJoinIR`. Version 8 (S-0040/phase-2-currency-as-a-declared-relation) adds
    ``fx_rates`` here. Version 9
    (S-0050/D-14) adds ``cumulative``/``derived``/``filter`` to every
    :class:`MetricIR`, and version 10 adds ``period_agg`` to every
    :class:`CumulativeIR` — a second shape change under the same RFC, and a
    second number, because "the first one is not released yet" is a reason to
    skip the bump only until someone diffs two IRs that both call themselves 9.
    Version 11 (S-0041/D-32) adds ``sources``, ``enum_values`` and
    ``enum_spellings`` to every :class:`SourceColumnIR`: a merged entity's
    rules are evaluated once over the union, so the per-mapping facts they read
    move onto the per-mapping node. Version 13 (S-0063/the-document) adds
    ``exposures`` — a node that changes no SELECT and moves every fingerprint
    anyway, which is the encoder working as §5.4 intends: the *shape* is
    covered, so two compilers that disagree about what an IR holds can never
    agree on a fingerprint. Version 14 (S-0064/the-spec-surface) adds ``freshness`` to
    every :class:`SourceIR`, and moves every fingerprint for the reason version
    7 established: the encoder writes field names per *instance*, so a project
    whose sources declare no threshold would otherwise encode identically
    before and after the field existed, and two compilers of different shape
    would agree on both the version and the fingerprint while disagreeing about
    what an IR holds. Version 18 (S-0076/zonein-is-how-a-utc-source-says-so) adds ``zone_in`` to every
    :class:`SourceFieldIR` — a declaration no SELECT reads, moving every    fingerprint for version 14's reason and no other. Version 19 (S-0077/D-2) adds
    ``includes_zero_denominator`` to every :class:`Ratio`, which is the same
    shape again: a declaration, read by a rule rather than by a SELECT.
    Version 20 (S-0079/D-2) adds ``determines`` to every :class:`ColumnIR`. A
    default of ``()`` is not a reason to skip the bump: the encoder writes each
    dataclass's field count and names per *instance*, so every project with an
    entity column re-fingerprints whether or not it declares a determination.
    Version 21 (S-0002/D-2) adds ``upstream`` here — the identity of each
    project this one imports from, and the nodes it bound from them — which is
    the same shape a third time: a default of ``()`` moves every project's
    fingerprint, because the shape is covered and not merely the values.
    The bump is
    the point — every artifact's fingerprint header moves, and ``plan()``
    refuses to diff across versions rather than misreading one as the other.

    Version 7 is why a *nested* field addition bumps this at all. Had the field
    landed without one, the encoder — which writes field names per instance —
    would have left every project with no mart joins encoding no ``MartJoinIR``
    and carrying its old fingerprint, so two compilers of different shape would
    have agreed on both the fingerprint and the version and ``plan()`` would
    have diffed across a schema change it could not see. ``role_playing_dates``
    is such a project in this tree: marts, goldens, a fingerprint, and not one
    ``via:`` step. With the bump the version is in the stream, so every
    project's fingerprint moves — which is the whole point. Version 5's
    ``UnreachableMetric.via`` had the same shape and set the same precedent.

    Note that ``steps`` shifts every fingerprint even for a project with no
    steps at all: the canonical encoder writes each dataclass's field count
    and every field name, so the *shape* is covered, not merely the values.
    That is the intended reading of S-0020/fingerprint — an IR shape change is
    supposed to be loud.
    """

    bloomery_ir_version: int = 21
    entities: tuple[EntityIR, ...] = ()
    metrics: tuple[MetricIR, ...] = ()
    unreachable: tuple[UnreachableMetric, ...] = ()
    relationships: tuple[RelationshipIR, ...] = ()
    marts: tuple[MartIR, ...] = ()
    #: Rollup marts, sorted by name (S-0065/the-obligation). Deliberately *not* folded
    #: into ``marts``: see :class:`RollupIR`.
    rollups: tuple[RollupIR, ...] = ()
    #: Declared downstream consumers, sorted by name (S-0063/the-document). A leaf
    #: of the lineage graph and an input to ``plan()``'s impact report; nothing
    #: is built for one.
    exposures: tuple[ExposureIR, ...] = ()
    date_dimension: DateDimensionIR | None = None
    fx_rates: FxRatesIR | None = None
    reconcile: tuple[ReconcileIR, ...] = ()
    coverage: tuple[CoverageIR, ...] = ()
    steps: tuple[StepIR, ...] = ()
    #: What this project publishes for another to read (S-0002 (§5.1), S-0002/D-1).
    #: ``None`` where no exports document was authored, which is the only
    #: spelling of "exports nothing" — the document refuses to be empty.
    #:
    #: **A new field is appended, never inserted.** Every field here has a
    #: default, so one inserted mid-list does not raise for a caller who bound
    #: positionally — it silently rebinds, and a `DateDimensionIR` lands in
    #: `exports` while `date_dimension` comes back `None`. Appending is what
    #: keeps the addition additive (S-0035/D-1), and
    #: `test_the_newest_field_is_appended` is what keeps the next one honest.
    exports: ExportsIR | None = None
    #: Each project this one imports from, sorted by alias (S-0002/D-2), with
    #: the nodes it bound from them. Empty for a project with no imports
    #: document, which is every project that compiled before composition.
    upstream: tuple[UpstreamIR, ...] = ()


# ....................... #


def carries_quality_flags(entity: EntityIR) -> bool:
    """Whether this entity's relation has ``_quality_flags``/``_quality_ok``.

    A mapped entity always does — the two columns are the general form
    evaluated at compile, constants where no rule fires (S-0033/schema-additions-and-the-array-capability). A
    **step-produced** entity does only when it carries an ``on_fail: flag``
    rule, which is the one case whose body is a SELECT the projection can wrap
    (S-0059/onfail-flag-on-a-tier-2-output, S-0059/D-11, S-0059/D-12).

    Derived rather than stored. A new :class:`EntityIR` field would move every
    fingerprint in the corpus — the encoder is type-driven over field names and
    count — including for projects that wire no steps at all. It is also total
    without knowing the step's tier: a ``python_model`` output can never
    satisfy the second clause, because ``resolve.steps`` refuses the only
    disposition that would put a ``flag`` rule on one.

    Read by everything that projects or counts those columns: the mart
    flattener's ``has_quality_flags`` dimension, the quality mart's branch set,
    and the Tier 2 model emission that puts them there. Those three disagreeing
    is a mart selecting a column no relation has — a model that compiles clean,
    passes every golden, and fails on its first run with a binder error.
    """

    return entity.produced_by is None or any(rule.on_fail is OnFail.FLAG for rule in entity.quality)
