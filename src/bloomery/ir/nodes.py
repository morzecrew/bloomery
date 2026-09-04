"""The frozen IR node tree (RFC 0003 §5.1–§5.3; RFC 0010 §5.3–§5.4).

Frozen slotted stdlib dataclasses — not Pydantic: the IR is compiler-internal;
it needs hashing and value semantics, its builder is its validator (RFC 0003
D1). Every collection is a tuple with an explicit lexicographic sort key,
except authored-order fields (``key``, transform chains, ``partition_by``,
mart flatten order — RFC 0003 D4). Floats never appear (RFC 0003 D5).

The IR *builder* (spec → IR) lands with M2+; in M1 the IR is constructed by
hand in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Final, cast

from sqlglot import parse_one
from sqlglot.expressions.core import Expression

from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
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
# The physical names the data-quality nodes imply (RFC 0016 §5.5–§5.6,
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
#: rules whose recipe rewrote this row's value (RFC 0016 D87). Separate from
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
#: The four lineage node-id prefixes (RFC 0031 §5.3, RFC 0051 §5.2). Every
#: node id but an entity field's is ``<prefix>.<rest>``; an entity field is
#: ``<entity>.<field>`` bare, so an entity named after one of these mints ids
#: in another kind's namespace. Reserved as entity names for that reason.
#:
#: Here rather than beside the node builders in ``resolve.graph`` because the
#: guardrail that refuses them sits *below* ``resolve`` in the layer contract
#: and cannot import it. ``tests/unit/test_resolve/test_graph.py`` pins the
#: two together: every builder's id must start with a member of this tuple,
#: so a node kind added with a fifth prefix fails there rather than silently
#: escaping the reservation.
NODE_ID_PREFIXES: Final = ("canonical", "metric", "source", "step")
#: The provenance column a **merged** entity carries: which source relation a
#: row came from (RFC 0024 D7). Load-bearing rather than diagnostic — the
#: collision audit reports *which* sources shared a key, and without it the
#: report is "this key is duplicated somewhere", which is not actionable on a
#: five-source entity.
#:
#: Emitted only on merged entities, like :data:`REPAIRS_COLUMN` and unlike the
#: two universal columns (D7): on a single-source entity it is a constant, and
#: putting a constant into every relation forever to spare one classified
#: change is how a schema move gets hidden from ``plan()``.
SOURCE_COLUMN = "_source"

#: The validity interval of an ``scd: type2`` relation (RFC 0023 §5.3, D7).
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
    """Resolved materialization strategy (RFC 0002 D7 — explicit or derived)."""

    FULL = "full"
    INCREMENTAL_BY_KEY = "incremental_by_key"
    INCREMENTAL_BY_PARTITION = "incremental_by_partition"


# ....................... #


class StepKind(StrEnum):
    """The ladder tier a step occupies (RFC 0017 §5.1, D1). Tier 0 is the
    transform whitelist and is not a step: a step kind names a tier that needs
    a body somebody wrote."""

    SQL_MACRO = "sql_macro"
    SQL_MODEL = "sql_model"
    PYTHON_MODEL = "python_model"


# ....................... #


class Determinism(StrEnum):
    """RFC 0017 §5.5, D5. ``NONDETERMINISTIC`` reaches the IR only in the
    sense that it is spellable in a manifest — the compile stage refuses it,
    because a step whose backfill disagrees with the original run destroys
    restatement, the capability the architecture is organized around."""

    PURE = "pure"
    SEEDED = "seeded"
    NONDETERMINISTIC = "nondeterministic"


# ....................... #


class Lineage(StrEnum):
    """Whether a step's outputs can be traced column by column (RFC 0017
    §5.1). Tier 3 loses it, and says so rather than letting a consumer infer
    it from the kind."""

    COARSE = "coarse"
    COLUMN = "column"


# ....................... #


class Layer(StrEnum):
    """Warehouse layer, consumed by naming policies (RFC 0008)."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


# ....................... #


class Unit(StrEnum):
    """Unit metadata driving the unit-coherence guardrail (RFC 0006 §5.2);
    a column without catalog metadata is ``UNKNOWN``."""

    CURRENCY = "currency"
    COUNT = "count"
    UNKNOWN = "unknown"


# ....................... #


class TaxBasis(StrEnum):
    """Tax-basis metadata (RFC 0006 §5.2): ``net`` and ``gross`` never meet
    in additive arithmetic; ``UNKNOWN`` poisons it."""

    NET = "net"
    GROSS = "gross"
    UNKNOWN = "unknown"


# ....................... #


class Additivity(StrEnum):
    """Metric additivity (RFC 0002 §5.5)."""

    ADDITIVE = "additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"


# ....................... #


class Cardinality(StrEnum):
    """Relationship cardinality (original spec §3.2)."""

    MANY_TO_ONE = "many_to_one"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"


# ....................... #


class OnFail(StrEnum):
    """A quality rule's row disposition (RFC 0016 §5.1, D2) — explicit per
    rule, never a global default.

    Deliberately no ``DROP``: silently discarding rows is the fastest way for a
    BI product to lose trust permanently, and it is the disposition everyone
    reaches for first. ``QUARANTINE`` *is* drop plus recoverability — most
    quarantined rows return after a spec fix.

    ``REPAIR`` was deferred out of v1 (D17) and joined the vocabulary when
    RFC 0017's step registry supplied the recipe contract it was gated on
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
    (RFC 0011 D5)."""

    LAST = "last"
    FIRST = "first"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


# ....................... #
# SQL expressions (RFC 0003 §5.2)


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
    rendering re-parses at emit (RFC 0003 D2)."""

    sql: str

    # ....................... #

    def ast(self) -> Expression:
        """A fresh SQLGlot AST for this expression — always a copy; mutating
        the returned tree never affects other callers."""

        return _parse_sql(self.sql).copy()


# ....................... #
# Silver: entities (RFC 0003 §5.1)


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
    """A target-native audit lowered from an ``assert:`` clause (RFC 0006
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
    """One column's **lowering**, for one source (RFC 0024 D26).

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
    #: against (RFC 0024 D32). Per source rather than on the rule, because the
    #: paths are one mapping's and the rule is evaluated once over the merged
    #: relation: carrying them on the rule would make source B's branch read
    #: source A's ``$.a.b`` off a bronze relation that need not have it.
    #: Empty for a column outside the quality system.
    sources: tuple[str, ...] = ()
    #: This branch's ``enum_map`` targets, deduplicated and sorted — the set
    #: ``in_enum`` admits for rows from this source (RFC 0024 D32). Two
    #: mappings may map different spellings onto different vocabularies, so
    #: the admissible set is a branch fact exactly as ``sources`` is.
    enum_values: tuple[str, ...] = ()
    #: This branch's ``enum_map`` spellings, deduplicated and sorted. Carried
    #: for the same reason the rule used to carry them: a widening that points
    #: a new spelling at an existing target changes no target, and ``plan()``
    #: could not see it otherwise (RFC 0016 §6).
    enum_spellings: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class SourceFieldIR:
    """One lowered (target field ← source path) entry with its chain."""

    target_field: str
    source_path: str
    transform: tuple[TransformStepIR, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class SourceIR:
    """The bronze relation an entity is built from, with its field lowering
    entries sorted by target field (minimal M1 surface).

    ``mapping_version`` is the authored ``mapping_version:`` of the document
    that produced this entity. It reaches the IR because the reject table's
    schema carries it (RFC 0016 §5.6): a quarantined row records *which
    version of which mapping* rejected it, or replay cannot tell a row that
    still fails from a row the mapping has since learned to read.

    ``unmapped`` is the acknowledged tail — bronze paths the mapping declares
    exist and deliberately does not read, sorted. It reaches the IR for the
    same reason: the reject table's ``raw`` column is *the bronze payload*,
    not the mapped subset, and ``quarantine.redact`` only ever has something
    to remove there (a redacted path that the mapping reads is the compile
    error ``RedactionConflict``, RFC 0016 §5.6).
    """

    relation: str
    fields: tuple[SourceFieldIR, ...] = ()
    #: This source's projection of each entity column, sorted by name
    #: (RFC 0024 D26). ``fields`` is what the reject payload and replay read;
    #: this is what the SELECT projects. The two answer different questions
    #: and are grained differently — see :class:`SourceColumnIR`.
    columns: tuple[SourceColumnIR, ...] = ()
    mapping_version: int = 1
    unmapped: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class ColumnIR:
    """One entity column's **schema**: declared type and catalog metadata.
    ``description`` comes from the canonical field, when one is bound — it is
    carried into semantic-layer emissions (RFC 0013 R1).

    **The lowered expression is not here** (RFC 0024 D26). Every field on this
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
    #: schema like the rest of this node, and stays here (RFC 0024 D26).
    renamed_from: str | None
    required: bool
    description: str | None = None


# ....................... #
# Silver: data quality (RFC 0016 §5.3–§5.6)


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
    (RFC 0016 §5.4, D19). Folding it into ``FLAG`` would misdescribe the
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
    two rules that would sort equal are the same rule (RFC 0003 §5.3).

    ``on_fail`` is the last component and it is **load-bearing**, not
    decoration (RFC 0016 D50): name generation walks this order, so two rules
    differing only in their disposition sorting equal made the assignment fall
    through to authored order — swapping two YAML lines then compiled the same
    spec to two different IRs. It sorts last so it only ever breaks a tie
    nothing else could break.
    """

    return (rule.kind, rule.column or "", rule.name, rule.params, str(rule.on_fail or ""))


# ....................... #


@dataclass(frozen=True, slots=True)
class DedupeIR:
    """Entity-level dedupe (RFC 0016 §5.4, D20), lowered to a ``ROW_NUMBER``
    over ``PARTITION BY <entity key>``.

    The sort order is total by construction: ``field`` DESC, then each
    ``tie_break`` column DESC, then the stable source-row identity
    ``_source_row_id`` DESC — every key ``NULLS LAST``. ``tie_break`` keeps
    authored order (it is a sort order, therefore semantic — RFC 0003 D4);
    empty here means the compile stage has yet to refuse it
    (``DedupeTieBreakMissing``), never that ties are allowed.
    """

    keep: str
    field: str
    tie_break: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class QuarantineIR:
    """The per-entity ``<entity>__reject`` policy (RFC 0016 §5.6, D10).

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
    """One cross-entity reconciliation check (RFC 0016 §5.3) — the check that
    catches a *correct formula over wrong data*. ``tolerance`` is a
    :class:`~decimal.Decimal`; floats never enter the IR (RFC 0003 D5)."""

    name: str
    left: str
    right: str
    tolerance: Decimal
    on_fail: OnFail


# ....................... #


@dataclass(frozen=True, slots=True)
class CoverageIR:
    """One cross-entity coverage check (RFC 0016 D90): every row of a
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
    and name generation falls through to authored order (RFC 0016 D50). Read
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
    #: (RFC 0024 D1/D3). More than one is a **union merge**: the silver model
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
    #: ordinary mapped one (RFC 0017 §5.8).
    #:
    #: A step output *is* an entity — that is what lets marts, metrics and
    #: downstream mappings reference it "like any silver entity" — but it is
    #: not one bloomery builds a SELECT for: the step's generated wrapper
    #: writes the relation. Without this marker the emitter's entity loop
    #: would emit a second model at the same path, which is the collision D28
    #: refuses everywhere else.
    produced_by: str | None = None


# ....................... #
# Metrics (RFC 0003 §5.1; policies per RFC 0011 D5)


# ....................... #


@dataclass(frozen=True, slots=True)
class DimensionRef:
    """The single role-playing dimension model (RFC 0010 §5.3), lowered per
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
    over, and the rule along it (RFC 0011 D5)."""

    over: DimensionRef
    rule: SemiAdditiveRule


# ....................... #


@dataclass(frozen=True, slots=True)
class Ratio:
    """Additive decomposition of a non-additive metric (RFC 0011 D5)."""

    numerator: str
    denominator: str


# ....................... #


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """A whole number of time units — ``(1, "year")``, ``(7, "day")``.

    One node for the two places a window appears (RFC 0034 D2): a derived
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
    the metric read, and the offset it is read at (RFC 0034 D1).

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
    """A metric computed by an expression over other metrics (RFC 0034 D1).

    ``inputs`` is sorted by alias, and the alias is what ``expr`` references.
    Like a :class:`Ratio`, this decomposes a metric that has no measure of
    its own — the planner recomputes it from the measures its inputs need
    (RFC 0011 D5).
    """

    expr: SqlExpr
    inputs: tuple[MetricInputIR, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class CumulativeIR:
    """How a metric accumulates over time (RFC 0034 D5): exactly one of a
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
    """One row-level restriction on a metric (RFC 0034 D8).

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
    ``plan()``'s downstream-impact computation (RFC 0003 §5.1).
    ``description`` (authored or template-merged) is carried into semantic-
    layer emissions (RFC 0013 R1) — it grounds the Query Agent."""

    name: str
    grain: str
    additivity: Additivity
    agg: str | None
    expr: SqlExpr | None
    ratio: Ratio | None
    semi_additive: SemiAdditivePolicy | None
    #: The RFC 0034 forms. ``derived`` decomposes a metric with no measure of
    #: its own, like ``ratio`` and mutually exclusive with ``cumulative``,
    #: which accumulates a metric that has one. ``filter`` restricts the rows
    #: either aggregates.
    cumulative: CumulativeIR | None = None
    derived: DerivedIR | None = None
    filter: tuple[MetricFilterIR, ...] = ()
    description: str | None = None
    depends_on: tuple[str, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class UnreachableMetric:
    """An unreachable metric with its specific missing leaves, sorted —
    product-facing IR output, not a log line (RFC 0003 D6).

    ``missing`` names *leaves* and never intermediate metrics (RFC 0005 D3),
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
# Gold: marts (RFC 0010 §5.4)


# ....................... #


@dataclass(frozen=True, slots=True)
class MartColumnIR:
    """One flattened wide-schema column, traced to exactly one source entity
    column; ``ref`` is set for role/date-derived columns."""

    name: str
    type: LogicalType
    source_entity: str
    source_column: str
    ref: DimensionRef | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class MartDimensionIR:
    """A requestable dimension of a mart and the flattened column serving it."""

    ref: DimensionRef
    column: str


# ....................... #


@dataclass(frozen=True, slots=True)
class MartJoinIR:
    """One resolved build-time join of a mart (RFC 0010 §5.5, RFC 0008 D11):
    the declared relationship, the joined entity, the column prefix (also the
    join alias), and the ``on`` pairs — (flattened from-side column in the
    mart's namespace, to-side entity column), sorted by from-side column.
    Consumed only by the mart-building emitter; the planner never joins.

    ``as_of`` is the anchor for an as-of join (RFC 0023 §5.3): the base-side
    column the joined entity's validity interval is read against, already in
    the mart's namespace like the left half of ``on``. ``None`` is an
    ordinary equality join, which is every join over a non-historical
    entity. The interval *column names* are not carried here — they are the
    same two names on every target by construction
    (:data:`~bloomery.ir.VALID_FROM` / :data:`~bloomery.ir.VALID_TO`), so a
    per-entity copy would be a constant wearing a field.
    """

    relationship: str
    entity: str
    prefix: str
    on: tuple[tuple[str, str], ...]
    as_of: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class MartAssertIR:
    """One aggregate assertion over a mart (RFC 0016 D89).

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
    build) and the planner (no joins), so they cannot disagree (RFC 0010 D1).
    ``joins`` keeps the authored flatten order (it is semantic: later joins
    may key off earlier-joined columns, RFC 0003 D4)."""

    name: str
    grain: str
    base: str
    columns: tuple[MartColumnIR, ...]
    measures: tuple[str, ...]
    dimensions: tuple[MartDimensionIR, ...]
    joins: tuple[MartJoinIR, ...]
    partition_by: tuple[PartitionSpec, ...]
    materialization: Materialization
    #: Aggregate assertions over this mart (RFC 0016 D89), sorted by name.
    #: Assertions rather than quality rules because a mart row has nothing to
    #: dispose of — no source identity, no reject table, no replay.
    asserts: tuple[MartAssertIR, ...] = ()
    cost_hint: int = 1


# ....................... #


@dataclass(frozen=True, slots=True)
class DateDimensionIR:
    """The vertical-owned date dimension (RFC 0008 D13, RFC 0013 R1 rule 4):
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
    """The dated exchange-rate relation ``convert`` reads (RFC 0023 §5.4).

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
# Steps — RFC 0017 §5.6, D11/D15


# ....................... #


@dataclass(frozen=True, slots=True)
class StepColumnIR:
    """One column a step output declares it produces (RFC 0017 §5.2).

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
    """One relation a step produces, bound to a name (RFC 0017 §5.2, §5.8).

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
    type the manifest declared for it (RFC 0017 §5.2, D15).

    The value is text so the canonical encoding never meets a float (RFC 0003
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
    the spec asked of it (RFC 0017 §5.6, D11/D15).

    **Everything that can change behaviour is a field here**, and that is the
    entire mechanism rather than an implementation detail. The canonical
    encoder walks dataclasses generically, so every field below is
    fingerprint-covered by construction: a ``runtime_lock`` bump, a changed
    parameter, a new seed, a rewired input — each shifts
    ``project_fingerprint``, and ``plan()`` reads an ordinary structural diff
    with no special-casing for steps anywhere (D6, D11).

    ``parameters`` are :class:`StepParameterIR` values sorted by name and the
    wiring is ``(name, relation)`` pairs, all stringified, so the canonical
    encoding never meets a float (D15, RFC 0003 D5) — the same discipline
    :class:`QualityRuleIR.params` follows.

    ``body`` carries the SQL of a Tier 1 or Tier 2 step, canonicalized at
    lowering. It lives in the IR rather than being read from the registry at
    emit because emitters consume IR and never the spec or registry layer
    (RFC 0008); a Tier 3 step has no body here at all, since bloomery never
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
    (RFC 0017 §5.2)."""

    return (step.ref, step.version)


# ....................... #


@dataclass(frozen=True, slots=True)
class ProjectIR:
    """The compile pipeline's product: all collections sorted by name
    (RFC 0003 §5.1). ``bloomery_ir_version`` is fingerprint-covered, so an IR
    shape change changes every fingerprint loudly (RFC 0003 §5.4).

    Version 2 (RFC 0016 M12) adds the data-quality shape: ``reconcile`` here,
    ``quality``/``dedupe``/``quarantine`` on every :class:`EntityIR`. Version 3
    (RFC 0017 M13) adds ``steps``. Version 4 adds ``coverage`` here and
    ``asserts`` on every :class:`MartIR` (RFC 0016 D89/D90). Version 5
    (RFC 0022 M19) adds ``via`` to every :class:`UnreachableMetric`. Version 6
    (RFC 0024 D17/D26) moves each column's lowered expression off
    :class:`ColumnIR` onto a per-source :class:`SourceColumnIR`, so an entity
    can be built from more than one mapping. Version 7 (RFC 0023 §5.3) adds
    ``as_of`` to every :class:`MartJoinIR`. Version 8 (RFC 0023 §5.4) adds
    ``fx_rates`` here. Version 9
    (RFC 0034 D14) adds ``cumulative``/``derived``/``filter`` to every
    :class:`MetricIR`, and version 10 adds ``period_agg`` to every
    :class:`CumulativeIR` — a second shape change under the same RFC, and a
    second number, because "the first one is not released yet" is a reason to
    skip the bump only until someone diffs two IRs that both call themselves 9.
    Version 11 (RFC 0024 D32) adds ``sources``, ``enum_values`` and
    ``enum_spellings`` to every :class:`SourceColumnIR`: a merged entity's
    rules are evaluated once over the union, so the per-mapping facts they read
    move onto the per-mapping node.
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
    That is the intended reading of RFC 0003 §5.4 — an IR shape change is
    supposed to be loud.
    """

    bloomery_ir_version: int = 11
    entities: tuple[EntityIR, ...] = ()
    metrics: tuple[MetricIR, ...] = ()
    unreachable: tuple[UnreachableMetric, ...] = ()
    relationships: tuple[RelationshipIR, ...] = ()
    marts: tuple[MartIR, ...] = ()
    date_dimension: DateDimensionIR | None = None
    fx_rates: FxRatesIR | None = None
    reconcile: tuple[ReconcileIR, ...] = ()
    coverage: tuple[CoverageIR, ...] = ()
    steps: tuple[StepIR, ...] = ()


# ....................... #


def carries_quality_flags(entity: EntityIR) -> bool:
    """Whether this entity's relation has ``_quality_flags``/``_quality_ok``.

    A mapped entity always does — the two columns are the general form
    evaluated at compile, constants where no rule fires (RFC 0016 §5.5). A
    **step-produced** entity does only when it carries an ``on_fail: flag``
    rule, which is the one case whose body is a SELECT the projection can wrap
    (RFC 0051 §5.3, D11/D12).

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
