"""Compact hand-built IR builders for the plan-stage tests (RFC 0007).

The differ is a pure function of two ``ProjectIR``s, so its unit tests build
minimal trees directly — one knob per classification branch. Collections are
sorted here exactly as the real builder sorts them (RFC 0003 §5.3), so tests
may pass members in any order.
"""

from __future__ import annotations

from bloomery.ir import (
    Additivity,
    AuditIR,
    ColumnIR,
    DateDimensionIR,
    EntityIR,
    MartColumnIR,
    MartDimensionIR,
    MartIR,
    MartJoinIR,
    Materialization,
    MetricIR,
    PartitionSpec,
    ProjectIR,
    Ratio,
    RelationshipIR,
    SCDKind,
    SemiAdditivePolicy,
    SourceFieldIR,
    SourceIR,
    SqlExpr,
    TaxBasis,
    Unit,
    UnreachableMetric,
)
from bloomery.typing import LogicalType, StringType


def column(
    name: str,
    *,
    type_: LogicalType | None = None,
    canonical: str | None = None,
    unit: Unit | None = None,
    tax_basis: TaxBasis | None = None,
    expr: str | None = None,
    recipe_id: str | None = None,
    renamed_from: str | None = None,
    required: bool = False,
    description: str | None = None,
) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=type_ if type_ is not None else StringType(),
        canonical=canonical,
        unit=unit,
        tax_basis=tax_basis,
        expr=SqlExpr(expr if expr is not None else name),
        recipe_id=recipe_id,
        renamed_from=renamed_from,
        required=required,
        description=description,
    )


def entity(
    name: str = "order_item",
    *,
    grain: str = "one row per item",
    key: tuple[str, ...] = ("id",),
    scd: SCDKind = SCDKind.TYPE1,
    materialization: Materialization = Materialization.FULL,
    partition_by: tuple[PartitionSpec, ...] = (),
    columns: tuple[ColumnIR, ...] | None = None,
    relation: str = "raw__items",
    source_fields: tuple[SourceFieldIR, ...] = (),
    audits: tuple[AuditIR, ...] = (),
) -> EntityIR:
    resolved = columns if columns is not None else (column("id", required=True),)
    return EntityIR(
        name=name,
        grain=grain,
        key=key,
        scd=scd,
        materialization=materialization,
        partition_by=partition_by,
        columns=tuple(sorted(resolved, key=lambda c: c.name)),
        source=SourceIR(
            relation=relation,
            fields=tuple(sorted(source_fields, key=lambda f: (f.target_field, f.source_path))),
        ),
        audits=audits,
    )


def metric(
    name: str,
    *,
    grain: str = "order_item",
    additivity: Additivity = Additivity.ADDITIVE,
    agg: str | None = "sum",
    expr: str | None = "amount",
    ratio: Ratio | None = None,
    semi_additive: SemiAdditivePolicy | None = None,
    description: str | None = None,
    depends_on: tuple[str, ...] = (),
) -> MetricIR:
    return MetricIR(
        name=name,
        grain=grain,
        additivity=additivity,
        agg=agg,
        expr=SqlExpr(expr) if expr is not None else None,
        ratio=ratio,
        semi_additive=semi_additive,
        description=description,
        depends_on=tuple(sorted(depends_on)),
    )


def mart(
    name: str = "items",
    *,
    grain: str = "order_item",
    base: str = "order_item",
    columns: tuple[MartColumnIR, ...] = (),
    measures: tuple[str, ...] = (),
    dimensions: tuple[MartDimensionIR, ...] = (),
    joins: tuple[MartJoinIR, ...] = (),
    partition_by: tuple[PartitionSpec, ...] = (),
    materialization: Materialization = Materialization.FULL,
    cost_hint: int = 1,
) -> MartIR:
    return MartIR(
        name=name,
        grain=grain,
        base=base,
        columns=tuple(sorted(columns, key=lambda c: c.name)),
        measures=tuple(sorted(measures)),
        dimensions=dimensions,
        joins=joins,
        partition_by=partition_by,
        materialization=materialization,
        cost_hint=cost_hint,
    )


def mart_column(
    name: str,
    *,
    type_: LogicalType | None = None,
    source_entity: str = "order_item",
    source_column: str | None = None,
) -> MartColumnIR:
    return MartColumnIR(
        name=name,
        type=type_ if type_ is not None else StringType(),
        source_entity=source_entity,
        source_column=source_column if source_column is not None else name,
    )


def project(
    *,
    entities: tuple[EntityIR, ...] = (),
    metrics: tuple[MetricIR, ...] = (),
    unreachable: tuple[UnreachableMetric, ...] = (),
    relationships: tuple[RelationshipIR, ...] = (),
    marts: tuple[MartIR, ...] = (),
    date_dimension: DateDimensionIR | None = None,
) -> ProjectIR:
    return ProjectIR(
        bloomery_ir_version=1,
        entities=tuple(sorted(entities, key=lambda e: e.name)),
        metrics=tuple(sorted(metrics, key=lambda m: m.name)),
        unreachable=tuple(sorted(unreachable, key=lambda u: u.name)),
        relationships=tuple(sorted(relationships, key=lambda r: r.name)),
        marts=tuple(sorted(marts, key=lambda m: m.name)),
        date_dimension=date_dimension,
    )
