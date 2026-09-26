"""The authoritative Redshift lane (S-0015 phases 3 and 4, S-0012/D-3): the
port's SQL put to Redshift's own compiler with ``EXPLAIN`` and ``EXPLAIN
VERBOSE``, and then the targeted execution corpus that runs it, against a real
cluster or Serverless workgroup.

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

**The corpus (phase 4).** A plan settles acceptance and nothing about answers:
``REGEXP_SUBSTR(x, p, 1, 1, 'e')`` plans exactly as well when it returns the
whole match as when it returns the capture, and ``JSON_PARSE`` plans whether or
not the ``SUPER`` it builds can then be navigated. So each construct the port
emits and no other rung can judge gets one value case here — ``SUPER`` and
PartiQL, timestamp conversion, ``TRY_CAST``, decimal limits and arithmetic,
regexp capture, ``SHA2``'s input and output types, null semantics — plus one
end-to-end quarantine run. It stays small and its tables tiny on purpose: this
is the rung whose cost scales with the corpus rather than with the port.

The lane skips with its reason when the credential is absent (there is no cluster
on a laptop and none in a sandbox) — collection stands either way, which is what
lets the acceptance run where the engine cannot.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from sqlglot import exp, parse_one
from support.compiling import compile_fixture
from support.redshift import (
    NO_CREDENTIALS,
    explain,
    fixtures_by_class,
    live_cluster,
    live_dsn,
    live_fixtures,
    live_row,
    live_scratch,
    model_statements,
    port_sql,
    port_transform,
    relation_ddl,
    submit_live,
    supplied_relations,
    to_live,
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


# ....................... #
# The targeted execution corpus (S-0015 phase 4): values, not plans.

PORT = RedshiftDialect()


def _over(expression: str, **operands: str) -> str:
    """``expression`` evaluated over literal operands — this rung's tiny table.

    A one-row subquery rather than a relation: the corpus asks what the engine
    computes from the port's spelling, and a table would add a DDL round trip
    per case without adding a value.
    """
    columns = ", ".join(f"{literal} AS {name}" for name, literal in operands.items())
    return f"SELECT {expression} FROM (SELECT {columns}) AS operands"


def _navigated(expression: str, path: str, physical: str, **operands: str) -> str:
    """A ``SUPER`` the port constructs, reached into with PartiQL and cast back
    to a scalar the wire has a type for.

    Two levels because PartiQL navigates a *column*: ``OBJECT('a', 1).a`` is
    not something Redshift parses, and every ``SUPER`` the port produces is a
    function call (S-0015/D-4).
    """
    inner = _over(f"{expression} AS v", **operands)
    return f"SELECT CAST(v.{path} AS {physical}) FROM ({inner}) AS s"


#: The port's spellings, rendered once here so a case reads as the value it
#: asserts. Each is pinned offline in `tests/unit/test_dialects/test_redshift.py`
#: and accepted by the compiler above; what neither can say is what it returns.
SUPER_OBJECT = port_sql(PORT.json_object([("a", exp.column("x"))]))
SUPER_PARSE = port_sql(parse_one("CAST(x AS JSON)"))
SUPER_TRY_CAST = port_sql(parse_one("TRY_CAST(x AS JSON)"))
BRONZE_EXTRACT = port_sql(parse_one("payload ->> '$.a.b'"))
TRY_BIGINT = port_sql(parse_one("TRY_CAST(x AS BIGINT)"))
TEXT_SHA256 = port_sql(PORT.text_sha256(exp.column("x")))
TO_UTC = port_transform("to_utc", "Europe/Paris")
PARSE_TS = port_transform("parse_ts", "%Y-%m-%d %H:%M:%S")
DIVIDE = port_transform("divide", "3", input_type=DecimalType(12, 4))
REGEX_CAPTURE = port_transform("regex_extract", "sku-([0-9]+)", 1)
REGEX_WHOLE = port_transform("regex_extract", "sku-[0-9]+", 0)

#: The `_quality_flags` fallback as the port emits it when `DialectFeature.ARRAY`
#: is undeclared (S-0015/D-6): a comma-delimited string with the leading
#: separator trimmed, the shape seen in `models/silver/*__reject.sql`.
FLAGS = (
    "TRIM(LEADING ',' FROM CASE WHEN failed THEN ',stock_level_not_negative' ELSE '' END"
    " || CASE WHEN failed THEN ',stock_level_range_min' ELSE '' END)"
)

#: One case per construct: the SQL to run and the value Redshift must return.
CORPUS: tuple[tuple[str, str, object], ...] = (
    # `SUPER` and PartiQL (S-0015/D-4). `OBJECT` builds one and `JSON_PARSE`
    # parses one; both plan whether or not what they built can be navigated.
    ("super-object-navigates", _navigated(SUPER_OBJECT, "a", "BIGINT", x="1"), 1),
    (
        "super-parse-navigates-nested",
        _navigated(SUPER_PARSE, "b.c", "BIGINT", x="'{\"b\": {\"c\": 7}}'"),
        7,
    ),
    # The bronze path the port keeps: Redshift's `JSON_EXTRACT_PATH_TEXT` reads
    # *text* where PostgreSQL's reads `json`, and returns text either way.
    (
        "bronze-extraction-returns-text",
        _over(BRONZE_EXTRACT, payload="'{\"a\": {\"b\": \"7\"}}'"),
        "7",
    ),
    # `TRY_CAST`. The declared capability is "a cast that yields NULL rather
    # than raising", and the `coercible` marker is that NULL.
    ("try-cast-uncastable-text-is-null", _over(TRY_BIGINT, x="'not a number'"), None),
    ("try-cast-castable-text-is-the-value", _over(TRY_BIGINT, x="'42'"), 42),
    # The `SUPER` half of it, which is a rewrite rather than a cast: a bare
    # `JSON_PARSE` *raises* on malformed input, and a raise takes the run with
    # it instead of quarantining the row.
    ("try-cast-super-malformed-is-null", _over(f"({SUPER_TRY_CAST}) IS NULL", x="'{'"), True),
    (
        "try-cast-super-valid-is-not-null",
        _over(f"({SUPER_TRY_CAST}) IS NULL", x="'{\"a\": 1}'"),
        False,
    ),
    # Timestamps. `CONVERT_TIMEZONE(source, target, ts)` reads a zoneless clock
    # as being in `source`; a port that had it backwards moves every instant by
    # twice the offset, and both offsets are the same sign in winter.
    (
        "to-utc-standard-time",
        _over(TO_UTC, x="CAST('2024-01-02 03:04:05' AS TIMESTAMP)"),
        datetime(2024, 1, 2, 2, 4, 5),  # noqa: DTZ001 — Redshift TIMESTAMP is zoneless
    ),
    (
        "to-utc-summer-time",
        _over(TO_UTC, x="CAST('2024-07-01 12:00:00' AS TIMESTAMP)"),
        datetime(2024, 7, 1, 10, 0, 0),  # noqa: DTZ001 — as above
    ),
    # `TO_TIMESTAMP` returns `TIMESTAMPTZ` having attached the session zone; the
    # cast back is what keeps the parsed value the text's own (S-0021).
    (
        "parse-ts-is-zoneless",
        _over(PARSE_TS, x="'2024-03-04 05:06:07'"),
        datetime(2024, 3, 4, 5, 6, 7),  # noqa: DTZ001 — as above
    ),
    # Decimals. 38 digits is Redshift's limit, so this is the widest value the
    # port's `DECIMAL(38, 0)` can carry and the first one a drift past it loses.
    (
        "decimal-38-digit-limit",
        _over(f"CAST(x AS {PORT.physical_type(DecimalType(38, 0))})", x="'" + "9" * 38 + "'"),
        Decimal("9" * 38),
    ),
    (
        "decimal-division-keeps-its-scale",
        _over(DIVIDE, x="CAST(10 AS DECIMAL(12, 4))"),
        Decimal("3.3333"),
    ),
    # Regexp. The case the whole rewrite exists for: `'e'` extracts the first
    # subexpression, and the spelling SQLGlot would have emitted binds the group
    # number to *position* and returns the whole match — which plans identically.
    ("regexp-extracts-the-capture", _over(REGEX_CAPTURE, x="'sku-42-eu'"), "42"),
    ("regexp-group-zero-is-the-whole-match", _over(REGEX_WHOLE, x="'sku-42-eu'"), "sku-42"),
    # `SHA2` takes text and returns lowercase hex text — PostgreSQL's `sha256`
    # takes and returns `bytea`, which is why `reject_id` is spelled this way.
    (
        "sha256-of-text-is-hex-text",
        _over(TEXT_SHA256, x="'abc'"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    ),
    # Null semantics. `reject_id` concatenates its parts, so one NULL part is a
    # NULL identity rather than a shorter string.
    (
        "sha256-of-null-is-null",
        _over(f"{TEXT_SHA256} IS NULL", x="CAST(NULL AS VARCHAR(MAX))"),
        True,
    ),
    ("concat-with-null-is-null", _over("('a' || x) IS NULL", x="CAST(NULL AS VARCHAR(MAX))"), True),
    # And the flags fallback's own null semantics: a row that failed nothing
    # carries the empty string, not NULL — `_quality_ok` is a two-valued claim
    # and the Postgres tier found it three-valued (tests/engines/test_postgres_quality.py:92).
    ("flags-of-a-clean-row-are-empty-not-null", _over(FLAGS, failed="FALSE"), ""),
    (
        "flags-are-comma-delimited-without-a-leading-comma",
        _over(FLAGS, failed="TRUE"),
        "stock_level_not_negative,stock_level_range_min",
    ),
)


@pytest.mark.parametrize(
    ("select", "expected"),
    [pytest.param(select, expected, id=name) for name, select, expected in CORPUS],
)
def test_redshift_returns_the_value_the_port_intends(
    cluster: psycopg.Connection, select: str, expected: object
) -> None:
    """One construct, one value, read back as the engine's own type.

    No scratch schema and no tables: every case selects from a one-row subquery,
    so the corpus costs one round trip each and nothing is left on the cluster.
    """
    assert live_row(cluster, select)[0] == expected


def test_utc_now_is_utc_when_the_session_clock_is_not(cluster: psycopg.Connection) -> None:
    """The port's `utc_now` under a session zone that is not UTC.

    `GETDATE()` is the session's wall clock, so a port that reached for it would
    return local time labelled UTC — and every offline rung, every plan, and
    every run under a UTC session agrees with the correct port exactly. Only a
    non-UTC session tells them apart.
    """
    cluster.execute("SET TIME ZONE 'America/New_York'")
    try:
        now, session_clock = live_row(cluster, f"SELECT {port_sql(PORT.utc_now())}, GETDATE()")
    finally:
        cluster.execute("SET TIME ZONE 'UTC'")

    assert isinstance(now, datetime)
    # Fifteen minutes, not one: `CURRENT_TIMESTAMP` is the *transaction's* clock
    # and this lane holds one open across the corpus. The divergence being
    # caught is four or five hours wide, so the slack costs the case nothing.
    assert abs(now - datetime.now(UTC).replace(tzinfo=None)) < timedelta(minutes=15), (
        f"the port's utc_now returned {now!r}; the session clock read {session_clock!r}"
    )


# ....................... #
# The quarantine end of it: rows in, rows routed.

#: The quality fixture's bronze relation, declared as bronze is in life — text,
#: so there is something to coerce. :func:`support.redshift.relation_ddl` types
#: each column as the *entity* declares it, which is right for the empty
#: relations the plan rung submits and wrong for a lane with values in it.
QUARANTINE_DDL = (
    "CREATE TABLE bronze.wms__stock_levels ("
    '"warehouse" VARCHAR(MAX), "day" VARCHAR(MAX), "on_hand" VARCHAR(MAX), '
    '"operator_note" VARCHAR(MAX), "_load_id" VARCHAR(MAX), '
    '"_ingested_at" VARCHAR(MAX), "_source_row_id" VARCHAR(MAX))'
)

#: Three rows: one clean, one per coercion failure. Tiny on purpose — the claim
#: is about routing, and a fourth row of the same kind would cost a scan and
#: settle nothing.
QUARANTINE_ROWS = (
    ("w1", "2026-01-01", "5", "", "L1", "2026-01-01T00:00:00", "r1"),
    ("w2", "not-a-date", "7", "", "L1", "2026-01-01T00:00:00", "r2"),
    ("w3", "2026-01-02", "abc", "", "L1", "2026-01-01T00:00:00", "r3"),
)

#: The two models this run needs. The fixture's marts and its date spine read
#: from these and add nothing to the claim — `gold.dim_date` alone builds 4018
#: rows from a `GENERATE_SERIES`, which on a metered cluster is the whole reason
#: this rung stays small.
QUARANTINE_MODELS = ("silver.inventory_level", "silver.inventory_level__reject")


@pytest.fixture
def quarantined(cluster: psycopg.Connection, scratch: str) -> str:
    """``semi_additive_inventory`` built on the engine over the three rows."""
    submit_live(cluster, QUARANTINE_DDL, scratch)
    with cluster.cursor() as cursor:
        cursor.executemany(
            to_live(
                "INSERT INTO bronze.wms__stock_levels (warehouse, day, on_hand, operator_note,"
                " _load_id, _ingested_at, _source_row_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                scratch,
            ),
            QUARANTINE_ROWS,
        )

    artifacts = compile_fixture("semi_additive_inventory", dialect="redshift")
    statements = dict(model_statements(artifacts))
    for relation in QUARANTINE_MODELS:
        submit_live(cluster, statements[relation], scratch)

    return scratch


def test_the_clean_row_is_the_only_one_delivered(
    cluster: psycopg.Connection, quarantined: str
) -> None:
    """What `EXPLAIN` cannot see: a `TRY_CAST` that planned may still have
    raised, and a row that coerced may still have been routed the wrong way."""
    kept = cluster.execute(
        to_live('SELECT _source_row_id FROM silver."inventory_level" ORDER BY 1', quarantined)
    ).fetchall()

    assert [row[0] for row in kept] == ["r1"]


def test_each_uncastable_cell_is_quarantined_under_its_own_rule(
    cluster: psycopg.Connection, quarantined: str
) -> None:
    """The rule names come back in a delimited string rather than an array,
    because the port does not declare `DialectFeature.ARRAY` (S-0015/D-6) — so
    this is also where that decision's emitted shape is read back."""
    rejected = dict(
        cluster.execute(
            to_live(
                'SELECT _source_row_id, failed_rules FROM silver."inventory_level__reject"',
                quarantined,
            )
        ).fetchall()
    )

    assert isinstance(rejected["r2"], str), "failed_rules is not the delimited-string fallback"
    assert "stock_date_coercible" in rejected["r2"]
    assert "stock_level_coercible" in rejected["r3"]


def test_every_bronze_row_is_accounted_for(
    cluster: psycopg.Connection, quarantined: str
) -> None:
    """S-0033's conservation law on the engine itself: delivered plus
    quarantined equals ingested, with nothing dropped in between."""
    kept, rejected = (
        cluster.execute(to_live(f'SELECT COUNT(*) FROM silver."{name}"', quarantined)).fetchone()[0]
        for name in ("inventory_level", "inventory_level__reject")
    )

    assert kept + rejected == len(QUARANTINE_ROWS)
