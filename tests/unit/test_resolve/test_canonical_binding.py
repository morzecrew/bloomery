"""A metric's `expr` names its `requires:` canonicals, and the IR binds each to
the grain entity's field linked to it (S-0022/D-10, #338).

A catalog template is written in canonical names so that a project whose field
is spelled otherwise can still use it; that is what a `canonical:` link is for.
Nothing bound them, so `unit_price * quantity` reached Cube and MetricFlow over a
mart that spells the field `qty`, and compiled clean.
"""

from __future__ import annotations

import pytest
from support.compiling import fixture_sources, load_fixture
from support.steps import registry_for

from bloomery import Target, build_project_ir, compile_project, load_project
from bloomery.errors import GuardrailError, UnitMismatch

pytestmark = pytest.mark.unit


def _renamed() -> dict[str, str]:
    """`ecom_basic` with the line's `quantity` field spelled `qty`, linked as before."""
    sources = fixture_sources("ecom_basic")
    for key in ("entity_model", "mapping_order_items"):
        line = next(row for row in sources[key].splitlines() if row.strip().startswith("quantity:"))
        assert sources[key].count(line) == 1
        sources[key] = sources[key].replace(line, line.replace("quantity:", "qty:", 1))
    return sources


def test_a_template_expr_reads_the_field_its_canonical_links() -> None:
    _project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(load_project(_renamed()), catalog)

    (metric,) = (metric for metric in ir.metrics if metric.name == "gross_revenue")
    assert metric.expr is not None
    assert metric.expr.sql == "unit_price * qty"


@pytest.mark.parametrize("target", [Target.CUBE, Target.METRICFLOW])
def test_the_semantic_layer_queries_the_mart_s_column(target: Target) -> None:
    _project, catalog = load_fixture("ecom_basic")
    artifacts = compile_project(
        load_project(_renamed()), target=target, dialect="duckdb", catalog=catalog
    )

    text = "\n".join(artifact.content for artifact in artifacts)
    assert "unit_price * qty" in text
    assert "unit_price * quantity" not in text


def test_a_canonical_a_step_output_links_is_bound_too() -> None:
    """`identity_resolution`'s template counts `customer_ref`, which the step's
    wiring links to its `canonical_id` output (S-0034/D-49): MetricFlow counted
    a column the mart did not have."""
    project, catalog = load_fixture("identity_resolution")
    ir = build_project_ir(project, catalog, steps=registry_for("identity_resolution"))

    (metric,) = (metric for metric in ir.metrics if metric.name == "customer_count")
    assert metric.expr is not None
    assert metric.expr.sql == "canonical_id"


def test_the_units_guard_still_reads_a_bound_operand() -> None:
    """The units guard looks operands up by canonical name, and after binding
    the expression names the field: unread, money plus a count would pass."""
    sources = _renamed()
    sources["metrics"] += (
        "  priced_count:\n"
        "    requires: [unit_price, quantity]\n"
        "    grain: order_item\n"
        "    additivity: additive\n"
        "    agg: sum\n"
        '    expr: "unit_price + quantity"\n'
    )
    _project, catalog = load_fixture("ecom_basic")

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(sources), catalog)

    assert any(isinstance(leaf, UnitMismatch) for leaf in excinfo.value.collected)
