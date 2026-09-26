"""Snowflake harness: the SQL API v2, reached over HTTP, with submission,
polling and row canonicalization — pointed either at the OSS emulator
(S-0013/D-3) or at a real account, which is the same protocol either way.

**Why no driver.** The emulator speaks Snowflake's SQL API v2 — one POST to
submit, one GET to poll — which is HTTP and JSON and nothing else, so the
harness is :mod:`urllib` and :mod:`json`. A Snowflake driver in a dependency
group would install a vendor SDK for two endpoints, and S-0012/D-4 keeps the
engine drivers this repository does carry test-only for the same reason: what
a lane needs is the smallest thing that can ask the engine a question.

**Why the endpoint may come from the environment.** ``BLOOMERY_SNOWFLAKE_EMULATOR_URL``
points the harness at an already-running emulator — a CI service container, a
local ``docker run`` — and is what makes the lane runnable where testcontainers
is not. Absent it, the harness starts the pinned image itself; absent Docker,
:func:`unavailable` gives the caller a reason to skip with (S-0013/D-7: a lane
that finds no way to reach its engine skips saying so rather than failing).

**The image is pinned, and not to the newest tag.** ``main`` and every tag
built after 2026-04-27 do not start at all: the Dockerfile builds on
``rust:1.95-slim`` (trixie, glibc 2.41) and runs on ``debian:bookworm-slim``
(glibc 2.36), so the binary dies on its own loader with ``version
'GLIBC_2.38' not found``. ``sha-a57ece0`` is the newest tag whose binary
links against 2.35 and therefore runs. An emulator that cannot start is not a
lane, and `latest` — which the emulator's README advertises — has never been
published.

**The live account is credentials from the environment and nothing else**
(S-0013/D-7). ``BLOOMERY_SNOWFLAKE_ACCOUNT`` names the account identifier and
``BLOOMERY_SNOWFLAKE_TOKEN`` carries the bearer token — a programmatic access
token by default, another type by naming it in
``BLOOMERY_SNOWFLAKE_TOKEN_TYPE`` — so nothing reaches the repository and a
lane that finds neither gets a sentence from :func:`credentials_missing` to
skip with. The optional context variables (database, schema, warehouse, role)
travel in the submission body, which is where the SQL API takes them.

**Executing is a further step, gated on a further variable.** The compile lane
submits nothing but ``EXPLAIN`` and so needs no warehouse at all;
:func:`execution_missing` is what the lane that *runs* statements skips on, and
:func:`scratch_database` is where everything it creates goes — a transient
database named for the run, dropped when the run ends.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

__all__ = [
    "ACCOUNT_ENV",
    "ENDPOINT_ENV",
    "IMAGE",
    "TOKEN_ENV",
    "Answer",
    "Emulator",
    "SqlApi",
    "account",
    "credentials_missing",
    "emulator",
    "execution_missing",
    "scratch_database",
    "unavailable",
]

#: The default local lane's engine (S-0013/D-3), pinned to an exact tag: a
#: surrogate whose version can change under the lane cannot tell a regression
#: from an upgrade (S-0014/D-3, the same rule one port over). See the module
#: docstring for why this tag rather than the newest one.
IMAGE = "ghcr.io/sivchari/snowflake-emulator:sha-a57ece0"

#: An emulator someone else started: the harness talks to it instead of
#: starting its own.
ENDPOINT_ENV = "BLOOMERY_SNOWFLAKE_EMULATOR_URL"

_PORT = 8080

#: How long the emulator gets to answer ``/health`` after its container starts,
#: and how long a submitted statement gets before the harness stops polling.
_READY_SECONDS = 60.0
_POLL_SECONDS = 60.0
_POLL_INTERVAL = 0.05

#: The emulator returns every value as text and names its type in
#: ``rowType``; a fraction wider than :class:`~datetime.datetime` carries is
#: truncated rather than refused, because nanoseconds are the emulator's
#: spelling of a timestamp and six digits is Python's.
_SUB_SECOND = re.compile(r"(\.\d{6})\d+\Z")


@dataclass(frozen=True)
class Answer:
    """One statement's outcome: the rows it returned, or why it was refused."""

    status: int
    #: ``(name, Snowflake type)`` per column, from ``resultSetMetaData``.
    columns: tuple[tuple[str, str], ...] = ()
    rows: tuple[tuple[object, ...], ...] = ()
    code: str | None = None
    message: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == 200


class SqlApi:
    """A client for one SQL API v2 endpoint — an emulator, or an account.

    ``headers`` carries whatever the endpoint needs to authenticate (nothing,
    for the emulator) and ``context`` the session fields — database, schema,
    warehouse, role — the SQL API takes in the submission body rather than in a
    connection string.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        context: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json", **(headers or {})}
        self._context = dict(context or {})

    # ....................... #

    def submit(
        self,
        statement: str,
        *,
        asynchronous: bool = False,
        parameters: dict[str, str] | None = None,
    ) -> Answer:
        """Submit ``statement`` and return what the endpoint made of it.

        ``asynchronous`` takes the SQL API's other path: the submission is
        answered ``202`` with a handle, and the result is polled for. Real
        Snowflake answers ``202`` on its own whenever a statement outruns the
        request timeout, so the polling loop is not optional machinery — this
        flag is how the lane gets to exercise it deliberately.

        ``parameters`` carries session parameters for this submission alone —
        ``TIMEZONE`` is the one a lane needs, because every submission gets its
        own session and an ``ALTER SESSION`` would not survive to the next
        statement. Asking the same question under two zones is how a zoneless
        value is told from one that renders against the reader (S-0013/D-1).
        """
        query = "?async=true" if asynchronous else ""
        body: dict[str, object] = {
            "statement": statement,
            "timeout": int(_POLL_SECONDS),
            **self._context,
        }
        if parameters:
            body["parameters"] = parameters
        answer = self._request(f"{self.base_url}/api/v2/statements{query}", body=body)
        if answer.status != 202:
            return answer
        return self._poll(answer)

    def explain(self, statement: str) -> Answer:
        """Submit ``statement`` for compilation only (S-0013/authoritative-layers).

        ``EXPLAIN`` runs the engine's parser, binder and function resolution and
        produces a plan without executing, so a lane built on it can neither
        scan nor bill — and on Snowflake it needs no running warehouse.
        """
        return self.submit(f"EXPLAIN USING JSON {statement}")

    def rows(
        self, statement: str, *, parameters: dict[str, str] | None = None
    ) -> tuple[tuple[object, ...], ...]:
        """The canonicalized rows of a statement the endpoint must accept."""
        answer = self.submit(statement, parameters=parameters)
        if not answer.accepted:
            msg = f"{self.base_url} refused {statement!r}: {answer.code} {answer.message}"
            raise AssertionError(msg)
        return answer.rows

    def using(self, **context: str) -> SqlApi:
        """The same endpoint, with the session context these fields override.

        The SQL API carries database, schema, warehouse and role in the body of
        every submission rather than in a connection, and each submission gets
        its own session — so a ``USE DATABASE`` does not survive to the next
        statement, and the context is the only way a lane points at something
        it created.
        """
        return SqlApi(
            self.base_url, headers=self._headers, context={**self._context, **context}
        )

    # ....................... #

    def _poll(self, accepted: Answer) -> Answer:
        handle = accepted.message  # the handle, carried out of the 202 body
        deadline = time.monotonic() + _POLL_SECONDS
        while True:
            answer = self._request(f"{self.base_url}/api/v2/statements/{handle}")
            if answer.status != 202:
                return answer
            if time.monotonic() >= deadline:
                msg = f"statement {handle} was still running after {_POLL_SECONDS}s"
                raise AssertionError(msg)
            time.sleep(_POLL_INTERVAL)

    def _request(self, url: str, *, body: dict[str, object] | None = None) -> Answer:
        data = json.dumps(body).encode() if body is not None else None
        # The SQL API is the whole surface: one POST to submit, one GET to poll.
        request = urllib.request.Request(url, data=data, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=_POLL_SECONDS) as response:
                return _answer(response.status, json.load(response))
        except urllib.error.HTTPError as refusal:
            # A refused statement is an answer, not a transport failure: the
            # emulator says 422 and names the reason, which is what a lane
            # measuring an emulator's gaps is here to read.
            return _answer(refusal.status, json.load(refusal))

    def wait_until_ready(self, *, seconds: float = _READY_SECONDS) -> None:
        deadline = time.monotonic() + seconds
        while True:
            try:
                with urllib.request.urlopen(f"{self.base_url}/health", timeout=5) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError) as exc:
                last = exc
            else:
                last = None
            if time.monotonic() >= deadline:
                msg = f"{self.base_url} did not become healthy in {seconds}s ({last})"
                raise AssertionError(msg)
            time.sleep(0.2)


#: The surrogate lane's name for the client (S-0013/D-3, D-4). One protocol,
#: two names on purpose: a lane talking to an emulator says so in every line it
#: reads, and never borrows the word a real account's lane uses.
Emulator = SqlApi


def _answer(status: int, payload: dict[str, object]) -> Answer:
    if status == 202:
        # The submission was accepted asynchronously; everything that matters
        # is the handle, which `_poll` reads back out of `message`.
        handle = payload.get("statementHandle")
        return Answer(status=202, message=str(handle))
    if status != 200:
        return Answer(
            status=status,
            code=str(payload.get("code")),
            message=str(payload.get("message")),
        )
    metadata = payload.get("resultSetMetaData") or {}
    assert isinstance(metadata, dict)
    row_type = metadata.get("rowType") or []
    assert isinstance(row_type, list)
    columns = tuple((str(c["name"]), str(c["type"])) for c in row_type)
    data = payload.get("data") or []
    assert isinstance(data, list)
    rows = tuple(
        tuple(_canonical(value, type_) for value, (_name, type_) in zip(row, columns, strict=True))
        for row in data
    )
    return Answer(status=200, columns=columns, rows=rows)


def _canonical(value: str | None, type_: str) -> object:
    """One cell, as the type the emulator declared for its column.

    Every value crosses the SQL API as text, so a lane comparing against
    Python values has to put the types back — and it has to put them back the
    same way every time, or two lanes reading the same column disagree about
    what they read. Decimals stay :class:`~decimal.Decimal` and never become
    floats (S-0020/D-5).
    """
    if value is None:
        return None
    if type_ == "FIXED":
        # Snowflake's one fixed-point type: an integer is the scale-0 case,
        # and the emulator does not carry the scale in the value.
        return int(value) if value.lstrip("-").isdigit() else Decimal(value)
    if type_ == "REAL":
        return Decimal(value)
    if type_ == "BOOLEAN":
        return value.lower() == "true"
    if type_ == "DATE":
        return date.fromisoformat(value)
    if type_.startswith("TIMESTAMP"):
        return datetime.fromisoformat(_SUB_SECOND.sub(r"\1", value))
    if type_ in {"VARIANT", "OBJECT", "ARRAY"}:
        return json.loads(value)
    return value


def unavailable() -> str | None:
    """Why this machine cannot reach an emulator, or ``None`` if it can.

    The reason is a sentence a skip can carry: a contributor with no Docker
    reads what was missing rather than a red lane (S-0013/D-7).
    """
    if os.environ.get(ENDPOINT_ENV):
        return None
    try:
        import docker
    except ImportError:  # pragma: no cover — the engines group is installed
        return f"no {ENDPOINT_ENV} and the docker client is not installed"
    try:
        docker.from_env().ping()
    except Exception as exc:  # every failure here is the same skip
        return f"no {ENDPOINT_ENV} and no Docker daemon to start {IMAGE}: {exc}"
    return None


# ....................... #
# The real account (S-0013/D-7): credentials from the environment, never here


#: The account identifier, as it appears in the account URL.
ACCOUNT_ENV = "BLOOMERY_SNOWFLAKE_ACCOUNT"

#: The bearer token. Never a password, never a key file: the SQL API takes a
#: token and this harness never learns how one was minted.
TOKEN_ENV = "BLOOMERY_SNOWFLAKE_TOKEN"

#: Which kind of token, for the header Snowflake requires beside the bearer.
TOKEN_TYPE_ENV = "BLOOMERY_SNOWFLAKE_TOKEN_TYPE"
_DEFAULT_TOKEN_TYPE = "PROGRAMMATIC_ACCESS_TOKEN"

#: Session context, all optional: a compile-only lane needs no warehouse, and
#: an unqualified relation resolves against whatever the account defaults to.
_CONTEXT_ENV = {
    "database": "BLOOMERY_SNOWFLAKE_DATABASE",
    "schema": "BLOOMERY_SNOWFLAKE_SCHEMA",
    "warehouse": "BLOOMERY_SNOWFLAKE_WAREHOUSE",
    "role": "BLOOMERY_SNOWFLAKE_ROLE",
}


def credentials_missing() -> str | None:
    """Why this environment cannot reach an account, or ``None`` if it can.

    A sentence a skip can carry rather than a red lane: the live lanes run
    behind a GitHub Environment and on nobody's laptop by default, and a lane
    failing on an absent variable would train everyone to ignore it
    (S-0013/D-7).
    """
    absent = [name for name in (ACCOUNT_ENV, TOKEN_ENV) if not os.environ.get(name)]
    if absent:
        return f"no Snowflake account reachable: {' and '.join(absent)} is not set"
    return None


def execution_missing() -> str | None:
    """Why this environment cannot *execute* on an account, or ``None``.

    Everything :func:`credentials_missing` asks for, and a warehouse besides.
    A statement that scans needs one; ``EXPLAIN`` does not, which is what keeps
    the compile lane structurally unable to reach a warehouse and this one
    honest about needing a separate job (S-0013/local-execution).
    """
    reason = credentials_missing()
    if reason:
        return reason
    variable = _CONTEXT_ENV["warehouse"]
    if not os.environ.get(variable):
        return f"no Snowflake warehouse to execute on: {variable} is not set"
    return None


def account() -> SqlApi:
    """A client for the account the environment names.

    No context manager and nothing to tear down, because the compile lane
    creates nothing — that is what makes it safe to point at a real account.
    """
    identifier = os.environ[ACCOUNT_ENV]
    token = os.environ[TOKEN_ENV]
    return SqlApi(
        f"https://{identifier}.snowflakecomputing.com",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Snowflake-Authorization-Token-Type": os.environ.get(
                TOKEN_TYPE_ENV, _DEFAULT_TOKEN_TYPE
            ),
            "Accept": "application/json",
            # Snowflake's SQL API wants a caller it can name in its own logs.
            "User-Agent": "bloomery-tests/1",
        },
        context={
            field: value
            for field, name in _CONTEXT_ENV.items()
            if (value := os.environ.get(name, ""))
        },
    )


@contextmanager
def scratch_database(client: SqlApi, schemas: Sequence[str] = ()) -> Iterator[SqlApi]:
    """A database of this run's own, with ``schemas`` in it, dropped on the way out.

    Named for the run and never for the lane: an account is shared by every job
    pointed at it, and a relation found by a literal another run also uses is
    the failure that presents as whichever lane the scheduler interleaved with.

    ``TRANSIENT`` so nothing here carries fail-safe storage — an interrupted run
    leaves a database nobody is billed a recovery window for, and the drop is in
    a ``finally`` so a failing assertion still tidies up.
    """
    database = f"bloomery_t_{uuid4().hex[:8]}"
    client.rows(f"CREATE TRANSIENT DATABASE {database}")
    try:
        bound = client.using(database=database)
        for schema in schemas:
            bound.rows(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        yield bound
    finally:
        client.rows(f"DROP DATABASE IF EXISTS {database}")


@contextmanager
def emulator() -> Iterator[Emulator]:
    """A running emulator: the one the environment names, or a fresh container.

    The container is the caller's own — testcontainers publishes the port on a
    fresh host port per container, so two lanes on one machine never collide
    over a fixed one.
    """
    endpoint = os.environ.get(ENDPOINT_ENV)
    if endpoint:
        client = Emulator(endpoint)
        client.wait_until_ready()
        yield client
        return

    from testcontainers.core.container import DockerContainer

    container = DockerContainer(IMAGE).with_exposed_ports(_PORT)
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(_PORT)
        client = Emulator(f"http://{host}:{port}")
        client.wait_until_ready()
        yield client
