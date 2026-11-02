"""`regex_extract` where the pattern does not match, executed on DuckDB (#392,
S-0025/D-24).

DuckDB's `regexp_extract` answers `''` there, and PostgreSQL and Trino answer
NULL. The mappings below are the reporter's: an amoCRM deal's outcome and won
flag, which fall back through `coalesce` when the status is neither 142 nor
143, and a МойСклад reference read off a URL that a document without a
customer does not carry. On `''` the outcome was `''`, the flag was NULL rather
than 0, and the missing customer was a customer called `''`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import duckdb
import pytest
from sqlglot import exp
from support.compiling import FIXTURES, fixture_sources
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.dialects import DuckDBDialect
from bloomery.dialects.duckdb import _unshadowing
from bloomery.ir import canon
from bloomery.transforms import DEFAULT_REGISTRY

pytestmark = pytest.mark.execution

FIXTURE = "semi_additive_inventory"

_CUSTOMER = "3f2b8c1e-0d4a-4b6e-9a7c-5e1f2d3c4b5a"


def _replaced(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"the fixture no longer reads {old!r}"
    return text.replace(old, new)


def _sources() -> dict[str, str]:
    sources = fixture_sources(FIXTURE)
    sources["entity_model"] = _replaced(
        sources["entity_model"],
        "      stock_level: {type: int, canonical: stock_level}\n",
        "      stock_level: {type: int, canonical: stock_level}\n"
        "      outcome: {type: string}\n"
        "      won: {type: int}\n"
        "      customer_id: {type: string}\n",
    )
    sources["mapping"] = _replaced(
        sources["mapping"],
        "fields:\n",
        "fields:\n"
        "  outcome:\n"
        '    from: "$.status"\n'
        '    transform: [{regex_extract: ["^(14[23])$", 1]}, '
        '{enum_map: ["142", won, "143", lost]}, {coalesce: open}]\n'
        "  won:\n"
        '    from: "$.status"\n'
        '    transform: [{regex_extract: ["^(142)$", 1]}, '
        '{enum_map: ["142", "1"]}, {coalesce: "0"}, to_int]\n'
        "  customer_id:\n"
        '    from: "$.customer_href"\n'
        '    transform: [{regex_extract: ["([0-9a-f-]{36})$", 1]}]\n',
    )
    return sources


@pytest.fixture(scope="module")
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text(encoding="utf-8"))
    artifacts = compile_project(
        load_project(_sources()), target=Target.SQLMESH, dialect="duckdb", catalog=catalog
    )
    connection = warehouse("bronze", "silver", "gold")
    connection.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, "
        "on_hand VARCHAR, status VARCHAR, _load_id VARCHAR, _ingested_at VARCHAR, "
        "_source_row_id VARCHAR, operator_note VARCHAR, customer_href VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, '2026-01-01', '5', ?, 'L1', "
        "'2026-01-01 00:00:00', ?, NULL, ?)",
        [
            ("w1", "142", "r1", f"https://api.moysklad.ru/entity/counterparty/{_CUSTOMER}"),
            ("w2", "143", "r2", "https://api.moysklad.ru/entity/counterparty/"),
            ("w3", "12345", "r3", None),
        ],
    )
    materialize(connection, artifacts)
    yield connection
    connection.close()


def test_a_status_the_pattern_does_not_match_falls_back(conn: duckdb.DuckDBPyConnection) -> None:
    rows = conn.execute(
        "SELECT _source_row_id, outcome, won FROM silver.inventory_level ORDER BY 1"
    ).fetchall()

    assert rows == [("r1", "won", 1), ("r2", "lost", 0), ("r3", "open", 0)]


def test_a_reference_the_document_does_not_carry_is_null(conn: duckdb.DuckDBPyConnection) -> None:
    rows = conn.execute(
        "SELECT _source_row_id, customer_id FROM silver.inventory_level ORDER BY 1"
    ).fetchall()

    assert rows == [("r1", _CUSTOMER), ("r2", None), ("r3", None)]


def _extracted(node: exp.Expression, value: str) -> object:
    sql = DuckDBDialect().render(node)
    (cell,) = duckdb.connect().execute(f"SELECT {sql} FROM (SELECT ?::VARCHAR AS s)", [value]).fetchone()
    return cell


def test_an_empty_capture_stays_empty() -> None:
    """`^(a*)` matches `b` and captures the empty text, which is `''` on
    PostgreSQL and Trino too, so `NULLIF(…, '')` is not the fix."""
    extract = DEFAULT_REGISTRY["regex_extract"].builder

    assert _extracted(canon(extract(exp.column("s"), "^(a*)", 1)).ast(), "b") == ""


def test_a_group_that_takes_no_part_in_the_match_is_null() -> None:
    """`(a)|b` matches `b` through its other branch, so group 1 is unset: NULL
    on PostgreSQL and Trino, and `''` from DuckDB's own `regexp_extract`."""
    extract = DEFAULT_REGISTRY["regex_extract"].builder

    assert _extracted(canon(extract(exp.column("s"), "(a)|b", 1)).ast(), "b") is None


def test_the_extract_s_flags_reach_the_rewrite() -> None:
    """A hand-built extract may carry flags, and the rewrite keeps them: `a`
    under `i` matches `A`."""
    extract = exp.RegexpExtract(
        this=exp.column("s"),
        expression=exp.Literal.string("a"),
        group=exp.Literal.number(0),
        parameters=exp.Literal.string("i"),
    )

    assert _extracted(extract, "A") == "A"


def test_an_extract_of_an_extract_is_guarded_at_both_steps() -> None:
    """The inner step's non-match has to reach the outer one as NULL: the
    outer pattern matches the empty text, so an unguarded inner `''` would come
    out as `''`."""
    extract = DEFAULT_REGISTRY["regex_extract"].builder
    chain = canon(extract(extract(exp.column("s"), "id=([0-9]+)", 1), "^([0-9]*)", 1)).ast()

    assert _extracted(chain, "id=1234") == "1234"
    assert _extracted(chain, "x") is None


def test_an_extract_in_the_pattern_is_guarded_too() -> None:
    """A hand-built extract may take its pattern from another. Unguarded, the
    inner non-match is the empty pattern, which matches anything."""
    inner = exp.RegexpExtract(
        this=exp.column("s"), expression=exp.Literal.string("p=(.+)"), group=exp.Literal.number(1)
    )
    outer = exp.RegexpExtract(this=exp.column("s"), expression=inner, group=exp.Literal.number(0))

    assert _extracted(outer, "x") is None


def test_a_chain_names_its_subject_once() -> None:
    """The subject is bound once per extract, so a chain's SQL grows linearly.
    A spelling that names it twice doubles at every step: `2 ** 3` copies of
    `s` for three extracts."""
    extract = DEFAULT_REGISTRY["regex_extract"].builder
    chain = exp.column("s")
    for pattern in ("a(.*)", "b(.*)", "c(.*)"):
        chain = extract(chain, pattern, 1)

    assert re.findall(r"\bs\b", DuckDBDialect().render(canon(chain).ast())) == ["s"]


def test_a_name_taken_in_any_case_is_passed_over() -> None:
    """DuckDB documents unquoted identifiers as case-insensitive, so the
    parameter avoids `__SUBJECT` as well. DuckDB 1.5.6 binds that spelling to
    the column ahead of the parameter, so only the name chosen can show it."""
    assert _unshadowing([exp.column("__SUBJECT"), exp.column("__subject_1")]) == "__subject_2"


def test_the_binding_never_shadows_a_column_an_argument_reads() -> None:
    """A hand-built extract may read its pattern from a column. A parameter
    named like that column would read the subject, `cab`, as the pattern."""
    extract = exp.RegexpExtract(
        this=exp.column("s"), expression=exp.column("__subject"), group=exp.Literal.number(0)
    )
    sql = DuckDBDialect().render(extract)
    (cell,) = duckdb.connect().execute(f"SELECT {sql} FROM (SELECT 'cab' AS s, 'a' AS __subject)").fetchone()

    assert cell == "a"
