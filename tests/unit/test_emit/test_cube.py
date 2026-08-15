"""The Cube emitter (RFC 0008 §5.4): artifact shape, dimension typing,
measure meta propagation, calculated ratio measures, the stored-non-additive
defense, and dialect independence."""

from __future__ import annotations

from typing import cast

import pytest
import yaml

from bloomery import Target
from bloomery.dialects import DialectPort
from bloomery.emit import ArtifactKind, EmitContext, EmittedArtifact
from bloomery.emit.base import Feature
from bloomery.emit.cube import CubeEmitter
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import (
    Additivity,
    ColumnIR,
    DimensionRef,
    EntityIR,
    MartColumnIR,
    MartDimensionIR,
    MartIR,
    Materialization,
    MetricIR,
    ProjectIR,
    Ratio,
    SCDKind,
    SourceColumnIR,
    SourceIR,
    SqlExpr,
)
from bloomery.naming import DefaultNaming, PrefixNaming
from bloomery.typing import DateType, DecimalType, LogicalType, StringType
from support.compiling import compile_fixture

pytestmark = pytest.mark.unit


class _PoisonedDialect:
    """A dialect port that refuses to render — proving the Cube emitter is
    dialect-independent by construction, not by luck."""

    name = "poisoned"

    def render(self, node: object) -> str:
        raise AssertionError("the Cube emitter must never render through the dialect port")

    def physical_type(self, t: object) -> str:
        raise AssertionError("the Cube emitter must never map physical types")

    def supports(self, feature: object) -> bool:
        return False


def _ctx(naming: DefaultNaming | PrefixNaming | None = None) -> EmitContext:
    return EmitContext(
        dialect=cast("DialectPort", _PoisonedDialect()),
        naming=naming if naming is not None else DefaultNaming(),
        fingerprint="blm1:test",
    )


def _column(name: str, column_type: LogicalType) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=column_type,
        canonical=None,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=False,
    )


def _projection(name: str) -> SourceColumnIR:
    """This source\'s lowering of the column (RFC 0024 D26)."""
    return SourceColumnIR(name=name, expr=SqlExpr(name))


#: Every column these builders declare, lowered as itself. The emitted
#: SELECT projects `SourceIR.columns`, so a name missing here is a column
#: the model cannot produce (RFC 0024 D26).
_SOURCE = SourceIR(
    relation="src",
    columns=tuple(
        _projection(name)
        for name in (
            "amount",
            "order_id",
        )
    ),
)


def _entity(name: str = "order") -> EntityIR:
    return EntityIR(
        name=name,
        grain=f"one row per {name}",
        key=("order_id",),
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=(_column("amount", DecimalType(12, 4)), _column("order_id", StringType())),
        source=_SOURCE,
    )


def _mart(measures: tuple[str, ...]) -> MartIR:
    columns = (
        MartColumnIR(name="amount", type=DecimalType(12, 4), source_entity="order",
                     source_column="amount"),
        MartColumnIR(name="order_id", type=StringType(), source_entity="order",
                     source_column="order_id"),
        MartColumnIR(name="ordered_day", type=DateType(), source_entity="order",
                     source_column="order_date",
                     ref=DimensionRef(dimension="day", role="ordered")),
    )  # fmt: skip
    return MartIR(
        name="orders",
        grain="order",
        base="order",
        columns=columns,
        measures=measures,
        dimensions=tuple(
            MartDimensionIR(
                ref=c.ref if c.ref is not None else DimensionRef(dimension=c.name), column=c.name
            )
            for c in columns
        ),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
    )


def _project(metrics: tuple[MetricIR, ...], measures: tuple[str, ...]) -> ProjectIR:
    return ProjectIR(entities=(_entity(),), metrics=metrics, marts=(_mart(measures),))


def _metric(
    name: str,
    *,
    additivity: Additivity = Additivity.ADDITIVE,
    agg: str | None = "sum",
    expr: str | None = "amount",
    ratio: Ratio | None = None,
) -> MetricIR:
    return MetricIR(
        name=name,
        grain="order",
        additivity=additivity,
        agg=agg,
        expr=SqlExpr(expr) if expr is not None else None,
        ratio=ratio,
        semi_additive=None,
    )


def _cube_yaml(artifacts: tuple[EmittedArtifact, ...], name: str) -> dict[str, object]:
    artifact = next(a for a in artifacts if a.path == f"model/cubes/{name}.yml")
    (cube,) = cast("dict[str, list[dict[str, object]]]", yaml.safe_load(artifact.content))["cubes"]
    return cube


def test_capabilities_declare_the_cube_feature_set() -> None:
    assert CubeEmitter().capabilities().supported == frozenset(
        {
            Feature.QUERY_TIME_JOIN,
            Feature.MULTI_FACT,
            Feature.ROW_LEVEL_SECURITY,
            Feature.ROLE_PLAYING_DIM,
        }
    )


def test_emit_never_touches_the_dialect_port() -> None:
    # _PoisonedDialect raises on any render — success proves independence.
    artifacts = CubeEmitter().emit(_project((_metric("revenue"),), ("revenue",)), _ctx())
    assert [a.path for a in artifacts] == [
        "model/cubes/orders.yml",
        "model/views/orders_view.yml",
    ]
    assert all(a.kind is ArtifactKind.MODEL for a in artifacts)


def test_sql_table_comes_from_the_gold_naming_policy() -> None:
    artifacts = CubeEmitter().emit(
        _project((_metric("revenue"),), ("revenue",)), _ctx(PrefixNaming(prefix="acme"))
    )
    cube = _cube_yaml(artifacts, "orders")
    assert cube["sql_table"] == "acme_gold.mart_orders"


def test_dimensions_type_by_role_and_logical_type() -> None:
    artifacts = CubeEmitter().emit(_project((_metric("revenue"),), ("revenue",)), _ctx())
    dimensions = {
        cast("str", d["name"]): d
        for d in cast("list[dict[str, object]]", _cube_yaml(artifacts, "orders")["dimensions"])
    }
    assert dimensions["amount"]["type"] == "number"
    assert dimensions["order_id"]["type"] == "string"
    assert dimensions["ordered_day"]["type"] == "time"
    assert dimensions["ordered_day"]["meta"] == {"granularity": "day"}


def test_measure_meta_propagates_additivity_and_grain() -> None:
    (artifact, _view) = compile_fixture("ecom_basic", target=Target.CUBE)
    (cube,) = cast("dict[str, list[dict[str, object]]]", yaml.safe_load(artifact.content))["cubes"]
    (measure,) = cast("list[dict[str, object]]", cube["measures"])
    assert measure["name"] == "gross_revenue"
    assert measure["type"] == "sum"
    assert measure["sql"] == "unit_price * quantity"
    assert measure["meta"] == {"additivity": "additive", "grain": "order_item"}


def test_semi_additive_measure_carries_its_policy_in_meta() -> None:
    artifacts = compile_fixture("semi_additive_inventory", target=Target.CUBE)
    # The fixture also emits the quality mart's cube (RFC 0016 §5.8).
    artifact = next(a for a in artifacts if a.path == "model/cubes/inventory.yml")
    (cube,) = cast("dict[str, list[dict[str, object]]]", yaml.safe_load(artifact.content))["cubes"]
    (measure,) = cast("list[dict[str, object]]", cube["measures"])
    assert measure["name"] == "stock_on_hand"
    assert measure["type"] == "sum"
    assert measure["meta"] == {
        "additivity": "semi_additive",
        "grain": "inventory_level",
        "semi_additive": {"over": "stock_date", "rule": "last"},
    }


def test_count_measure_takes_no_sql_and_ratio_is_calculated() -> None:
    (artifact, _view) = compile_fixture("non_additive_aov", target=Target.CUBE)
    (cube,) = cast("dict[str, list[dict[str, object]]]", yaml.safe_load(artifact.content))["cubes"]
    measures = {
        cast("str", m["name"]): m for m in cast("list[dict[str, object]]", cube["measures"])
    }
    assert measures["order_count"]["type"] == "count"
    assert "sql" not in measures["order_count"]  # Cube's count counts rows
    aov = measures["average_order_value"]
    assert aov["type"] == "number"  # calculated, never a stored aggregate
    assert aov["sql"] == "{revenue} / NULLIF({order_count}, 0)"
    assert aov["meta"] == {"additivity": "non_additive"}


def test_ratio_requires_both_components_on_the_owning_mart() -> None:
    # The denominator is not a measure anywhere: the ratio is simply absent
    # (the planner refuses it by name at request time, RFC 0013 D6).
    metrics = (
        _metric(
            "aov",
            additivity=Additivity.NON_ADDITIVE,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="revenue", denominator="order_count"),
        ),
        _metric("revenue"),
    )
    artifacts = CubeEmitter().emit(_project(metrics, ("revenue",)), _ctx())
    measures = cast("list[dict[str, object]]", _cube_yaml(artifacts, "orders")["measures"])
    assert [m["name"] for m in measures] == ["revenue"]


def test_stored_non_additive_is_refused_defense_in_depth() -> None:
    metrics = (
        _metric(
            "aov",
            additivity=Additivity.NON_ADDITIVE,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="revenue", denominator="order_count"),
        ),
    )
    with pytest.raises(UnsupportedByTarget, match=r"mart 'orders' stores non-additive.*'aov'"):
        CubeEmitter().emit(_project(metrics, ("aov",)), _ctx())


def test_unmappable_aggregation_is_refused() -> None:
    metrics = (_metric("revenue", agg="median"),)
    with pytest.raises(UnsupportedByTarget, match=r"'revenue' uses aggregation 'median'"):
        CubeEmitter().emit(_project(metrics, ("revenue",)), _ctx())


def test_measure_without_expression_is_refused() -> None:
    metrics = (_metric("revenue", expr=None),)
    with pytest.raises(UnsupportedByTarget, match=r"'revenue' has no expression"):
        CubeEmitter().emit(_project(metrics, ("revenue",)), _ctx())


def test_view_exposes_the_mart_members() -> None:
    artifacts = CubeEmitter().emit(_project((_metric("revenue"),), ("revenue",)), _ctx())
    view_artifact = next(a for a in artifacts if a.path == "model/views/orders_view.yml")
    assert "-- " not in view_artifact.content  # YAML comments only
    (view,) = cast(
        "dict[str, list[dict[str, object]]]", yaml.safe_load(view_artifact.content)
    )["views"]
    assert view["name"] == "orders_view"
    assert view["cubes"] == [{"join_path": "orders", "includes": "*"}]


def test_fingerprint_header_is_yaml_commented() -> None:
    artifacts = CubeEmitter().emit(_project((_metric("revenue"),), ("revenue",)), _ctx())
    for artifact in artifacts:
        assert artifact.content.startswith(
            "# Generated by bloomery — do not edit.\n# fingerprint: blm1:test\n"
        )
        assert artifact.content.endswith("\n")
        assert not artifact.content.endswith("\n\n")


# ....................... #
# RFC 0008 §10 → D17: one view per **mart**


TWO_MARTS_ONE_GRAIN_MODEL = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12,4)"}
      order_date: {type: timestamp}
"""

TWO_MARTS_ONE_GRAIN_MAPPING = """
mapping_version: 1
target: order
source: shop__orders
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 4]}]}
  order_date: {from: "$.created_at", transform: [{parse_ts: ISO8601}]}
"""

TWO_MARTS_ONE_GRAIN_MARTS = """
marts_version: 1
marts:
  finance:
    grain: order
    base: order
    flatten: [{date: order_date, role: booked}]
  ops:
    grain: order
    base: order
    flatten: [{date: order_date, role: shipped}]
"""


def test_two_marts_at_one_grain_are_two_views() -> None:
    """RFC 0008 §10 asked whether views group per metric or per metric-*grain*.
    Neither: **per mart**, and this is the case that tells the three apart —
    two marts at one grain, which the corpus otherwise never exercises.

    Per-grain would have to merge these into one view, and a Cube view over two
    cubes needs a ``join_path`` between them. bloomery models no relationship
    between marts — they are independently pre-joined (RFC 0010) — so a merged
    view could only be emitted by inventing a join, which is what this project
    refuses everywhere else. Per-metric fragments the dimension set for no
    gain, since ``measure_owners`` already pins each metric to one mart.
    """
    from bloomery import Target, compile_project, load_project

    project = load_project(
        {
            "entity_model": TWO_MARTS_ONE_GRAIN_MODEL,
            "mapping": TWO_MARTS_ONE_GRAIN_MAPPING,
            "marts": TWO_MARTS_ONE_GRAIN_MARTS,
        }
    )
    artifacts = compile_project(project, target=Target.CUBE, dialect="duckdb")
    views = sorted(a.path for a in artifacts if a.path.startswith("model/views/"))
    assert views == ["model/views/finance_view.yml", "model/views/ops_view.yml"]


def test_a_view_names_exactly_one_cube() -> None:
    """The structural half of the same decision: one ``join_path``, no join.
    A view naming two cubes is the shape bloomery has nothing to build the
    join from."""
    from bloomery import Target, compile_project, load_project

    project = load_project(
        {
            "entity_model": TWO_MARTS_ONE_GRAIN_MODEL,
            "mapping": TWO_MARTS_ONE_GRAIN_MAPPING,
            "marts": TWO_MARTS_ONE_GRAIN_MARTS,
        }
    )
    for artifact in compile_project(project, target=Target.CUBE, dialect="duckdb"):
        if not artifact.path.startswith("model/views/"):
            continue
        (view,) = yaml.safe_load(artifact.content)["views"]
        assert len(view["cubes"]) == 1
        assert view["cubes"][0]["includes"] == "*"
