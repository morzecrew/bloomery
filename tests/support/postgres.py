"""The PostgreSQL 16 container the reference differentials share (S-0092/D-2).

One ``postgres:16-alpine`` container per session, one connection, its session
time zone set to UTC — the zoneless-UTC reading every timestamp comparison in
the differential assumes (S-0081). The image is pinned like every engine
module's, because a tier whose engine version can move under it cannot tell a
regression from an upgrade (S-0014/D-3); the Docker tiers are opt-in and
excluded from ``just test``.

``POSTGRES_DIFFERENCES`` is the PostgreSQL half's register of allowed engine
differences, in the shape :mod:`support.engine_differences` defines (S-0092/D-3):
a difference is a written row or a defect, never a tolerance. It lives beside
the harness rather than in the shared table because the shared table is scoped
to :mod:`support.reference`'s DuckDB half; the differential consults both.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from support.engine_differences import Difference

#: Pinned, matching the sibling engine modules: a tier whose engine version can
#: change under it cannot tell a regression from an upgrade (S-0014/D-3).
POSTGRES_IMAGE = "postgres:16-alpine"


@pytest.fixture(scope="session")
def postgres() -> Iterator[psycopg.Connection]:
    """A session-scoped connection whose session time zone is UTC.

    ``autocommit`` so a statement the differential deliberately refuses (an
    overflow cast an :data:`support.reference.OVERFLOW` demands) leaves no
    aborted transaction behind for the next drawn example."""
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        connection = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
            autocommit=True,
        )
        connection.execute("SET TIME ZONE 'UTC'")
        yield connection
        connection.close()


#: PostgreSQL's ``split_part`` answers ``''`` where the portable reading a
#: declared ``nullifies=True`` transform carries is NULL — the same divergence
#: DuckDB shows, because ``split_part`` returns an empty string for an index
#: past the last field rather than NULL (``varlena.c``). The engine is held to
#: ``''`` exactly, not to a wideness (S-0092/D-4).
POSTGRES_DIFFERENCES: tuple[Difference, ...] = (
    Difference(
        engine="postgres",
        transform="split_part",
        predicate=lambda source: True,
        held_to=lambda produced, reference: produced == ("" if reference is None else reference),
        justification=(
            "src/bloomery/transforms/_builtins.py:264 — split_part declares "
            "nullifies=True on the portable NULL reading; PostgreSQL answers '' "
            "for an out-of-range index"
        ),
    ),
)