"""Hand-constructed IR trees for M1 tests (the spec→IR builder is M2+).

``build_project_ir`` exercises every RFC 0003 / RFC 0010 node type and is
imported by both the fingerprint unit tests and the subprocess determinism
guard, so the exact same tree is hashed under different ``PYTHONHASHSEED``s.
"""

from __future__ import annotations

from bloomery.ir import (
    Additivity,
    AuditIR,
    Cardinality,
    ColumnIR,
    DateDimensionIR,
    DimensionRef,
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
    SemiAdditiveRule,
    SourceFieldIR,
    SourceIR,
    SqlExpr,
    TaxBasis,
    TransformStepIR,
    Unit,
    UnreachableMetric,
)
from bloomery.typing import DecimalType, IntType, StringType, TimestampType


def _column(name: str, *, canonical: str | None = None) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=DecimalType(12, 4) if name == "unit_price" else StringType(),
        canonical=canonical,
        unit=Unit.CURRENCY if name == "unit_price" else None,
        tax_basis=TaxBasis.NET if name == "unit_price" else None,
        expr=SqlExpr(name),
        recipe_id="from_total" if name == "unit_price" else None,
        renamed_from=None,
        required=name == "order_id",
    )


def build_project_ir(*, column_names: tuple[str, ...] = ("unit_price", "order_id")) -> ProjectIR:
    """One ProjectIR reaching every node type. ``column_names`` may arrive in
    any order — columns are sorted here, as the real builder must sort them
    (RFC 0003 §5.3), so permuted input yields an equal IR."""
    columns = tuple(_column(name, canonical=name) for name in sorted(column_names))
    entity = EntityIR(
        name="order_item",
        grain="one row per line on an order",
        key=("order_id", "line_no"),  # authored order preserved
        scd=SCDKind.TYPE1,
        materialization=Materialization.INCREMENTAL_BY_PARTITION,
        partition_by=(PartitionSpec(transform="days", column="order_date"),),
        columns=columns,
        source=SourceIR(
            relation="shopify__order_lines",
            fields=(
                SourceFieldIR(
                    target_field="order_id",
                    source_path="$.order_id",
                    transform=(TransformStepIR(name="to_string"),),
                ),
                SourceFieldIR(
                    target_field="unit_price",
                    source_path="$.total",
                    transform=(
                        TransformStepIR(name="to_decimal", args=(12, 4)),
                        TransformStepIR(name="parse_ts", args=("ISO8601",)),
                    ),
                ),
            ),
        ),
        audits=(AuditIR(kind="not_null", column="order_id"),),
    )
    metrics = (
        MetricIR(
            name="average_order_value",
            grain="order",
            additivity=Additivity.NON_ADDITIVE,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="gross_revenue", denominator="order_count"),
            semi_additive=None,
            depends_on=("gross_revenue", "order_count"),
        ),
        MetricIR(
            name="gross_revenue",
            grain="order_item",
            additivity=Additivity.ADDITIVE,
            agg="sum",
            expr=SqlExpr("unit_price * quantity"),
            ratio=None,
            semi_additive=None,
            depends_on=("quantity", "unit_price"),
        ),
        MetricIR(
            name="stock_on_hand",
            grain="inventory_level",
            additivity=Additivity.SEMI_ADDITIVE,
            agg="sum",
            expr=SqlExpr("stock_level"),
            ratio=None,
            semi_additive=SemiAdditivePolicy(
                over=DimensionRef(dimension="date"),
                rule=SemiAdditiveRule.LAST,
            ),
            depends_on=("stock_level",),
        ),
    )
    ordered = DimensionRef(dimension="date", role="ordered")
    mart = MartIR(
        name="order_items",
        grain="order_item",
        base="order_item",
        columns=(
            MartColumnIR(
                name="ordered_day",
                type=TimestampType(),
                source_entity="order_item",
                source_column="order_date",
                ref=ordered,
            ),
            MartColumnIR(
                name="quantity",
                type=IntType(),
                source_entity="order_item",
                source_column="quantity",
            ),
        ),
        measures=("gross_revenue",),
        dimensions=(MartDimensionIR(ref=ordered, column="ordered_day"),),
        joins=(
            MartJoinIR(
                relationship="item_of_order",
                entity="order",
                prefix="order_",
                on=(("order_id", "order_id"),),
            ),
        ),
        partition_by=(PartitionSpec(transform="days", column="ordered_day"),),
        materialization=Materialization.FULL,
        cost_hint=2,
    )
    return ProjectIR(
        bloomery_ir_version=3,
        entities=(entity,),
        metrics=metrics,
        unreachable=(UnreachableMetric(name="net_revenue", missing=("discount",)),),
        relationships=(
            RelationshipIR(
                name="item_of_order",
                from_entity="order_item",
                to_entity="order",
                via=(("order_id", "order_id"),),
                cardinality=Cardinality.MANY_TO_ONE,
            ),
        ),
        marts=(mart,),
        date_dimension=DateDimensionIR(
            name="dim_date", grain="day", start_year=2020, end_year=2030
        ),
    )
