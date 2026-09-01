"""Hydration and caching of the planner artifact (RFC 0014): the
:class:`HydrationKey`, the pure L2 codec (:func:`build_manifest_bytes` /
:func:`hydrate_manifest`), and the in-process :class:`LruManifestHydrator`
the planner takes.

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
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Final

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

# ----------------------- #

__all__ = [
    "HydrationKey",
    "LruManifestHydrator",
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


# ....................... #


def hydration_key(ir: ProjectIR) -> HydrationKey:
    """The :class:`HydrationKey` for a project at the running versions."""

    return HydrationKey(
        spec_fingerprint=project_fingerprint(ir),
        bloomery_version=_BLOOMERY_VERSION,
        metricflow_version=_METRICFLOW_VERSION,
    )


# ....................... #


def build_manifest_bytes(ir: ProjectIR, *, naming: NamingPolicy) -> bytes:
    """The L2 payload: the **post-transform** manifest's sorted-keys JSON
    (``emit_manifest`` returns transformed — RFC 0013 R1), UTF-8 encoded.
    Pure and deterministic; byte determinism is the emitter's golden-tested
    contract (RFC 0014 §6)."""

    return manifest_json(emit_manifest(ir, naming=naming)).encode("utf-8")


# ....................... #


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


# ....................... #


class LruManifestHydrator:
    """The default in-process L1 (RFC 0014 D3/D6): an LRU of hydrated lookups
    keyed by :class:`HydrationKey`.

    A miss first consults the caller-injected ``fetch_l2`` (the caller's I/O —
    bloomery performs none); when absent or empty it rebuilds from the IR via
    :func:`build_manifest_bytes`. ``hits``/``misses`` are plain counters the
    caller polls into its own metrics system — no observability dependency
    (RFC 0014 D6).

    The LRU itself is :func:`functools.lru_cache`, per instance: the eviction
    order, the bound, and the hit/miss counters are all what it already ships,
    and a hand-rolled ``OrderedDict`` of the three was the same policy written
    out longhand. Per instance rather than per class because ``fetch_l2``,
    ``prewarm`` and the naming policy are constructor state — a shared cache
    would serve one hydrator's entries to another configured differently.

    **Safe to share across threads**, which is what the documented "build the
    planner once and reuse it" means in a service: the cache's own state is
    lock-protected, and a manifest is hydrated as a pure function of
    ``(key, ir)`` — see :meth:`_hydrate` for the poisoning bug that shape
    exists to prevent. Two obligations stay with the caller, because bloomery
    holds no lock of its own: **``fetch_l2`` is invoked concurrently** and
    must be thread-safe, and concurrent misses of the same *cold* key each
    call it — duplicate work on a cold key, never a wrong answer. Put
    single-flight deduplication inside ``fetch_l2`` if that I/O is expensive.

    A third obligation is about the bytes rather than the threads:
    **``fetch_l2`` must answer for the key it was handed, or answer with
    nothing.** Non-empty bytes are hydrated and cached under *that* key
    unexamined, so a store keyed loosely — one manifest serving several
    fingerprints, a stale write, a shared prefix — returns another project's
    manifest and keeps returning it, exactly the poisoning shape
    :meth:`_hydrate` moved the IR into the cache key to prevent. Bloomery
    cannot check this: the payload is MetricFlow's manifest and carries no
    fingerprint, so verifying would mean re-deriving one on every L2 hit —
    the parse the L2 exists to avoid. Returning ``None`` when unsure is
    always safe; a miss rebuilds from the IR. The reference states the same
    contract for callers who read docs rather than docstrings
    (``pages/docs/reference/api.md``).
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
        self._fetch_l2 = fetch_l2
        self._prewarm = prewarm
        # Bound to `self`, so the cache and its counters die with the hydrator.
        self._cached = lru_cache(maxsize=max_entries)(self._hydrate)

    # ....................... #

    @property
    def hits(self) -> int:
        """L1 hits since construction."""

        return self._cached.cache_info().hits

    # ....................... #

    @property
    def misses(self) -> int:
        """L1 misses since construction — each one hydrated a manifest."""

        return self._cached.cache_info().misses

    # ....................... #

    @property
    def hit_rate(self) -> float:
        """Hits over total lookups (0.0 before any lookup)."""
        info = self._cached.cache_info()
        total = info.hits + info.misses
        return info.hits / total if total else 0.0

    # ....................... #

    def _hydrate(self, key: HydrationKey, ir: ProjectIR) -> SemanticManifestLookup:
        """One miss: L2 bytes when the caller supplies them, else a fresh build.

        Both the key and the IR are *arguments*, so the result is a function of
        what it was called with and nothing else — the property
        :func:`functools.lru_cache` is built on. An earlier version passed only
        the key and handed the IR over through an instance attribute; two
        threads calling :meth:`get` with different IRs could interleave between
        that write and its read, and the manifest built from one thread's IR was
        then cached under the other thread's key, where every later hit returned
        it. Nothing evicts a poisoned entry, so it stayed wrong.

        Caching on the pair costs one extra ``hash(ir)`` (~4.8 us against the
        ~229 us :func:`hydration_key` already spends on the same fixture) and
        partitions exactly as the key alone did: equal IRs hash and compare
        equal, unequal IRs already have unequal fingerprints. The pair is not
        redundant, though — it is what keeps the version axes in the key
        (RFC 0014 D2/D7), which an IR-only cache would have quietly dropped.
        """
        data = self._fetch_l2(key) if self._fetch_l2 is not None else None

        # `not data`, not `is None`: an L2 that answers with zero bytes has
        # answered with no manifest. Reading that as a payload sent `b""` into
        # `parse_raw` and raised a pydantic ValidationError out of a cache
        # lookup — a partially-written key is a miss, which is what the
        # class docstring has always claimed.
        if not data:
            data = build_manifest_bytes(ir, naming=self.naming)

        return hydrate_manifest(data, prewarm=self._prewarm)

    # ....................... #

    def get(self, ir: ProjectIR) -> SemanticManifestLookup:
        """The hydrated lookup for ``ir`` — an L1 hit is a dict lookup; a miss
        hydrates and evicts least-recently-used entries past ``max_entries``.

        Safe to share across threads: nothing here writes instance state, so the
        worst a race costs is two threads building one manifest and one of the
        two results being discarded.
        """

        return self._cached(hydration_key(ir), ir)
