"""The SQLMesh emitter (RFC 0008 §5.3): artifact shape, path ordering,
fingerprint headers, kind mapping, naming-policy routing."""

from __future__ import annotations

import pytest

from bloomery import Target, build_project_ir, compile_project, project_fingerprint
from bloomery.emit import ArtifactKind
from bloomery.naming import PrefixNaming
from support.compiling import compile_fixture, extract_select, load_fixture

pytestmark = pytest.mark.unit


def test_minimal_artifact_shape() -> None:
    (artifact,) = compile_fixture("minimal")
    assert artifact.path == "models/silver/event.sql"
    assert artifact.kind is ArtifactKind.MODEL
    assert artifact.content.endswith("\n")
    assert not artifact.content.endswith("\n\n")
    assert "\r" not in artifact.content
    assert "MODEL (" in artifact.content
    assert "name silver.event," in artifact.content
    assert "kind FULL," in artifact.content
    assert "grain (event_id)" in artifact.content
    assert "FROM bronze.raw__events" in artifact.content


def test_artifacts_are_sorted_by_path() -> None:
    artifacts = compile_fixture("ecom_basic")
    paths = [a.path for a in artifacts]
    assert paths == sorted(paths)
    assert paths == ["models/silver/order.sql", "models/silver/order_item.sql"]


def test_fingerprint_header_matches_the_built_ir() -> None:
    project, catalog = load_fixture("ecom_basic")
    fingerprint = project_fingerprint(build_project_ir(project, catalog))
    for artifact in compile_fixture("ecom_basic"):
        assert f"-- fingerprint: {fingerprint}" in artifact.content


def test_incremental_by_partition_lowers_to_time_range_kind() -> None:
    artifacts = compile_fixture("ecom_basic")
    order_item = next(a for a in artifacts if a.path.endswith("order_item.sql"))
    assert "kind INCREMENTAL_BY_TIME_RANGE (time_column order_date)," in order_item.content
    assert "partitioned_by (days(order_date))" in order_item.content
    assert "grain (order_id, line_no)," in order_item.content


def test_select_projects_every_column_sorted() -> None:
    artifacts = compile_fixture("ecom_basic")
    order_item = next(a for a in artifacts if a.path.endswith("order_item.sql"))
    select = extract_select(order_item.content)
    assert select.startswith("SELECT")
    for alias in ("line_no", "order_date", "order_id", "quantity", "unit_price"):
        assert f"AS {alias}" in select


def test_naming_policy_routes_paths_and_relations() -> None:
    project, catalog = load_fixture("minimal")
    artifacts = compile_project(
        project,
        target=Target.SQLMESH,
        dialect="duckdb",
        naming=PrefixNaming(prefix="acme"),
        catalog=catalog,
    )
    (artifact,) = artifacts
    assert artifact.path == "models/acme_silver/event.sql"
    assert "name acme_silver.event," in artifact.content
    assert "FROM acme_bronze.raw__events" in artifact.content


def test_checksum_matches_content() -> None:
    import hashlib

    for artifact in compile_fixture("ecom_basic"):
        assert artifact.checksum == hashlib.sha256(artifact.content.encode()).hexdigest()


def test_incremental_by_key_lowers_to_unique_key_kind() -> None:
    from bloomery import load_project

    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id, kind]
    materialization: incremental_by_key
    fields:
      event_id: {type: string, required: true}
      kind: {type: string, required: true}
"""
    mapping = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
  kind: {from: "$.kind", transform: [to_string]}
"""
    (artifact,) = compile_project(
        load_project({"entity_model": model, "mapping": mapping}),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    assert "kind INCREMENTAL_BY_UNIQUE_KEY (unique_key (event_id, kind))," in artifact.content
