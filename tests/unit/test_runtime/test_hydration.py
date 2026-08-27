"""Hydration unit tests (RFC 0014 §6): key composition over all three
invalidation axes, the pure codec round-trip over every mart fixture, LRU
hit/miss counting and eviction order, the fetch_l2 seam, and the prewarm
flag."""

from __future__ import annotations

import importlib.metadata
import threading
from unittest import mock

import pytest
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.ir import DateDimensionIR, ProjectIR, project_fingerprint
from bloomery.naming import DefaultNaming, NamingPolicy, PrefixNaming
from bloomery.runtime import (
    HydrationKey,
    LruManifestHydrator,
    build_manifest_bytes,
    hydrate_manifest,
    hydration_key,
)
from bloomery.runtime import hydration as hydration_module
from support.planning import fixture_ir

pytestmark = pytest.mark.unit

NAMING = DefaultNaming()

MART_FIXTURES = [
    "ecom_basic",
    "multi_mart_refusal",
    "non_additive_aov",
    "role_playing_dates",
    "semi_additive_inventory",
]


# ....................... #
# Key (RFC 0014 D2/D7): all three axes, mismatch = miss by construction


def test_key_carries_all_three_components() -> None:
    ir = fixture_ir("non_additive_aov")
    key = hydration_key(ir)
    assert key.spec_fingerprint == project_fingerprint(ir)
    assert key.bloomery_version
    # The installed version, not a literal: the contract is that the key
    # carries MetricFlow's version (RFC 0014 D2 — a bump must miss the
    # cache), and a hard-coded prefix asserts the pin instead, which the
    # goldens' `minor_version` and the pyproject bound already do.
    assert key.metricflow_version == importlib.metadata.version("metricflow")


def test_any_component_change_is_a_different_key() -> None:
    base = HydrationKey("f1", "b1", "m1")
    assert base != HydrationKey("f2", "b1", "m1")
    assert base != HydrationKey("f1", "b2", "m1")
    assert base != HydrationKey("f1", "b1", "m2")
    assert base == HydrationKey("f1", "b1", "m1")


def test_spec_edit_changes_the_key() -> None:
    assert hydration_key(fixture_ir("non_additive_aov")) != hydration_key(
        fixture_ir("semi_additive_inventory")
    )


# ....................... #
# Codec (RFC 0014 D3/D5): pure, post-transform, JSON — never pickle


@pytest.mark.parametrize("name", MART_FIXTURES)
def test_codec_round_trips_every_fixture_manifest(name: str) -> None:
    ir = fixture_ir(name)
    data = build_manifest_bytes(ir, naming=NAMING)
    assert data == manifest_json(emit_manifest(ir, naming=NAMING)).encode("utf-8")
    lookup = hydrate_manifest(data)
    assert isinstance(lookup, SemanticManifestLookup)


def test_bytes_are_deterministic_and_naming_sensitive() -> None:
    ir = fixture_ir("non_additive_aov")
    assert build_manifest_bytes(ir, naming=NAMING) == build_manifest_bytes(ir, naming=NAMING)
    assert build_manifest_bytes(ir, naming=NAMING) != build_manifest_bytes(
        ir, naming=PrefixNaming("acme")
    )


def test_prewarm_issues_the_throwaway_explain() -> None:
    data = build_manifest_bytes(fixture_ir("non_additive_aov"), naming=NAMING)
    lookup = hydrate_manifest(data, prewarm=True)
    assert isinstance(lookup, SemanticManifestLookup)


def test_prewarm_skips_metric_less_manifests() -> None:
    spineless = ProjectIR(
        date_dimension=DateDimensionIR(name="dim_date", grain="day", start_year=2020, end_year=2030)
    )
    data = build_manifest_bytes(spineless, naming=NAMING)
    assert isinstance(hydrate_manifest(data, prewarm=True), SemanticManifestLookup)


# ....................... #
# LRU (RFC 0014 D3/D6)


def test_hit_and_miss_counters() -> None:
    hydrator = LruManifestHydrator(NAMING)
    ir = fixture_ir("non_additive_aov")
    assert hydrator.hit_rate == 0.0
    first = hydrator.get(ir)
    second = hydrator.get(ir)
    assert first is second  # a hit returns the cached lookup, not a rebuild
    assert (hydrator.hits, hydrator.misses) == (1, 1)
    assert hydrator.hit_rate == 0.5


def test_eviction_is_least_recently_used() -> None:
    hydrator = LruManifestHydrator(NAMING, max_entries=2)
    aov = fixture_ir("non_additive_aov")
    inventory = fixture_ir("semi_additive_inventory")
    roles = fixture_ir("role_playing_dates")
    hydrator.get(aov)
    hydrator.get(inventory)
    hydrator.get(aov)  # refresh aov → inventory is now least recent
    hydrator.get(roles)  # evicts inventory
    assert (hydrator.hits, hydrator.misses) == (1, 3)
    hydrator.get(aov)  # still cached
    assert (hydrator.hits, hydrator.misses) == (2, 3)
    hydrator.get(inventory)  # was evicted → miss again
    assert (hydrator.hits, hydrator.misses) == (2, 4)


def test_version_bump_is_a_miss_by_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 0014 D7: versions live in the key, so a bump makes old entries
    unreachable — a miss, never an error (no ``IncompatibleArtifact``)."""
    hydrator = LruManifestHydrator(NAMING)
    ir = fixture_ir("non_additive_aov")
    hydrator.get(ir)
    monkeypatch.setattr(hydration_module, "_METRICFLOW_VERSION", "999.0.0")
    hydrator.get(ir)
    assert (hydrator.hits, hydrator.misses) == (0, 2)
    monkeypatch.setattr(hydration_module, "_BLOOMERY_VERSION", "999.0.0")
    hydrator.get(ir)
    assert (hydrator.hits, hydrator.misses) == (0, 3)


def test_fetch_l2_bytes_are_used_when_present() -> None:
    ir = fixture_ir("non_additive_aov")
    payload = build_manifest_bytes(ir, naming=NAMING)
    calls: list[HydrationKey] = []

    def fetch(key: HydrationKey) -> bytes | None:
        calls.append(key)
        return payload

    hydrator = LruManifestHydrator(NAMING, fetch_l2=fetch)
    lookup = hydrator.get(ir)
    assert isinstance(lookup, SemanticManifestLookup)
    assert calls == [hydration_key(ir)]
    hydrator.get(ir)  # L1 hit — L2 is not consulted again
    assert len(calls) == 1


def test_fetch_l2_none_falls_back_to_a_fresh_build() -> None:
    ir = fixture_ir("non_additive_aov")
    hydrator = LruManifestHydrator(NAMING, fetch_l2=lambda _key: None)
    assert isinstance(hydrator.get(ir), SemanticManifestLookup)
    assert (hydrator.hits, hydrator.misses) == (0, 1)


def test_fetch_l2_empty_bytes_falls_back_to_a_fresh_build() -> None:
    """An L2 that answers with **no bytes** is a miss, not a payload.

    The docstring has always said "when absent or empty it rebuilds", but the
    check read ``data is None``, so a partially-written cache entry — a Redis
    key created and not yet filled, which is exactly the shape an L2 produces
    under a crash — reached ``parse_raw`` and raised a pydantic
    ``ValidationError`` out of a cache lookup. Empty is a miss.
    """
    ir = fixture_ir("non_additive_aov")
    hydrator = LruManifestHydrator(NAMING, fetch_l2=lambda _key: b"")
    assert isinstance(hydrator.get(ir), SemanticManifestLookup)
    assert (hydrator.hits, hydrator.misses) == (0, 1)


def test_concurrent_gets_never_cache_one_ir_under_another_s_key() -> None:
    """Two threads, two specs, one hydrator: each key gets its own manifest.

    An earlier form of this cache keyed on :class:`HydrationKey` and passed the
    IR to the miss path through an instance attribute. Two ``get`` calls could
    interleave between that write and its read, so the manifest built from one
    thread's IR was stored under the other thread's key — and, because nothing
    evicts a poisoned entry, every later hit on that key returned it.

    The barrier is what makes this deterministic rather than lucky: both threads
    are held inside the build until each has entered it, which is exactly the
    window the attribute version lost the IR in.
    """
    first = fixture_ir("non_additive_aov")
    second = fixture_ir("semi_additive_inventory")
    assert hydration_key(first) != hydration_key(second)

    barrier = threading.Barrier(2, timeout=30)
    built: dict[HydrationKey, ProjectIR] = {}
    lock = threading.Lock()
    real_build = hydration_module.build_manifest_bytes

    def recording_build(ir: ProjectIR, *, naming: NamingPolicy) -> bytes:
        barrier.wait()  # both threads inside the miss path at once
        with lock:
            built[hydration_key(ir)] = ir
        return real_build(ir, naming=naming)

    hydrator = LruManifestHydrator(NAMING)
    results: dict[str, SemanticManifestLookup] = {}

    def run(name: str, ir: ProjectIR) -> None:
        results[name] = hydrator.get(ir)

    with mock.patch.object(hydration_module, "build_manifest_bytes", recording_build):
        threads = [
            threading.Thread(target=run, args=("first", first)),
            threading.Thread(target=run, args=("second", second)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

    # Every rebuild used the IR whose key it was stored under — the property the
    # attribute version could not hold.
    assert {key: hydration_key(ir) for key, ir in built.items()} == {
        hydration_key(first): hydration_key(first),
        hydration_key(second): hydration_key(second),
    }
    # ...and each key still answers with its own manifest afterwards.
    assert hydrator.get(first) is results["first"]
    assert hydrator.get(second) is results["second"]
    assert results["first"] is not results["second"]


def test_lru_prewarm_flag_reaches_hydration() -> None:
    hydrator = LruManifestHydrator(NAMING, prewarm=True)
    assert isinstance(hydrator.get(fixture_ir("non_additive_aov")), SemanticManifestLookup)
