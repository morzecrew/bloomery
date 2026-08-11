"""A running Cube, over a Postgres holding the mart it describes.

Shared by the two tiers that need Cube alive (RFC 0009 §5.2 tier 6 and §5.8's
equivalence tier), because standing it up is the expensive part and neither
tier is about the standing up.

**The pairing is the point.** Cube's ``sql_table`` names ``gold.mart_<name>``
under the naming policy, and the planner's SQL reads the *same* relation — so
if both are pointed at one Postgres, the two legs are reading one table by
construction rather than by two seeding routines that must be kept in step.
That is what makes an equivalence result mean something: a difference can only
come from the query, never from the data.

The mart table is created from ``MartIR`` through the Postgres dialect port —
the same port that types the emitted DDL — rather than hand-written per
fixture. A column list written out here would be a third statement of the
schema, free to drift from the two that matter.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from bloomery.dialects import get_dialect
from bloomery.ir import Layer, MartIR
from bloomery.naming import DefaultNaming

__all__ = [
    "CUBE_IMAGE",
    "POSTGRES_IMAGE",
    "CubeStack",
    "cube_stack",
    "mart_relation",
]

#: Pinned rather than ``latest``. A tier whose engine version moves under it
#: cannot tell a regression from an upgrade — the same reason the Trino tier
#: pins (RFC 0009 D21).
CUBE_IMAGE = "cubejs/cube:v1.7.18"
POSTGRES_IMAGE = "postgres:16-alpine"

_DB = "bloomery"
_USER = "bloomery"
_PASSWORD = "bloomery"  # nosec B105 — a throwaway container credential
_PORT = get_dialect("postgres")


def mart_relation(mart: MartIR) -> tuple[str, str]:
    """``(namespace, relation)`` for a mart, under the default naming policy —
    read from the policy rather than spelled, so this harness and the emitters
    cannot disagree about where the table is."""
    return DefaultNaming().relation(mart.name, Layer.GOLD)


@dataclass(frozen=True, slots=True)
class CubeStack:
    """A live Cube and the Postgres beneath it."""

    connection: psycopg.Connection
    api: str

    def meta(self) -> dict[str, Any]:
        return self._get("meta", {})

    def load(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        """One Cube query, as rows. Cube answers ``continueWait`` while a query
        is still running, so this polls rather than reading the first reply as
        an answer — a silent empty frame would make every equivalence
        comparison trivially pass."""
        for _attempt in range(30):
            payload = self._get("load", {"query": json.dumps(query)})
            if "error" not in payload:
                return list(payload["data"])
            if "Continue wait" not in str(payload["error"]):
                msg = f"cube refused the query: {payload['error']}"
                raise RuntimeError(msg)
            time.sleep(1)
        msg = "cube did not answer within the wait budget"
        raise RuntimeError(msg)

    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request = urllib.request.Request(f"{self.api}/{endpoint}{query}")  # noqa: S310
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return json.loads(response.read())


def _create_mart(connection: psycopg.Connection, mart: MartIR) -> None:
    namespace, relation = mart_relation(mart)
    columns = ", ".join(
        f'"{column.name}" {_PORT.physical_type(column.type)}' for column in mart.columns
    )
    connection.execute(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
    connection.execute(f'CREATE TABLE {namespace}."{relation}" ({columns})')


def _insert(connection: psycopg.Connection, mart: MartIR, rows: Sequence[Sequence[Any]]) -> None:
    namespace, relation = mart_relation(mart)
    names = ", ".join(f'"{column.name}"' for column in mart.columns)
    placeholders = ", ".join(["%s"] * len(mart.columns))
    with connection.cursor() as cursor:
        cursor.executemany(
            f'INSERT INTO {namespace}."{relation}" ({names}) VALUES ({placeholders})', rows
        )
    connection.commit()


@contextmanager
def cube_stack(
    mart: MartIR, schema: Sequence[tuple[str, str]], rows: Sequence[Sequence[Any]]
) -> Iterator[CubeStack]:
    """Postgres + Cube on one network, with ``mart`` created and seeded.

    ``schema`` is the emitted Cube model as ``(path, content)`` pairs, written
    into the container's model directory — the artifacts under test, not a
    hand-written schema.
    """
    with Network() as network:
        postgres = (
            DockerContainer(POSTGRES_IMAGE)
            .with_env("POSTGRES_DB", _DB)
            .with_env("POSTGRES_USER", _USER)
            .with_env("POSTGRES_PASSWORD", _PASSWORD)
            .with_exposed_ports(5432)
            .with_network(network)
            .with_network_aliases("warehouse")
            .waiting_for(
                LogMessageWaitStrategy("database system is ready to accept connections")
            )
        )
        with postgres:
            connection = psycopg.connect(
                host=postgres.get_container_host_ip(),
                port=int(postgres.get_exposed_port(5432)),
                user=_USER,
                password=_PASSWORD,
                dbname=_DB,
            )
            _create_mart(connection, mart)
            _insert(connection, mart, rows)
            cube = (
                DockerContainer(CUBE_IMAGE)
                # Dev mode is what makes the REST API answer without a signed
                # JWT. It is a *test* affordance and says nothing about how
                # bloomery's output should be deployed.
                .with_env("CUBEJS_DEV_MODE", "true")
                .with_env("CUBEJS_DB_TYPE", "postgres")
                .with_env("CUBEJS_DB_HOST", "warehouse")
                .with_env("CUBEJS_DB_PORT", "5432")
                .with_env("CUBEJS_DB_NAME", _DB)
                .with_env("CUBEJS_DB_USER", _USER)
                .with_env("CUBEJS_DB_PASS", _PASSWORD)
                .with_env("CUBEJS_API_SECRET", "bloomery-test")
                .with_exposed_ports(4000)
                .with_network(network)
            )
            for path, content in schema:
                cube.with_copy_into_container(  # type: ignore[attr-defined]
                    content.encode(), f"/cube/conf/{path}"
                )
            with cube:
                api = (
                    f"http://{cube.get_container_host_ip()}:"
                    f"{cube.get_exposed_port(4000)}/cubejs-api/v1"
                )
                stack = CubeStack(connection=connection, api=api)
                _await_ready(stack)
                yield stack
            connection.close()


def _await_ready(stack: CubeStack) -> None:
    """Poll ``/meta`` until Cube has loaded the model.

    Cube serves the port before it has read the schema directory, so a test
    that queried immediately would see an empty cube list and read it as "the
    emitter produced nothing" — a false failure that looks exactly like a real
    one.
    """
    for _attempt in range(60):
        try:
            if stack.meta().get("cubes"):
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(2)
    msg = "cube never served a non-empty /meta"
    raise RuntimeError(msg)


def schema_files(artifacts: Sequence[Any]) -> list[tuple[str, str]]:
    """The Cube artifacts as ``(path, content)``, ready for the container."""
    return [(str(Path(artifact.path)), artifact.content) for artifact in artifacts]
