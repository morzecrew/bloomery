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
from typing import cast

from sqlglot import parse_one
from sqlglot.expressions.core import Expression

from bloomery.typing import LogicalType

__all__ = [
    "Additivity",
    "AuditIR",
    "Cardinality",
    "ColumnIR",
    "DateDimensionIR",
    "DedupeIR",
    "DimensionRef",
    "EntityIR",
    "Layer",
    "MartColumnIR",
    "MartDimensionIR",
    "MartIR",
    "MartJoinIR",
    "Materialization",
    "MetricIR",
    "OnFail",
    "PartitionSpec",
    "ProjectIR",
    "QualityRuleIR",
    "QuarantineIR",
    "Ratio",
    "ReconcileIR",
    "RelationshipIR",
    "SCDKind",
    "SemiAdditivePolicy",
    "SemiAdditiveRule",
    "SourceFieldIR",
    "SourceIR",
    "SqlExpr",
    "TaxBasis",
    "TransformStepIR",
    "Unit",
    "UnreachableMetric",
    "quality_sort_key",
]

# ....................... #
# Enums (values are the spec-layer vocabulary; fingerprint encodes by value)


class SCDKind(StrEnum):
    """Slowly-changing-dimension kind (original spec §3.3)."""

    TYPE1 = "type1"
    TYPE2 = "type2"


class Materialization(StrEnum):
    """Resolved materialization strategy (RFC 0002 D7 — explicit or derived)."""

    FULL = "full"
    INCREMENTAL_BY_KEY = "incremental_by_key"
    INCREMENTAL_BY_PARTITION = "incremental_by_partition"


class Layer(StrEnum):
    """Warehouse layer, consumed by naming policies (RFC 0008)."""

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class Unit(StrEnum):
    """Unit metadata driving the unit-coherence guardrail (RFC 0006 §5.2);
    a column without catalog metadata is ``UNKNOWN``."""

    CURRENCY = "currency"
    COUNT = "count"
    UNKNOWN = "unknown"


class TaxBasis(StrEnum):
    """Tax-basis metadata (RFC 0006 §5.2): ``net`` and ``gross`` never meet
    in additive arithmetic; ``UNKNOWN`` poisons it."""

    NET = "net"
    GROSS = "gross"
    UNKNOWN = "unknown"


class Additivity(StrEnum):
    """Metric additivity (RFC 0002 §5.5)."""

    ADDITIVE = "additive"
    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"


class Cardinality(StrEnum):
    """Relationship cardinality (original spec §3.2)."""

    MANY_TO_ONE = "many_to_one"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"


class OnFail(StrEnum):
    """A quality rule's row disposition (RFC 0016 §5.1, D2) — explicit per
    rule, never a global default.

    Deliberately no ``DROP``: silently discarding rows is the fastest way for a
    BI product to lose trust permanently, and it is the disposition everyone
    reaches for first. ``QUARANTINE`` *is* drop plus recoverability — most
    quarantined rows return after a spec fix. Deliberately no ``REPAIR`` in v1
    (D17), deferred on a repair-recipe contract.

    Severity order for a row failing several rules is ``FAIL > QUARANTINE >
    FLAG`` (D18), which makes every combination deterministic — so no
    rule/disposition pair needs compile-time rejection.
    """

    FLAG = "flag"  # row passes unchanged; recorded in _quality_flags
    QUARANTINE = "quarantine"  # row diverted to <entity>__reject; replayable
    FAIL = "fail"  # blocking audit; the run stops


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


@lru_cache(maxsize=512)
def _parse_sql(sql: str) -> Expression:
    """Parse canonical dialect-neutral SQL once per distinct string.

    The cached AST is never handed out directly — :meth:`SqlExpr.ast` returns
    a copy, so the cache can never be mutated through a caller.
    """
    # ``parse_one`` is annotated with the ``Expr`` base, but every node it can
    # return (including multi-statement ``Block``) is an ``Expression``.
    return cast("Expression", parse_one(sql))


@dataclass(frozen=True, slots=True)
class SqlExpr:
    """A SQL expression held as its canonical dialect-neutral string — the
    string is the value (hashable, version-stable equality); dialect-specific
    rendering re-parses at emit (RFC 0003 D2)."""

    sql: str

    def ast(self) -> Expression:
        """A fresh SQLGlot AST for this expression — always a copy; mutating
        the returned tree never affects other callers."""
        return _parse_sql(self.sql).copy()


# ....................... #
# Silver: entities (RFC 0003 §5.1)


@dataclass(frozen=True, slots=True)
class PartitionSpec:
    """One partition entry: an optional transform (``days``/``months``/
    ``years``/``hours``) over a column; ``transform=None`` is identity."""

    transform: str | None
    column: str


@dataclass(frozen=True, slots=True)
class AuditIR:
    """A target-native audit lowered from an ``assert:`` clause (RFC 0006
    §5.6); ``params`` is a tuple of (name, value) pairs sorted by name."""

    kind: str
    column: str
    params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TransformStepIR:
    """One resolved transform-chain step (authored order is semantic)."""

    name: str
    args: tuple[str | int, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceFieldIR:
    """One lowered (target field ← source path) entry with its chain."""

    target_field: str
    source_path: str
    transform: tuple[TransformStepIR, ...] = ()


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
    mapping_version: int = 1
    unmapped: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ColumnIR:
    """One entity column with its lowered expression and catalog metadata.
    ``description`` comes from the canonical field, when one is bound — it is
    carried into semantic-layer emissions (RFC 0013 R1)."""

    name: str
    type: LogicalType
    canonical: str | None
    unit: Unit | None
    tax_basis: TaxBasis | None
    expr: SqlExpr
    recipe_id: str | None
    renamed_from: str | None
    required: bool
    description: str | None = None


# ....................... #
# Silver: data quality (RFC 0016 §5.3–§5.6)


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


def quality_sort_key(rule: QualityRuleIR) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    """The canonical order of :attr:`EntityIR.quality` — one function so no
    consumer can invent a second one. Total over the node's whole value, so
    two rules that would sort equal are the same rule (RFC 0003 §5.3)."""
    return (rule.kind, rule.column or "", rule.name, rule.params)


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


@dataclass(frozen=True, slots=True)
class EntityIR:
    """One silver entity: key in authored order (it is meaningful), columns
    sorted by name, audits sorted by (kind, column).

    ``quality`` is sorted by ``(kind, column or "", name, params)`` — a total
    key over the node's whole value, so permuting the authored rule order can
    never change the IR even before rule names are generated, and two rules of
    one kind on one column (``range min`` and ``range max``, §5.3's worked
    example) still order deterministically by their bounds.
    """

    name: str
    grain: str
    key: tuple[str, ...]
    scd: SCDKind
    materialization: Materialization
    partition_by: tuple[PartitionSpec, ...]
    columns: tuple[ColumnIR, ...]
    source: SourceIR
    audits: tuple[AuditIR, ...] = ()
    quality: tuple[QualityRuleIR, ...] = ()
    dedupe: DedupeIR | None = None
    quarantine: QuarantineIR | None = None


# ....................... #
# Metrics (RFC 0003 §5.1; policies per RFC 0011 D5)


@dataclass(frozen=True, slots=True)
class DimensionRef:
    """The single role-playing dimension model (RFC 0010 §5.3), lowered per
    consumer (mart builder, planner, Cube emitter)."""

    dimension: str
    role: str | None = None

    @property
    def qualified(self) -> str:
        """``<role>_<dimension>`` when role-qualified, else the bare name."""
        return f"{self.role}_{self.dimension}" if self.role else self.dimension


@dataclass(frozen=True, slots=True)
class SemiAdditivePolicy:
    """Typed semi-additive policy: the dimension the metric is not additive
    over, and the rule along it (RFC 0011 D5)."""

    over: DimensionRef
    rule: SemiAdditiveRule


@dataclass(frozen=True, slots=True)
class Ratio:
    """Additive decomposition of a non-additive metric (RFC 0011 D5)."""

    numerator: str
    denominator: str


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
    description: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnreachableMetric:
    """An unreachable metric with its specific missing leaves, sorted —
    product-facing IR output, not a log line (RFC 0003 D6)."""

    name: str
    missing: tuple[str, ...]


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


@dataclass(frozen=True, slots=True)
class MartColumnIR:
    """One flattened wide-schema column, traced to exactly one source entity
    column; ``ref`` is set for role/date-derived columns."""

    name: str
    type: LogicalType
    source_entity: str
    source_column: str
    ref: DimensionRef | None = None


@dataclass(frozen=True, slots=True)
class MartDimensionIR:
    """A requestable dimension of a mart and the flattened column serving it."""

    ref: DimensionRef
    column: str


@dataclass(frozen=True, slots=True)
class MartJoinIR:
    """One resolved build-time join of a mart (RFC 0010 §5.5, RFC 0008 D11):
    the declared relationship, the joined entity, the column prefix (also the
    join alias), and the ``on`` pairs — (flattened from-side column in the
    mart's namespace, to-side entity column), sorted by from-side column.
    Consumed only by the mart-building emitter; the planner never joins."""

    relationship: str
    entity: str
    prefix: str
    on: tuple[tuple[str, str], ...]


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
    cost_hint: int = 1


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
# Root


@dataclass(frozen=True, slots=True)
class ProjectIR:
    """The compile pipeline's product: all collections sorted by name
    (RFC 0003 §5.1). ``bloomery_ir_version`` is fingerprint-covered, so an IR
    shape change changes every fingerprint loudly (RFC 0003 §5.4).

    Version 2 (RFC 0016 M12) adds the data-quality shape: ``reconcile`` here,
    ``quality``/``dedupe``/``quarantine`` on every :class:`EntityIR`. The bump
    is the point — every artifact's fingerprint header moves, and ``plan()``
    refuses to diff a v1 IR against a v2 one rather than misreading it.
    """

    bloomery_ir_version: int = 2
    entities: tuple[EntityIR, ...] = ()
    metrics: tuple[MetricIR, ...] = ()
    unreachable: tuple[UnreachableMetric, ...] = ()
    relationships: tuple[RelationshipIR, ...] = ()
    marts: tuple[MartIR, ...] = ()
    date_dimension: DateDimensionIR | None = None
    reconcile: tuple[ReconcileIR, ...] = ()
