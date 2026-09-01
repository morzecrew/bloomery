"""Engine tier (RFC 0009 §5.2 tier 5): a reconcile check over a NULL key, run
on real PostgreSQL.

The DuckDB tier already states what the comparison must *mean*
(``tests/execution/test_reconcile_null_keys.py``). This one exists because
meaning is not the only thing an engine has an opinion about: the first
null-safe spelling of this model was a single ``FULL OUTER JOIN ... ON a IS NOT
DISTINCT FROM b``, which renders identically on all three dialects, runs on two
of them, and is **refused outright** by PostgreSQL —

    FULL JOIN is only supported with merge-joinable or hash-joinable join
    conditions

— because its full join is planned as a merge or hash join and a null-safe
condition is neither. Rendering equality across dialects is not execution
equality, and only a container can tell the two apart. So the same specs and
the same seed as the DuckDB tier run here, and the assertions are the same
claims: one row per compared key, the NULL group agreeing, the one-sided keys
still failing.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from bloomery import Target, compile_project, load_project
from support.compiling import extract_select
from support.reconcile import LINES, ORDERS, SOURCES

pytestmark = pytest.mark.engine("postgres")

RECONCILE = 'silver."lines_match_total__reconcile"'


@pytest.fixture(scope="module")
def reconciled() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        conn.execute("SET TIME ZONE 'UTC'")
        for schema in ("bronze", "silver"):
            conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute("CREATE TABLE bronze.src__lines (id TEXT, order_id TEXT, amount NUMERIC)")
        conn.execute("CREATE TABLE bronze.src__orders (id TEXT, amount NUMERIC)")
        with conn.cursor() as cursor:
            cursor.executemany("INSERT INTO bronze.src__lines VALUES (%s, %s, %s)", LINES)
            cursor.executemany("INSERT INTO bronze.src__orders VALUES (%s, %s)", ORDERS)
        conn.commit()
        artifacts = [
            a
            for a in compile_project(
                load_project(SOURCES), target=Target.SQLMESH, dialect="postgres"
            )
            if a.path.startswith("models/silver/") and a.path.endswith(".sql")
        ]
        # The two entities before the check that compares them: a reconcile
        # model reads both silver relations, so it cannot be the first table
        # created. Ordering keeps a failure legible rather than making it a
        # missing-relation error.
        for artifact in sorted(artifacts, key=lambda a: a.path.endswith("__reconcile.sql")):
            name = artifact.path.rsplit("/", 1)[-1].removesuffix(".sql")
            # Run-context macros have no meaning outside SQLMesh; what is under
            # test is the comparison, not the run window.
            body = re.sub(r"@[a-z_]+", "'2026-01-01'", extract_select(artifact.content))
            conn.execute(f'CREATE TABLE silver."{name}" AS {body}')
        conn.commit()
        yield conn
        conn.close()


def test_the_model_runs_at_all(reconciled: psycopg.Connection) -> None:
    """The regression this file was added for.

    The `CREATE TABLE` in the fixture is the assertion — under the ``FULL
    JOIN`` spelling it raised ``psycopg.errors.FeatureNotSupported`` and every
    test in the module errored at setup. Stated as its own test so a future
    failure reads as "postgres will not run this" rather than as whichever
    assertion happened to be collected first.
    """
    (rows,) = reconciled.execute(f"SELECT COUNT(*) FROM {RECONCILE}").fetchone() or (None,)
    assert rows == 4


def test_a_null_key_compares_once_rather_than_failing_twice(
    reconciled: psycopg.Connection,
) -> None:
    """The same claim the DuckDB tier makes, on the engine that could not
    express it in the original spelling: one row, and it passes."""
    assert reconciled.execute(
        f"SELECT left_value, right_value, difference, within_tolerance "
        f"FROM {RECONCILE} WHERE order_id IS NULL"
    ).fetchall() == [(Decimal("7.00"), Decimal("7.00"), Decimal("0.00"), True)]


def test_one_sided_keys_are_still_the_loudest_disagreement(
    reconciled: psycopg.Connection,
) -> None:
    """Two ``LEFT JOIN``s off the key union have to keep what the ``FULL JOIN``
    was for: a key on one side only fails rather than vanishing."""
    rows = {
        order_id: (left, right, difference, within)
        for order_id, left, right, difference, within in reconciled.execute(
            f"SELECT order_id, left_value, right_value, difference, within_tolerance "
            f"FROM {RECONCILE}"
        ).fetchall()
    }
    # `difference` stays NULL on a one-sided key — the DuckDB tier's assertion,
    # asked of this engine too.
    assert rows["o2"] == (Decimal("3.00"), None, None, False)
    assert rows["o3"] == (None, Decimal("9.00"), None, False)
    assert rows["o1"] == (Decimal("15.00"), Decimal("15.00"), Decimal("0.00"), True)
