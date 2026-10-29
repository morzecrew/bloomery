"""A metric's filter dimensions and its `semi_additive.over` are bound through the
grain's canonical links, as its `expr` is (#368, S-0022/D-11).

A catalog template is the one definition of a metric across projects, so it
names columns by canonical. Only the `expr` was bound: a filter or an `over`
written in canonical names was read as the mart's literal column, and a project
that spelled the column otherwise could not instantiate the template.
"""

from __future__ import annotations

import pytest
from support.compiling import FIXTURES, fixture_sources, load_fixture

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project, plan
from bloomery.ir import ColumnIR, MetricIR, ProjectIR, bound_name
from bloomery.ir.lower import unbound
from bloomery.plan import ChangeClass
from bloomery.typing import StringType

pytestmark = pytest.mark.unit

FIXTURE = "semi_additive_inventory"

#: Canonicals for the two columns the template reads by link.
CANONICALS = (
    "  warehouse_code:\n    entity: inventory_level\n    type: string\n"
    "    recipes:\n      - {id: direct, requires: [warehouse_code]}\n"
    "  stock_at:\n    entity: inventory_level\n    type: date\n"
    "    recipes:\n      - {id: direct, requires: [stock_at]}\n"
)

TEMPLATE = (
    "metric_templates:\n"
    "  stock_in_w1:\n"
    "    requires: [stock_level]\n"
    "    grain: inventory_level\n"
    "    additivity: semi_additive\n"
    "    agg: sum\n"
    '    expr: "stock_level"\n'
    "    semi_additive: {over: stock_at, rule: last}\n"
    "    filter:\n"
    "      - {dimension: warehouse_code, op: eq, values: [w1]}\n"
)


def _catalog():  # noqa: ANN202 — a loaded `Catalog`
    text = (FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8")
    head = "canonical_fields:\n"
    assert text.count(head) == 1
    return load_catalog(text.replace(head, head + CANONICALS) + TEMPLATE)


def _sources(*, warehouse: str = "warehouse_id", date: str = "stock_date") -> dict[str, str]:
    """The fixture with its two key columns linked to the template's canonicals,
    spelled ``warehouse`` and ``date``."""
    sources = fixture_sources(FIXTURE)

    def swap(key: str, old: str, new: str) -> None:
        assert sources[key].count(old) == 1, (key, old)
        sources[key] = sources[key].replace(old, new)

    swap("entity_model", "key: [warehouse_id, stock_date]", f"key: [{warehouse}, {date}]")
    swap(
        "entity_model",
        "      warehouse_id: {type: string, required: true}\n"
        "      stock_date: {type: date, required: true}\n",
        f"      {warehouse}: {{type: string, required: true, canonical: warehouse_code}}\n"
        f"      {date}: {{type: date, required: true, canonical: stock_at}}\n",
    )
    swap("entity_model", "by warehouse_id, stock_date", f"by {warehouse}, {date}")
    for old, new in (("warehouse_id", warehouse), ("stock_date", date)):
        swap("mapping", f"  {old}:", f"  {new}:")
    swap("marts", "{date: stock_date, role: snapshot}", f"{{date: {date}, role: snapshot}}")
    swap("metrics", "metrics:\n", "metrics:\n  stock_in_w1: {template: stock_in_w1}\n")
    swap("marts", "measures: [stock_on_hand]", "measures: [stock_on_hand, stock_in_w1]")
    swap("metrics", "semi_additive: {over: stock_date, rule: last}", f"semi_additive: {{over: {date}, rule: last}}")
    return sources


def _build(**spelling: str) -> ProjectIR:
    return build_project_ir(load_project(_sources(**spelling)), _catalog())


def _metric(ir: ProjectIR) -> MetricIR:
    return next(metric for metric in ir.metrics if metric.name == "stock_in_w1")


def _column(name: str, canonical: str | None) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=StringType(),
        canonical=canonical,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=False,
    )


# ....................... #


def test_the_template_compiles_and_reads_the_project_s_columns() -> None:
    """The issue's two refusals: the filter's dimension and the `over` axis."""
    metric = _metric(_build())

    assert [clause.dimension for clause in metric.filter] == ["warehouse_id"]
    assert metric.semi_additive is not None
    assert metric.semi_additive.over.dimension == "stock_date"


def test_a_name_no_column_links_keeps_its_literal_reading() -> None:
    """The fixture's own metric names its columns as they are spelled."""
    ir = _build()
    (own,) = (metric for metric in ir.metrics if metric.name == "stock_on_hand")

    assert own.semi_additive is not None
    assert own.semi_additive.over.dimension == "stock_date"


def test_a_grain_column_of_that_name_is_read_as_written() -> None:
    """A filter names a mart column. Where the grain has a column spelled as the
    name, that is the column the author wrote, though another one links the
    name as its canonical: binding would read the other one."""
    columns = (_column("warehouse_code", None), _column("warehouse_id", "warehouse_code"))

    assert bound_name("warehouse_code", columns) == "warehouse_code"
    assert bound_name("warehouse_code", columns[1:]) == "warehouse_id"


def test_a_name_two_columns_link_is_read_as_written() -> None:
    """Neither column is the one the name means, as for an `expr` (D-10)."""
    columns = (_column("site", "warehouse_code"), _column("warehouse_id", "warehouse_code"))

    assert bound_name("warehouse_code", columns) == "warehouse_code"


def test_a_renamed_linked_column_respells_the_metric_and_restates_nothing() -> None:
    """Binding follows the field (S-0022/D-10): `plan()` compares a metric in
    canonical spelling, so a rename under it is not a new definition. That
    holds for the template, bound, and for the fixture's own metric, which
    names the renamed column as it is spelled in each version."""
    old = _build()
    new = _build(warehouse="site", date="as_of")

    restated = [c for c in plan(old, new).changes if c.change_class is ChangeClass.RESTATING]
    assert not [c for c in restated if c.subject.startswith("metric:")], restated
    assert unbound(_metric(old), old.entities) == unbound(_metric(new), new.entities)


def test_unbound_respells_the_filter_and_the_axis() -> None:
    ir = _build(warehouse="site", date="as_of")
    metric = unbound(_metric(ir), ir.entities)

    assert [clause.dimension for clause in metric.filter] == ["warehouse_code"]
    assert metric.semi_additive is not None
    assert metric.semi_additive.over.dimension == "stock_at"


def test_unbound_leaves_an_unlinked_column_alone() -> None:
    project, catalog = load_fixture(FIXTURE)
    ir = build_project_ir(project, catalog)
    (own,) = (metric for metric in ir.metrics if metric.name == "stock_on_hand")

    assert unbound(own, ir.entities) == own


def test_the_semantic_layers_filter_on_the_project_s_column() -> None:
    """Run as emitted: MetricFlow's `where` and Cube's measure filter."""
    artifacts = {
        target: "\n".join(
            artifact.content
            for artifact in compile_project(
                load_project(_sources()), target=target, dialect="duckdb", catalog=_catalog()
            )
        )
        for target in (Target.METRICFLOW, Target.CUBE)
    }

    assert "{{ Dimension('inventory_level__warehouse_id') }} = 'w1'" in artifacts[Target.METRICFLOW]
    assert "{CUBE}.warehouse_id = ''w1''" in artifacts[Target.CUBE]
    assert not any("warehouse_code" in text or "stock_at" in text for text in artifacts.values())
