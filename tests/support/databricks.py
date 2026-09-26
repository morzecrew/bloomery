"""The live Databricks harness (S-0016): the SQL Statement Execution API over
HTTP, and nothing else.

Test apparatus, never library code (S-0016/D-1): no Spark session, no engine
driver, no cloud SDK — installing bloomery must not pull a warehouse client,
and the `databricks` port renders text and answers no question that needs a
warehouse. What lives here is the other half of that split: the one place the
suite talks to a real warehouse, so the lane above it can ask the engine
whether the generated SQL is acceptable.

Five environment variables and no configuration file (S-0016/D-10): a
contributor with none of them sees a stated skip rather than a red suite, and
the names are the ones the Databricks CLI already uses, so a workspace already
set up needs nothing new. ``.env.example`` names them and nothing else.

Plain :mod:`urllib` rather than ``databricks-sdk`` or ``requests``: the API is
three endpoints — submit, poll, cancel — and a dependency added for them would
be one more thing pinned in the lockfile for a lane that skips by default.

The authoritative statements are :meth:`Warehouse.explain` and
:meth:`Warehouse.describe` (S-0016/D-4): ``EXPLAIN EXTENDED`` asks the real
analyzer whether the statement is accepted, ``DESCRIBE QUERY`` asks it what
types the result carries. Neither executes anything or scans any data, which
is what makes them affordable on the edition the lane is sized for.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# ----------------------- #

__all__ = [
    "CORPUS",
    "STATEMENT_TIMEOUT",
    "VARIABLES",
    "Credentials",
    "EngineError",
    "Result",
    "Warehouse",
    "credentials",
    "missing_reason",
]

#: The five variables the lane reads, in the order ``.env.example`` names them.
VARIABLES = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "DATABRICKS_WAREHOUSE_ID",
    "DATABRICKS_CATALOG",
    "DATABRICKS_SCHEMA",
)

#: The fixtures the authoritative lane sweeps: the five the databricks golden
#: matrix holds (``tests/golden/test_sqlmesh_dialects.py``), because those are
#: the artifacts whose rendering the port froze — the JSON accessor, the
#: reserved relation name, ``TIMESTAMP_NTZ``, the reject table's
#: ``TO_JSON(NAMED_STRUCT(…))``, the calendar's ``EXPLODE``.
#:
#: Deliberately not every spec fixture (S-0016/D-6): Free Edition is one
#: serverless ``2X-Small`` warehouse under fair-use quotas with no SLA, and a
#: lane sized by what the edition can carry is a lane that keeps running.
CORPUS = (
    "ecom_basic",
    "minimal",
    "multi_source",
    "multi_source_quality",
    "role_playing_dates",
)

#: Wall-clock ceiling for one statement, enforced here rather than left to the
#: API: a warehouse that is starting from cold, a quota that has been reached
#: and a query that will never finish are indistinguishable from the client
#: side, and all three have to end in a failure that names the statement.
#:
#: Under pytest's 300s per-test ceiling with room for the poll loop's last
#: sleep, so a statement that hangs fails as itself rather than as a killed run.
STATEMENT_TIMEOUT = 120.0

#: The API's own synchronous wait, at its documented maximum: a statement that
#: finishes inside it needs no poll at all, which is most of them once the
#: warehouse is warm.
_WAIT_TIMEOUT = "30s"

_POLL_INTERVAL = 2.0

_STATEMENTS = "/api/2.0/sql/statements"

_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"})

#: What a Databricks planner failure looks like in the *body* of an ``EXPLAIN``
#: result. The API reports such a failure as a successful statement whose single
#: row is the analyzer's complaint, so a lane that only checked the statement
#: state would read every unanalyzable query as accepted.
_PLAN_FAILURES = (
    "AnalysisException",
    "ParseException",
    "Error occurred during query planning",
    "org.apache.spark.sql.catalyst",
)


class EngineError(RuntimeError):
    """The engine's own refusal, surfaced with the engine's own words.

    ``code`` is the Databricks error code (``TABLE_OR_VIEW_NOT_FOUND``,
    ``UNRESOLVED_COLUMN``, …) rather than a message: a code is stable across
    workspace versions, so a failure here reads as a behaviour change and not
    as a reworded string.
    """

    def __init__(self, code: str, message: str, statement: str) -> None:
        self.code = code
        self.message = message
        self.statement = statement
        super().__init__(f"{code or 'ERROR'}: {message}\n  statement: {_excerpt(statement)}")


@dataclass(frozen=True, slots=True)
class Credentials:
    """A workspace, a token, a warehouse, and the catalog and schema every
    statement runs against — ``workspace.bloomery_conformance`` on the lane's
    own workspace (S-0016/D-10), never a schema anything else writes to."""

    host: str
    token: str
    warehouse_id: str
    catalog: str
    schema: str


@dataclass(frozen=True, slots=True)
class Result:
    """One statement's outcome: the result schema and the rows.

    Values are the API's own ``JSON_ARRAY`` text — every column a string, SQL
    ``NULL`` as ``None``. Not coerced to Python types here: the engine's
    rendering of a value *is* what several of the runtime checks are about
    (a decimal's scale, a digest's hex casing), and a harness that parsed
    ``3.5000`` into a float would throw away the evidence.
    """

    #: ``(name, type_text)`` per column, as the result manifest declares it.
    columns: tuple[tuple[str, str], ...]
    rows: tuple[tuple[str | None, ...], ...]


def credentials() -> Credentials | None:
    """The five variables, or ``None`` when any of them is absent."""
    values = {name: os.environ.get(name, "").strip() for name in VARIABLES}
    if not all(values.values()):
        return None
    return Credentials(
        host=values["DATABRICKS_HOST"].rstrip("/"),
        token=values["DATABRICKS_TOKEN"],
        warehouse_id=values["DATABRICKS_WAREHOUSE_ID"],
        catalog=values["DATABRICKS_CATALOG"],
        schema=values["DATABRICKS_SCHEMA"],
    )


def missing_reason() -> str:
    """Why the lane is skipping, naming the variables that are not set.

    A stated skip is the contributor path (S-0016/D-10), so the reason has to
    be actionable on its own: whoever reads it in a pytest summary has neither
    this file nor a workspace open.
    """
    absent = [name for name in VARIABLES if not os.environ.get(name, "").strip()]
    return (
        "no live Databricks warehouse: "
        + ", ".join(absent)
        + " not set (see .env.example; the lane is opt-in and runs on main, "
        "on a schedule and on manual dispatch)"
    )


@dataclass(frozen=True, slots=True)
class Warehouse:
    """A SQL warehouse, addressed one statement at a time."""

    credentials: Credentials

    # ....................... #

    def run(self, statement: str) -> Result:
        """Submit, poll to a terminal state, and return the normalized result.

        Raises :class:`EngineError` when the engine refuses the statement and
        :class:`TimeoutError` when :data:`STATEMENT_TIMEOUT` passes first — in
        which case the statement is cancelled, because an abandoned query on a
        billed warehouse keeps running.
        """
        deadline = time.monotonic() + STATEMENT_TIMEOUT
        payload = self._submit(statement)

        while (state := _state(payload)) not in _TERMINAL:
            if time.monotonic() >= deadline:
                self._cancel(str(payload["statement_id"]))
                msg = (
                    f"statement did not finish within {STATEMENT_TIMEOUT:.0f}s "
                    f"(last state {state}): {_excerpt(statement)}"
                )
                raise TimeoutError(msg)
            time.sleep(_POLL_INTERVAL)
            # The socket timeout is what is left of the deadline, so a stalled
            # poll cannot hold the loop past it and the cancel above still
            # reaches a running statement promptly.
            payload = self._request(
                "GET",
                f"{_STATEMENTS}/{payload['statement_id']}",
                statement,
                timeout=max(1.0, deadline - time.monotonic()),
            )

        if state != "SUCCEEDED":
            error = payload["status"].get("error", {})
            raise EngineError(
                str(error.get("error_code", state)),
                str(error.get("message", f"statement ended in state {state}")),
                statement,
            )

        return self._collect(payload, statement)

    def rows(self, statement: str) -> tuple[tuple[str | None, ...], ...]:
        return self.run(statement).rows

    def scalar(self, statement: str) -> str | None:
        """The single value of a single-row, single-column statement."""
        rows = self.rows(statement)
        assert len(rows) == 1 and len(rows[0]) == 1, f"not a scalar result: {rows!r}"
        return rows[0][0]

    def execute(self, statement: str) -> None:
        """Run a statement whose rows are of no interest (DDL, an insert)."""
        self.run(statement)

    # ....................... #

    def explain(self, statement: str) -> str:
        """``EXPLAIN EXTENDED`` over ``statement`` — the acceptance question
        (S-0016/D-4), asked of the real analyzer without executing anything.

        The plan text is returned for a caller that wants to read it; a plan
        that reports a planner failure raises :class:`EngineError` instead,
        since the API calls such a statement SUCCEEDED.
        """
        plan = "\n".join(
            value or "" for row in self.rows(f"EXPLAIN EXTENDED {statement}") for value in row
        )
        for marker in _PLAN_FAILURES:
            if marker in plan:
                raise EngineError("PLANNING_FAILED", plan.strip(), statement)
        return plan

    def describe(self, statement: str) -> dict[str, str]:
        """``DESCRIBE QUERY`` over ``statement`` as ``column -> type``.

        The declared-versus-produced type contract, checked against the real
        analyzer (S-0016/D-4) rather than against the Spark surrogate, which is
        precisely where Spark and Databricks SQL are documented to differ.
        ``DESCRIBE QUERY`` returns ``(col_name, data_type, comment)``.
        """
        return {
            str(row[0]): str(row[1])
            for row in self.rows(f"DESCRIBE QUERY {statement}")
            if row[0] is not None and row[1] is not None
        }

    # ....................... #

    def _submit(self, statement: str) -> dict[str, Any]:
        return self._request(
            "POST",
            _STATEMENTS,
            statement,
            body={
                "statement": statement,
                "warehouse_id": self.credentials.warehouse_id,
                "catalog": self.credentials.catalog,
                "schema": self.credentials.schema,
                "wait_timeout": _WAIT_TIMEOUT,
                "on_wait_timeout": "CONTINUE",
                "disposition": "INLINE",
                "format": "JSON_ARRAY",
            },
        )

    def _cancel(self, statement_id: str) -> None:
        try:
            self._request("POST", f"{_STATEMENTS}/{statement_id}/cancel", "cancel")
        except (EngineError, OSError):  # pragma: no cover — best effort
            pass

    def _collect(self, payload: dict[str, Any], statement: str) -> Result:
        """The manifest's columns and every chunk's rows.

        Chunks are followed rather than ignored: an inline result over one
        chunk would otherwise arrive silently truncated, and a check that
        asserts on a prefix of the rows is worse than no check.
        """
        manifest = payload.get("manifest", {}).get("schema", {}).get("columns", [])
        columns = tuple(
            (str(column["name"]), str(column.get("type_text", ""))) for column in manifest
        )

        rows: list[tuple[str | None, ...]] = []
        result: dict[str, Any] | None = payload.get("result", {})
        while result:
            rows.extend(tuple(row) for row in result.get("data_array", []))
            link = result.get("next_chunk_internal_link")
            result = self._request("GET", str(link), statement) if link else None

        return Result(columns=columns, rows=tuple(rows))

    def _request(
        self,
        method: str,
        path: str,
        statement: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float = STATEMENT_TIMEOUT,
    ) -> dict[str, Any]:
        request = urllib.request.Request(  # noqa: S310 — https, from the host variable
            f"{self.credentials.host}{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.credentials.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read())
        except urllib.error.HTTPError as failure:
            # The workspace's own diagnosis where it sent one — a 400 carrying
            # `INVALID_PARAMETER_VALUE` says more than "HTTP 400" ever will.
            detail = _detail(failure)
            raise EngineError(
                str(detail.get("error_code", f"HTTP_{failure.code}")),
                str(detail.get("message", failure.reason)),
                statement,
            ) from failure


# ....................... #


def _state(payload: dict[str, Any]) -> str:
    return str(payload.get("status", {}).get("state", "UNKNOWN"))


def _detail(failure: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        parsed = json.loads(failure.read())
    except (ValueError, OSError):  # pragma: no cover — a non-JSON error body
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _excerpt(statement: str) -> str:
    """The first line of a statement, for an error message that has to stay
    readable when the statement is a two-hundred-line generated model."""
    first = statement.strip().splitlines()[0] if statement.strip() else ""
    return first if len(first) <= 120 else f"{first[:117]}..."
