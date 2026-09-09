"""The Cube emitter (RFC 0008 §5.4): artifact shape, dimension typing,
measure meta propagation, calculated ratio measures, the stored-non-additive
defense, and dialect independence."""

from __future__ import annotations

import dataclasses
import re
from typing import cast

import pytest
import yaml

from bloomery import Target
from bloomery.dialects import DialectPort
from bloomery.emit import ArtifactKind, EmitContext, EmittedArtifact
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
    RollupIR,
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
        sources=(_SOURCE,),
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


def test_a_distinct_count_is_a_stored_count_distinct_measure() -> None:
    """`distinct_count` is a stored measure — outside `COMPUTED` — lowered as
    the `count_distinct` type Cube already had, with the class in `meta` so
    the word reaches the artifact (logs/T-0028.md).
    """
    metric = _metric(
        "distinct_customers",
        additivity=Additivity.DISTINCT_COUNT,
        agg="count_distinct",
        expr="customer_id",
    )
    artifacts = CubeEmitter().emit(_project((metric,), ("distinct_customers",)), _ctx())
    (measure,) = cast("list[dict[str, object]]", _cube_yaml(artifacts, "orders")["measures"])

    assert measure["type"] == "count_distinct"
    assert measure["sql"] == "customer_id"
    assert measure["meta"] == {"additivity": "distinct_count", "grain": "order"}


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
    # The word reaches the artifact, so minting the member moves bytes: Cube
    # carries the additivity as measure metadata (logs/T-0023.md, D-148).
    assert aov["meta"] == {"additivity": "ratio"}


def test_ratio_requires_both_components_on_the_owning_mart() -> None:
    # The denominator is not a measure anywhere: the ratio is simply absent
    # (the planner refuses it by name at request time, RFC 0013 D6).
    metrics = (
        _metric(
            "aov",
            additivity=Additivity.RATIO,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="revenue", denominator="order_count"),
        ),
        _metric("revenue"),
    )
    artifacts = CubeEmitter().emit(_project(metrics, ("revenue",)), _ctx())
    measures = cast("list[dict[str, object]]", _cube_yaml(artifacts, "orders")["measures"])
    assert [m["name"] for m in measures] == ["revenue"]


def test_a_named_non_additive_metric_is_served_when_its_components_are_stored() -> None:
    """A mart's `measures:` is "metrics this mart serves", not "numbers it
    stores" — so naming a ratio there is an ordinary request, served by
    computing it from components the mart does store.

    This emitter used to refuse it, and only when the author named it: leaving
    the ratio out of `measures:` produced the very same calculated measure. That
    made Cube the one target rejecting a project the other three compiled.
    """
    metrics = (
        _metric("revenue", agg="sum", expr="amount"),
        _metric("order_count", agg="count", expr="order_id"),
        _metric(
            "aov",
            additivity=Additivity.RATIO,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="revenue", denominator="order_count"),
        ),
    )
    artifacts = CubeEmitter().emit(_project(metrics, ("aov", "order_count", "revenue")), _ctx())
    body = next(a.content for a in artifacts if a.path.endswith("orders.yml"))
    assert "name: aov" in body
    # Computed, never stored: a ratio is a `number` over the two measures.
    assert "{revenue} / NULLIF({order_count}, 0)" in body
    assert body.count("name: aov") == 1  # named *and* derivable emits it once


def test_a_non_additive_metric_whose_components_are_absent_is_simply_absent() -> None:
    """The companion case, and the one that stays quiet.

    With no `revenue` or `order_count` on the mart there is nothing to compute
    from, so the metric does not appear — matching what the MetricFlow emitter
    does with the same spec, where the planner refuses it by name at request
    time rather than the compiler refusing the project.
    """
    metrics = (
        _metric(
            "aov",
            additivity=Additivity.RATIO,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="revenue", denominator="order_count"),
        ),
    )
    artifacts = CubeEmitter().emit(_project(metrics, ("aov",)), _ctx())
    body = next(a.content for a in artifacts if a.path.endswith("orders.yml"))
    assert "aov" not in body


def test_a_non_additive_metric_without_a_ratio_is_refused_not_dropped() -> None:
    """The additivity guardrail accepts a non-additive metric backed by an
    additive *decomposition* instead of a ratio (RFC 0006 §5.4), and only the
    ratio has a Cube shape.

    Skipping every non-additive metric from the stored pass while the
    calculated pass picks up only the ratio-backed ones made this one vanish
    from the artifact — a served metric the author named, silently absent, on
    the one target that used to refuse it loudly.
    """
    metrics = (
        _metric("revenue", agg="sum", expr="amount"),
        _metric(
            "margin_rate",
            additivity=Additivity.NON_ADDITIVE,
            agg=None,
            expr="amount / 2",
            ratio=None,
        ),
    )
    with pytest.raises(UnsupportedByTarget, match=r"'margin_rate' is non_additive"):
        CubeEmitter().emit(_project(metrics, ("margin_rate", "revenue")), _ctx())


def test_a_ratio_never_templates_against_a_measure_the_cube_does_not_define() -> None:
    """The consequence the refusal above prevents, kept as its own case.

    A ratio whose component is itself non-additive and decomposition-backed
    emitted `{margin_rate} / NULLIF({order_count}, 0)` while `margin_rate` was
    nowhere in the cube — Cube's `{member}` templating resolving against a
    measure that does not exist.
    """
    metrics = (
        _metric("order_count", agg="count", expr="order_id"),
        _metric(
            "margin_rate",
            additivity=Additivity.NON_ADDITIVE,
            agg=None,
            expr="amount / 2",
            ratio=None,
        ),
        _metric(
            "rate_per_order",
            additivity=Additivity.RATIO,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="margin_rate", denominator="order_count"),
        ),
    )
    measures = ("margin_rate", "order_count", "rate_per_order")
    with pytest.raises(UnsupportedByTarget, match=r"'margin_rate' is non_additive"):
        CubeEmitter().emit(_project(metrics, measures), _ctx())


def test_every_member_a_measure_templates_is_a_measure_the_cube_defines() -> None:
    """The invariant behind both cases above, asserted directly rather than
    through the shapes that happened to break it."""
    metrics = (
        _metric("revenue", agg="sum", expr="amount"),
        _metric("order_count", agg="count", expr="order_id"),
        _metric(
            "aov",
            additivity=Additivity.RATIO,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="revenue", denominator="order_count"),
        ),
    )
    artifacts = CubeEmitter().emit(_project(metrics, ("aov", "order_count", "revenue")), _ctx())
    cube = _cube_yaml(artifacts, "orders")
    measures = cast("list[dict[str, object]]", cube["measures"])
    defined = {cast("str", measure["name"]) for measure in measures}
    referenced = {
        member
        for measure in measures
        for member in re.findall(r"\{(\w+)\}", cast("str", measure.get("sql", "")))
    }
    assert referenced <= defined, f"templated against undefined members: {referenced - defined}"


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


# ....................... #
# Rollups → pre_aggregations (RFC 0058 §5.3, P3)


def _bucketed_mart(*buckets: str) -> MartIR:
    """The harness mart plus one date-role bucket column per name.

    Buckets rather than plain date columns, because the count that decides
    `time_dimension:` is of buckets: only a bucket carries the granularity
    Cube requires beside it.
    """

    base = _mart(("revenue",))
    extra = tuple(
        MartColumnIR(name=name, type=DateType(), source_entity="order",
                     source_column="order_date",
                     ref=DimensionRef(dimension=name.removeprefix("ordered_"), role="ordered"))
        for name in buckets
    )  # fmt: skip
    columns = tuple(sorted((*base.columns, *extra), key=lambda c: c.name))
    return dataclasses.replace(
        base,
        columns=columns,
        dimensions=tuple(
            MartDimensionIR(
                ref=c.ref if c.ref is not None else DimensionRef(dimension=c.name), column=c.name
            )
            for c in columns
        ),
    )


def _rolled(
    *rollups: RollupIR,
    mart: MartIR | None = None,
    metrics: tuple[MetricIR, ...] = (),
) -> ProjectIR:
    return ProjectIR(
        entities=(_entity(),),
        metrics=metrics or (_metric("revenue"),),
        marts=(mart if mart is not None else _mart(("revenue",)),),
        rollups=rollups,
    )


def _rollup(name: str = "orders_monthly", *, keep: tuple[str, ...] = ("ordered_day",),
            measures: tuple[str, ...] = ("revenue",), of: str = "orders") -> RollupIR:
    return RollupIR(name=name, of=of, keep=keep, measures=measures)  # fmt: skip


def _pre_aggs(project: ProjectIR, mart_name: str = "orders") -> list[dict[str, object]]:
    cube = _cube_yaml(CubeEmitter().emit(project, _ctx()), mart_name)
    return cast("list[dict[str, object]]", cube.get("pre_aggregations", []))


def test_a_rollup_becomes_a_pre_aggregation_on_its_parent() -> None:
    """The payoff (§5.3): the block names what the rollup carries and keeps,
    and nothing else — what Cube may serve from it is bounded by what is in
    it."""

    (block,) = _pre_aggs(_rolled(_rollup(keep=("order_id", "ordered_day"))))

    assert block == {
        "name": "orders_monthly",
        "type": "rollup",
        "measures": ["CUBE.revenue"],
        "dimensions": ["CUBE.order_id"],
        "time_dimension": "CUBE.ordered_day",
        "granularity": "day",
    }


def test_a_mart_nothing_rolls_up_has_no_pre_aggregations_key() -> None:
    """Absent rather than empty: every project before RFC 0058 has no rollups,
    and an empty key on every cube would move every existing golden to say
    nothing new."""

    cube = _cube_yaml(CubeEmitter().emit(_project((_metric("revenue"),), ("revenue",)), _ctx()),
                      "orders")  # fmt: skip

    assert "pre_aggregations" not in cube


def test_a_rollup_of_another_mart_does_not_reach_this_cube() -> None:
    """`of:` decides which cube carries the block, and a rollup naming a mart
    this project does not build reaches none."""

    assert _pre_aggs(_rolled(_rollup(of="somewhere_else"))) == []


def test_a_rollup_keeping_one_bucket_and_nothing_else_omits_dimensions() -> None:
    """An empty `dimensions:` is noise rather than information."""

    (block,) = _pre_aggs(_rolled(_rollup(keep=("ordered_day",))))

    assert "dimensions" not in block
    assert block["time_dimension"] == "CUBE.ordered_day"


def test_a_rollup_keeping_no_bucket_names_no_time_dimension() -> None:
    """`granularity:` must accompany `time_dimension:`, and only a bucket
    carries one — so a rollup keeping none names neither."""

    (block,) = _pre_aggs(_rolled(_rollup(keep=("order_id",))))

    assert "time_dimension" not in block
    assert "granularity" not in block
    assert block["dimensions"] == ["CUBE.order_id"]


def test_a_rollup_keeping_two_buckets_names_neither_as_the_time_dimension() -> None:
    """Cube allows one `time_dimension` per pre-aggregation, and picking one of
    two would be arbitrary. Both stay ordinary dimensions: the pre-aggregation
    is semantically identical and only less partitionable (logs/T-0035.md)."""

    project = _rolled(
        _rollup(keep=("ordered_day", "ordered_month")), mart=_bucketed_mart("ordered_month")
    )
    (block,) = _pre_aggs(project)

    assert "time_dimension" not in block
    assert block["dimensions"] == ["CUBE.ordered_day", "CUBE.ordered_month"]


def test_two_rollups_of_one_parent_are_two_blocks_in_name_order() -> None:
    project = _rolled(
        _rollup("orders_by_day", keep=("ordered_day",)),
        _rollup("orders_by_id", keep=("order_id",)),
    )

    assert [block["name"] for block in _pre_aggs(project)] == ["orders_by_day", "orders_by_id"]


def test_a_ratio_is_absent_and_its_operands_are_present() -> None:
    """Cube may only pre-aggregate a stored number. The quotient is calculated
    from the operands R013 required the rollup to carry, so listing it would
    ask Cube to pre-aggregate something the relation never holds."""

    metrics = (
        _metric("orders", agg="count", expr="order_id"),
        _metric("revenue"),
        _metric("aov", additivity=Additivity.RATIO, agg=None, expr=None,
                ratio=Ratio(numerator="revenue", denominator="orders")),
    )  # fmt: skip
    project = _rolled(
        _rollup(measures=("aov", "orders", "revenue")),
        mart=dataclasses.replace(_mart(("aov", "orders", "revenue")), measures=("aov", "orders", "revenue")),
        metrics=metrics,
    )
    (block,) = _pre_aggs(project)

    assert block["measures"] == ["CUBE.orders", "CUBE.revenue"]


def test_a_rollup_is_no_cube_no_view_and_no_member() -> None:
    """Row 14 (`LOCKED`) from the emitter side: a rollup adds a key inside the
    parent's document and nothing else. If it ever became a cube of its own it
    would be a second surface serving the same measures."""

    artifacts = CubeEmitter().emit(_rolled(_rollup()), _ctx())
    cube = _cube_yaml(artifacts, "orders")

    assert [a.path for a in artifacts] == [
        "model/cubes/orders.yml",
        "model/views/orders_view.yml",
    ]
    assert [m["name"] for m in cast("list[dict[str, object]]", cube["measures"])] == ["revenue"]
    assert all("orders_monthly" not in str(d["name"])
               for d in cast("list[dict[str, object]]", cube["dimensions"]))  # fmt: skip


def test_a_rollup_storing_no_measure_is_refused_not_written_empty() -> None:
    """The empty case decided rather than inherited.

    The compile path cannot produce one — R013 requires a ratio's operands be
    carried and they are additive, so a proven rollup always stores a number.
    But this emitter is public and takes any `ProjectIR`, and `measures: []` is
    a model Cube rejects at load without mentioning bloomery.
    """

    ratio = _metric("aov", additivity=Additivity.RATIO, agg=None, expr=None,
                    ratio=Ratio(numerator="revenue", denominator="orders"))  # fmt: skip
    project = _rolled(
        _rollup(measures=("aov",)),
        mart=dataclasses.replace(_mart(("aov",)), measures=("aov",)),
        metrics=(ratio, _metric("orders", agg="count", expr="order_id"), _metric("revenue")),
    )

    with pytest.raises(UnsupportedByTarget, match="stores no measure"):
        CubeEmitter().emit(project, _ctx())


def _two_marts(*, rollup_of: str, measures: tuple[str, ...] = ("revenue",)) -> ProjectIR:
    """Two marts serving one metric, so `measure_owners` has a choice to make.

    `a_cheap` owns every metric both list — lower `cost_hint` wins — which
    leaves `z_dear`'s cube defining none of them.
    """

    base = _mart(measures)
    metrics = tuple(
        _metric(name, agg="count" if name == "orders" else "sum",
                expr="order_id" if name == "orders" else "amount")
        for name in measures
    )  # fmt: skip
    return ProjectIR(
        entities=(_entity(),),
        metrics=metrics,
        marts=(
            dataclasses.replace(base, name="a_cheap", cost_hint=1),
            dataclasses.replace(base, name="z_dear", cost_hint=5),
        ),
        rollups=(_rollup(of=rollup_of, measures=measures),),
    )


def test_a_pre_aggregation_never_names_a_measure_its_cube_does_not_define() -> None:
    """`MartIR.measures` is "metrics this mart serves", and `measure_owners`
    puts each on exactly one cube. A mart listing a metric a cheaper mart owns
    emits no measure for it, so a pre-aggregation naming it would reference a
    member the cube does not define — which Cube rejects or ignores.

    The block is dropped rather than the project refused, which is what this
    file already does with a ratio whose components sit elsewhere: no query
    against this cube can ask for the measure at all, so the block would have
    been unusable rather than merely absent.
    """

    assert _pre_aggs(_two_marts(rollup_of="z_dear"), "z_dear") == []

    (block,) = _pre_aggs(_two_marts(rollup_of="a_cheap"), "a_cheap")
    assert block["measures"] == ["CUBE.revenue"]


def test_a_pre_aggregation_keeps_the_measures_its_cube_does_own() -> None:
    """The partial case: a rollup carrying two measures on a cube owning one
    pre-aggregates that one, which is a correct and useful materialization for
    every query the cube can actually answer."""

    project = _two_marts(rollup_of="z_dear", measures=("orders", "revenue"))
    owner = dataclasses.replace(
        project.marts[1], measures=("orders", "revenue"), cost_hint=5
    )
    # `revenue` moves to the cheap mart and `orders` stays here: one each.
    cheap = dataclasses.replace(project.marts[0], measures=("revenue",), cost_hint=1)
    (block,) = _pre_aggs(dataclasses.replace(project, marts=(cheap, owner)), "z_dear")

    assert block["measures"] == ["CUBE.orders"]


def test_every_measure_a_pre_aggregation_names_is_one_its_cube_defines() -> None:
    """The invariant behind both cases above, asserted directly rather than
    through the shapes that happened to break it — the same statement
    `test_every_member_a_measure_templates_is_a_measure_the_cube_defines` makes
    about ratio templating.
    """

    project = _two_marts(rollup_of="z_dear", measures=("orders", "revenue"))

    for artifact in CubeEmitter().emit(project, _ctx()):
        if not artifact.path.startswith("model/cubes/"):
            continue
        (cube,) = cast("dict[str, list[dict[str, object]]]",
                       yaml.safe_load(artifact.content))["cubes"]  # fmt: skip
        defined = {
            cast("str", m["name"])
            for m in cast("list[dict[str, object]]", cube["measures"])
        }
        for block in cast("list[dict[str, object]]", cube.get("pre_aggregations", [])):
            named = {
                member.removeprefix("CUBE.")
                for member in cast("list[str]", block["measures"])
            }
            assert named <= defined, f"{artifact.path}: {named - defined} not defined"
