"""Execution tier (RFC 0009 §5.2 tier 4): what each transform *declares* it
produces, against what DuckDB actually produces (RFC 0028 D5).

RFC 0028 asked whether an **emit-time** check should assert that a silver
column's rendered type matches its declared physical type. It should not, and
the reasons are worth keeping next to the thing that replaced it:

* Compilation does no I/O (RFC 0003), so emit has no engine to ask. The only
  static model available is SQLGlot's type annotator, and it answers
  ``UNKNOWN`` for ``AtTimeZone`` on DuckDB — precisely the node ``to_utc``'s
  zone-aware value lived in — so the check would not have caught the defect
  that prompted the question.
* Where the annotator *does* answer, it answers from an explicit ``CAST`` in
  the tree, which is bloomery's own claim read back to itself.
* A type-shaped check invites a cast-shaped fix, and a cast converts rather
  than asserts. Wrapping the old ``to_utc`` in ``CAST(… AS TIMESTAMP)``
  satisfies the declared type on every port while keeping the wrong instant on
  two of them — a check a wrong fix passes is worse than no check.

So the check runs where the ground truth is. This module is DuckDB, in the
tier that needs no Docker; :mod:`tests.engines.test_type_conformance` is the
same corpus on PostgreSQL and Trino.

**Why per-transform and not per-column.** The declaration and the construction
sit next to each other on :class:`~bloomery.transforms.registry.TransformSpec`,
and a chain is those steps composed. Proving each transform's produced type
equals its declared one, for every input type the typechecker admits, gives
the whole-column property by induction — a stronger claim than any spot check
on a compiled fixture, and one that covers transforms no fixture uses.
"""

from __future__ import annotations

import duckdb
import pytest
from support.type_conformance import (
    CASES,
    assert_matches_known,
    canonical,
    measure,
    source_columns,
)

from bloomery.dialects import get_dialect

pytestmark = pytest.mark.execution

PORT = get_dialect("duckdb")


def _literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


@pytest.fixture(scope="module")
def probe() -> duckdb.DuckDBPyConnection:
    """One row, one column per case, each column the case's declared *input*
    type — a real column rather than a folded constant."""
    connection = duckdb.connect()
    columns = ", ".join(
        f"CAST({_literal(value)} AS {physical}) AS {name}"
        for name, physical, value in source_columns(PORT)
    )
    connection.execute(f"CREATE TABLE probe AS SELECT {columns}")
    return connection


def test_declared_types_are_what_duckdb_produces(probe: duckdb.DuckDBPyConnection) -> None:
    def run(sql: str) -> str:
        try:
            result = probe.sql(sql)
            produced = canonical(str(result.types[0]), dialect="duckdb")
        except duckdb.Error as error:
            return f"error:{type(error).__name__}"
        result.fetchall()  # the type is planned; this proves it also runs
        return produced

    assert_matches_known(measure(PORT, run), port="duckdb")


def test_every_case_runs_or_is_registered(probe: duckdb.DuckDBPyConnection) -> None:
    """The battery's own floor: a case that silently stopped being executed
    would take its assertion with it."""
    assert len(CASES) == len(source_columns(PORT))
    assert probe.sql("SELECT COUNT(*) FROM probe").fetchall() == [(1,)]
