"""A metric says which direction of change is good news (#364, S-0094/D-11).

`better: higher | lower | neither` on a metric or its catalog template, carried
into `MetricIR.better` and to the semantic layers' metadata, so a consumer that
colours a delta or reads a target as a ceiling takes it from the spec rather
than from a list of names kept beside it. Absent, it is undeclared: nothing is
emitted, and a ratio or derived metric never infers it from its parts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from support.compiling import FIXTURES, fixture_sources

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project, plan
from bloomery.errors import SpecParseError
from bloomery.ir import MetricIR
from bloomery.plan import ChangeClass

pytestmark = pytest.mark.unit


def _sources(**better: str) -> dict[str, str]:
    """`ecom_basic`, with `better:` on the named metrics."""
    sources = fixture_sources("ecom_basic")
    for name, value in better.items():
        head = f"  {name}:\n"
        assert sources["metrics"].count(head) == 1, f"the fixture no longer declares {name}"
        sources["metrics"] = sources["metrics"].replace(head, f"{head}    better: {value}\n")
    return sources


def _catalog(template_better: str | None = None):  # noqa: ANN202 — a loaded `Catalog`
    text = Path(FIXTURES / "ecom_basic" / "catalog.yaml").read_text(encoding="utf-8")
    if template_better is not None:
        head = "  gross_revenue:\n    requires: [unit_price, quantity]\n"
        assert text.count(head) == 1
        text = text.replace(head, f"  gross_revenue:\n    better: {template_better}\n{head[17:]}")
    return load_catalog(text)


def _metrics(sources: dict[str, str], catalog=None) -> dict[str, MetricIR]:  # noqa: ANN001
    ir = build_project_ir(load_project(sources), catalog or _catalog())
    return {metric.name: metric for metric in ir.metrics}


def _artifacts(target: Target, sources: dict[str, str]) -> dict[str, str]:
    return {
        artifact.path: artifact.content
        for artifact in compile_project(
            load_project(sources), target=target, dialect="duckdb", catalog=_catalog()
        )
    }


# ....................... #
# The spec and the IR


@pytest.mark.parametrize("value", ["higher", "lower", "neither"])
def test_a_metric_declares_its_direction(value: str) -> None:
    assert _metrics(_sources(order_count=value))["order_count"].better == value


def test_absent_is_undeclared() -> None:
    assert {metric.better for metric in _metrics(fixture_sources("ecom_basic")).values()} == {None}


def test_any_other_value_is_refused() -> None:
    with pytest.raises(SpecParseError, match="'higher', 'lower' or 'neither'") as refused:
        load_project(_sources(order_count="up"))

    assert refused.value.source_path == "metrics: metrics.order_count.better"


def test_a_template_gives_it_and_the_metric_s_own_wins() -> None:
    assert _metrics(fixture_sources("ecom_basic"), _catalog("lower"))["gross_revenue"].better == (
        "lower"
    )
    assert _metrics(_sources(gross_revenue="neither"), _catalog("lower"))[
        "gross_revenue"
    ].better == ("neither")


def test_a_ratio_does_not_infer_it_from_its_parts() -> None:
    metrics = _metrics(_sources(gross_revenue="lower", order_count="lower"))

    assert metrics["average_order_value"].better is None


# ....................... #
# The targets


def test_metricflow_carries_it_in_the_metric_s_meta() -> None:
    manifest = json.loads(
        _artifacts(Target.METRICFLOW, _sources(gross_revenue="lower"))["semantic_manifest.json"]
    )
    metrics = {metric["name"]: metric for metric in manifest["metrics"]}

    assert metrics["gross_revenue"]["config"]["meta"] == {
        "owner": "finance-reporting@example.com",
        "better": "lower",
    }


def test_cube_carries_it_in_the_measure_s_meta() -> None:
    artifacts = _artifacts(Target.CUBE, _sources(gross_revenue="lower"))
    (cube,) = yaml.safe_load(artifacts["model/cubes/order_items.yml"])["cubes"]
    (measure,) = (m for m in cube["measures"] if m["name"] == "gross_revenue")

    assert measure["meta"]["better"] == "lower"


def test_absent_emits_byte_for_byte_as_before() -> None:
    """Undeclared, no artifact of any target changes."""
    for target in (Target.METRICFLOW, Target.CUBE, Target.DBT, Target.SQLMESH):
        assert "better" not in "".join(_artifacts(target, fixture_sources("ecom_basic")).values())


# ....................... #
# The plan


def test_a_changed_direction_is_metadata_only() -> None:
    """Nothing reads it but a consumer, so nothing is rebuilt (S-0094/D-8)."""
    old = build_project_ir(load_project(fixture_sources("ecom_basic")), _catalog())
    new = build_project_ir(load_project(_sources(gross_revenue="lower")), _catalog())
    changes = plan(old, new).changes

    assert [(c.subject, c.change_class, c.detail) for c in changes] == [
        ("metric:gross_revenue", ChangeClass.ADDITIVE, "better changed (metadata only)")
    ]
