"""Mart flattening: ``lower_marts(mart_set, draft) -> MartLowering``
(RFC 0010 §5.4–§5.5, D6).

Pure: spec in, wide schema out — every consumer sees the *resolved* column
set, never the flatten recipe. Each mart resolves against the draft IR's
entities, relationships, and reachable metrics: the base entity anchors the
grain; ``via:`` steps flatten declared ``many_to_one``/``one_to_one``
relationships transitively in authored order under mandatory prefixes;
``date:`` steps expand a base-entity date/timestamp column into
``<role>_<bucket>`` columns for exactly ``{day, week, month, quarter, year}``
(RFC 0010 D4). Every flattened column becomes a requestable
:class:`~bloomery.ir.MartDimensionIR` (RFC 0010 §10), and every column traces
to exactly one source entity column.

Validation is total — this module never raises. Violations are collected as
:class:`~bloomery.errors.GuardrailError` leaves: :class:`GrainViolation`
(mart grain must equal the base grain, and measure grain must strictly equal
mart grain — RFC 0010 D2), :class:`FanoutRisk` (a ``via:`` step that is not
a declared, transitively reachable ``many_to_one``/``one_to_one``
relationship — RFC 0010 D3), :class:`MartMissingTimeDimension` (a
measure-carrying mart without a date role — RFC 0010 D9), and untyped
:class:`GuardrailError` leaves for collisions and unresolvable names. The
guardrail stage (RFC 0006 §5.1) batches them into its single aggregate; a
mart with any violation contributes no :class:`~bloomery.ir.MartIR`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.errors import (
    FanoutRisk,
    GrainViolation,
    GuardrailError,
    MartMissingTimeDimension,
)
from bloomery.ir import (
    Cardinality,
    DimensionRef,
    MartColumnIR,
    MartDimensionIR,
    MartIR,
    MartJoinIR,
    Materialization,
    partition_specs,
)
from bloomery.spec.marts import ViaStep
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

if TYPE_CHECKING:
    from bloomery.ir import EntityIR, ProjectIR
    from bloomery.spec.marts import DateRoleStep, Mart, MartSet

__all__ = [
    "DATE_BUCKETS",
    "MartLowering",
    "lower_marts",
]

#: The bucket set a date role expands into — exactly the RFC 0011 ``TimeGrain``
#: set minus ``hour``, which is deliberately not expanded (RFC 0010 D4).
DATE_BUCKETS = ("day", "week", "month", "quarter", "year")

_TYPE_NAMES: dict[type[LogicalType], str] = {
    StringType: "string",
    IntType: "int",
    BoolType: "bool",
    DateType: "date",
    TimestampType: "timestamp",
    VariantType: "variant",
}


def _type_name(t: LogicalType) -> str:
    if isinstance(t, DecimalType):
        return f"decimal({t.precision}, {t.scale})"
    return _TYPE_NAMES[type(t)]


@dataclass(frozen=True, slots=True)
class MartLowering:
    """The flattener's product: cleanly lowered marts (sorted by name) and
    every violation found, as guardrail leaves for the stage aggregate."""

    marts: tuple[MartIR, ...]
    violations: tuple[GuardrailError, ...]


@dataclass(slots=True)
class _Flatten:
    """Mutable per-mart flatten state, threaded through the authored steps.

    ``prefixes`` maps each flattened entity to its *earliest* prefix (``""``
    for the base): when the same entity is flattened twice, chains keep
    resolving against the first flatten — deterministic, authored-order rule.
    """

    columns: dict[str, MartColumnIR]
    prefixes: dict[str, str]
    joins: list[MartJoinIR]
    roles: list[str]


def _grain_prose(entity_name: str, entities: dict[str, EntityIR]) -> str:
    entity = entities.get(entity_name)
    return entity.grain if entity is not None else "undeclared in this project"


def _flatten_via(
    step: ViaStep,
    index: int,
    path: str,
    draft: ProjectIR,
    entities: dict[str, EntityIR],
    state: _Flatten,
) -> list[GuardrailError]:
    """One ``via:`` step: validate the relationship, record the resolved join,
    and flatten the joined entity's columns under the step's prefix."""
    step_path = f"{path}.flatten[{index}].via"
    rel = next((r for r in draft.relationships if r.name == step.via), None)
    if rel is None:
        known = sorted(r.name for r in draft.relationships)
        msg = f"flatten step names no declared relationship {step.via!r}; known: {known}"
        return [FanoutRisk(msg, source_path=step_path)]
    if rel.cardinality is Cardinality.ONE_TO_MANY:
        msg = (
            f"relationship {rel.name!r} is one_to_many: flattening it multiplies the "
            f"mart's own rows once per {rel.to_entity!r} row (RFC 0006 §5.3). Fix: "
            "flatten only many_to_one/one_to_one relationships, or model a mart at "
            f"the grain of {rel.to_entity!r}"
        )
        return [FanoutRisk(msg, source_path=step_path)]
    if rel.from_entity not in state.prefixes:
        msg = (
            f"relationship {rel.name!r} joins from entity {rel.from_entity!r}, which is "
            "neither the base nor a previously flattened entity — chains flatten "
            "transitively in authored order (RFC 0010 D3). Fix: flatten a relationship "
            f"reaching {rel.from_entity!r} first"
        )
        return [FanoutRisk(msg, source_path=step_path)]
    to_entity = entities.get(rel.to_entity)
    if to_entity is None:
        msg = (
            f"relationship {rel.name!r} joins entity {rel.to_entity!r}, which no mapping "
            "lowers — a mart cannot flatten an unbuilt entity"
        )
        return [GuardrailError(msg, source_path=step_path)]

    from_prefix = state.prefixes[rel.from_entity]
    state.joins.append(
        MartJoinIR(
            relationship=rel.name,
            entity=rel.to_entity,
            prefix=step.prefix,
            on=tuple((f"{from_prefix}{from_col}", to_col) for from_col, to_col in rel.via),
        )
    )
    violations: list[GuardrailError] = []
    for column in to_entity.columns:  # sorted by name on EntityIR
        flattened = f"{step.prefix}{column.name}"
        existing = state.columns.get(flattened)
        if existing is not None:
            msg = (
                f"flattened column {flattened!r} (column {column.name!r} of entity "
                f"{rel.to_entity!r}) collides with the column already flattened from "
                f"entity {existing.source_entity!r} — collisions are errors, never "
                "auto-renamed (RFC 0010 D3). Fix: change the prefix"
            )
            violations.append(GuardrailError(msg, source_path=f"{path}.flatten[{index}].prefix"))
            continue
        state.columns[flattened] = MartColumnIR(
            name=flattened,
            type=column.type,
            source_entity=rel.to_entity,
            source_column=column.name,
        )
    state.prefixes.setdefault(rel.to_entity, step.prefix)
    return violations


def _flatten_date(
    step: DateRoleStep,
    index: int,
    path: str,
    base: EntityIR,
    state: _Flatten,
) -> list[GuardrailError]:
    """One ``date:`` step: validate role and source column, then expand into
    the ``<role>_<bucket>`` columns with their :class:`DimensionRef`s."""
    role_path = f"{path}.flatten[{index}].role"
    if step.role in state.roles:
        msg = (
            f"date role {step.role!r} is declared more than once — a mart may declare "
            "the same role at most once (RFC 0010 §5.2). Fix: rename one of the roles"
        )
        return [GuardrailError(msg, source_path=role_path)]
    state.roles.append(step.role)
    date_path = f"{path}.flatten[{index}].date"
    source = next((c for c in base.columns if c.name == step.date), None)
    if source is None:
        known = sorted(c.name for c in base.columns)
        msg = (
            f"date role {step.role!r} names column {step.date!r}, which is not a column "
            f"of base entity {base.name!r}; known columns: {known}"
        )
        return [GuardrailError(msg, source_path=date_path)]
    if not isinstance(source.type, (DateType, TimestampType)):
        msg = (
            f"date role source column {step.date!r} has type "
            f"{_type_name(source.type)!r}; a role-playing time dimension requires a "
            "date or timestamp column (RFC 0010 §5.2)"
        )
        return [GuardrailError(msg, source_path=date_path)]
    violations: list[GuardrailError] = []
    for bucket in DATE_BUCKETS:
        name = f"{step.role}_{bucket}"
        existing = state.columns.get(name)
        if existing is not None:
            msg = (
                f"date-role column {name!r} collides with the column already flattened "
                f"from entity {existing.source_entity!r} — collisions are errors, never "
                "auto-renamed (RFC 0010 D3). Fix: rename the role"
            )
            violations.append(GuardrailError(msg, source_path=role_path))
            continue
        state.columns[name] = MartColumnIR(
            name=name,
            type=DateType(),  # buckets are calendar dates; emitters cast (RFC 0010 D4)
            source_entity=base.name,
            source_column=step.date,
            ref=DimensionRef(dimension=bucket, role=step.role),
        )
    return violations


def _check_measures(
    mart: Mart,
    path: str,
    draft: ProjectIR,
    entities: dict[str, EntityIR],
) -> list[GuardrailError]:
    """RFC 0010 §5.5 rules 1 and 5: measures are reachable metrics whose
    grain strictly equals the mart grain."""
    metrics = {m.name: m for m in draft.metrics}
    unreachable = {u.name: u for u in draft.unreachable}
    violations: list[GuardrailError] = []
    for measure in mart.measures:
        measure_path = f"{path}.measures.{measure}"
        metric = metrics.get(measure)
        if metric is None:
            if measure in unreachable:
                missing = list(unreachable[measure].missing)
                msg = (
                    f"measure {measure!r} is an unreachable metric — its leaves "
                    f"{missing} have no mapped derivation path (RFC 0005 §5.3), so the "
                    "mart cannot serve it. Fix: map the missing leaves, or remove the "
                    "measure"
                )
            else:
                msg = f"measure names no declared metric {measure!r}; known: {sorted(metrics)}"
            violations.append(GuardrailError(msg, source_path=measure_path))
            continue
        if metric.grain != mart.grain:
            msg = (
                f"measure {measure!r} has grain {metric.grain!r} "
                f"({_grain_prose(metric.grain, entities)}), not the mart's grain "
                f"{mart.grain!r} ({_grain_prose(mart.grain, entities)}) — measure grain "
                "must strictly equal mart grain (RFC 0010 D2). Flattened into the mart "
                f"it is duplicated once per {mart.grain!r} row and any SUM over it "
                "overstates. Fix: remove it from this mart's measures, or serve it "
                f"from a mart at grain {metric.grain!r}"
            )
            violations.append(GrainViolation(msg, source_path=measure_path))
    return violations


def _materialization(mart: Mart) -> Materialization:
    """RFC 0002 D7, applied to marts as to entities (RFC 0010 §4): explicit
    wins; else partitioned marts default to incremental-by-partition."""
    if mart.materialization is not None:
        return Materialization(mart.materialization)
    if mart.partition_by:
        return Materialization.INCREMENTAL_BY_PARTITION
    return Materialization.FULL


def _mart_ir(name: str, mart: Mart, state: _Flatten) -> MartIR:
    columns = tuple(sorted(state.columns.values(), key=lambda c: c.name))
    # Every flattened column is a requestable dimension (RFC 0010 §10). A
    # bucket column's ref.qualified equals its column name, so sorting by
    # column name is sorting by qualified name.
    dimensions = tuple(
        MartDimensionIR(
            ref=column.ref if column.ref is not None else DimensionRef(dimension=column.name),
            column=column.name,
        )
        for column in columns
    )
    return MartIR(
        name=name,
        grain=mart.grain,
        base=mart.base,
        columns=columns,
        measures=tuple(sorted(mart.measures)),
        dimensions=dimensions,
        joins=tuple(state.joins),  # authored order — join order is semantic
        partition_by=partition_specs(mart.partition_by),
        materialization=_materialization(mart),
        cost_hint=mart.cost_hint,
    )


def _lower_mart(
    name: str, mart: Mart, draft: ProjectIR
) -> tuple[MartIR | None, list[GuardrailError]]:
    path = f"marts: marts.{name}"
    entities = {e.name: e for e in draft.entities}
    base = entities.get(mart.base)
    if base is None:
        msg = (
            f"mart base names entity {mart.base!r}, which no mapping lowers; "
            f"mapped entities: {sorted(entities)}"
        )
        return None, [GuardrailError(msg, source_path=f"{path}.base")]

    violations: list[GuardrailError] = []
    if mart.grain != mart.base:
        msg = (
            f"mart grain {mart.grain!r} does not equal its base entity {mart.base!r} "
            f"(grain: {base.grain}) — a mart is a fact table at exactly its base grain "
            f"(RFC 0010 D2). Fix: declare grain: {mart.base}, or rebase the mart"
        )
        violations.append(GrainViolation(msg, source_path=f"{path}.grain"))

    state = _Flatten(
        columns={
            column.name: MartColumnIR(
                name=column.name,
                type=column.type,
                source_entity=base.name,
                source_column=column.name,
            )
            for column in base.columns
        },
        prefixes={base.name: ""},
        joins=[],
        roles=[],
    )
    for index, step in enumerate(mart.flatten):
        if isinstance(step, ViaStep):
            violations.extend(_flatten_via(step, index, path, draft, entities, state))
        else:
            violations.extend(_flatten_date(step, index, path, base, state))
    violations.extend(_check_measures(mart, path, draft, entities))
    if mart.measures and not state.roles:
        msg = (
            f"mart carries measures {sorted(mart.measures)} but declares no date role — "
            "MetricFlow requires agg_time_dimension on every measure and fails obscurely "
            "without one (RFC 0010 D9). Fix: add a date role flatten step, e.g. "
            "{date: <date/timestamp column>, role: <role>}"
        )
        violations.append(MartMissingTimeDimension(msg, source_path=path))
    if violations:
        return None, violations
    return _mart_ir(name, mart, state), []


def lower_marts(mart_set: MartSet | None, draft: ProjectIR) -> MartLowering:
    """Resolve every authored mart against the draft IR (RFC 0010 D6).

    Total — never raises: the cleanly lowered marts come back sorted by name,
    and every violation across all marts comes back as guardrail leaves for
    the stage's single aggregate (RFC 0006 §5.1). A mart with any violation
    contributes no :class:`MartIR`; a project without a marts document lowers
    to the empty tuple (RFC 0010 D7).
    """
    if mart_set is None:
        return MartLowering(marts=(), violations=())
    marts: list[MartIR] = []
    violations: list[GuardrailError] = []
    for name in sorted(mart_set.marts):
        mart_ir, found = _lower_mart(name, mart_set.marts[name], draft)
        violations.extend(found)
        if mart_ir is not None:
            marts.append(mart_ir)
    return MartLowering(marts=tuple(marts), violations=tuple(violations))
