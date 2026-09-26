"""The Redshift surrogate lane (S-0015 phase 2): the port's SQL submitted to a
real PostgreSQL standing in for a Redshift cluster — rung 4, **evidence and
never the oracle** (S-0012/D-1).

What a green run here says, in full: PostgreSQL accepted these statements. It
provisions a cluster, connects over the wire protocol, runs the port's DDL and
DML, and reads rows back — which is what the surrogate is genuinely good for
(S-0015/local-execution-and-what-it-cannot-say) and the whole of it. It says
nothing about ``SUPER``, PartiQL, Redshift-only functions, Redshift's type
rules or its planner, and it cannot: those fixtures are the `redshift-native`
class and :func:`support.redshift.surrogate_fixtures` does not return them
(S-0015/D-3), so this lane cannot reach one by anyone's oversight.

The marker is ``surrogate("redshift_postgres")`` rather than
``engine("redshift")`` (S-0012/D-2, S-0015/D-2): every module here but this one
names the engine it ran against, and a Postgres-backed shim wearing that marker
would read in a CI log as "Redshift passed" — which no run on this rung is
entitled to say. Only the live lane speaks for the engine.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from support.compiling import compile_fixture
from support.redshift import (
    SURROGATE,
    fixtures_by_class,
    model_statements,
    quoted,
    relation_ddl,
    reset_layers,
    rows,
    submit,
    supplied_relations,
    surrogate_cluster,
    surrogate_fixtures,
)

pytestmark = pytest.mark.surrogate(SURROGATE)


@pytest.fixture(scope="module")
def cluster() -> Iterator[psycopg.Connection]:
    with surrogate_cluster() as connection:
        yield connection


@pytest.fixture
def clean(cluster: psycopg.Connection) -> psycopg.Connection:
    reset_layers(cluster)
    return cluster


def test_the_native_class_is_excluded_by_construction() -> None:
    """The exclusion is a property of what the lane is parametrized on, asserted
    here so it fails in the lane rather than in a reviewer's attention."""
    classified = fixtures_by_class()
    assert classified["redshift-native"], "the native class has emptied — the split is not splitting"
    assert not set(surrogate_fixtures()) & set(classified["redshift-native"])


@pytest.mark.parametrize("fixture_name", surrogate_fixtures())
def test_postgres_accepts_the_ports_ddl_and_dml(
    clean: psycopg.Connection, fixture_name: str
) -> None:
    """Every model of a `postgres-compatible` fixture builds on the surrogate.

    ``CREATE TABLE … AS`` over empty bronze relations: DDL, DML and relation
    resolution for the statements the port emits. What each built relation is
    then read for is that it resolves and is selectable, and not what is in it —
    a value this lane produced would be PostgreSQL's value, and PostgreSQL is
    not the oracle for one (S-0015/D-2). Not an emptiness assertion either:
    ``gold.dim_date`` is a ``GENERATE_SERIES`` date spine that reads no bronze
    relation and builds its 4018 rows from nothing (the PostgreSQL tier asserts
    that count at tests/engines/test_postgres_execution.py:129), so "empty in,
    empty out" is not a property of the models this lane submits.
    """
    artifacts = compile_fixture(fixture_name, dialect="redshift")
    supplied = supplied_relations(fixture_name)
    statements = tuple(
        (relation, create)
        for relation, create in model_statements(artifacts)
        if relation not in supplied
    )
    ddl = relation_ddl(fixture_name, built={name for name, _ in statements})
    # A fixture whose only entity is SCD-2 has no model this lane runs — the
    # framework maintains that relation, not a SELECT (see `supplied_relations`)
    # — and what it has instead is the DDL for it.
    assert statements or ddl, f"{fixture_name} left the lane nothing to submit"

    for create_table in ddl:
        submit(clean, create_table)

    for relation, create in statements:
        submit(clean, create)
        submit(clean, f"SELECT * FROM {quoted(relation)} LIMIT 0")


def test_rows_round_trip_over_the_wire(clean: psycopg.Connection) -> None:
    """The DML half with values in it: seed bronze, build, read back.

    ``minimal`` because the claim is about the wire and the harness — that what
    was inserted comes back through the port's SELECT — and not about any
    computation Redshift would do differently.
    """
    artifacts = compile_fixture("minimal", dialect="redshift")
    statements = model_statements(artifacts)

    for ddl in relation_ddl("minimal", built={name for name, _ in statements}):
        submit(clean, ddl)
    with clean.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO bronze.raw__events VALUES (%s, %s, %s)",
            [("e1", "click", "2024-01-02T03:04:05"), ("e2", "view", "2024-02-03T04:05:06")],
        )
    for _relation, create in statements:
        submit(clean, create)

    assert [(row[0], row[1]) for row in rows(clean, "silver.event")] == [
        ("e1", "click"),
        ("e2", "view"),
    ]
