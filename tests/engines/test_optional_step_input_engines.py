"""Engine tier: an optional step input, bound and unbound, on real PostgreSQL
and real Trino (S-0034/D-61).

The DuckDB tier proves the body computes the right rows. This proves the
empty relation an unbound input reads as is legal on the two engines and keeps
the declared types: a derived table without an alias, a ``WHERE`` the engine
refuses, or a NULL whose type does not join a ``VARCHAR`` key is byte-stable in
every golden and fails here. Trino is the strict one of the two: it coerces
no text to a number and no NULL of one type to another.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import psycopg
import pytest
import trino
from support.compiling import extract_select

from bloomery import Target, compile_project, load_project
from bloomery.steps import StepManifest, StepRegistry
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

#: Pinned as :mod:`tests.engines.test_merged_cleaning_engines` pins them.
TRINO_IMAGE = "trinodb/trino:483"
POSTGRES_IMAGE = "postgres:16-alpine"

MANIFEST: dict[str, object] = {
    "ref": "net_units",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "inputs": {
        "lines": {"grain": "order_line", "requires": ["product_id", "quantity"]},
        "returns": {
            "grain": "return_line",
            "optional": True,
            "columns": {"product_id": "string", "quantity": "int"},
        },
    },
    "outputs": {
        "net": {
            "grain": "one row per product",
            "key": ["product_id"],
            "produces": {"product_id": {"type": "string"}, "units": {"type": "int"}},
        }
    },
}

#: The join key is the typed column: an untyped NULL product_id would join a
#: VARCHAR on a lenient engine and be refused on a strict one.
BODY = (
    "WITH sold AS (SELECT product_id, SUM(quantity) AS units FROM silver.order_line GROUP BY 1), "
    "returned AS (SELECT product_id, SUM(quantity) AS units FROM returns GROUP BY 1) "
    "SELECT s.product_id, s.units - COALESCE(r.units, 0) AS units "
    "FROM sold AS s LEFT JOIN returned AS r ON r.product_id = s.product_id"
)

EXPECTED = {False: [("a", 5), ("b", 1)], True: [("a", 4), ("b", 1)]}


def select(dialect: str, *, returns: bool) -> str:
    bound = ", returns: silver.return_line" if returns else ""
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: net_units@1\n"
                f"    inputs: {{lines: silver.order_line{bound}}}\n"
                "    outputs: {net: silver.net_units}\n"
            ),
        }
    )
    registry = StepRegistry(
        {("net_units", 1): StepManifest.model_validate(MANIFEST)},
        sql_bodies={("net_units", 1): BODY},
    )
    artifacts = compile_project(project, target=Target.SQLMESH, dialect=dialect, steps=registry)
    return extract_select(next(a.content for a in artifacts if a.path.endswith("/net_units.sql")))


def check(run: Callable[[str], list[tuple[object, ...]]], dialect: str, *, returns: bool) -> None:
    rows = run(f"SELECT product_id, units FROM ({select(dialect, returns=returns)}) AS n ORDER BY 1")
    assert [(product, int(units)) for product, units in rows] == EXPECTED[returns]


# ....................... #
# PostgreSQL


@pytest.fixture(scope="module")
def postgres() -> Iterator[Callable[[str], list[tuple[object, ...]]]]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        connection = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        connection.autocommit = True
        connection.execute("CREATE SCHEMA silver")
        for table, rows in (("order_line", "('a', 3), ('a', 2), ('b', 1)"), ("return_line", "('a', 1)")):
            connection.execute(f"CREATE TABLE silver.{table} (product_id TEXT, quantity BIGINT)")
            connection.execute(f"INSERT INTO silver.{table} VALUES {rows}")

        def run(sql: str) -> list[tuple[object, ...]]:
            return [tuple(row) for row in connection.execute(sql).fetchall()]

        yield run
        connection.close()


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("returns", [False, True], ids=["unbound", "bound"])
def test_the_optional_input_runs_on_postgres(
    postgres: Callable[[str], list[tuple[object, ...]]], returns: bool
) -> None:
    check(postgres, "postgres", returns=returns)


# ....................... #
# Trino


@pytest.fixture(scope="module")
def trino_engine() -> Iterator[Callable[[str], list[tuple[object, ...]]]]:
    with TrinoContainer(TRINO_IMAGE) as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )

        def run(sql: str) -> list[tuple[object, ...]]:
            cursor = connection.cursor()
            cursor.execute(sql)
            return [tuple(row) for row in cursor.fetchall()]

        run("CREATE SCHEMA IF NOT EXISTS memory.silver")
        for table, rows in (("order_line", "('a', 3), ('a', 2), ('b', 1)"), ("return_line", "('a', 1)")):
            run(f"CREATE TABLE memory.silver.{table} (product_id varchar, quantity bigint)")
            run(f"INSERT INTO memory.silver.{table} VALUES {rows}")

        yield run


@pytest.mark.engine("trino")
@pytest.mark.parametrize("returns", [False, True], ids=["unbound", "bound"])
def test_the_optional_input_runs_on_trino(
    trino_engine: Callable[[str], list[tuple[object, ...]]], returns: bool
) -> None:
    check(trino_engine, "trino", returns=returns)
