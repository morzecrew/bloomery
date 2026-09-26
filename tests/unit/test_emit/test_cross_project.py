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

#: What the downstream calls it. The alias keys the compile input and every
#: resolution (S-0002/D-2), and is nothing dbt can resolve a ``ref()`` against.
ALIAS = "platform"

#: What the upstream calls *itself* — the one identity a bloomery project
#: carries, exported by the fixture (S-0002/D-10). Deliberately not the alias:
#: dbt's cross-project reference names the producer, and a fixture whose export
#: name matched the alias would let a target spelling the alias pass.
NAME = "ecom_platform"

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
    a project component on the call, not a second kind of reference — and the
    component is the upstream's exported name, never the local alias, because
    that is what dbt resolves against (S-0002/D-10)."""

    sql = _artifact(_compile(Target.DBT), "models/gold/mart_lines.sql").content

    assert f"{{{{ ref('{NAME}', 'order_item') }}}}" in sql
    assert f"ref('{ALIAS}'" not in sql
    # And the local entity keeps the one-argument form beside it, which is
    # what makes the project component a property of the node rather than of
    # the compile.
    assert "ref('order_item')" not in sql


def test_dbt_declares_the_projects_its_refs_name() -> None:
    """A two-argument ``ref()`` resolves only against ``dependencies.yml``;
    emitting one without the other is a project dbt refuses to parse. The entry
    is the upstream's exported name, which is the name the upstream's own
    ``dbt_project.yml`` carries (S-0002/D-10)."""

    artifact = _artifact(_compile(Target.DBT), "dependencies.yml")

    assert artifact.kind is ArtifactKind.CONFIG
    assert yaml.safe_load(artifact.content)["projects"] == [{"name": NAME}]


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


# ....................... #
# The published side (S-0002/D-1): what dbt has to say for a two-argument `ref()` to resolve


def test_dbt_publishes_the_exported_models() -> None:
    """dbt's default access is `protected`, and a cross-project `ref()` resolves
    only against a public model — so an export list that stayed a bloomery
    fact would publish nothing dbt can read (PR #172 review). Exported marts
    and non-SCD2 entities carry `access: public`; the rest of the schema
    document is what it was."""
    artifacts = compile_project(
        load_project(fixture_sources(UPSTREAM)),
        target=Target.DBT,
        dialect="duckdb",
        catalog=_catalog(),
    )
    schema = yaml.safe_load(_artifact(artifacts, "models/schema.yml").content)
    public = {entry["name"] for entry in schema["models"] if entry.get("access") == "public"}

    # `mart_` is the gold prefix of the naming policy both projects share (D-7).
    assert public == {"order", "order_item", "mart_order_items"}
    assert all(entry.get("access") in (None, "public") for entry in schema["models"])


# ....................... #
# S-0002/D-10: the producer's own name, and the refusal where there is none


def _nameless_upstream() -> ProjectIR:
    """The upstream with its exported name taken away, and nothing else."""

    documents = dict(fixture_sources(UPSTREAM))
    documents["exports"] = documents["exports"].replace(f"  name: {NAME}\n", "")

    return build_project_ir(load_project(documents), catalog=_catalog())


def test_the_dbt_project_is_named_after_its_own_export_name() -> None:
    """The other side of the two-argument ``ref()``: a downstream naming
    ``ecom_platform`` resolves only if the upstream's own ``dbt_project.yml``
    says so — and the ``models:`` block is keyed by the same name, or it
    governs no model at all."""
    artifacts = compile_project(
        load_project(fixture_sources(UPSTREAM)),
        target=Target.DBT,
        dialect="duckdb",
        catalog=_catalog(),
    )
    project = yaml.safe_load(_artifact(artifacts, "dbt_project.yml").content)

    assert project["name"] == NAME
    assert sorted(project["models"][NAME]) == ["gold", "silver"]


def test_a_project_exporting_no_name_is_still_called_bloomery() -> None:
    """A project nothing references across a boundary needs no name of its own,
    so the scaffold keeps the one every emitted project had."""
    project = yaml.safe_load(
        _artifact(_compile(Target.DBT, imports=False), "dbt_project.yml").content
    )

    assert project["name"] == "bloomery"
    assert list(project["models"]) == ["bloomery"]


def test_dbt_refuses_an_upstream_that_exports_no_name() -> None:
    """Refused rather than emitted: a ``ref()`` and a ``dependencies.yml``
    naming the alias resolve only where the upstream's dbt project happens to
    be called that, and the tree would parse as bloomery output and fail in
    dbt. The refusal names the alias and the fix, which is upstream."""

    with pytest.raises(EmitError) as raised:
        compile_project(
            load_project(DOWNSTREAM),
            target=Target.DBT,
            dialect="duckdb",
            catalog=_catalog(),
            upstream={ALIAS: _nameless_upstream()},
        )

    assert f"{ALIAS!r}" in str(raised.value)
    assert "exports document" in str(raised.value)


@pytest.mark.parametrize("target", [Target.SQLMESH, Target.CUBE, Target.METRICFLOW])
def test_no_other_target_asks_for_a_name(target: Target) -> None:
    """SQLMesh names the relation, Cube and MetricFlow read a mart: none of
    them has a cross-project reference, so none of them needs the producer's
    identity (S-0002/D-10)."""

    artifacts = compile_project(
        load_project(DOWNSTREAM),
        target=target,
        dialect="duckdb",
        catalog=_catalog(),
        upstream={ALIAS: _nameless_upstream()},
    )

    assert artifacts


# ....................... #
# S-0002/D-9: a local declaration that names an imported node is judged with it


EXPOSED = {
    **DOWNSTREAM,
    "exposures": f"""
exposures_version: 1
exposures:
  revenue_board:
    kind: dashboard
    owner: analytics@example.com
    depends_on:
      metrics: [gross_revenue]
      marts: [order_items]
""",
}


def test_an_exposure_may_name_an_imported_mart_and_metric() -> None:
    """The exposure was authored here and reads a relation another project
    built; dbt spells that dependency as the two-argument `ref()` (D-9)."""
    artifacts = compile_project(
        load_project(EXPOSED),
        target=Target.DBT,
        dialect="duckdb",
        catalog=_catalog(),
        upstream={ALIAS: _upstream()},
    )
    (exposure,) = yaml.safe_load(_artifact(artifacts, "models/exposures.yml").content)["exposures"]

    assert exposure["name"] == "revenue_board"
    # The local mart `lines` serves `gross_revenue`, so the metric leg adds it;
    # the imported mart is the two-argument reference.
    assert exposure["depends_on"] == [f"ref('{NAME}', 'mart_order_items')", "ref('mart_lines')"]
