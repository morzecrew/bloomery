"""The local Spark surrogate harness (S-0016): one session, pinned, and the
few settings a comparison against it depends on.

Test apparatus, never library code (S-0016/D-1): no Spark session enters
`src/bloomery`, the `databricks` port renders text and nothing else, and the
only place this repository starts a JVM is here, under `tests/support/`.

What this lane is (S-0016/D-3): rung 4s, a *surrogate*. Local Spark answers
whether shared Spark semantics accept and evaluate the emitted SQL. It never
answers whether Databricks does — that is the live lane's question, and the
`surrogate("databricks_spark")` marker keeps the distinction in the one place
it is otherwise invisible, a test name in a CI log.

Four settings are pinned because a comparison against a session that did not
pin them measures the session rather than the SQL:

- **Timezone** `UTC`. The repository's zoneless-UTC invariant (S-0045) means
  a derived date or hour must not read a session zone; a surrogate on the
  machine's local zone would find that defect only on machines east of
  Greenwich.
- **ANSI mode** on. The port maps `timestamp` to `TIMESTAMP_NTZ`, and that
  choice pins this session to ANSI mode (S-0016/D-8), where a failing `CAST`
  raises rather than yielding NULL and `TRY_CAST` is the NULL-on-failure cast
  the quality layer needs. Databricks SQL runs this way; a non-ANSI surrogate
  would pass statements the warehouse refuses.
- **Fixture registration** through :func:`relation`, so every relation a case
  reads is a temporary view of literal rows with declared physical types,
  created in this session and visible to nothing else.
- **Result canonicalization** through :func:`rows`, which orders the result
  and renders each value as text: an engine comparison that admits row order
  or `Decimal` repr differences reports noise before it reports a defect.

Per-process and self-named (S-0067/D-8): the suite runs in parallel, so the
application name and the warehouse directory carry this process's id rather
than a literal another worker also picks.

PySpark is a test-only optional dependency group (S-0016/D-2), absent from a
default `uv sync`, so the lane skips with a stated reason rather than failing
for everyone who never targets Databricks.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import shutil
import tempfile
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pyspark.sql import SparkSession

# ----------------------- #

__all__ = [
    "SURROGATE",
    "missing_reason",
    "relation",
    "rows",
    "session",
]

#: The marker argument this lane carries. Never `databricks` (S-0016/D-3).
SURROGATE = "databricks_spark"

#: The pinned session. `local[1]` and one shuffle partition because every
#: relation here is a handful of literal rows: parallelism would buy nothing
#: and cost a scheduler per case.
CONF: dict[str, str] = {
    "spark.sql.session.timeZone": "UTC",
    "spark.sql.ansi.enabled": "true",
    "spark.sql.shuffle.partitions": "1",
    "spark.ui.enabled": "false",
}


def missing_reason() -> str | None:
    """Why the lane is skipping, or `None` when it can run.

    Actionable on its own: whoever reads it in a pytest summary has neither
    this file nor a JVM in mind.
    """
    if importlib.util.find_spec("pyspark") is None:
        return (
            "pyspark is not installed: the lane is opt-in, "
            "`uv sync --group spark` installs it"
        )
    if not (os.environ.get("JAVA_HOME") or shutil.which("java")):
        return "no JVM found: local Spark needs Java 17+ on PATH or JAVA_HOME set"
    return None


@functools.cache
def session() -> SparkSession:
    """The one session for this process, built on first use.

    Cached rather than a fixture: a JVM takes seconds to start and the
    settings are pinned, so there is nothing a second session would isolate.
    """
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.master("local[1]")
        .appName(f"bloomery-surrogate-{os.getpid()}")
        # Per-process (S-0067/D-8): a shared default would have two xdist
        # workers writing one warehouse directory.
        .config("spark.sql.warehouse.dir", tempfile.mkdtemp(prefix="bloomery-spark-"))
    )
    for key, value in CONF.items():
        builder = builder.config(key, value)
    return builder.getOrCreate()


# ....................... #
# Fixture registration


def relation(
    name: str,
    columns: Sequence[tuple[str, str]],
    values: Sequence[Sequence[str]],
) -> None:
    """Register `name` as a temporary view over literal rows.

    `columns` is `(name, physical type)` and `values` holds SQL literals, so
    a case declares the types its expectation depends on rather than
    inheriting whatever a bare literal infers — `DECIMAL(12, 4)` and
    `TIMESTAMP_NTZ` both differ from what Spark reads off a literal.
    """
    names = ", ".join(f"`{column}`" for column, _ in columns)
    casts = ", ".join(f"CAST(`{column}` AS {physical}) AS `{column}`" for column, physical in columns)
    body = ", ".join("(" + ", ".join(row) + ")" for row in values)
    session().sql(
        f"CREATE OR REPLACE TEMPORARY VIEW `{name}` AS "
        f"SELECT {casts} FROM VALUES {body} AS t({names})"
    )


# ....................... #
# Result canonicalization


def canonical(value: Any) -> Any:
    """One value as text, or `None`.

    `Decimal` keeps its scale as written, a timestamp or date its ISO
    spelling, an array its element order — the three shapes where a
    comparison against a declared expectation would otherwise fail on repr.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(canonical(element) for element in value)
    if isinstance(value, (Decimal, bool, int, float)):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def rows(sql: str) -> tuple[tuple[Any, ...], ...]:
    """Execute `sql` and return its rows, canonicalized and ordered.

    Sorted here rather than in the statement: a case that has to carry an
    `ORDER BY` to be comparable is a case testing the harness.
    """
    result = [tuple(canonical(value) for value in row) for row in session().sql(sql).collect()]
    return tuple(sorted(result, key=repr))
