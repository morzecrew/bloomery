"""The dedupe total order (RFC 0016 §5.4, D20) and the reject identity (§5.6,
D21).

Dedupe is asserted at the **AST** level for null ordering, not on rendered
text: SQLGlot's DuckDB generator omits ``NULLS LAST`` because it is that
engine's default, so a string match would pass on Postgres and silently stop
checking anything on DuckDB. The property D20 states is that every sort key
carries ``DESC NULLS LAST``, and that is a property of the node.
"""

from __future__ import annotations

import hashlib

import duckdb
import pytest
from sqlglot import exp

from bloomery.ir import DedupeIR
from bloomery.quality import (
    REJECT_COLUMNS,
    ROW_ID_COLUMN,
    canon_literal,
    dedupe_order,
    dedupe_row_number,
    dedupe_sort_columns,
    reject_id,
    with_dedupe_qualify,
)

pytestmark = pytest.mark.unit

DEDUPE = DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id", "_batch"))
KEY = ("warehouse_id", "stock_date")


# ....................... #
# The total order (D20)


def test_the_sort_order_ends_at_the_stable_row_identity() -> None:
    """After ``field`` and the tie-breaks, ``_source_row_id`` makes the winner
    unique by construction — no two rows can compare equal."""
    assert dedupe_sort_columns(DEDUPE) == (
        "_ingested_at",
        "_load_id",
        "_batch",
        ROW_ID_COLUMN,
    )


def test_tie_break_keeps_authored_order() -> None:
    """A sort order is semantic (RFC 0003 D4) — sorting it would change which
    row wins."""
    reversed_break = DedupeIR(keep="latest_by", field="ts", tie_break=("z", "a"))
    assert dedupe_sort_columns(reversed_break) == ("ts", "z", "a", ROW_ID_COLUMN)


def test_every_sort_key_is_desc_nulls_last() -> None:
    """D20 pins null ordering on **every** key, ``_source_row_id`` included:
    ``DESC`` defaults to ``NULLS FIRST`` on several engines, so an illegally
    null identity must still lose, never win."""
    terms = dedupe_order(DEDUPE)
    assert len(terms) == len(dedupe_sort_columns(DEDUPE))
    for term in terms:
        assert term.args["desc"] is True
        assert term.args["nulls_first"] is False


def test_generators_elide_nulls_last_only_where_it_is_the_engine_default() -> None:
    """The AST carries ``NULLS LAST`` on every key (asserted above); a
    generator may drop it where the engine already orders that way — DuckDB
    defaults to ``NULLS LAST`` in both directions, Postgres does not and so
    spells it out. Asserting on rendered text alone would therefore check
    nothing on DuckDB, which is why the invariant lives on the node."""
    node = dedupe_row_number(DEDUPE, KEY)
    assert "NULLS LAST" not in node.sql(dialect="duckdb")
    assert node.sql(dialect="postgres").count("NULLS LAST") == len(dedupe_sort_columns(DEDUPE))


def test_partition_is_the_entity_key() -> None:
    node = dedupe_row_number(DEDUPE, KEY)
    partition = [column.name for column in node.args["partition_by"]]
    assert partition == list(KEY)


def test_qualify_renders_natively_on_duckdb_and_as_a_subquery_elsewhere() -> None:
    """One neutral AST, per-dialect legal rendering — §5.4's note and the
    RFC 0008 doctrine, not a second template."""
    select = exp.Select().select(exp.column("a")).from_(exp.table_("t"))
    qualified = with_dedupe_qualify(select, DEDUPE, KEY)
    assert "QUALIFY" in qualified.sql(dialect="duckdb")
    postgres = qualified.sql(dialect="postgres")
    assert "QUALIFY" not in postgres
    assert "ROW_NUMBER() OVER" in postgres
    assert "NULLS LAST" in postgres


def test_qualify_does_not_mutate_its_input() -> None:
    select = exp.Select().select(exp.column("a")).from_(exp.table_("t"))
    before = select.sql()
    with_dedupe_qualify(select, DEDUPE, KEY)
    assert select.sql() == before


def test_the_winner_is_row_number_one() -> None:
    select = exp.Select().select(exp.column("a")).from_(exp.table_("t"))
    qualify = with_dedupe_qualify(select, DEDUPE, KEY).args["qualify"]
    assert isinstance(qualify.this, exp.EQ)
    assert qualify.this.expression.this == "1"


# ....................... #
# reject_id (D21)


def test_reject_id_is_sha256_over_the_length_prefixed_pair() -> None:
    """The value is recomputable from the reject row itself, so the test
    recomputes it in Python and compares against what the SQL produces."""
    relation, row_id = "wms__stock_levels", "row-42"
    node = reject_id(relation, exp.column("_source_row_id"))
    sql = f"SELECT {node.sql(dialect='duckdb')} FROM (SELECT ? AS _source_row_id)"
    with duckdb.connect(":memory:") as connection:
        emitted = connection.execute(sql, [row_id]).fetchone()
    assert emitted is not None
    expected = hashlib.sha256(
        f"{canon_literal(relation)}{canon_literal(row_id)}".encode()
    ).hexdigest()
    assert emitted[0] == expected


def test_reject_id_is_stable_across_calls_and_dialects() -> None:
    node = reject_id("rel", exp.column(ROW_ID_COLUMN))
    again = reject_id("rel", exp.column(ROW_ID_COLUMN))
    assert node.sql() == again.sql()
    for dialect in ("duckdb", "postgres", "trino"):
        assert "SHA256" in node.sql(dialect=dialect)


def test_length_prefixing_makes_the_pair_injective() -> None:
    """``('ab', 'c')`` and ``('a', 'bc')`` must not collide — the property the
    length prefix buys."""
    assert canon_literal("ab") + canon_literal("c") != canon_literal("a") + canon_literal("bc")


def test_load_id_is_not_part_of_the_identity() -> None:
    """D21: re-deliveries of the same source row across loads land on the
    **same** reject row; a per-load identity would violate replay idempotence."""
    node = reject_id("rel", exp.column(ROW_ID_COLUMN))
    assert "_load_id" not in node.sql()
    assert "_load_id" in REJECT_COLUMNS  # still carried, as an attribute


def test_the_reject_schema_matches_the_rfc() -> None:
    assert REJECT_COLUMNS == (
        "reject_id",
        "source_relation",
        "mapping",
        "mapping_version",
        "failed_rules",
        "key_values",
        "raw",
        "_load_id",
        "_ingested_at",
        "_source_row_id",
        "first_seen",
        "last_seen",
        "resolved_at",
    )
