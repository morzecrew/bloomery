"""`parse_ts: UNIX_SECONDS` and `UNIX_MILLIS` on DuckDB, executed (S-0096, #324).

The texts are the ones the design measured on DuckDB, PostgreSQL and Trino, and
each answer is pinned under a UTC and an Asia/Tokyo session: an engine's own
epoch function moved with the session zone, so a spelling that did would show
here as two different answers. Run plain and as the quality system shapes it,
since outside the quality system the counts' cast is a plain `CAST`.
"""

from __future__ import annotations

from datetime import datetime

import duckdb
import pytest
from sqlglot import exp
from support.compiling import FIXTURES, fixture_sources
from support.epoch_cases import MILLIS, SECONDS
from support.execution import materialize, warehouse

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.dialects import get_dialect
from bloomery.resolve.build import _try_cast_shape  # pyright: ignore[reportPrivateUsage]
from bloomery.transforms import DEFAULT_REGISTRY

pytestmark = pytest.mark.execution

def _rendered(fmt: str, *, quality: bool) -> str:
    node = DEFAULT_REGISTRY["parse_ts"].builder(exp.column("x"), fmt)
    return get_dialect("duckdb").render(_try_cast_shape(node) if quality else node)


@pytest.mark.parametrize("quality", [False, True])
@pytest.mark.parametrize("zone", ["UTC", "Asia/Tokyo"])
@pytest.mark.parametrize(("fmt", "cases"), [("UNIX_SECONDS", SECONDS), ("UNIX_MILLIS", MILLIS)])
def test_every_measured_text_reads_one_instant_under_any_session(
    fmt: str, cases: dict[str | None, datetime | None], zone: str, quality: bool
) -> None:
    connection = duckdb.connect()
    connection.execute(f"SET TimeZone = '{zone}'")
    sql = _rendered(fmt, quality=quality)

    answers = {
        text: connection.execute(f"SELECT {sql} FROM (SELECT ?::VARCHAR AS x)", [text]).fetchone()[0]  # type: ignore[index]
        for text in cases
    }

    assert answers == cases


def test_an_uncastable_epoch_is_a_coercion_failure_on_a_quality_entity() -> None:
    """The guard's NULL from a non-NULL source is what `coercible` marks, as for
    `ISO8601_INSTANT` over zoneless text: `parse_ts` is not `nullifies`."""
    sources = fixture_sources("semi_additive_inventory")
    old = "      stock_level: {type: int, canonical: stock_level}\n"
    assert sources["entity_model"].count(old) == 1
    sources["entity_model"] = sources["entity_model"].replace(
        old, old + "      counted_at: {type: timestamp}\n"
    )
    sources["mapping"] = sources["mapping"].replace(
        "fields:\n", 'fields:\n  counted_at: {from: "$.counted", transform: [{parse_ts: UNIX_SECONDS}]}\n', 1
    )
    catalog = load_catalog(
        (FIXTURES / "semi_additive_inventory" / "catalog.yaml").read_text(encoding="utf-8")
    )
    connection = warehouse("bronze", "silver", "gold")
    connection.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, on_hand VARCHAR, "
        "counted VARCHAR, _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR, "
        "operator_note VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, '2026-01-01', '5', ?, 'L1', "
        "'2026-01-01 00:00:00', ?, NULL)",
        [("w1", "1761561600", "r1"), ("w2", "1761561600.5", "r2")],
    )
    materialize(
        connection,
        compile_project(
            load_project(sources), target=Target.SQLMESH, dialect="duckdb", catalog=catalog
        ),
    )

    kept = connection.execute("SELECT _source_row_id, counted_at FROM silver.inventory_level").fetchall()
    rejected = dict(
        connection.execute(
            "SELECT _source_row_id, failed_rules FROM silver.inventory_level__reject"
        ).fetchall()
    )
    assert kept == [("r1", datetime(2025, 10, 27, 10, 40))]
    assert "counted_at_coercible" in rejected["r2"]
