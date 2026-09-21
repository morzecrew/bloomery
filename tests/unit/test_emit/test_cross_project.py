"""Emitting across a project boundary (S-0002/D-2, S-0002/D-7).

The four targets disagree about what an imported relation *is*, and the
disagreement is the subject here. dbt has a cross-project reference and needs
the ``dependencies.yml`` entry that makes it resolvable; SQLMesh has none and
names the relation directly, which is what turns the shared naming policy from
a preference into a constraint; Cube and MetricFlow build nothing either way,
so an imported mart reads exactly as a local one does.

One downstream project throughout: a local ``shipment`` entity (a project with
no entity of its own is not a project) and a mart whose base is the *imported*
``order_item``. The mart base is the only construct that can name an imported
node today — an authored relationship is checked against local entities — so
it is both the realistic case and the whole of the surface.
"""

from __future__ import annotations

import json

import pytest
import yaml

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.errors import EmitError
from bloomery.ir import ProjectIR
from support.compiling import FIXTURES, extract_select, fixture_sources

pytestmark = pytest.mark.unit

#: The one fixture with an export list, so the only one that can be an upstream.
UPSTREAM = "ecom_basic"

#: What the downstream calls it. A bloomery project carries no identity of its
#: own (S-0002/D-2), so the alias is the only name either side agrees on.
ALIAS = "platform"

DOWNSTREAM = {
    "imports": f"""
imports_version: 1
imports:
  {ALIAS}:
    entities: [order, order_item]
    marts: [order_items]
    metrics: [gross_revenue, order_count]
""",
    "entity_model": """
spec_version: 1
entities:
  shipment:
    grain: one row per shipment
    key: [shipment_id]
    fields:
      shipment_id: {type: string, required: true}
      order_id: {type: string, required: true}
      shipped_at: {type: timestamp}
""",
    "mapping": """
mapping_version: 1
source: raw__shipments
target: shipment
key:
  shipment_id: {from: "$.shipment_id", transform: [to_string]}
fields:
  order_id: {from: "$.order_id"}
  shipped_at: {from: "$.shipped_at"}
""",
    "marts": """
marts_version: 1
marts:
  lines:
    grain: order_item
    base: order_item
    flatten:
      - {date: order_date, role: ordered}
    measures: [gross_revenue]
""",
}


def _catalog():
    return load_catalog((FIXTURES / UPSTREAM / "catalog.yaml").read_text())


def _upstream() -> ProjectIR:
    return build_project_ir(load_project(fixture_sources(UPSTREAM)), catalog=_catalog())


def _compile(target: Target, *, imports: bool = True) -> tuple[EmittedArtifact, ...]:
    documents = dict(DOWNSTREAM)
    if not imports:
        del documents["imports"]
        # Nothing imported leaves the mart's base unresolvable, so the mart
        # goes with it: what this leg asks is what a *single-project* compile
        # of the same downstream emits.
        del documents["marts"]

    return compile_project(
        load_project(documents),
        target=target,
        dialect="duckdb",
        catalog=_catalog(),
        upstream={ALIAS: _upstream()} if imports else {},
    )


def _artifact(artifacts: tuple[EmittedArtifact, ...], path: str) -> EmittedArtifact:
    found = [artifact for artifact in artifacts if artifact.path == path]
    assert found, f"no {path} in {[artifact.path for artifact in artifacts]}"
    return found[0]


# ....................... #


def test_dbt_names_an_imported_entity_with_a_two_argument_ref() -> None:
    """dbt's way of naming a relation another project builds (S-0002/D-2):
    a project component on the call, not a second kind of reference."""

    sql = _artifact(_compile(Target.DBT), "models/gold/mart_lines.sql").content

    assert f"{{{{ ref('{ALIAS}', 'order_item') }}}}" in sql
    # And the local entity keeps the one-argument form beside it, which is
    # what makes the project component a property of the node rather than of
    # the compile.
    assert "ref('order_item')" not in sql


def test_dbt_declares_the_projects_its_refs_name() -> None:
    """A two-argument ``ref()`` resolves only against ``dependencies.yml``;
    emitting one without the other is a project dbt refuses to parse."""

    artifact = _artifact(_compile(Target.DBT), "dependencies.yml")

    assert artifact.kind is ArtifactKind.CONFIG
    assert yaml.safe_load(artifact.content)["projects"] == [{"name": ALIAS}]


def test_dbt_writes_no_dependencies_file_without_imports() -> None:
    """An empty ``projects:`` list is not the same artifact as no artifact,
    and a single-project compile emitted neither before composition existed
    (S-0002/I-1)."""

    paths = [artifact.path for artifact in _compile(Target.DBT, imports=False)]

    assert "dependencies.yml" not in paths


def test_sqlmesh_names_an_imported_relation_directly() -> None:
    """SQLMesh has no cross-project reference (S-0002/D-2), so the relation is
    named as the shared naming policy names it (S-0002/D-7) — and this target
    emits nothing declaring where it came from."""

    artifacts = _compile(Target.SQLMESH)
    select = extract_select(_artifact(artifacts, "models/gold/mart_lines.sql").content)

    assert "silver.order_item" in select
    assert [artifact.path for artifact in artifacts if "depend" in artifact.path] == []


@pytest.mark.parametrize("target", [Target.SQLMESH, Target.DBT])
def test_no_model_is_emitted_for_an_imported_relation(target: Target) -> None:
    """The upstream's relation is the upstream's to build. A downstream that
    emitted a model for it would have two projects writing one table."""

    paths = [artifact.path for artifact in _compile(target)]

    assert not [path for path in paths if "order_item" in path or "mart_order_items" in path]
    assert "models/silver/shipment.sql" in paths  # its own, still built


def test_cube_reads_an_imported_mart_as_a_mart() -> None:
    """Cube builds nothing, so describing a relation another project maintains
    is the whole of what it does for a local mart too."""

    paths = [artifact.path for artifact in _compile(Target.CUBE)]

    assert "model/cubes/order_items.yml" in paths
    assert "model/views/order_items_view.yml" in paths


def test_metricflow_describes_an_imported_mart_against_the_shared_relation() -> None:
    """MetricFlow's semantic model points at the relation the shared policy
    names (S-0002/D-7) — the upstream built it under that name, and nothing in
    the manifest says it was imported."""

    manifest = json.loads(
        _artifact(_compile(Target.METRICFLOW), "semantic_manifest.json").content
    )
    models = {model["name"]: model for model in manifest["semantic_models"]}

    assert models["order_items"]["node_relation"]["schema_name"] == "gold"
    assert models["order_items"]["node_relation"]["alias"] == "mart_order_items"


# ....................... #
# A mart that crossed without the metrics its measures name. The export list
# carries every name by hand (S-0002/D-1), so this is a shape the boundary
# permits, not a malformed one — the downstream's own mart goes with the
# metrics, since a measure naming no declared metric is the guardrail's
# refusal rather than this one.


def _without_metrics(target: Target) -> tuple[EmittedArtifact, ...]:
    documents = {key: value for key, value in DOWNSTREAM.items() if key != "marts"}
    documents["imports"] = f"""
imports_version: 1
imports:
  {ALIAS}:
    entities: [order, order_item]
    marts: [order_items]
"""
    return compile_project(
        load_project(documents),
        target=target,
        dialect="duckdb",
        catalog=_catalog(),
        upstream={ALIAS: _upstream()},
    )


@pytest.mark.parametrize("target", [Target.CUBE, Target.METRICFLOW])
def test_a_mart_whose_metrics_did_not_cross_is_refused_naming_them(target: Target) -> None:
    """The measure name arrives with no aggregation, expression or additivity
    behind it, and neither target can invent one. Both say so in one sentence
    naming the mart, the measure and the two lists that would fix it — a raw
    ``KeyError`` is not something a downstream author can act on."""

    with pytest.raises(EmitError) as raised:
        _without_metrics(target)

    assert "'gross_revenue'" in str(raised.value)
    assert "'order_items'" in str(raised.value)
    assert "imports" in str(raised.value)


@pytest.mark.parametrize("target", [Target.SQLMESH, Target.DBT])
def test_the_sql_targets_compile_the_same_shape(target: Target) -> None:
    """The refusal above belongs to the targets that *describe* a mart. A
    target that builds one reads the imported mart only as a relation to name,
    and the metrics behind its measures are nothing it needed."""

    assert "models/silver/shipment.sql" in [artifact.path for artifact in _without_metrics(target)]
