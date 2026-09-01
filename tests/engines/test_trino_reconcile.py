"""Engine tier (RFC 0009 §5.2 tier 5): the reconcile check over a NULL key,
run on real Trino — the third engine's copy of the claim.

The DuckDB tier states what the comparison must *mean*
(``tests/execution/test_reconcile_null_keys.py``) and the Postgres mirror
exists because that engine **refused** the first spelling outright: rendering
equality across dialects is not execution equality, and only a container can
tell the two apart. Trino was the one shipped engine on which the current
two-``LEFT JOIN`` spelling — whose join conditions are ``IS NOT DISTINCT
FROM``, exactly the shape PostgreSQL could not plan — had never run at all.

Same specs, same seed, same assertions as the other two tiers: one row per
compared key, the NULL group agreeing, the one-sided keys still failing.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal

import pytest
import trino
from testcontainers.community.trino import TrinoContainer

from bloomery import Target, compile_project, load_project
from support.compiling import extract_select
from support.reconcile import LINES, ORDERS, SOURCES

pytestmark = pytest.mark.engine("trino")

IMAGE = "trinodb/trino:483"

RECONCILE = 'memory.silver."lines_match_total__reconcile"'


def _run(connection: trino.dbapi.Connection, statement: str) -> list[list[object]]:
    cursor = connection.cursor()
    cursor.execute(statement)
    return cursor.fetchall()


def _row(fields: tuple[object, ...]) -> str:
    rendered = ", ".join(
        "CAST(NULL AS VARCHAR)"
        if field is None
        else f"DECIMAL '{field}'"
        if isinstance(field, Decimal)
        else f"'{field}'"
        for field in fields
    )
    return f"({rendered})"


@pytest.fixture(scope="module")
def reconciled() -> Iterator[trino.dbapi.Connection]:
    with TrinoContainer(IMAGE) as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )
        for schema in ("bronze", "silver"):
            _run(connection, f"CREATE SCHEMA IF NOT EXISTS memory.{schema}")
        _run(
            connection,
            "CREATE TABLE memory.bronze.src__lines (id varchar, order_id varchar, "
            "amount decimal(12, 2))",
        )
        _run(
            connection,
            "CREATE TABLE memory.bronze.src__orders (id varchar, amount decimal(12, 2))",
        )
        _run(
            connection,
            "INSERT INTO memory.bronze.src__lines VALUES "
            + ", ".join(_row(line) for line in LINES),
        )
        _run(
            connection,
            "INSERT INTO memory.bronze.src__orders VALUES "
            + ", ".join(_row(order) for order in ORDERS),
        )
        artifacts = [
            a
            for a in compile_project(load_project(SOURCES), target=Target.SQLMESH, dialect="trino")
            if a.path.startswith("models/silver/") and a.path.endswith(".sql")
        ]
        # The two entities before the check that compares them, so a failure
        # reads as its own rather than as a missing relation.
        for artifact in sorted(artifacts, key=lambda a: a.path.endswith("__reconcile.sql")):
            name = artifact.path.rsplit("/", 1)[-1].removesuffix(".sql")
            # Run-context macros have no meaning outside SQLMesh; what is under
            # test is the comparison, not the run window.
            body = re.sub(r"@[a-z_]+", "'2026-01-01'", extract_select(artifact.content))
            _run(connection, f'CREATE TABLE memory.silver."{name}" AS {body}')
        yield connection


def test_the_model_runs_at_all(reconciled: trino.dbapi.Connection) -> None:
    """The Postgres mirror's headline, asked of the engine that never answered
    it: the ``CREATE TABLE`` in the fixture is the assertion, stated as its own
    test so a refusal reads as "trino will not run this" rather than as
    whichever assertion collected first."""
    assert _run(reconciled, f"SELECT COUNT(*) FROM {RECONCILE}")[0][0] == 4


def test_a_null_key_compares_once_rather_than_failing_twice(
    reconciled: trino.dbapi.Connection,
) -> None:
    rows = _run(
        reconciled,
        f"SELECT left_value, right_value, difference, within_tolerance "
        f"FROM {RECONCILE} WHERE order_id IS NULL",
    )
    assert [tuple(row) for row in rows] == [
        (Decimal("7.00"), Decimal("7.00"), Decimal("0.00"), True)
    ]


def test_one_sided_keys_are_still_the_loudest_disagreement(
    reconciled: trino.dbapi.Connection,
) -> None:
    rows = {
        order_id: (left, right, difference, within)
        for order_id, left, right, difference, within in _run(
            reconciled,
            f"SELECT order_id, left_value, right_value, difference, within_tolerance "
            f"FROM {RECONCILE}",
        )
    }
    # `difference` stays NULL on a one-sided key — the DuckDB tier's assertion,
    # asked of this engine too.
    assert rows["o2"] == (Decimal("3.00"), None, None, False)
    assert rows["o3"] == (None, Decimal("9.00"), None, False)
    assert rows["o1"] == (Decimal("15.00"), Decimal("15.00"), Decimal("0.00"), True)
