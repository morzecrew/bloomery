"""Engine tier (RFC 0009 §5.2 tier 5): a **cleaned merged entity** built and
queried on real PostgreSQL and real Trino (RFC 0024 P2, RFC 0035).

The DuckDB tier proves the pipeline computes the right rows. This proves the
same SQL is legal and means the same thing on the two engines a project would
actually deploy to, and three constructs in it are engine-sensitive in ways no
golden can catch:

**The dedupe ``QUALIFY`` over a ``UNION ALL``.** Postgres has no ``QUALIFY`` at
all — the dialect port rewrites it — and the rewrite now has to happen over a
union subquery rather than a plain SELECT.

**``reject_id``'s digest.** DuckDB's ``SHA256(VARCHAR)`` returns hex, Postgres'
returns ``bytea``, and Trino's does not accept text at all (RFC 0016 D83). A
merged entity is the first shape where two branches compute it, and the whole
point of the pair ``(source_relation, _source_row_id)`` is that the engines
agree on which rows are distinct.

**The metadata audit's ``PARTITION BY _source, _source_row_id``** (RFC 0024
D34), which is what keeps a blocking audit from refusing correct data the first
time two shops with ordinary per-table row sequences are merged.

One table of expectations, asserted on both engines, so a disagreement shows up
as a value rather than as an absence.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import PurePosixPath

import psycopg
import pytest
import trino
from support.compiling import compile_fixture, expand_engine_macros, extract_select

from bloomery.emit import ArtifactKind
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.trino import TrinoContainer

FIXTURE = "multi_source_quality"

#: Pinned for the reason :mod:`tests.engines.test_trino` gives: a tier that
#: silently changes engine version cannot tell a regression from an upgrade.
TRINO_IMAGE = "trinodb/trino:483"
POSTGRES_IMAGE = "postgres:16-alpine"

#: ``(order, position, sku, quantity, created_at, financial_status, row_id)``.
#: The DuckDB tier's seed, unchanged, because a different seed would make a
#: disagreement between engines unreadable.
SHOPIFY = [
    ("A-1", "1", "SKU-1", "2", "2024-03-01T00:00:00", "paid", "s1"),
    ("A-2", "1", "SKU-2", "1", "2024-03-02T00:00:00", "reversed", "s2"),
    ("A-3", "1", "SKU-3", "1", "2024-03-03T00:00:00", "unheard_of", "s3"),
]

#: ``(order_number, item_index, product_sku, qty, created, state, row_id)``.
#: ``w2``'s quantity is uncastable on *Woo's* path; ``w3`` carries the raw value
#: only Shopify's chain maps. Note ``w1`` shares ``s1``'s row identity — that
#: collision is legal under RFC 0016 D21 and is exactly what D34's partition and
#: ``reject_id``'s pair exist for.
WOO = [
    ("B-1", "1", "SKU-9", "4", "2024-03-01T00:00:00", "COMPLETE", "s1"),
    ("B-2", "1", "SKU-8", "twelve", "2024-03-02T00:00:00", "COMPLETE", "w2"),
    ("B-3", "1", "SKU-7", "1", "2024-03-03T00:00:00", "reversed", "w3"),
]

#: ``(id, query, expected rows)`` — asserted on every engine. The queries read
#: the *materialized* relations, so what they are really asserting is that the
#: emitted SQL ran at all and put the rows where the DuckDB tier says.
CASES: list[tuple[str, str, list[tuple[object, ...]]]] = [
    (
        # One rule over the union, each branch comparing against its own path.
        "coercible-reads-its-own-path",
        "SELECT _source_row_id, source_relation FROM silver.order_line__reject "
        "WHERE {failed:quantity_coercible} ORDER BY _source_row_id",
        [("w2", "woo__order_lines")],
    ),
    (
        # `reversed` is admissible on one branch and not on the other, on the
        # same raw text (RFC 0024 D32).
        "in-enum-admits-per-branch",
        "SELECT _source_row_id FROM silver.order_line__reject "
        "WHERE {failed:status_in_enum} ORDER BY _source_row_id",
        [("s3",), ("w3",)],
    ),
    (
        # …and the row the other branch's chain does map is in the entity.
        "the-admitted-row-is-in-the-entity",
        "SELECT status FROM silver.order_line WHERE _source_row_id = 's2' "
        "AND _source = 'shopify__order_lines'",
        [("reversed",)],
    ),
    (
        # Provenance per branch (RFC 0035 D2), on a reject table that stays one
        # per entity (RFC 0016 D10, upheld by RFC 0035 D1).
        "reject-rows-name-their-own-mapping",
        "SELECT _source_row_id, source_relation, mapping_version "
        "FROM silver.order_line__reject ORDER BY _source_row_id, source_relation",
        [
            ("s3", "shopify__order_lines", 1),
            ("w2", "woo__order_lines", 1),
            ("w3", "woo__order_lines", 1),
        ],
    ),
    (
        # `reject_id` is a digest of the *pair*: `s1` is a row identity both
        # shops used, and neither row is in the reject table — but the property
        # the pair exists for is that ids stay distinct, which the count checks
        # over whatever rows are there.
        "reject-ids-are-distinct",
        "SELECT COUNT(*) - COUNT(DISTINCT reject_id) FROM silver.order_line__reject",
        [(0,)],
    ),
    (
        # §6's conservation law over a bag of two branches.
        "every-row-lands-on-one-side",
        "SELECT (SELECT COUNT(*) FROM silver.order_line) "
        "+ (SELECT COUNT(*) FROM silver.order_line__reject)",
        [(6,)],
    ),
]

#: The audits, run as **bloomery emitted them** — body and all, with
#: ``@this_model`` resolved. Asserted separately from :data:`CASES` because they
#: are the one class of artifact whose text a hand-written query cannot stand in
#: for: an audit is a claim about what stops the run, and a test that rewrote
#: the claim would pass while the emitted body was wrong. The metadata audit was
#: exactly that for one commit — the lowering partitioned by
#: ``(_source, _source_row_id)`` (RFC 0024 D34) and the SQLMesh envelope emitted
#: a hardcoded ``PARTITION BY _source_row_id``, on the only target that supports
#: quarantine.
AUDIT_CASES: list[tuple[str, str, int]] = [
    # Blocking, and it must be **silent** here, for two separate reasons that
    # both used to break it:
    #
    #   * `s1` is one row identity in two source relations, which RFC 0016 D21
    #     makes legal — an audit partitioned by the identity alone reports it;
    #   * every row's `_ingested_at` is ISO 8601 with a `T`, and Trino's cast
    #     does not accept that separator, so an *unmarked* `TRY_CAST` reads
    #     every row as an uncastable timestamp (RFC 0027's marker is what makes
    #     the question the same question on every engine).
    #
    # The seed writes the `T` deliberately: it is the spelling a real bronze
    # layer ships, and the one that was broken.
    ("ingestion-metadata", "order_line_ingestion_metadata", 0),
    # Blocking, and silent: no key is held by both shops in this seed.
    ("source-collision", "order_line_source_collision", 0),
    # The accounting law, on every production run.
    ("conservation", "order_line_conservation", 0),
]

IDS = [case[0] for case in CASES]

#: ``failed_rules`` is a real array on both engines (RFC 0016 D23 — the flag
#: collection is an array where the dialect has one), and the two spell
#: membership differently. One expectations table, one placeholder, rather than
#: two copies of every case: the claim under test is that the engines *agree*,
#: and a claim about agreement written twice can drift.
MEMBERSHIP = {
    "postgres": "'{rule}' = ANY(failed_rules)",
    "trino": "contains(failed_rules, '{rule}')",
}


def _bind(sql: str, dialect: str) -> str:
    """Resolve the ``{failed:<rule>}`` placeholders for one engine."""
    for rule in ("quantity_coercible", "status_in_enum"):
        sql = sql.replace(f"{{failed:{rule}}}", MEMBERSHIP[dialect].format(rule=rule))
    return sql


def check(run: Callable[[str], list[tuple[object, ...]]], case_index: int, engine: str) -> None:
    """One case, executed on one engine, against the shared expectations."""

    _label, sql, expected = CASES[case_index]
    rows = [tuple(row) for row in run(_bind(sql, engine))]
    normalized = [tuple(int(v) if isinstance(v, (int, float)) else v for v in row) for row in rows]
    assert normalized == expected, f"{engine}: {normalized} != {expected}"


def _ordered(dialect: str) -> list[tuple[str, str, str]]:
    """``(namespace, relation, select)`` for every model, silver before gold —
    the engine's scheduler stood in for, exactly as the DuckDB tier's
    :func:`support.execution.materialize` stands in for it there."""

    # `ArtifactKind.MODEL`, not "every `.sql`": audits and the replay artifact
    # are `.sql` too and are neither relations nor runnable here — an audit
    # reads `@this_model` and replay is a MERGE. They have their own assertions
    # below, run as emitted.
    models = [
        artifact
        for artifact in compile_fixture(FIXTURE, dialect=dialect)
        if artifact.kind is ArtifactKind.MODEL and artifact.path.endswith(".sql")
    ]
    return [
        (
            PurePosixPath(artifact.path).parent.name,
            PurePosixPath(artifact.path).stem,
            extract_select(artifact.content),
        )
        for artifact in sorted(
            models, key=lambda a: PurePosixPath(a.path).parent.name != "silver"
        )
    ]


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
        # Autocommit: a case whose SQL is refused would otherwise abort the
        # transaction and every later case would report
        # `InFailedSqlTransaction` instead of its own result — one failure
        # wearing thirteen names.
        connection.autocommit = True
        connection.execute("SET TIME ZONE 'UTC'")
        for schema in ("bronze", "silver", "gold"):
            connection.execute(f"CREATE SCHEMA {schema}")
        connection.execute(
            'CREATE TABLE bronze.shopify__order_lines ("order" JSONB, position TEXT, '
            "variant JSONB, quantity TEXT, properties JSONB, created_at TEXT, "
            "financial_status TEXT, _load_id TEXT, _ingested_at TEXT, _source_row_id TEXT)"
        )
        connection.execute(
            "CREATE TABLE bronze.woo__order_lines (order_number TEXT, item_index TEXT, "
            "product_sku TEXT, qty TEXT, created TEXT, state TEXT, _load_id TEXT, "
            "_ingested_at TEXT, _source_row_id TEXT)"
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO bronze.shopify__order_lines VALUES "
                "(jsonb_build_object('id', %s::text), %s, jsonb_build_object('sku', %s::text), "
                "%s, jsonb_build_object('gift_note', NULL), %s, %s, 'load-1', "
                "'2024-03-10T00:00:00', %s)",
                SHOPIFY,
            )
            cursor.executemany(
                "INSERT INTO bronze.woo__order_lines VALUES "
                "(%s, %s, %s, %s, %s, %s, 'load-1', '2024-03-10T00:00:00', %s)",
                WOO,
            )
        for namespace, relation, select in _ordered("postgres"):
            connection.execute(f'CREATE TABLE {namespace}."{relation}" AS {select}')

        def run(sql: str) -> list[tuple[object, ...]]:
            return list(connection.execute(sql).fetchall())

        yield run
        connection.close()


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("case_index", range(len(CASES)), ids=IDS)
def test_the_cleaned_merge_runs_on_postgres(
    postgres: Callable[[str], list[tuple[object, ...]]], case_index: int
) -> None:
    check(postgres, case_index, "postgres")


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

        for schema in ("bronze", "silver", "gold"):
            run(f"CREATE SCHEMA IF NOT EXISTS memory.{schema}")
        run(
            'CREATE TABLE memory.bronze.shopify__order_lines ("order" varchar, '
            "position varchar, variant varchar, quantity varchar, properties varchar, "
            "created_at varchar, financial_status varchar, _load_id varchar, "
            "_ingested_at varchar, _source_row_id varchar)"
        )
        run(
            "CREATE TABLE memory.bronze.woo__order_lines (order_number varchar, "
            "item_index varchar, product_sku varchar, qty varchar, created varchar, "
            "state varchar, _load_id varchar, _ingested_at varchar, _source_row_id varchar)"
        )
        run(
            "INSERT INTO memory.bronze.shopify__order_lines VALUES "
            + ", ".join(
                f"('{{\"id\":\"{order}\"}}', '{position}', '{{\"sku\":\"{sku}\"}}', "
                f"'{quantity}', '{{\"gift_note\":null}}', '{created}', '{status}', 'load-1', "
                f"'2024-03-10T00:00:00', '{row_id}')"
                for order, position, sku, quantity, created, status, row_id in SHOPIFY
            )
        )
        run(
            "INSERT INTO memory.bronze.woo__order_lines VALUES "
            + ", ".join(
                "(" + ", ".join(f"'{value}'" for value in row[:6])
                + ", 'load-1', '2024-03-10T00:00:00', "
                + f"'{row[6]}')"
                for row in WOO
            )
        )
        for namespace, relation, select in _ordered("trino"):
            run(f'CREATE TABLE memory.{namespace}."{relation}" AS {select}')

        yield run


@pytest.mark.engine("trino")
@pytest.mark.parametrize("case_index", range(len(CASES)), ids=IDS)
def test_the_cleaned_merge_runs_on_trino(
    trino_engine: Callable[[str], list[tuple[object, ...]]], case_index: int
) -> None:
    check(lambda sql: trino_engine(sql.replace("silver.", "memory.silver.")), case_index, "trino")


def _audit_body(name: str, dialect: str, relation: str) -> str:
    """One emitted audit, ready to run: its SELECT with ``@this_model`` bound.

    ``@this_model`` is SQLMesh's macro for the audited relation and this tier
    has no SQLMesh — the same substitution
    :func:`support.compiling.expand_engine_macros` makes everywhere else, for
    the same reason.
    """
    artifact = next(
        a
        for a in compile_fixture(FIXTURE, dialect=dialect)
        if a.path == f"audits/{name}.sql"
    )
    body = artifact.content[artifact.content.index(");") + 2 :]
    return expand_engine_macros(body.replace("@this_model", relation)).strip()


def check_audit(
    run: Callable[[str], list[tuple[object, ...]]], case_index: int, dialect: str, relation: str
) -> None:
    """One emitted audit, executed, against the row count it must report."""
    _label, name, expected = AUDIT_CASES[case_index]
    rows = run(f"SELECT COUNT(*) FROM ({_audit_body(name, dialect, relation)}) AS _violations")
    assert int(rows[0][0]) == expected, f"{dialect} {name}: {rows[0][0]} violation(s), not {expected}"


@pytest.mark.engine("postgres")
@pytest.mark.parametrize("case_index", range(len(AUDIT_CASES)), ids=[c[0] for c in AUDIT_CASES])
def test_the_emitted_audits_are_silent_on_postgres(
    postgres: Callable[[str], list[tuple[object, ...]]], case_index: int
) -> None:
    check_audit(postgres, case_index, "postgres", "silver.order_line")


@pytest.mark.engine("trino")
@pytest.mark.parametrize("case_index", range(len(AUDIT_CASES)), ids=[c[0] for c in AUDIT_CASES])
def test_the_emitted_audits_are_silent_on_trino(
    trino_engine: Callable[[str], list[tuple[object, ...]]], case_index: int
) -> None:
    # No blanket rewrite here: :func:`_audit_body` is handed the qualified
    # relation, so the body already reads `memory.silver.…` and replacing again
    # produces `memory.memory.silver.…`.
    check_audit(trino_engine, case_index, "trino", "memory.silver.order_line")
