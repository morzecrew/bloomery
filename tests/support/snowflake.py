"""Snowflake surrogate harness (S-0013/D-3): the OSS emulator, reached over its
SQL API v2 surface, with submission, polling and row canonicalization.

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
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

__all__ = [
    "ENDPOINT_ENV",
    "IMAGE",
    "Answer",
    "Emulator",
    "emulator",
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


class Emulator:
    """A client for one running emulator."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    # ....................... #

    def submit(self, statement: str, *, asynchronous: bool = False) -> Answer:
        """Submit ``statement`` and return what the emulator made of it.

        ``asynchronous`` takes the SQL API's other path: the submission is
        answered ``202`` with a handle, and the result is polled for. Real
        Snowflake answers ``202`` on its own whenever a statement outruns the
        request timeout, so the polling loop is not optional machinery — this
        flag is how the lane gets to exercise it deliberately.
        """
        query = "?async=true" if asynchronous else ""
        answer = self._request(
            f"{self.base_url}/api/v2/statements{query}",
            body={"statement": statement, "timeout": int(_POLL_SECONDS)},
        )
        if answer.status != 202:
            return answer
        return self._poll(answer)

    def rows(self, statement: str) -> tuple[tuple[object, ...], ...]:
        """The canonicalized rows of a statement the emulator must accept."""
        answer = self.submit(statement)
        if not answer.accepted:
            msg = f"the emulator refused {statement!r}: {answer.code} {answer.message}"
            raise AssertionError(msg)
        return answer.rows

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
        # Plain HTTP to a local emulator: the SQL API is the whole surface.
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
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
