"""The Redshift surrogate harness (S-0015): the fixture split the local lane
reads, built before there is a lane to read it.

Floci gives a Redshift-shaped control plane over a real PostgreSQL container,
and LocalStack emulates the AWS control plane and Data API. Both are the
*surrogate* rung — evidence, never the oracle (S-0012/D-1) — and a lane using
either marks itself

.. code-block:: python

    @pytest.mark.surrogate("redshift_postgres")

so a CI log never reads as "Redshift passed". LocalStack stays optional while
bloomery is a pure compiler (S-0015/D-5): it emulates surfaces the compiler does
not touch, so no lane is blocked on it.

**The split (S-0015/D-3).** Fixtures fall into two named classes, and the native
class never runs on the surrogate: PostgreSQL is not an oracle for ``SUPER``,
PartiQL, Redshift-only functions or Redshift's own type rules, so a green run
over a native fixture would be a claim the lane cannot make. Without the split
the lane's coverage number silently includes cases it cannot speak to, which is
how a partial lane comes to be read as a full one.

Nothing consumes this yet — the lane is phase 2. It is here because the split is
cheap before there are fixtures and expensive afterwards.

**Why the classification is derived rather than listed.** A hand-kept list of
native fixtures is right on the day it is written and silently wrong the day a
fixture gains a ``variant`` field or a ``quarantine:`` block — and the failure
is invisible, because a fixture that quietly moves into the compatible class
makes the lane look *better*. So the classes are computed from what the port
actually emits, against the port's own Redshift-only vocabulary below.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from contextlib import contextmanager

import psycopg
import sqlglot
from sqlglot import expressions as exp
from support.compiling import (
    compile_fixture,
    extract_select,
    load_fixture,
    spec_fixture_names,
)
from support.execution import DEFAULT_SCHEMAS, relation_of
from support.steps import registry_for
from testcontainers.community.postgres import PostgresContainer

from bloomery import ProjectIR, build_project_ir
from bloomery.dialects import RedshiftDialect
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.errors import BloomeryError
from bloomery.ir import SCDKind
from bloomery.typing import LogicalType

# ----------------------- #

#: The two classes, spelled as S-0015/D-3 spells them.
POSTGRES_COMPATIBLE = "postgres-compatible"
REDSHIFT_NATIVE = "redshift-native"

#: The surrogate marker a lane over :func:`surrogate_fixtures` carries.
SURROGATE = "redshift_postgres"

#: Redshift-only spellings :class:`~bloomery.dialects.redshift.RedshiftDialect`
#: emits, each one a construct PostgreSQL either does not define or reads
#: differently — so a fixture whose SQL contains any of them is `redshift-native`
#: and the surrogate is not its oracle:
#:
#: * ``SUPER``, ``JSON_PARSE``, ``CAN_JSON_PARSE``, ``OBJECT(`` — the ``SUPER``
#:   data model (S-0015/D-4). PostgreSQL has none of the three functions.
#: * ``CONVERT_TIMEZONE`` — Redshift's zone conversion, absent in PostgreSQL,
#:   which spells the same thing ``AT TIME ZONE`` and (per S-0025/D-3) means
#:   something else by it.
#: * ``REGEXP_SUBSTR`` with a match parameter — the same function name in both,
#:   with a different argument list and a different reading of the third
#:   argument, which is exactly the "plausible-looking spelling" class.
#: * ``SHA2`` — Redshift's text digest. PostgreSQL's ``sha256`` takes and
#:   returns ``bytea``, which is why the PostgreSQL port spells it differently.
#: * ``GETDATE`` — Redshift's session clock, no PostgreSQL equivalent.
NATIVE_SPELLINGS = (
    "CAN_JSON_PARSE",
    "CONVERT_TIMEZONE",
    "GETDATE",
    "JSON_PARSE",
    "OBJECT(",
    "REGEXP_SUBSTR",
    "SHA2(",
    "SUPER",
)

#: Divergences that are **not** discriminators and so must not be read as one.
#: Every fixture's DDL carries ``VARCHAR(MAX)`` — Redshift's ``string``, and a
#: type PostgreSQL does not parse at all. It is a property of the port rather
#: than of any fixture, so it cannot separate the classes; a lane on the
#: surrogate has to answer for it once, for every fixture alike. Named here so
#: that "postgres-compatible" is read as "no Redshift-only *construct*" and not
#: as "runs on PostgreSQL unchanged".
PORT_WIDE_DIVERGENCES = ("VARCHAR(MAX)",)


def classify(fixture_name: str) -> str | None:
    """Which class ``fixture_name`` is in, or ``None`` if it emits no SQL here.

    ``None`` is not a third class: it is a fixture the port never renders —
    either a refusal fixture, which is refused on every dialect and exists to
    be, or one this port declines (``dirty_corpus``, whose ``normalize`` rule
    needs a normalization function Redshift does not have). Neither has emitted
    SQL for a lane to run, so neither belongs in a class; returning ``None``
    keeps that visible instead of parking them in the compatible class, where
    they would inflate its count and never run.
    """

    try:
        artifacts = compile_fixture(fixture_name, dialect="redshift")
    except BloomeryError:
        return None

    sql = "\n".join(artifact.content for artifact in artifacts)
    native = any(spelling in sql for spelling in NATIVE_SPELLINGS)

    return REDSHIFT_NATIVE if native else POSTGRES_COMPATIBLE


def fixtures_by_class() -> dict[str, tuple[str, ...]]:
    """Every spec fixture the port renders, under its class name."""

    classified: dict[str, list[str]] = {POSTGRES_COMPATIBLE: [], REDSHIFT_NATIVE: []}

    for name in spec_fixture_names():
        name_class = classify(name)

        if name_class is not None:
            classified[name_class].append(name)

    return {key: tuple(names) for key, names in classified.items()}


def surrogate_fixtures() -> tuple[str, ...]:
    """The fixtures a lane on the PostgreSQL-backed surrogate may run.

    The compatible class and nothing else — this is the function that makes
    S-0015/D-3 a mechanism rather than a note, because a lane parametrized on it
    cannot reach a native fixture by forgetting to exclude one.
    """

    return fixtures_by_class()[POSTGRES_COMPATIBLE]


# ----------------------- #
# The surrogate harness: connection, submission, canonicalization.


#: The image the surrogate cluster is a real PostgreSQL container of — the same
#: one the PostgreSQL engine tier runs, because the surrogate's whole claim is
#: "PostgreSQL accepted this" (S-0015/D-2) and two versions would make it two
#: claims. Floci manages a container of its own per emulated cluster and adds a
#: Redshift-shaped control plane on top; nothing bloomery emits addresses that
#: control plane, so the container is taken directly (S-0015/D-5 for the same
#: reason on LocalStack: emulated surfaces a pure compiler never touches).
SURROGATE_IMAGE = "postgres:16-alpine"


@contextmanager
def surrogate_cluster() -> Iterator[psycopg.Connection]:
    """A connected surrogate cluster: provision, connect, speak the wire.

    Autocommit, because the lane's interest is statement-by-statement
    acceptance: inside a transaction the first refusal aborts every statement
    after it, and a lane that reports one failure per fixture instead of one
    per statement has lost the thing it was run for.
    """

    with PostgresContainer(SURROGATE_IMAGE, driver=None) as container:
        connection = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
        )
        connection.execute("SET TIME ZONE 'UTC'")
        yield connection
        connection.close()


def reset_layers(conn: psycopg.Connection) -> None:
    """Drop and recreate the three layer schemas.

    Per fixture rather than per cluster: two fixtures both build
    ``silver.customer`` from different mappings, so a sweep that kept one
    database would be asserting whichever ran first.
    """

    for schema in DEFAULT_SCHEMAS:
        conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.execute(f"CREATE SCHEMA {schema}")


def to_surrogate(sql: str) -> str:
    """The port-wide divergences answered, once, for every fixture alike.

    ``VARCHAR(MAX)`` is Redshift's ``string`` and PostgreSQL does not parse it;
    unqualified ``VARCHAR`` is PostgreSQL's unbounded text, which is what the
    Redshift type means. This is the accommodation
    :data:`PORT_WIDE_DIVERGENCES` names, and it is applied here — in one
    place, to everything submitted — so that a reader of a green lane can see
    exactly how much the surrogate had to be met halfway.
    """

    return sql.replace("VARCHAR(MAX)", "VARCHAR")


def submit(conn: psycopg.Connection, sql: str) -> None:
    """One statement to the surrogate, through the accommodation."""

    conn.execute(to_surrogate(sql))


def quoted(relation: str) -> str:
    """``namespace.relation`` as a statement may name it.

    The relation half is quoted because ``order`` is reserved in PostgreSQL and
    a fixture is entitled to name an entity that.
    """

    namespace, _, name = relation.partition(".")
    return f'{namespace}."{name}"'


def rows(conn: psycopg.Connection, relation: str) -> list[tuple[object, ...]]:
    """Every row of ``namespace.relation``, order-normalized.

    Sorted by the rendered row rather than by a key, the way the DuckDB tier's
    snapshot is (:func:`support.execution.snapshot`): what a surrogate row
    comparison asserts is that nothing moved, including columns no key covers.
    """

    with conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {quoted(relation)}")  # noqa: S608
        return sorted((tuple(row) for row in cursor.fetchall()), key=repr)


def _qualified(relation: str) -> str:
    """A source relation as the emitted SQL spells it: bronze unless it says
    otherwise. A mapping may read a ``silver.`` relation the operator supplies
    (an SCD-2 entity, a rate table), and that one carries its own namespace."""

    return relation if "." in relation else f"bronze.{relation}"


def _project_ir(fixture_name: str) -> ProjectIR:
    project, catalog = load_fixture(fixture_name)
    return build_project_ir(project, catalog=catalog, steps=registry_for(fixture_name))


def supplied_relations(fixture_name: str) -> frozenset[str]:
    """Relations the operator supplies, which no model of this fixture builds.

    An SCD-2 entity is the case that matters: its versions come from the
    operator's snapshotting and its ``valid_from``/``valid_to`` come from the
    framework's own SCD handling, so the model's SELECT does not carry them and
    a harness that ran it would leave the as-of join reading a relation without
    the columns it joins on. The DuckDB tier makes the same exclusion by hand
    (:func:`support.execution.materialize`'s ``supplied``); here it is read off
    the IR so a fixture that becomes type-2 does not need the lane edited.
    """

    return frozenset(
        f"silver.{entity.name}"
        for entity in _project_ir(fixture_name).entities
        if entity.scd is SCDKind.TYPE2
    )


def relation_ddl(fixture_name: str, *, built: Collection[str]) -> tuple[str, ...]:
    """``CREATE TABLE`` for every relation the fixture reads and no model builds.

    Three kinds of relation, all derived rather than written out per fixture, so
    that a fixture which gains a field does not leave the lane running against a
    stale table:

    * **bronze**, from the mapping's own source paths — what the port's SELECT
      actually reads. A root a mapping reaches into (``$.order.id``) is typed
      ``JSON``, because the port lowers that to ``JSON_EXTRACT_PATH_TEXT`` and
      PostgreSQL's takes ``json`` where Redshift's takes text.
    * **silver relations the operator supplies** — an SCD-2 entity, or one an
      identity-resolution mapping reads — from the entity's declared columns,
      plus the validity pair for a type-2.
    * **the rate relation**, when the catalog declares one: named columns, no
      rows, enough for the conversion join to resolve.

    Types come from the port's own :meth:`physical_type` for the column each
    path feeds. Bronze is raw text in life and the DuckDB tier seeds it that
    way, but a lane over *empty* relations has no values to coerce and still has
    the port's arithmetic to satisfy — ``total / qty`` over two ``TEXT`` columns
    is refused by PostgreSQL before it ever looks at a row.
    """

    ir = _project_ir(fixture_name)
    columns: dict[str, dict[str, str]] = {}

    for entity in ir.entities:
        declared_types = {column.name: _physical(column.type) for column in entity.columns}
        for source in entity.sources:
            relation = _qualified(source.relation)
            if relation in built:
                continue
            if not source.fields:
                # Nothing maps into this relation — it is read whole, the way an
                # identity-resolution mapping reads the resolved entity.
                columns.setdefault(relation, {}).update(declared_types)
                continue
            for field in source.fields:
                root, _, rest = field.source_path.removeprefix("$.").partition(".")
                _declare(
                    columns.setdefault(relation, {}),
                    root.strip('"'),
                    "JSON" if rest else declared_types.get(field.target_field, "VARCHAR"),
                )
            for path in source.unmapped:
                root, _, rest = path.removeprefix("$.").partition(".")
                _declare(columns.setdefault(relation, {}), root.strip('"'), "VARCHAR")

    for relation in sorted(supplied_relations(fixture_name) - frozenset(columns)):
        entity = next(e for e in ir.entities if f"silver.{e.name}" == relation)
        columns[relation] = {column.name: _physical(column.type) for column in entity.columns}

    for relation in supplied_relations(fixture_name):
        columns[relation].update({"valid_from": "TIMESTAMP", "valid_to": "TIMESTAMP"})

    if ir.fx_rates is not None and _rate_relation(ir.fx_rates.relation) not in built:
        rates = ir.fx_rates
        columns[_rate_relation(rates.relation)] = {
            rates.from_currency: "VARCHAR",
            rates.to_currency: "VARCHAR",
            rates.rate: "DECIMAL(18, 6)",
            rates.valid_from: "DATE",
            rates.valid_to: "DATE",
        }

    return tuple(
        f"CREATE TABLE {relation} ("
        + ", ".join(f'"{name}" {declared}' for name, declared in sorted(names.items()))
        + ")"
        for relation, names in sorted(columns.items())
    )


def _rate_relation(relation: str) -> str:
    """The rate relation as the port addresses it: silver unless it says
    otherwise. It is a declared relation rather than a mapped source
    (S-0040/phase-2-currency-as-a-declared-relation), and the conversion join
    reads it beside the entity it converts."""

    return relation if "." in relation else f"silver.{relation}"


def _physical(logical: LogicalType) -> str:
    """The port's own physical type, through the surrogate's accommodation."""

    return to_surrogate(RedshiftDialect().physical_type(logical))


def _declare(declared: dict[str, str], name: str, physical: str) -> None:
    """Record one bronze column's type, JSON winning every disagreement.

    A root two mappings read differently — one reaching into it, one reading it
    whole — is a ``json`` column either way; anything else that disagrees keeps
    the first reading, which is enough for relations that hold no rows.
    """

    if declared.get(name) == "JSON":
        return
    if physical == "JSON" or name not in declared:
        declared[name] = physical


def model_statements(
    artifacts: tuple[EmittedArtifact, ...],
) -> tuple[tuple[str, str], ...]:
    """``(relation, CREATE TABLE … AS <select>)`` per model, in build order.

    The order is read off what each SELECT reads, not off the layer names: a
    silver entity may read a sibling silver relation, so "silver before gold"
    is not enough. Python models are skipped — their bodies are platform code
    no lane on this rung runs.
    """

    models = {
        ".".join(relation_of(artifact)): extract_select(artifact.content)
        for artifact in artifacts
        if artifact.kind is ArtifactKind.MODEL and artifact.path.endswith(".sql")
    }

    pending = {
        relation: _reads(select, frozenset(models) - {relation})
        for relation, select in models.items()
    }
    ordered: list[tuple[str, str]] = []
    built: set[str] = set()
    while pending:
        ready = sorted(name for name, reads in pending.items() if reads <= built)
        if not ready:  # pragma: no cover — a cycle would be a compiler bug
            msg = f"cyclic model dependencies among {sorted(pending)}"
            raise AssertionError(msg)
        for name in ready:
            namespace, _, relation = name.partition(".")
            ordered.append(
                (name, f'CREATE TABLE {namespace}."{relation}" AS {models[name]}')
            )
            built.add(name)
            del pending[name]

    return tuple(ordered)


def _reads(select: str, known: frozenset[str]) -> frozenset[str]:
    """Which of ``known`` one SELECT reads, off the parsed tree."""

    tree = sqlglot.parse_one(select, dialect="redshift")
    return frozenset(
        {
            f"{table.args['db'].name}.{table.this.name}"
            for table in tree.find_all(exp.Table)
            if table.args.get("db") is not None and isinstance(table.this, exp.Identifier)
        }
        & known
    )
