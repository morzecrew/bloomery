"""Planner-side runtime seam (S-0030/the-adapter-and-the-render-only-client, S-0031): the render-only SQL
client MetricFlow plans through, and manifest hydration/caching — the
package's one impure-*adjacent* corner (an in-process LRU; still no I/O).
Never imported by the compile path — the layering contract keeps ``runtime``
an independent sibling of ``compile``; only ``planner`` sits above it."""

from bloomery.runtime.hydration import (
    HydrationKey,
    LruManifestHydrator,
    build_manifest_bytes,
    hydrate_manifest,
    hydration_key,
)
from bloomery.runtime.sql_client import RenderOnlySqlClient, sql_client_for_dialect

# ----------------------- #

__all__ = [
    "HydrationKey",
    "LruManifestHydrator",
    "RenderOnlySqlClient",
    "build_manifest_bytes",
    "hydrate_manifest",
    "hydration_key",
    "sql_client_for_dialect",
]
