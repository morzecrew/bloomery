"""Hydration and caching of the planner artifact (RFC 0014): the
:class:`HydrationKey`, the pure L2 codec (:func:`build_manifest_bytes` /
:func:`hydrate_manifest`), the :class:`ManifestHydrator` protocol, and the
default in-process :class:`LruManifestHydrator`.

The planner artifact is MetricFlow's own **post-transform** manifest
(RFC 0014 D1, superseding RFC 0012's ``CompiledSemantic``): L2 is its JSON
(~145 KB) stored by the *caller* — bloomery defines only the key and the
bytes, never the store (hard invariant #1, no I/O; the one seam is the
injected ``fetch_l2`` callable, owned and executed by the caller); L1 is the
hydrated ``SemanticManifestLookup`` (~1.6 MB) in the in-process LRU here.
Storing post-transform is load-bearing: cold hydration is exactly
``parse_raw`` + lookup construction (10.5 ms measured at 30 models —
RFC 0014 §5.5; budgets 50 ms cold / 10 ms warm, asserted in
``tests/bench/test_hydration.py``). Serialization is the emitter's
sorted-keys JSON — **never pickle** (RFC 0014 D5).

Version mismatch is a cache **miss by construction** (RFC 0014 D7): the
bloomery and MetricFlow versions live in the key, read once at import into
module constants (a pure metadata lookup — no clock, no env), so a bump
changes every key and old entries are simply never looked up again.

The LRU is the package's one deliberately confined piece of mutable state
(RFC 0014 D8): ``runtime/`` performs no I/O and is kept out of the compile
path by the import-linter contract — only ``planner/`` may reach it.
"""

from __future__ import annotations

import importlib.metadata
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

# RFC 0013 §5.9a: keep a module that finishes
# ``metricflow_semantic_interfaces.protocols`` the first MSI import — see
# ``bloomery.emit.metricflow`` for the circular-import account.
from metricflow_semantic_interfaces.implementations.semantic_manifest import (
    PydanticSemanticManifest,
)

# isort: split
from metricflow.engine.metricflow_engine import MetricFlowEngine, MetricFlowQueryRequest
from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

from bloomery.emit.metricflow import emit_manifest, manifest_json
from bloomery.ir import project_fingerprint
from bloomery.runtime.sql_client import sql_client_for_dialect

if TYPE_CHECKING:
    from collections.abc import Callable

    from bloomery.ir import ProjectIR
    from bloomery.naming import NamingPolicy

__all__ = [
    "HydrationKey",
    "LruManifestHydrator",
    "ManifestHydrator",
    "build_manifest_bytes",
    "hydrate_manifest",
    "hydration_key",
]

#: Read once at import into constants (RFC 0014 D2/D7): the versions are
#: cache-key components, never per-call environment reads.
_BLOOMERY_VERSION: Final[str] = importlib.metadata.version("bloomery")
_METRICFLOW_VERSION: Final[str] = importlib.metadata.version("metricflow")


@dataclass(frozen=True, slots=True)
class HydrationKey:
    """The one cache key covering all three invalidation axes (RFC 0014 D2):
    a spec edit, a bloomery bump, or a MetricFlow bump each change the key,
    so stale entries are unreachable — a miss, never an error."""

    spec_fingerprint: str
    bloomery_version: str
    metricflow_version: str


def hydration_key(ir: ProjectIR) -> HydrationKey:
    """The :class:`HydrationKey` for a project at the running versions."""
    return HydrationKey(
        spec_fingerprint=project_fingerprint(ir),
        bloomery_version=_BLOOMERY_VERSION,
        metricflow_version=_METRICFLOW_VERSION,
    )


def build_manifest_bytes(ir: ProjectIR, *, naming: NamingPolicy) -> bytes:
    """The L2 payload: the **post-transform** manifest's sorted-keys JSON
    (``emit_manifest`` returns transformed — RFC 0013 R1), UTF-8 encoded.
    Pure and deterministic; byte determinism is the emitter's golden-tested
    contract (RFC 0014 §6)."""
    return manifest_json(emit_manifest(ir, naming=naming)).encode("utf-8")


def hydrate_manifest(data: bytes, *, prewarm: bool = False) -> SemanticManifestLookup:
    """L2 bytes → the hydrated lookup: ``parse_raw`` + construction, no
    transform (L2 stores post-transform — RFC 0014 D3).

    ``prewarm=True`` issues one throwaway render-only ``explain()`` against
    the first metric (RFC 0014 D9): ``SemanticManifestLookup`` defers ~6 ms
    of graph work to the first query; absorbing it here keeps first-query
    latency out of the warm path. Metric-less manifests skip it.
    """
    manifest = PydanticSemanticManifest.parse_raw(data)
    lookup = SemanticManifestLookup(manifest)
    if prewarm and manifest.metrics:
        engine = MetricFlowEngine(
            semantic_manifest_lookup=lookup,
            sql_client=sql_client_for_dialect("duckdb"),
        )
        engine.explain(MetricFlowQueryRequest.create(metric_names=[manifest.metrics[0].name]))
    return lookup


class ManifestHydrator(Protocol):
    """The hydration seam the planner consumes (RFC 0013 §5.3, RFC 0014
    §5.2): project IR in, hydrated lookup out — caching behind it is the
    implementation's business."""

    def get(self, ir: ProjectIR) -> SemanticManifestLookup: ...


class LruManifestHydrator:
    """The default in-process L1 (RFC 0014 D3/D6): an LRU of hydrated
    lookups keyed by :class:`HydrationKey`.

    A miss first consults the caller-injected ``fetch_l2`` (the caller's
    I/O — bloomery performs none); when absent or empty it rebuilds from the
    IR via :func:`build_manifest_bytes`. ``hits``/``misses`` are plain
    counters the caller polls into its own metrics system — no observability
    dependency (RFC 0014 D6).
    """

    def __init__(
        self,
        naming: NamingPolicy,
        *,
        max_entries: int = 500,
        fetch_l2: Callable[[HydrationKey], bytes | None] | None = None,
        prewarm: bool = False,
    ) -> None:
        self.naming = naming
        self.hits = 0
        self.misses = 0
        self._max_entries = max_entries
        self._fetch_l2 = fetch_l2
        self._prewarm = prewarm
        self._entries: OrderedDict[HydrationKey, SemanticManifestLookup] = OrderedDict()

    @property
    def hit_rate(self) -> float:
        """Hits over total lookups (0.0 before any lookup)."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def get(self, ir: ProjectIR) -> SemanticManifestLookup:
        """The hydrated lookup for ``ir`` — an L1 hit is a dict lookup; a
        miss hydrates (L2 bytes when the caller supplies them, else a fresh
        build) and evicts least-recently-used entries past ``max_entries``."""
        key = hydration_key(ir)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            self.hits += 1
            return cached
        self.misses += 1
        data = self._fetch_l2(key) if self._fetch_l2 is not None else None
        if data is None:
            data = build_manifest_bytes(ir, naming=self.naming)
        lookup = hydrate_manifest(data, prewarm=self._prewarm)
        self._entries[key] = lookup
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return lookup
