"""E2E tier (RFC 0009 §5.2 tier 6): a Cube container's ``/meta``.

§5.2 states this cell as "a cube container's `/meta` returns the expected
measures/dimensions", and the sentence above the row is why it exists at all:
*artifacts are valid input to the target, not just valid YAML*. The Cube
goldens lock the bytes; only Cube can say whether Cube loads them.

What that turns out to cover, once run: the `cubes:`/`views:` document shape,
whether `type:` values are ones Cube knows, whether a measure's `sql` parses in
Cube's own expression language, and whether the `meta:` blocks bloomery
attaches — `additivity`, `grain`, `semi_additive` — survive to the API a
consumer reads them from. That last one is load-bearing and untestable any
other way: RFC 0008 §5.1 gates *trusting* Cube's semi-additive behavior on the
equivalence suite and says the `meta` is what a consumer audits against, which
is only true if it arrives.

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from support.compiling import compile_fixture
from support.cube import CubeStack, cube_stack, schema_files
from support.planning import fixture_mart

pytestmark = pytest.mark.e2e

FIXTURE = "ecom_basic"
MART = "order_items"

#: ``(line_no, order_customer_id, order_date, order_id, order_order_id,
#: ordered_day, ordered_month, ordered_quarter, ordered_week, ordered_year,
#: quantity, unit_price)`` — the flattened mart's columns, in ``MartIR`` order.
ROWS: list[list[Any]] = [
    [1, "c1", "2024-01-02", "o1", "o1", "2024-01-02", "2024-01-01", "2024-01-01",
     "2024-01-01", "2024-01-01", 2, Decimal("10.0000")],
    [2, "c1", "2024-01-03", "o1", "o1", "2024-01-03", "2024-01-01", "2024-01-01",
     "2024-01-01", "2024-01-01", 3, Decimal("5.0000")],
    [1, "c2", "2024-02-05", "o2", "o2", "2024-02-05", "2024-02-01", "2024-01-01",
     "2024-02-05", "2024-01-01", 1, Decimal("20.0000")],
]  # fmt: skip


@pytest.fixture(scope="module")
def cube() -> Iterator[CubeStack]:
    mart = fixture_mart(FIXTURE, MART)
    artifacts = compile_fixture(FIXTURE, target="cube")
    with cube_stack(mart, schema_files(artifacts), ROWS) as stack:
        yield stack


def _cube_entry(stack: CubeStack, name: str) -> dict[str, Any]:
    return next(entry for entry in stack.meta()["cubes"] if entry["name"] == name)


def test_cube_loads_the_emitted_model(cube: CubeStack) -> None:
    """The whole tier in one assertion: Cube read the files and produced a
    cube. A schema Cube rejects yields an empty ``/meta``, which is what the
    harness refuses to accept as an answer."""
    assert {entry["name"] for entry in cube.meta()["cubes"]} >= {MART, f"{MART}_view"}


def test_the_measure_arrives_with_its_aggregation(cube: CubeStack) -> None:
    measures = {m["name"]: m for m in _cube_entry(cube, MART)["measures"]}
    assert measures[f"{MART}.gross_revenue"]["aggType"] == "sum"


def test_the_declared_meta_survives_to_the_api(cube: CubeStack) -> None:
    """RFC 0008 §5.1 says the `meta` is what a consumer audits Cube's
    semi-additive behaviour against. That claim is only true if `meta` reaches
    the API — a YAML key Cube silently dropped would leave every consumer
    auditing against nothing."""
    measure = next(
        m for m in _cube_entry(cube, MART)["measures"] if m["name"] == f"{MART}.gross_revenue"
    )
    assert measure["meta"] == {"additivity": "additive", "grain": "order_item"}


def test_every_flattened_column_is_a_requestable_dimension(cube: CubeStack) -> None:
    """RFC 0010 §10: every flattened column is requestable. Asserted against
    the mart's own column set rather than a list written here, so a column
    added to the flattener and dropped by the emitter is a failure."""
    mart = fixture_mart(FIXTURE, MART)
    served = {d["name"].removeprefix(f"{MART}.") for d in _cube_entry(cube, MART)["dimensions"]}
    expected = {dimension.column for dimension in mart.dimensions} - {"gross_revenue"}
    assert expected <= served


def test_the_date_role_buckets_arrive_as_time_dimensions(cube: CubeStack) -> None:
    """A bucket declared ``string`` would still answer queries and would group
    wrong — the failure mode a `/meta` check exists for."""
    dimensions = {d["name"]: d for d in _cube_entry(cube, MART)["dimensions"]}
    for bucket in ("day", "month", "quarter", "week", "year"):
        assert dimensions[f"{MART}.ordered_{bucket}"]["type"] == "time"


def test_the_cube_actually_answers_a_query(cube: CubeStack) -> None:
    """``/meta`` proves Cube *parsed* the model; only a query proves the
    ``sql_table`` resolves and the measure expression runs. ``gross_revenue``
    is ``unit_price * quantity`` summed, so January is 2×10 + 3×5."""
    rows = cube.load(
        {
            "measures": [f"{MART}.gross_revenue"],
            "dimensions": [f"{MART}.ordered_month"],
            "order": {f"{MART}.ordered_month": "asc"},
        }
    )
    assert [Decimal(row[f"{MART}.gross_revenue"]) for row in rows] == [
        Decimal("35.0000"),
        Decimal("20.0000"),
    ]
