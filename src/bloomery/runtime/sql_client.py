"""``RenderOnlySqlClient`` (RFC 0013 §5.3, D1): the ``SqlClient`` MetricFlow's
engine plans through — it renders SQL and can never connect to anything, by
construction. ``explain()`` never executes (verified, RFC 0013 D1); the three
execution members raise :class:`NotImplementedError` so the impossibility is
structural, not conventional.

``sql_client_for_dialect`` maps bloomery dialect names onto the (engine type,
plan renderer) pairs MetricFlow ships in-package. ``duckdb``, ``trino`` and
``postgres`` are wired — the shipped dialect set (RFC 0008 D5, M10); the
remaining upstream renderers (snowflake, bigquery, databricks, redshift)
slot in here when a dialect port ships for them.

This module lives in ``bloomery/runtime/`` — request-time planner
infrastructure, deliberately *outside* the compile pipeline: the import
contract keeps ``runtime`` an independent top-layer sibling of ``compile``
(RFC 0014 §layering), so no emitter or resolver can ever reach it and it can
never reach them.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, NoReturn

from metricflow.protocols.sql_client import SqlClient, SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow.sql.render.postgres import PostgresSQLSqlPlanRenderer
from metricflow.sql.render.trino import TrinoSqlPlanRenderer

from bloomery.errors import PlannerError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from metricflow.sql.render.sql_plan_renderer import SqlPlanRenderer

# ----------------------- #

__all__ = [
    "RenderOnlySqlClient",
    "sql_client_for_dialect",
]


class RenderOnlySqlClient(SqlClient):
    """Renders SQL. Cannot connect to anything, by construction (RFC 0013 D1)."""

    def __init__(self, engine: SqlEngine, renderer: SqlPlanRenderer) -> None:
        self._engine = engine
        self._renderer = renderer

    # ....................... #

    @property
    def sql_engine_type(self) -> SqlEngine:
        return self._engine

    # ....................... #

    @property
    def sql_plan_renderer(self) -> SqlPlanRenderer:
        return self._renderer

    # ....................... #

    def query(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise NotImplementedError("render-only")

    # ....................... #

    def execute(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise NotImplementedError("render-only")

    # ....................... #

    def dry_run(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise NotImplementedError("render-only")

    # ....................... #

    def close(self) -> None:
        """Nothing to close — there is no connection, by construction."""

    # ....................... #

    def render_bind_parameter_key(self, bind_parameter_key: object) -> str:
        return f"${bind_parameter_key}"


# ....................... #


#: Dialect name → (engine type, plan-renderer class): the shipped dialect
#: set (RFC 0008 D5). The remaining upstream renderers (snowflake, bigquery,
#: databricks, redshift) slot in alongside a matching dialect port.
_DIALECTS: Mapping[str, tuple[SqlEngine, type[SqlPlanRenderer]]] = MappingProxyType(
    {
        "duckdb": (SqlEngine.DUCKDB, DuckDbSqlPlanRenderer),
        "postgres": (SqlEngine.POSTGRES, PostgresSQLSqlPlanRenderer),
        "trino": (SqlEngine.TRINO, TrinoSqlPlanRenderer),
    }
)


def sql_client_for_dialect(name: str) -> RenderOnlySqlClient:
    """A fresh render-only client for a bloomery dialect name.

    Unknown names raise :class:`~bloomery.errors.PlannerError` listing every
    wired dialect, sorted — same doctrine as the dialect registry (RFC 0008 D8).
    """
    entry = _DIALECTS.get(name)

    if entry is None:
        msg = f"unknown planner dialect {name!r}: known dialects are {sorted(_DIALECTS)}"
        raise PlannerError(msg)

    engine, renderer_cls = entry
    return RenderOnlySqlClient(engine, renderer_cls())
