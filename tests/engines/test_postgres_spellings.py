"""Engine tier (S-0026/tier-contracts tier 5): where PostgreSQL needs a *different*
spelling for a transform, it still means the same thing (S-0046/what-was-measured (§2.3)).

The conformance battery next door proves a transform's produced type matches
its declared one. It cannot prove that a port which had to reach for different
SQL still computes the same answer — ``RIGHT(x, LENGTH(s)) = s`` has the type
``ENDS_WITH(x, s)`` has whether or not it agrees with it. So every rewrite that
replaces one engine's function with another's is asserted here against DuckDB,
value for value, over inputs chosen to break a near-equivalent:

* a suffix containing ``%``, which the tempting ``LIKE '%' || s`` spelling
  reads as a wildcard;
* a capture group that is not the whole match, which is what SQLGlot's
  generators silently dropped (S-0045/D-5);
* a non-match and a group that takes no part in the match, NULL on both:
  DuckDB's own ``regexp_extract`` answers ``''`` for either, and the DuckDB port
  reads the first match's group instead (S-0025/D-24) — next to an empty
  capture, which is ``''`` on both and must stay so.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import psycopg
import pytest
from sqlglot import exp
from testcontainers.community.postgres import PostgresContainer

from bloomery.dialects import get_dialect
from bloomery.ir.lower import canon
from bloomery.transforms import DEFAULT_REGISTRY

pytestmark = pytest.mark.engine("postgres")

#: ``(transform, args, values)`` — one row per rewrite this port carries.
CASES: tuple[tuple[str, tuple[object, ...], tuple[str, ...]], ...] = (
    ("strip_suffix", ("-eu",), ("42-eu", "42", "-eu", "", "eu")),
    # A suffix that is a LIKE wildcard: `RIGHT`/`LENGTH` treats it literally,
    # `LIKE '%' || s` would not.
    ("strip_suffix", ("%b",), ("a%b", "ab", "a%bc")),
    ("regex_extract", ("sku-([0-9]+)", 1), ("sku-42", "SKU-42", "sku-", "x")),
    ("regex_extract", ("sku-([0-9]+)", 0), ("sku-42", "nope")),
    ("regex_extract", ("^(a*)", 1), ("b", "aa")),
    ("regex_extract", ("(a)|b", 1), ("b", "a")),
)

#: ``(steps, values)`` — a rewritten step nested in another. The rewrite
#: replaces the outer step's node, and the inner one has to be reached inside
#: the replacement: unreached, it kept ``ENDS_WITH`` or ``REGEXP_EXTRACT``,
#: neither of which PostgreSQL defines.
CHAINS: tuple[tuple[tuple[tuple[str, tuple[object, ...]], ...], tuple[str, ...]], ...] = (
    ((("strip_suffix", ("-eu",)), ("strip_suffix", ("-eu",))), ("42-eu-eu", "42-eu", "42")),
    (
        (("strip_suffix", ("-eu",)), ("regex_extract", ("sku-([0-9]+)", 1))),
        ("sku-42-eu", "sku-42"),
    ),
    (
        (("regex_extract", ("id=(.*)", 1)), ("regex_extract", ("sku-([0-9]+)", 0))),
        ("id=sku-42", "id=sku-7"),
    ),
)


def _sql(transform: str, args: tuple[object, ...], dialect: str) -> str:
    return _chain_sql(((transform, args),), dialect)


def _chain_sql(steps: tuple[tuple[str, tuple[object, ...]], ...], dialect: str) -> str:
    built: exp.Expression = exp.column("s")
    for transform, args in steps:
        built = DEFAULT_REGISTRY[transform].builder(built, *args)
    return get_dialect(dialect).render(canon(built).ast())


@pytest.fixture(scope="module")
def postgres() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
        )
        yield conn
        conn.close()


@pytest.mark.parametrize(("transform", "args", "values"), CASES, ids=lambda v: str(v)[:40])
def test_postgres_spelling_agrees_with_duckdb(
    postgres: psycopg.Connection,
    transform: str,
    args: tuple[object, ...],
    values: tuple[str, ...],
) -> None:
    duck = duckdb.connect()
    for value in values:
        literal = value.replace("'", "''")
        duck_value = duck.sql(
            f"SELECT ({_sql(transform, args, 'duckdb')}) AS v "  # noqa: S608 — literals are ours
            f"FROM (SELECT CAST('{literal}' AS VARCHAR) AS s)"
        ).fetchall()[0][0]
        row = postgres.execute(
            f"SELECT ({_sql(transform, args, 'postgres')}) "  # noqa: S608 — literals are ours
            f"FROM (SELECT CAST('{literal}' AS TEXT) AS s) AS t"
        ).fetchone()
        assert row is not None
        pg_value = row[0]
        assert pg_value == duck_value, (
            f"{transform}{args} over {value!r}: duckdb {duck_value!r}, postgres {pg_value!r}"
        )


@pytest.mark.parametrize(("steps", "values"), CHAINS, ids=lambda v: str(v)[:60])
def test_a_nested_step_is_spelled_for_postgres_too(
    postgres: psycopg.Connection,
    steps: tuple[tuple[str, tuple[object, ...]], ...],
    values: tuple[str, ...],
) -> None:
    duck = duckdb.connect()
    for value in values:
        literal = value.replace("'", "''")
        duck_value = duck.sql(
            f"SELECT ({_chain_sql(steps, 'duckdb')}) AS v "  # noqa: S608 — literals are ours
            f"FROM (SELECT CAST('{literal}' AS VARCHAR) AS s)"
        ).fetchall()[0][0]
        row = postgres.execute(
            f"SELECT ({_chain_sql(steps, 'postgres')}) "  # noqa: S608 — literals are ours
            f"FROM (SELECT CAST('{literal}' AS TEXT) AS s) AS t"
        ).fetchone()
        assert row is not None
        assert row[0] == duck_value, f"{steps} over {value!r}: duckdb {duck_value!r}, postgres {row[0]!r}"
