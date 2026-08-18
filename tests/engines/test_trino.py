"""Engine tier (RFC 0009 §5.2 tier 5) on real Trino.

Trino was the engine bloomery made the most claims about and executed the
least. Three decisions were verified against it **by hand**, through
``docker exec``, because the repository carried no Trino client:

- D83 — the reject table's two constructions (``text_sha256``, ``json_object``)
  have Trino spellings, and its ``reject_id`` agrees with every other engine's;
- D86 — ``normalize`` and ``charset`` mean the same thing here as on DuckDB;
- D89 — a mart assertion's two body shapes both run.

A hand-verification is a claim with a date on it, not a test. This module is
those three, made permanent.

**Divergence from §5.2, recorded.** The tier is sketched there as
"trino+iceberg+minio (compose)". The memory connector is used instead: bloomery
emits SELECTs and models and never storage-format DDL, so an object store and a
table format would be three more moving parts serving no assertion here
(RFC 0009 D21).

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator

import pytest
from sqlglot import exp, parse_one

from bloomery.dialects import TrinoDialect
from bloomery.resolve.build import _try_cast_shape
from bloomery.transforms import DEFAULT_REGISTRY
import trino
from support.compiling import compile_fixture, extract_select
from testcontainers.community.trino import TrinoContainer

from bloomery.dialects import get_dialect
from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import violation

pytestmark = pytest.mark.engine("trino")

#: Pinned rather than ``latest``: an engine tier that silently changes engine
#: version is a tier that cannot tell a regression from an upgrade.
IMAGE = "trinodb/trino:483"

FIXTURE = "semi_additive_inventory"
ENTITY = "inventory_level"
SOURCE_RELATION = "wms__stock_levels"

_PORT = get_dialect("trino")

#: One clean row and one specimen per failure mode, mirroring the Postgres
#: tier so a disagreement between the two engines is legible as a diff.
ROWS = [
    ("w1", "2026-01-01", "5", "s1", "L1", "2026-01-01T00:00:00", "r1"),
    ("w2", "not-a-date", "7", "s2", "L1", "2026-01-01T00:00:00", "r2"),
    ("w3", "2026-01-02", "abc", "s3", "L1", "2026-01-01T00:00:00", "r3"),
    ("w5", "2026-01-03", "-5", "s5", "L1", "2026-01-01T00:00:00", "r5"),
]


def _canon(value: str) -> bytes:
    """The reject-table encoding, in Python: ``S<character length>:<value>``.

    Character length rather than utf-8 byte length — the deviation
    :mod:`bloomery.quality.reject` records, because no byte-length function is
    portable across the three shipped dialects.
    """
    return f"S{len(value)}:{value}".encode()


@pytest.fixture(scope="module")
def trino_db() -> Iterator[trino.dbapi.Connection]:
    with TrinoContainer(IMAGE) as container:
        connection = trino.dbapi.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8080)),
            user="bloomery",
            catalog="memory",
            schema="default",
        )
        for statement in (
            "CREATE SCHEMA IF NOT EXISTS memory.bronze",
            "CREATE SCHEMA IF NOT EXISTS memory.silver",
            f"CREATE TABLE memory.bronze.{SOURCE_RELATION} (warehouse varchar, day varchar, "
            "on_hand varchar, sku varchar, _load_id varchar, _ingested_at varchar, "
            "_source_row_id varchar)",
        ):
            _run(connection, statement)
        values = ", ".join(
            "(" + ", ".join(f"'{field}'" for field in row) + ")" for row in ROWS
        )
        _run(connection, f"INSERT INTO memory.bronze.{SOURCE_RELATION} VALUES {values}")
        artifacts = [
            artifact
            for artifact in compile_fixture(FIXTURE, dialect="trino")
            if artifact.path.startswith("models/silver/") and artifact.path.endswith(".sql")
        ]
        # The entity before its reject table: both read the same staged extract,
        # but ordering keeps a failure legible.
        for artifact in sorted(artifacts, key=lambda a: a.path.endswith("__reject.sql")):
            name = artifact.path.rsplit("/", 1)[-1].removesuffix(".sql")
            # Run-context macros have no meaning outside SQLMesh; what is under
            # test is the coercion and the routing, not the run window.
            body = re.sub(r"@[a-z_]+", "'2026-01-01'", extract_select(artifact.content))
            _run(connection, f'CREATE TABLE memory.silver."{name}" AS {body}')
        yield connection


def _run(connection: trino.dbapi.Connection, statement: str) -> list[list[object]]:
    cursor = connection.cursor()
    cursor.execute(statement)
    return cursor.fetchall()


# ....................... #
# D83 — the reject table, executed rather than rendered


def test_the_reject_model_materializes_at_all(trino_db: trino.dbapi.Connection) -> None:
    """D75 refused Trino a reject table outright: both constructions it is
    built from were ones Trino rejects, one unplannable and one unparseable.
    That the model creates is the whole of what D83 changed."""
    rows = _run(trino_db, f'SELECT COUNT(*) FROM memory.silver."{ENTITY}__reject"')
    assert rows[0][0] == 3  # r2, r3 and r5 divert; r1 is clean


def test_the_reject_id_agrees_with_the_python_encoder(
    trino_db: trino.dbapi.Connection,
) -> None:
    """The property ``reject_id`` actually needs is cross-engine *agreement*:
    the same source row must hash to the same identity wherever it is computed,
    or a replay run on one engine cannot find the row another quarantined.

    Asserted against the canon-bytes digest built here in Python, so this is a
    check on the *value* rather than on Trino agreeing with itself.
    """
    rows = _run(
        trino_db,
        f'SELECT _source_row_id, reject_id FROM memory.silver."{ENTITY}__reject" '
        "ORDER BY _source_row_id",
    )
    expected = {
        str(row_id): hashlib.sha256(_canon(SOURCE_RELATION) + _canon(str(row_id))).hexdigest()
        for row_id, _digest in rows
    }
    assert {str(row_id): digest for row_id, digest in rows} == expected


def test_both_json_payloads_are_readable_back(trino_db: trino.dbapi.Connection) -> None:
    """``raw`` is what replay re-runs the mapping against and ``key_values`` is
    what a human greps for, so a payload Trino writes but cannot read back
    would make the reject table a dead end rather than a recovery path.

    ``raw`` carries the bronze columns this entity's mapping **reads**, not
    every column of the source row — ``sku`` is in the table and not in the
    payload, which is ``quarantine.redact`` operating at the granularity D10
    pins it to.
    """
    raw, keys = _run(
        trino_db,
        "SELECT JSON_EXTRACT_SCALAR(raw, '$.day'), "
        "JSON_EXTRACT_SCALAR(key_values, '$.warehouse_id') "
        f'FROM memory.silver."{ENTITY}__reject" WHERE _source_row_id = \'r2\'',
    )[0]
    assert raw == "not-a-date"  # the value that failed, recoverable from the reject row
    assert keys == "w2"


def test_the_right_rows_are_kept_and_diverted(trino_db: trino.dbapi.Connection) -> None:
    """Rendering was never the hard part. The clean row survives; each specimen
    diverts on the rule that names its failure."""
    kept = _run(trino_db, f'SELECT _source_row_id FROM memory.silver."{ENTITY}" ORDER BY 1')
    assert [str(row[0]) for row in kept] == ["r1"]
    diverted = dict(
        (str(row_id), rules)
        for row_id, rules in _run(
            trino_db,
            f'SELECT _source_row_id, failed_rules FROM memory.silver."{ENTITY}__reject"',
        )
    )
    assert "stock_date_coercible" in diverted["r2"]
    assert "stock_level_coercible" in diverted["r3"]
    assert "stock_level_not_negative" in diverted["r5"]


def test_every_bronze_row_is_accounted_for(trino_db: trino.dbapi.Connection) -> None:
    """RFC 0016's conservation law on the engine D75 kept it off entirely."""
    kept = _run(trino_db, f'SELECT COUNT(*) FROM memory.silver."{ENTITY}"')[0][0]
    diverted = _run(trino_db, f'SELECT COUNT(*) FROM memory.silver."{ENTITY}__reject"')[0][0]
    assert kept + diverted == len(ROWS)


# ....................... #
# D86 — the two text rules
#
# Rendered through the **port**, never through sqlglot directly: the port is
# what emission uses, and a rewrite it performs is invisible to a direct render
# (the trap D86 records).

NFD_CAFE = "cafe\u0301"
NFC_CAFE = "caf\u00e9"
ZWSP_NAME = "Acme\u200bCorp"
CLEAN_NAME = "AcmeCorp"

#: ``(value, normalize fires, charset-forbid fires, charset-allow fires)``.
TEXT_ROWS: list[tuple[str | None, bool | None, bool | None, bool | None]] = [
    (NFD_CAFE, True, False, True),
    (NFC_CAFE, False, False, True),
    (ZWSP_NAME, False, True, True),
    (CLEAN_NAME, False, False, False),
    (None, None, None, None),
]


def _text_rule(kind: str, name: str, params: tuple[tuple[str, str], ...]) -> QualityRuleIR:
    return QualityRuleIR(
        name=name, kind=kind, column="name", on_fail=OnFail.FLAG, params=params
    )


@pytest.fixture(scope="module")
def text_table(trino_db: trino.dbapi.Connection) -> str:
    values = ", ".join(
        f"({index}, " + ("CAST(NULL AS varchar)" if row[0] is None else _unicode(row[0])) + ")"
        for index, row in enumerate(TEXT_ROWS)
    )
    _run(trino_db, f"CREATE TABLE memory.silver.names AS SELECT * FROM (VALUES {values}) AS t(ord, name)")
    return "memory.silver.names"


def _unicode(value: str) -> str:
    """A Trino ``U&'…'`` literal. Escapes, never the characters: a specimen
    that looks identical to its control in a diff cannot be reviewed."""
    body = "".join(character if character.isascii() else f"\\{ord(character):04x}" for character in value)
    return f"U&'{body}'"


def _verdicts(
    connection: trino.dbapi.Connection, table: str, rule: QualityRuleIR
) -> list[bool | None]:
    predicate = _PORT.render(violation(rule))
    rows = _run(connection, f"SELECT ord, ({predicate}) FROM {table} ORDER BY ord")
    return [fired for _ord, fired in rows]


def test_normalize_agrees_with_duckdb(
    trino_db: trino.dbapi.Connection, text_table: str
) -> None:
    """Trino spells all four normal forms and DuckDB spells one, which is why
    the rule admits only NFC. What matters here is that the one it admits means
    the same thing on both."""
    rule = _text_rule("normalize", "name_normalize", (("form", "nfc"),))
    assert _verdicts(trino_db, text_table, rule) == [row[1] for row in TEXT_ROWS]


def test_charset_deletes_rather_than_substitutes(
    trino_db: trino.dbapi.Connection, text_table: str
) -> None:
    """``TRANSLATE(x, members, '')`` removing a character when ``to`` is
    shorter is the whole construction; an engine that padded instead would make
    the predicate silently never fire."""
    forbid = _text_rule("charset", "name_charset", (("forbid_0000", "U+200B"),))
    allow = _text_rule("charset", "name_charset", (("allow_0000", "U+0020-U+007E"),))
    assert _verdicts(trino_db, text_table, forbid) == [row[2] for row in TEXT_ROWS]
    assert _verdicts(trino_db, text_table, allow) == [row[3] for row in TEXT_ROWS]


def test_both_rules_stay_silent_on_a_null(
    trino_db: trino.dbapi.Connection, text_table: str
) -> None:
    """D19 on the engine: NULL is neither a pass nor a violation, and a rule
    that fired on one would fire on every nullable column."""
    for rule in (
        _text_rule("normalize", "n", (("form", "nfc"),)),
        _text_rule("charset", "c", (("forbid_0000", "U+200B"),)),
    ):
        assert _verdicts(trino_db, text_table, rule)[-1] is None


# ....................... #
# D89 — a mart assertion's two body shapes


@pytest.fixture(scope="module")
def mart_table(trino_db: trino.dbapi.Connection) -> str:
    _run(
        trino_db,
        "CREATE TABLE memory.silver.mart_lines AS SELECT * FROM (VALUES "
        "(DATE '2026-01-01', DECIMAL '4.000000000'), "
        "(DATE '2026-01-01', DECIMAL '3.000000000'), "
        # February nets to zero: every row is real and the *total* is wrong,
        # which is the shape no per-row rule can see.
        "(DATE '2026-02-01', DECIMAL '5.000000000'), "
        "(DATE '2026-02-01', DECIMAL '-5.000000000')"
        ") AS t(ordered_month, amount)",
    )
    return "memory.silver.mart_lines"


def _assert_body(name: str, table: str) -> str:
    artifact = next(
        a
        for a in compile_fixture("quality_precedence", dialect="trino")
        if a.path == f"audits/{name}.sql"
    )
    return artifact.content.partition(");")[2].strip().replace("@this_model", table)


def test_the_grouped_assertion_reports_only_the_offending_group(
    trino_db: trino.dbapi.Connection, mart_table: str
) -> None:
    """The ``GROUP BY … HAVING`` shape, on the engine. An audit passes when it
    returns no rows, so the rows it returns are the report."""
    rows = _run(trino_db, _assert_body("lines_amount_positive_every_month", mart_table))
    assert [str(row[0]) for row in rows] == ["2026-02-01"]


def test_the_whole_mart_assertion_needs_no_grouping(
    trino_db: trino.dbapi.Connection, mart_table: str
) -> None:
    """A bare ``HAVING`` with no ``GROUP BY`` is the empty-``by`` form. Legal
    on all three shipped dialects — now asserted on each rather than read out
    of three manuals."""
    assert _run(trino_db, _assert_body("lines_rows_present", mart_table)) == []


def test_an_empty_mart_is_where_the_two_aggregates_part_company(
    trino_db: trino.dbapi.Connection
) -> None:
    """D19 reaching the mart, on Trino: ``SUM`` over an empty group is NULL so
    the comparison is ``UNKNOWN`` and the assertion stays silent, while
    ``COUNT`` answers 0 and fires. That difference is why an assertion cannot
    see a period that is missing altogether unless it counts."""
    _run(
        trino_db,
        "CREATE TABLE memory.silver.mart_empty AS SELECT * FROM (VALUES "
        "(DATE '2026-01-01', DECIMAL '1.000000000')) AS t(ordered_month, amount) WHERE false",
    )
    empty = "memory.silver.mart_empty"
    assert _run(trino_db, _assert_body("lines_amount_positive_every_month", empty)) == []
    assert _run(trino_db, _assert_body("lines_rows_present", empty)) == [[0]]


# ....................... #
# RFC 0027 — the ISO 8601 separator, executed rather than rendered


@pytest.mark.parametrize(
    ("spelling", "cast_to"),
    [
        ("2026-01-06T12:00:00", "TIMESTAMP"),
        ("2026-01-06 12:00:00", "TIMESTAMP"),
        ("2026-01-06", "DATE"),
    ],
)
def test_an_iso_parse_survives_both_separators(
    trino_db: trino.dbapi.Connection, spelling: str, cast_to: str
) -> None:
    """What `{parse_ts: ISO8601}` and `{parse_date: ISO8601}` emit here, run.

    This is the test RFC 0027 §6 asked for, and it is at this tier rather than
    a rendering assertion because the rendering was never what was wrong:
    `CAST(x AS TIMESTAMP)` is valid Trino, it just returns NULL for the `T`
    separator that ISO 8601 defines — and inside the quality system a NULL
    where the source was not null *is* a coercion failure, so every row of a
    source landed in the reject table while the data was fine.

    Both spellings for the timestamp parse — the `T` row is the regression,
    the space row is here so a rewrite that broke the ordinary case could not
    pass — and the date parse, which is unmarked and must stay that way.
    """
    node = DEFAULT_REGISTRY["parse_ts" if cast_to == "TIMESTAMP" else "parse_date"].builder(
        exp.Literal.string(spelling), "ISO8601"
    )
    rendered = TrinoDialect().render(parse_one(node.sql()))
    assert _run(trino_db, f"SELECT {rendered}")[0][0] is not None


def test_the_marker_still_marks_a_genuine_coercion_failure(
    trino_db: trino.dbapi.Connection,
) -> None:
    """The separator rewrite must not swallow real bad data.

    `REPLACE` accepts anything, so the guard against over-repair is that the
    cast still refuses a value that is not a timestamp at all — which is what
    keeps the `coercible` rule meaningful rather than always-clean.
    """
    node = DEFAULT_REGISTRY["parse_ts"].builder(exp.Literal.string("last tuesday"), "ISO8601")
    shaped = parse_one(_try_cast_shape(node).sql())
    assert _run(trino_db, f"SELECT {TrinoDialect().render(shaped)}")[0][0] is None
