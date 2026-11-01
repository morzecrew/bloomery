"""A naming policy that names a catalog, on every target (#389, S-0025/D-23).

Bronze is read from an attached Postgres and silver and gold are written to a
lake, and each target says so in its own vocabulary: a SQLMesh model name and
`FROM` of three parts, dbt's `database`, MetricFlow's `node_relation.database`
and Cube's `sql_table`. A plan names the relation the models wrote.
"""

from __future__ import annotations

import json
import re

import pytest
import yaml
from support.compiling import fixture_sources, load_fixture
from support.execution import relation_of
from support.planning import fixture_ir

from bloomery import MetricRequest, Target, compile_project, load_project
from bloomery.emit import EmittedArtifact
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import Layer
from bloomery.naming import DefaultNaming
from bloomery.planner.metricflow_planner import MetricFlowPlanner
from bloomery.runtime.hydration import LruManifestHydrator

pytestmark = pytest.mark.unit


class AttachedNaming:
    def relation(self, entity: str, layer: Layer) -> tuple[str, str, str]:
        namespace, relation = DefaultNaming().relation(entity, layer)
        return ("pg" if layer is Layer.BRONZE else "lake", namespace, relation)


def _artifacts(fixture: str, target: Target) -> tuple[EmittedArtifact, ...]:
    project, catalog = load_fixture(fixture)
    return compile_project(
        project, target=target, dialect="duckdb", catalog=catalog, naming=AttachedNaming()
    )


def _compiled(fixture: str, target: Target) -> dict[str, str]:
    return {artifact.path: artifact.content for artifact in _artifacts(fixture, target)}


_MODEL_NAME = re.compile(r"^MODEL \(\n  name (?P<name>[^,\n]+),", re.MULTILINE)


# ....................... #


#: The defect's spelling: the catalog inside a quoted namespace, then the
#: relation, ``"lake.silver".order``.
_FOLDED = re.compile(r'"(?:lake|pg)\.\w+"\.')


@pytest.mark.parametrize(
    ("fixture", "target"),
    [
        *((fixture, target) for fixture in ("role_playing_dates", "scd2_as_of") for target in Target),
        ("multi_source_quality", Target.SQLMESH),
        ("multi_source_quality", Target.DBT),
    ],
)
def test_no_target_folds_the_catalog_into_a_namespace(fixture: str, target: Target) -> None:
    for path, content in _compiled(fixture, target).items():
        assert _FOLDED.search(content) is None, path


def test_a_sqlmesh_model_is_named_and_read_by_three_parts() -> None:
    models = [a for a in _artifacts("role_playing_dates", Target.SQLMESH) if a.path.startswith("models/")]
    names = {a.path: _MODEL_NAME.search(a.content) for a in models}

    assert {path: match and match["name"] for path, match in names.items()} == {
        a.path: ".".join(relation_of(a)) for a in models
    }
    assert sorted(".".join(relation_of(a)) for a in models) == [
        "lake.gold.dim_date",
        "lake.gold.mart_orders",
        "lake.silver.order",
    ]
    (silver,) = (a.content for a in models if a.path == "models/lake/silver/order.sql")
    assert "FROM pg.bronze.oms__orders" in silver


def test_dbt_puts_a_catalog_s_models_under_its_database() -> None:
    artifacts = _compiled("role_playing_dates", Target.DBT)
    project = yaml.safe_load(artifacts["dbt_project.yml"])
    (source,) = yaml.safe_load(artifacts["models/sources.yml"])["sources"]

    assert project["models"]["bloomery"] == {
        "lake": {"+database": "lake", "gold": {"+schema": "gold"}, "silver": {"+schema": "silver"}}
    }
    assert {key: source[key] for key in ("name", "database", "schema")} == {
        "name": "pg_bronze",
        "database": "pg",
        "schema": "bronze",
    }
    assert "FROM {{ source('pg_bronze', 'oms__orders') }}" in artifacts["models/lake/silver/order.sql"]
    assert "{{ ref('order') }}" in artifacts["models/lake/gold/mart_orders.sql"]


def test_a_dbt_snapshot_targets_its_catalog() -> None:
    (snapshot,) = (
        content
        for path, content in _compiled("scd2_as_of", Target.DBT).items()
        if path.startswith("snapshots/")
    )

    assert "config(target_database='lake', target_schema='silver'," in snapshot


def test_metricflow_relations_carry_the_database() -> None:
    manifest = json.loads(_compiled("role_playing_dates", Target.METRICFLOW)["semantic_manifest.json"])
    (model,) = manifest["semantic_models"]
    (spine,) = manifest["project_configuration"]["time_spines"]

    assert model["node_relation"]["database"] == "lake"
    assert model["node_relation"]["relation_name"] == "lake.gold.mart_orders"
    assert spine["node_relation"]["relation_name"] == "lake.gold.dim_date"


def test_a_cube_reads_the_catalog_s_table() -> None:
    cube = yaml.safe_load(_compiled("role_playing_dates", Target.CUBE)["model/cubes/orders.yml"])

    assert cube["cubes"][0]["sql_table"] == "lake.gold.mart_orders"


def test_a_plan_reads_the_mart_the_models_wrote() -> None:
    planner = MetricFlowPlanner(LruManifestHydrator(AttachedNaming()), naming=AttachedNaming())
    plan = planner.plan(
        fixture_ir("role_playing_dates"),
        MetricRequest(metrics=("revenue",), dimensions=("shipped_month",)),
        dialect="duckdb",
    )

    assert "FROM lake.gold.mart_orders" in plan.sql
    assert plan.explanation is not None
    assert plan.explanation.mart == "lake.gold.mart_orders"


# ....................... #
# What dbt cannot place is refused, not emitted


def _dbt_refusal(naming: object, fixture: str = "role_playing_dates") -> str:
    project, catalog = load_fixture(fixture)
    with pytest.raises(UnsupportedByTarget) as refused:
        compile_project(project, target=Target.DBT, dialect="duckdb", catalog=catalog, naming=naming)
    return str(refused.value)


def test_two_bronze_namespaces_that_would_share_a_dbt_source_name_are_refused() -> None:
    """`raw` + `events` and a default-catalog `raw_events` both spell `raw_events`."""

    class Spelled:
        def relation(self, entity: str, layer: Layer) -> tuple[str | None, str, str]:
            namespace, relation = DefaultNaming().relation(entity, layer)
            if layer is not Layer.BRONZE:
                return (None, namespace, relation)
            return ("raw", "events", entity) if entity.startswith("shopify") else (None, "raw_events", entity)

    project = load_project(fixture_sources("multi_source_quality"))
    with pytest.raises(UnsupportedByTarget, match="would both be the dbt source 'raw_events'"):
        compile_project(project, target=Target.DBT, dialect="duckdb", naming=Spelled())


def test_two_relations_of_one_name_in_two_catalogs_are_refused() -> None:
    class Sharded:
        def relation(self, entity: str, layer: Layer) -> tuple[str, str, str]:
            namespace, relation = DefaultNaming().relation(entity, layer)
            if layer is Layer.BRONZE:
                return ("pg", namespace, relation)
            return ("east" if layer is Layer.SILVER else "west", namespace, "x")

    message = _dbt_refusal(Sharded())

    assert "models/east/silver/x.sql and models/west/gold/x.sql are both the dbt model 'x'" in message


def test_a_catalog_named_like_a_default_namespace_is_refused() -> None:
    """`models/gold/` would carry the catalog's `+database` over the default
    catalog's gold models."""

    class Overlapping:
        def relation(self, entity: str, layer: Layer) -> tuple[str | None, str, str]:
            namespace, relation = DefaultNaming().relation(entity, layer)
            return ("gold" if layer is Layer.SILVER else None, namespace, relation)

    assert "'gold' is both a catalog and a namespace of the default catalog" in _dbt_refusal(
        Overlapping()
    )
