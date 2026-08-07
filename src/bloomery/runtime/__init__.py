"""Planner-side runtime seam (RFC 0013 §5.3): the render-only SQL client
MetricFlow plans through. Never imported by the compile path — the layering
contract keeps ``runtime`` an independent sibling of ``compile``."""

from bloomery.runtime.sql_client import RenderOnlySqlClient, sql_client_for_dialect

__all__ = [
    "RenderOnlySqlClient",
    "sql_client_for_dialect",
]
