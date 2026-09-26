"""The authoritative Redshift lane (S-0015 phase 3, S-0012/D-3): the port's SQL
put to Redshift's own compiler with ``EXPLAIN`` and ``EXPLAIN VERBOSE``, against a
real cluster or Serverless workgroup.

This is the rung that speaks for the engine. A plan is built and nothing is run,
so what a green run here says is that Redshift's own parser, binder and type
resolution accepted these statements — syntax, function availability, argument
types, relation and column resolution — at the cost of a parse rather than a
scan. It is also the first rung that says anything about the `redshift-native`
class at all: S-0015/D-3 keeps ``SUPER``, ``CONVERT_TIMEZONE``, ``SHA2`` and
``REGEXP_SUBSTR`` off the surrogate because PostgreSQL is not their oracle, and
here they are the engine's business, so :func:`support.redshift.live_fixtures`
returns both classes.

``EXPLAIN`` covers queries, DML and ``CREATE TABLE AS``, but not arbitrary DDL,
so the port's physical types get their own small check beside it
(:func:`test_redshift_accepts_the_ports_physical_types`) — the only way a lane
finds out that ``TEXT`` would have meant ``VARCHAR(256)``.

**The marker.** ``engine("redshift")`` is the real engine's marker and this is
the real engine, so a green run is entitled to read as "Redshift passed" — the
thing S-0012/D-2 and S-0015/D-2 deny the Postgres-backed shim next door, which
keeps its ``surrogate`` marker and its own name. The marker's registration says
"requires Docker"; here the requirement is a credential instead, which is
recorded as a divergence rather than left to a reader to notice.

The lane skips with its reason when the credential is absent (there is no cluster
on a laptop and none in a sandbox) — collection stands either way, which is what
lets the acceptance run where the engine cannot.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from support.compiling import compile_fixture
from support.redshift import (
    NO_CREDENTIALS,
    explain,
    fixtures_by_class,
    live_cluster,
    live_dsn,
    live_fixtures,
    live_scratch,
    model_statements,
    relation_ddl,
    submit_live,
    supplied_relations,
)

from bloomery.dialects import RedshiftDialect
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

pytestmark = pytest.mark.engine("redshift")

#: Every logical type the port maps, for the DDL check ``EXPLAIN`` cannot make.
#: ``DecimalType(38, 0)`` is in because it is Redshift's limit and a port that
#: drifted past it would emit a type the engine refuses.
PHYSICAL_TYPES: tuple[LogicalType, ...] = (
    StringType(),
    IntType(),
    DecimalType(12, 4),
    DecimalType(38, 0),
    BoolType(),
    DateType(),
    TimestampType(),
    VariantType(),
)


@pytest.fixture(scope="module")
def cluster() -> Iterator[psycopg.Connection]:
    if live_dsn() is None:
        pytest.skip(NO_CREDENTIALS)
    with live_cluster() as connection:
        yield connection


@pytest.fixture
def scratch(cluster: psycopg.Connection) -> Iterator[str]:
    """This test's own layer schemas, rolled back when it ends."""
    with live_scratch(cluster) as suffix:
        yield suffix


def test_the_native_class_reaches_this_rung() -> None:
    """The lane's parametrization covers both classes, asserted where it fails
    rather than left to whoever compares two lists. No cluster needed: it is a
    property of what the lane is parametrized on."""
    classified = fixtures_by_class()
    assert classified["redshift-native"], "the native class has emptied — the split is not splitting"
    assert set(live_fixtures()) == set(classified["redshift-native"]) | set(
        classified["postgres-compatible"]
    )


@pytest.mark.parametrize("fixture_name", live_fixtures())
def test_redshift_plans_every_model(
    cluster: psycopg.Connection, scratch: str, fixture_name: str
) -> None:
    """Redshift's compiler accepts every model of every fixture the port renders.

    The source relations are created first, because a plan is where relation and
    column resolution happens and an unbound name is exactly what this rung is
    for. Then each model, in build order: ``EXPLAIN``, ``EXPLAIN VERBOSE``, and
    then the statement itself — the relation has to exist for the next model's
    binder, and over source relations that hold no rows building it scans
    nothing. Everything is inside the scratch transaction, so the cluster keeps
    none of it.

    SCD-2 relations are excluded the way the surrogate lane excludes them: the
    framework maintains those, no SELECT does, and what the fixture has instead
    is the DDL for them.
    """
    artifacts = compile_fixture(fixture_name, dialect="redshift")
    supplied = supplied_relations(fixture_name)
    statements = tuple(
        (relation, create)
        for relation, create in model_statements(artifacts)
        if relation not in supplied
    )
    ddl = relation_ddl(fixture_name, built={name for name, _ in statements}, native=True)
    assert statements or ddl, f"{fixture_name} left the lane nothing to submit"

    for create_table in ddl:
        submit_live(cluster, create_table, scratch)

    for _relation, create in statements:
        assert explain(cluster, create, scratch), "Redshift returned an empty plan"
        assert explain(cluster, create, scratch, verbose=True)
        submit_live(cluster, create, scratch)


def test_redshift_accepts_the_ports_physical_types(
    cluster: psycopg.Connection, scratch: str
) -> None:
    """The check beside the plan, because ``EXPLAIN`` covers no ``CREATE TABLE``.

    One table with a column per logical type the port maps. This is the assertion
    no offline rung can make: ``VARCHAR(MAX)``, ``SUPER`` and ``DECIMAL(38, 0)``
    are accepted here or the port's column types are fiction — and ``TEXT``, the
    spelling this port refuses, would have been accepted too and quietly meant
    something narrower.
    """
    port = RedshiftDialect()
    columns = ", ".join(
        f'"c{index}" {port.physical_type(logical)}'
        for index, logical in enumerate(PHYSICAL_TYPES)
    )
    submit_live(cluster, f"CREATE TABLE bronze.port_types ({columns})", scratch)

    assert explain(cluster, "SELECT * FROM bronze.port_types", scratch)
