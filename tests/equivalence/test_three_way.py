"""Equivalence tier (RFC 0009 §5.2 tier 7, §5.8): MetricFlow ↔ Cube ↔ reference SQL.

"The strongest correctness evidence available: independent implementations
agreeing." Two of the three legs are implementations bloomery *drives* — the
MetricFlow-backed planner and the Cube emitter's output — and neither is
consulted to write the third, which is what makes the third a tiebreaker rather
than a restatement.

**Both legs read one table.** Cube's ``sql_table`` and the planner's SQL name
the same ``gold.mart_<name>`` under the naming policy, so pointing them at one
Postgres makes them read one relation by construction. A difference can then
only come from the query. Two seeding routines kept in step would have made
every result ambiguous.

**Binding is positional, and that is a finding.** ``QueryPlan.columns``
describes the result frame — RFC 0011 calls it "the self-describing envelope"
— but its dimension names are the *requested* ones (``ordered_month``) while
the SQL MetricFlow generates aliases them its own way
(``order_item__ordered_day__month``). A caller matching descriptor to cursor
column by name gets nothing. Positional zip works and is what this module does;
RFC 0009 D24 records the mismatch and the two ways to close it.

Nightly (containers). ``engine("cube")``-marked per §5.8.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml
from support.compiling import compile_fixture
from support.cube import CubeStack, cube_stack, schema_files
from support.equivalence import SEEDS, as_frame, cube_query, normalize_key
from support.planning import fixture_ir, fixture_mart, make_planner

pytestmark = pytest.mark.engine("cube")

HERE = Path(__file__).parent
REQUESTS: list[dict[str, Any]] = yaml.safe_load((HERE / "golden_requests.yaml").read_text())
#: Grouped by fixture so the cache-of-one opens each stack exactly once.
REQUESTS.sort(key=lambda entry: str(entry["fixture"]))
DIVERGENCES: dict[str, Any] = yaml.safe_load((HERE / "known_divergences.yaml").read_text())

#: §5.8's tolerance, verbatim.
ATOL = Decimal("0.01")

PLANNER = make_planner()


@pytest.fixture(scope="module")
def stacks() -> Iterator[_OneAtATime]:
    """A Cube+Postgres pair for whichever fixture is being asked about, and
    **only** that one.

    The first cut held one per fixture at once and failed intermittently. The
    cause was *not* the container count, which is what it looked like and what
    this docstring first claimed: it was a wait bug (see
    :func:`support.cube.cube_stack`). Holding one at a time is kept anyway,
    because two Cube containers buy nothing here — the corpus is ordered by
    fixture, so a cache-of-one opens each stack exactly once either way.
    """
    keeper = _OneAtATime()
    try:
        yield keeper
    finally:
        keeper.close()


class _OneAtATime:
    """The stack for the fixture last asked for; the previous one is closed."""

    def __init__(self) -> None:
        self._name: str | None = None
        self._manager: Any = None
        self._stack: CubeStack | None = None

    def __getitem__(self, fixture: str) -> CubeStack:
        if fixture != self._name:
            self.close()
            seed = SEEDS[fixture]
            self._manager = cube_stack(
                fixture_mart(fixture, seed.mart),
                schema_files(compile_fixture(fixture, target="cube")),
                seed.rows,
            )
            self._stack = self._manager.__enter__()
            self._name = fixture
        assert self._stack is not None
        return self._stack

    def close(self) -> None:
        if self._manager is not None:
            self._manager.__exit__(None, None, None)
        self._manager = None
        self._stack = None
        self._name = None


def _planner_frame(
    entry: dict[str, Any], connection: psycopg.Connection
) -> dict[tuple[str, ...], Decimal | None]:
    ir = fixture_ir(entry["fixture"])
    plan = PLANNER.plan(ir, cube_query.request(entry), dialect="postgres")
    with connection.cursor() as cursor:
        cursor.execute(plan.sql)
        rows = cursor.fetchall()
    # Positional, never by name — see the module docstring and RFC 0009 D24.
    width = len(entry["dimensions"])
    return as_frame(rows, width)


def _reference_frame(
    entry: dict[str, Any], connection: psycopg.Connection
) -> dict[tuple[str, ...], Decimal | None]:
    sql = (HERE / "reference_sql" / entry["reference"]).read_text()
    with connection.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()
    return as_frame(rows, len(entry["dimensions"]))


def _close(
    left: dict[tuple[str, ...], Decimal | None],
    right: dict[tuple[str, ...], Decimal | None],
) -> bool:
    if set(left) != set(right):
        return False
    return all(
        (left[key] is None and right[key] is None)
        or (
            left[key] is not None
            and right[key] is not None
            and abs(left[key] - right[key]) <= ATOL  # type: ignore[operator]
        )
        for key in left
    )


def _ids() -> list[str]:
    return [str(entry["name"]) for entry in REQUESTS]


@pytest.mark.parametrize("entry", REQUESTS, ids=_ids())
def test_metricflow_and_cube_agree(entry: dict[str, Any], stacks: _OneAtATime) -> None:
    """§5.8's core assertion. Two independent implementations, one table, one
    request — the frames must match within ``atol=0.01``."""
    stack = stacks[entry["fixture"]]
    planner = _planner_frame(entry, stack.connection)
    served = cube_query.frame(stack, entry)
    if entry["name"] in {d["request"] for d in DIVERGENCES["divergences"]}:
        pytest.skip(f"{entry['name']} is a reviewed divergence")
    assert _close(planner, served), f"planner={planner} cube={served}"


@pytest.mark.parametrize(
    "entry", [e for e in REQUESTS if e.get("reference")], ids=lambda e: str(e["name"])
)
def test_the_reference_sql_agrees_with_both(
    entry: dict[str, Any], stacks: _OneAtATime
) -> None:
    """The third leg, run on every request that declares one rather than only
    after a disagreement — a tiebreaker nobody has ever checked cannot break a
    tie. It is hand-written against the mart, consulting neither engine's SQL,
    so agreement here is agreement about the *arithmetic*."""
    stack = stacks[entry["fixture"]]
    reference = _reference_frame(entry, stack.connection)
    assert _close(_planner_frame(entry, stack.connection), reference), "planner disagrees"
    assert _close(cube_query.frame(stack, entry), reference), "cube disagrees"


def test_the_corpus_has_a_seed_for_every_fixture_it_names() -> None:
    """A request naming a fixture with no seeded rows would compare two empty
    frames and pass — the way an equivalence suite goes quietly hollow."""
    assert {entry["fixture"] for entry in REQUESTS} <= set(SEEDS)


def test_every_seeded_fixture_has_rows() -> None:
    """The same hollowness, one level down: two empty frames are equal."""
    for fixture, seed in SEEDS.items():
        assert seed.rows, f"{fixture} seeds no rows"


def test_a_reviewed_divergence_carries_its_justification() -> None:
    """The file is empty today. It must not become a place to park a failure
    with no argument attached, so the shape is asserted before anything lands
    in it."""
    for entry in DIVERGENCES["divergences"]:
        assert {"request", "reason", "reviewed"} <= set(entry)
        assert entry["request"] in set(_ids())


def test_the_normalizer_does_not_collapse_distinct_keys() -> None:
    """The comparison's own control. Both engines render a date differently —
    ``datetime.date(2024, 1, 1)`` against ``'2024-01-01T00:00:00.000'`` — so a
    normalizer is unavoidable, and one that mapped everything to a constant
    would make every assertion above pass."""
    assert normalize_key("2024-01-01T00:00:00.000") == normalize_key("2024-01-01")
    assert normalize_key("2024-01-01") != normalize_key("2024-02-01")
