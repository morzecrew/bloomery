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
from enum import StrEnum
from functools import lru_cache
from typing import cast

from sqlglot import exp, parse_one

from bloomery.typing import LogicalType

__all__ = [
    "Additivity",
    "AuditIR",
    "Cardinality",
    "ColumnIR",
    "DimensionRef",
    "EntityIR",
    "Layer",
    "MartColumnIR",
    "MartDimensionIR",
    "MartIR",
    "Materialization",
    "MetricIR",
    "PartitionSpec",
    "ProjectIR",
    "Ratio",
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
def _parse_sql(sql: str) -> exp.Expression:
    """Parse canonical dialect-neutral SQL once per distinct string.

    The cached AST is never handed out directly — :meth:`SqlExpr.ast` returns
    a copy, so the cache can never be mutated through a caller.
    """
    # ``parse_one`` is annotated with the ``Expr`` base, but every node it can
    # return (including multi-statement ``Block``) is an ``Expression``.
    return cast("exp.Expression", parse_one(sql))


@dataclass(frozen=True, slots=True)
class SqlExpr:
    """A SQL expression held as its canonical dialect-neutral string — the
    string is the value (hashable, version-stable equality); dialect-specific
    rendering re-parses at emit (RFC 0003 D2)."""

    sql: str

    def ast(self) -> exp.Expression:
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
    entries sorted by target field (minimal M1 surface)."""

    relation: str
    fields: tuple[SourceFieldIR, ...] = ()


@dataclass(frozen=True, slots=True)
class ColumnIR:
    """One entity column with its lowered expression and catalog metadata."""

    name: str
    type: LogicalType
    canonical: str | None
    unit: Unit | None
    tax_basis: TaxBasis | None
    expr: SqlExpr
    recipe_id: str | None
    renamed_from: str | None
    required: bool


@dataclass(frozen=True, slots=True)
class EntityIR:
    """One silver entity: key in authored order (it is meaningful), columns
    sorted by name, audits sorted by (kind, column)."""

    name: str
    grain: str
    key: tuple[str, ...]
    scd: SCDKind
    materialization: Materialization
    partition_by: tuple[PartitionSpec, ...]
    columns: tuple[ColumnIR, ...]
    source: SourceIR
    audits: tuple[AuditIR, ...] = ()


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
    ``plan()``'s downstream-impact computation (RFC 0003 §5.1)."""

    name: str
    grain: str
    additivity: Additivity
    agg: str | None
    expr: SqlExpr | None
    ratio: Ratio | None
    semi_additive: SemiAdditivePolicy | None
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
class MartIR:
    """One wide pre-joined mart — read by both the mart builder (joins at
    build) and the planner (no joins), so they cannot disagree (RFC 0010 D1)."""

    name: str
    grain: str
    base: str
    columns: tuple[MartColumnIR, ...]
    measures: tuple[str, ...]
    dimensions: tuple[MartDimensionIR, ...]
    partition_by: tuple[PartitionSpec, ...]
    materialization: Materialization
    cost_hint: int = 1


# ....................... #
# Root


@dataclass(frozen=True, slots=True)
class ProjectIR:
    """The compile pipeline's product: all collections sorted by name
    (RFC 0003 §5.1). ``bloomery_ir_version`` is fingerprint-covered, so an IR
    shape change changes every fingerprint loudly (RFC 0003 §5.4)."""

    bloomery_ir_version: int = 1
    entities: tuple[EntityIR, ...] = ()
    metrics: tuple[MetricIR, ...] = ()
    unreachable: tuple[UnreachableMetric, ...] = ()
    relationships: tuple[RelationshipIR, ...] = ()
    marts: tuple[MartIR, ...] = ()
