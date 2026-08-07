"""RenderOnlySqlClient (RFC 0013 §5.3): renders SQL, cannot connect to
anything by construction — every execution member raises, and the dialect
mapping serves exactly the shipped dialect set (duckdb/postgres/trino,
RFC 0008 D5)."""

from __future__ import annotations

import pytest
from metricflow.protocols.sql_client import SqlEngine
from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer
from metricflow.sql.render.postgres import PostgresSQLSqlPlanRenderer
from metricflow.sql.render.trino import TrinoSqlPlanRenderer

from bloomery.errors import PlannerError
from bloomery.runtime import RenderOnlySqlClient, sql_client_for_dialect

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("dialect", "engine", "renderer_cls"),
    [
        ("duckdb", SqlEngine.DUCKDB, DuckDbSqlPlanRenderer),
        ("postgres", SqlEngine.POSTGRES, PostgresSQLSqlPlanRenderer),
        ("trino", SqlEngine.TRINO, TrinoSqlPlanRenderer),
    ],
)
def test_client_wiring_per_dialect(
    dialect: str, engine: SqlEngine, renderer_cls: type[object]
) -> None:
    client = sql_client_for_dialect(dialect)
    assert client.sql_engine_type is engine
    assert isinstance(client.sql_plan_renderer, renderer_cls)
    assert client.render_bind_parameter_key("k") == "$k"
    assert client.close() is None  # nothing to close — no connection exists


@pytest.mark.parametrize("member", ["query", "execute", "dry_run"])
def test_execution_members_are_impossible_by_construction(member: str) -> None:
    client = sql_client_for_dialect("duckdb")
    with pytest.raises(NotImplementedError, match="render-only"):
        getattr(client, member)("SELECT 1")


def test_unknown_dialect_is_refused_listing_known_names() -> None:
    with pytest.raises(PlannerError, match=r"'snowflake'.*\['duckdb', 'postgres', 'trino'\]"):
        sql_client_for_dialect("snowflake")


def test_client_is_constructible_with_an_explicit_engine_and_renderer() -> None:
    client = RenderOnlySqlClient(SqlEngine.DUCKDB, DuckDbSqlPlanRenderer())
    assert client.sql_engine_type is SqlEngine.DUCKDB
