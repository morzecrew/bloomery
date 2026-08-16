"""Execution tier for the union merge (RFC 0024 §6): the ``multi_source``
fixture round-tripping through DuckDB, and the collision audit verified **red**
on data whose key sets overlap.

The red case is the one that matters. A union whose collision audit silently
passes is worse than no union at all — the merge's whole correctness claim is
that the sources' key sets are disjoint, and this audit is the only thing that
establishes it, since compilation has no data (§5.4).
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest

from support.compiling import compile_fixture
from support.execution import audit_body, materialize, warehouse

from bloomery.emit import ArtifactKind, EmittedArtifact

pytestmark = pytest.mark.execution

_SHOPIFY = (
    "CREATE TABLE bronze.shopify__order_lines ("
    '  "order" JSON, position INTEGER, variant JSON, quantity INTEGER, properties JSON'
    ")"
)
_WOO = (
    "CREATE TABLE bronze.woo__order_lines ("
    "  order_number VARCHAR, item_index INTEGER, product_sku VARCHAR, qty INTEGER"
    ")"
)


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    connection.execute(_SHOPIFY)
    connection.execute(_WOO)
    yield connection
    connection.close()


def _seed_shopify(conn: duckdb.DuckDBPyConnection, rows: list[tuple[object, ...]]) -> None:
    conn.executemany(
        "INSERT INTO bronze.shopify__order_lines VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def _seed_woo(conn: duckdb.DuckDBPyConnection, rows: list[tuple[object, ...]]) -> None:
    conn.executemany("INSERT INTO bronze.woo__order_lines VALUES (?, ?, ?, ?)", rows)


def _collision_audit(artifacts: tuple[EmittedArtifact, ...]) -> EmittedArtifact:
    return next(
        artifact
        for artifact in artifacts
        if artifact.kind is ArtifactKind.AUDIT and artifact.path.endswith("_source_collision.sql")
    )


def test_both_shops_land_in_one_entity(conn: duckdb.DuckDBPyConnection) -> None:
    """Disjoint key sets — the shape the merge is for."""
    _seed_shopify(
        conn,
        [
            ('{"id": "S1"}', 1, '{"sku": "ABC"}', 2, '{"gift_note": "happy birthday"}'),
            ('{"id": "S1"}', 2, '{"sku": "DEF"}', 1, "{}"),
        ],
    )
    _seed_woo(conn, [("W7", 1, "GHI", 5)])
    materialize(conn, compile_fixture("multi_source"))
    rows = conn.execute(
        "SELECT order_id, line_no, sku, quantity, gift_note, _source "
        "FROM silver.order_line ORDER BY order_id, line_no"
    ).fetchall()
    assert rows == [
        ("S1", 1, "ABC", 2, "happy birthday", "shopify__order_lines"),
        ("S1", 2, "DEF", 1, None, "shopify__order_lines"),
        # `gift_note` is NULL for this shop's rows because it maps no such
        # field, and the branch still projects the column (§5.2 rule 3).
        ("W7", 1, "GHI", 5, None, "woo__order_lines"),
    ]


def test_provenance_survives_the_merge(conn: duckdb.DuckDBPyConnection) -> None:
    """``_source`` is load-bearing, not decoration (D7): without it the
    collision report is "this key is duplicated somewhere"."""
    _seed_shopify(conn, [('{"id": "S1"}', 1, '{"sku": "ABC"}', 1, "{}")])
    _seed_woo(conn, [("W7", 1, "GHI", 1)])
    materialize(conn, compile_fixture("multi_source"))
    sources = conn.execute(
        "SELECT DISTINCT _source FROM silver.order_line ORDER BY _source"
    ).fetchall()
    assert sources == [("shopify__order_lines",), ("woo__order_lines",)]


def test_the_collision_audit_passes_on_disjoint_keys(conn: duckdb.DuckDBPyConnection) -> None:
    _seed_shopify(conn, [('{"id": "S1"}', 1, '{"sku": "ABC"}', 1, "{}")])
    _seed_woo(conn, [("W7", 1, "GHI", 1)])
    artifacts = compile_fixture("multi_source")
    materialize(conn, artifacts)
    body = audit_body(_collision_audit(artifacts), "silver.order_line")
    assert conn.execute(body).fetchall() == []


def test_the_collision_audit_fires_on_a_key_in_two_sources(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """**Verified red.** Both shops claim order ``S1`` line ``1``, which is
    either genuine duplication or a shared key space by accident — and both are
    refusals (D5)."""
    _seed_shopify(conn, [('{"id": "S1"}', 1, '{"sku": "ABC"}', 1, "{}")])
    _seed_woo(conn, [("S1", 1, "GHI", 1)])
    artifacts = compile_fixture("multi_source")
    materialize(conn, artifacts)
    body = audit_body(_collision_audit(artifacts), "silver.order_line")
    # An audit passes when its query returns no rows; this one returns the
    # offending key, and the count that says how many sources claimed it.
    assert conn.execute(body).fetchall() == [("S1", 1, 2)]


def test_the_collision_audit_ignores_duplication_within_one_source(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """``COUNT(DISTINCT _source) > 1`` deliberately does not fire here: a key
    duplicated inside one source is ordinary duplication and ``dedupe:`` owns
    it (§5.4). A plain ``COUNT`` would refuse this, which is a blocking false
    refusal on data the merge has no quarrel with."""
    _seed_shopify(
        conn,
        [
            ('{"id": "S1"}', 1, '{"sku": "ABC"}', 1, "{}"),
            ('{"id": "S1"}', 1, '{"sku": "ABC"}', 1, "{}"),
        ],
    )
    artifacts = compile_fixture("multi_source")
    materialize(conn, artifacts)
    body = audit_body(_collision_audit(artifacts), "silver.order_line")
    assert conn.execute(body).fetchall() == []


def test_the_composite_key_is_grouped_whole(conn: duckdb.DuckDBPyConnection) -> None:
    """The reason the fixture's key is composite (§6, D13).

    Both shops use order id ``S1`` but on *different lines*, so the composite
    keys are disjoint and nothing should fire. An audit that grouped by
    ``order_id`` alone would merge the two distinct keys and refuse valid
    data — a false refusal on a blocking audit, which D13 names as the worst
    failure available to a generated check.
    """
    _seed_shopify(conn, [('{"id": "S1"}', 1, '{"sku": "ABC"}', 1, "{}")])
    _seed_woo(conn, [("S1", 2, "GHI", 1)])
    artifacts = compile_fixture("multi_source")
    materialize(conn, artifacts)
    body = audit_body(_collision_audit(artifacts), "silver.order_line")
    assert conn.execute(body).fetchall() == []
