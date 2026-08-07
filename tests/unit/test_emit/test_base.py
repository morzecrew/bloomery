"""Emitter port surface (RFC 0008 §5.1 amended): the Feature vocabulary,
capability checks, artifact checksums, and the emitter registry."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Iterator

import pytest

from bloomery.emit import (
    ArtifactKind,
    EmitContext,
    EmittedArtifact,
    Feature,
    SQLMeshEmitter,
    TargetCapabilities,
    get_emitter,
    register_emitter,
)
from bloomery.errors import EmitError

pytestmark = pytest.mark.unit

emit_module = importlib.import_module("bloomery.emit")


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(emit_module, "_overlay", {})
    yield


def test_feature_vocabulary_is_the_amended_closed_set() -> None:
    """RFC 0008 D10 amended by pivot R8 (CUMULATIVE, DERIVED_METRIC) and by
    RFC 0015 D-Q6 (SORT_NULLS_PLACEMENT)."""
    assert sorted(f.value for f in Feature) == [
        "audits",
        "cumulative",
        "derived_metric",
        "incremental",
        "multi_fact",
        "non_additive",
        "query_time_join",
        "role_playing_dim",
        "row_level_security",
        "scd_type_2",
        "semi_additive",
        "sort_nulls_placement",
        "variant_column",
    ]


def test_sort_nulls_placement_is_not_a_metricflow_planner_capability() -> None:
    """RFC 0015 D-Q6: MetricFlow's ``order_by_names`` is direction-only —
    the planner refuses non-default placements rather than declaring the
    feature."""
    from bloomery.emit.metricflow import METRICFLOW_PLANNER_CAPABILITIES

    assert not METRICFLOW_PLANNER_CAPABILITIES.supports(Feature.SORT_NULLS_PLACEMENT)


def test_capabilities_are_membership_checked() -> None:
    caps = TargetCapabilities(supported=frozenset({Feature.INCREMENTAL}))
    assert caps.supports(Feature.INCREMENTAL)
    assert not caps.supports(Feature.MULTI_FACT)


def test_sqlmesh_declared_capabilities() -> None:
    caps = SQLMeshEmitter().capabilities()
    for feature in (
        Feature.SCD_TYPE_2,
        Feature.VARIANT_COLUMN,
        Feature.INCREMENTAL,
        Feature.AUDITS,
        Feature.SEMI_ADDITIVE,
        Feature.NON_ADDITIVE,
        Feature.CUMULATIVE,
        Feature.DERIVED_METRIC,
    ):
        assert caps.supports(feature)
    assert not caps.supports(Feature.QUERY_TIME_JOIN)
    assert not caps.supports(Feature.MULTI_FACT)


def test_artifact_create_computes_the_sha256_checksum() -> None:
    artifact = EmittedArtifact.create(
        path="models/silver/event.sql", content="SELECT 1\n", kind=ArtifactKind.MODEL
    )
    assert artifact.checksum == hashlib.sha256(b"SELECT 1\n").hexdigest()
    assert artifact.kind is ArtifactKind.MODEL


def test_emit_context_is_frozen() -> None:
    context = EmitContext(dialect=object(), naming=object(), fingerprint="blm1:x")  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        context.fingerprint = "blm1:y"  # type: ignore[misc]


def test_get_emitter_returns_the_default() -> None:
    assert get_emitter("sqlmesh").name == "sqlmesh"


def test_unknown_target_lists_known_names() -> None:
    expected = r"unknown target 'looker': known targets are \['cube', 'dbt', 'sqlmesh'\]"
    with pytest.raises(EmitError, match=expected):
        get_emitter("looker")


def test_register_emitter_collision_is_an_error() -> None:
    with pytest.raises(EmitError, match="'sqlmesh' is already registered"):
        register_emitter(SQLMeshEmitter())


def test_register_emitter_overlay() -> None:
    class _Custom(SQLMeshEmitter):
        name = "custom"

    register_emitter(_Custom())
    assert get_emitter("custom").name == "custom"
