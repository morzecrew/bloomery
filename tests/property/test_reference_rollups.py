"""The DuckDB half of the rollup-aggregate differential (S-0092/D-7, S-0092/D-4).

A rollup mart groups a parent mart's rows and aggregates the metric's
expression — ``COUNT(expr)``, ``SUM(expr)``, ``MIN(expr)``, ``MAX(expr)`` — with
no ``COALESCE`` anywhere. Three facts follow, and all three are held here to
:mod:`support.reference`'s exact answer:

- a **retained group whose expression is NULL on every row** counts 0 and sums,
  minimises and maximises to NULL — ``COUNT(expr)`` skips NULL, it does not
  count the rows;
- a **group a filter removed entirely** has no row at all: ``GROUP BY`` forms a
  group only from the rows it is given, and the rollup adds no date spine to
  resurrect one, so the reference states the absence rather than a zero;
- a group with rows is the ordinary aggregate over the non-NULL ones.

The comparison is exact (:mod:`support.engine_differences` is consulted as
usual, though no row names any of these); a disagreement fails, printing the
groups, the engine's answer and the reference's. The PostgreSQL half runs under
``tests/engines/`` against a session-scoped container; this half is the one
every pull request guards.
"""

from __future__ import annotations

import functools
from typing import Any

import duckdb
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bloomery import Target, compile_project, load_project
from support.execution import materialize, warehouse
from support.reference import (
    ROLLUP_BRONZE_COLUMNS,
    ROLLUP_METRICS,
    ROLLUP_RELATION,
    ROLLUP_SOURCES,
    rollup,
    rollup_bronze_rows,
)

pytestmark = pytest.mark.property

#: How DuckDB is named in failure messages.
ENGINE = "duckdb"

#: The metric names the rollup projects, read by name rather than by position.
_METRICS = tuple(sorted(ROLLUP_METRICS))

#: A group map: key → the metric expression's value on each of its rows. A key
#: with an **empty** list is the group a filter removed entirely; a key whose
#: list is all ``None`` is the retained all-NULL group (S-0092/D-7).
_ROLLUP_CASES = st.dictionaries(
    st.sampled_from(["A", "B", "C", "D", "E"]),
    st.lists(st.one_of(st.none(), st.integers(-(10**6), 10**6)), max_size=6),
    min_size=1,
    max_size=4,
)


@functools.lru_cache(maxsize=None)
def _artifacts() -> tuple[Any, ...]:
    """The compiled rollup fixture: silver, the parent mart, and the rollup."""
    project = load_project(dict(ROLLUP_SOURCES))
    return compile_project(
        project, target=Target.SQLMESH, dialect=ENGINE, catalog=None, steps=None
    )


def _rollup_sql() -> str:
    """The emitted rollup SELECT's body, for the checks that read the SQL."""
    artifact = next(
        a for a in _artifacts() if a.path.endswith(f"gold/{ROLLUP_RELATION}.sql")
    )
    return artifact.content.split(");", 1)[1].strip()


def _run(groups: dict[str, list[int | None]]) -> dict[str, dict[str, int | None]]:
    """Seed the group map, build the project on DuckDB, and read the rollup as
    ``{group: {metric: value}}``."""
    connection = warehouse()
    try:
        connection.execute(
            f"CREATE TABLE bronze.raw__probe ({ROLLUP_BRONZE_COLUMNS})"
        )
        rows = rollup_bronze_rows(groups)
        if rows:
            connection.executemany(
                "INSERT INTO bronze.raw__probe VALUES (?, ?, ?, ?)", rows
            )
        materialize(connection, _artifacts())
        columns = ", ".join(_METRICS)
        result = connection.execute(
            f"SELECT grp, {columns} FROM gold.{ROLLUP_RELATION}"
        ).fetchall()
        return {
            row[0]: dict(zip(_METRICS, row[1:], strict=True)) for row in result
        }
    finally:
        connection.close()


def _assert_equal(
    groups: dict[str, list[int | None]],
    produced: dict[str, dict[str, int | None]],
    expected: dict[str, dict[str, int | None]],
) -> None:
    if produced != expected:
        msg = (
            f"the rollup on {ENGINE} disagreed with the reference for groups "
            f"{groups!r}: the engine answered {produced!r}, the reference says "
            f"{expected!r} (S-0092/D-4)"
        )
        raise AssertionError(msg)


# ----------------------- #
# The differential


@given(groups=_ROLLUP_CASES)
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_every_group_equals_the_reference_aggregates(
    groups: dict[str, list[int | None]],
) -> None:
    """Count, sum, min and max on every generated group — the all-NULL and the
    emptied group among them (S-0092/D-7)."""
    produced = _run(groups)
    _assert_equal(groups, produced, rollup(groups))


# ----------------------- #
# The facts the phase names, stated on their own


def test_an_all_null_group_counts_zero_and_sums_to_null() -> None:
    """``COUNT(expr)`` skips NULL: a retained group whose expression is NULL on
    every row is present, counts 0, and sums, minimises and maximises to NULL."""
    groups = {"A": [None, None, None], "B": [3, 5]}
    produced = _run(groups)

    assert produced["A"] == {"n": 0, "total": None, "lo": None, "hi": None}
    assert produced["B"] == {"n": 2, "total": 8, "lo": 3, "hi": 5}
    assert produced == rollup(groups)


def test_a_group_a_filter_removes_has_no_row() -> None:
    """A group whose every row is filtered out before the mart has no row on
    either engine; the reference states that absence, not a zero."""
    groups = {"A": [1, 2], "GONE": []}
    produced = _run(groups)

    assert "GONE" not in produced
    assert produced == rollup(groups) == {"A": {"n": 2, "total": 3, "lo": 1, "hi": 2}}


def test_the_rollup_aggregates_the_expression_and_adds_no_coalesce() -> None:
    """The emitter aggregates the metric's *expression* — ``COUNT(value)``, not
    ``COUNT(*)`` — and the SQL carries no ``COALESCE`` to turn a NULL sum into a
    zero (S-0092/D-7)."""
    sql = _rollup_sql()

    assert "COALESCE" not in sql
    for metric, aggregate in ROLLUP_METRICS.items():
        assert f"{aggregate.upper()}(value) AS {metric}" in sql


# ----------------------- #
# The battery's own teeth


def test_a_wrong_reference_value_fails_naming_the_group_and_both_answers() -> None:
    """The comparison is only a check if a wrong expected value fails."""
    groups = {"A": [3]}
    produced = _run(groups)
    wrong = {"A": {"n": 7, "total": 3, "lo": 3, "hi": 3}}

    with pytest.raises(AssertionError) as caught:
        _assert_equal(groups, produced, wrong)

    message = str(caught.value)
    assert "A" in message
    assert repr(produced) in message
    assert repr(wrong) in message