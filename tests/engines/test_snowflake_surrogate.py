"""Surrogate lane (rung 4) for the Snowflake port: the shared fixture corpus,
rendered for Snowflake, submitted to the OSS emulator (S-0013/D-3).

**Evidence, never the oracle** (S-0012/D-1). The lane is marked ``surrogate``
and never ``engine``, so a green run here cannot be read in a CI log as
Snowflake conformance — what it says is that something Snowflake-shaped
accepted, or refused, what bloomery rendered. The oracle is the account's own
compiler, which is phase 3's lane.

**What the emulator turned out to be able to do, measured over the whole
corpus rather than assumed.** Of the 128 statements the corpus renders for
Snowflake, none execute and 48 reach planning — the emulator's parser accepts
them and then cannot find a relation, because there is nothing to find:

- ``CREATE SCHEMA`` answers *"Schema BRONZE successfully created."* and
  creates nothing, so no relation can be placed in ``bronze``, ``silver`` or
  ``gold`` and no model bloomery emits has anywhere to be built;
- ``TIMESTAMP_NTZ`` — the type S-0013/D-1 locks ``timestamp`` to — is refused
  as a type outright, as is ``NUMBER(38, 0)``, which is what the port maps
  ``int`` to (S-0013/D-6);
- Snowflake's untyped ``ARRAY``, which every silver model casts an empty
  ``ARRAY_CONSTRUCT()`` to for ``_quality_flags``, does not parse.

So the lane asserts what an emulator in this state can be asked: that every
rendered statement is *answered*, and that every refusal is either the
emulator having no relations or a gap in the emulator's own parser — the
second measured against SQLGlot's Snowflake parser, so a rendering that
neither accepts is a finding about bloomery and fails here. The four
constructs above are pinned as gaps in :func:`test_the_measured_gaps_are_still_gaps`,
which turns red when a future image closes one — the evidence S-0013/D-5 asks
whoever runs both emulators to count.

Opt-in (Docker, or an emulator named by ``BLOOMERY_SNOWFLAKE_EMULATOR_URL``);
excluded from ``just test``, and skipped with a stated reason when neither is
there (S-0013/D-7).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from uuid import uuid4

import pytest
import sqlglot
from sqlglot.errors import SqlglotError
from support.compiling import compile_fixture, extract_select, spec_fixture_names
from support.snowflake import Emulator, emulator, unavailable

from bloomery.errors import BloomeryError

pytestmark = pytest.mark.surrogate("snowflake_emulator")

#: The fixtures that never reach the emulator because the Snowflake port
#: refuses them at compile, by name and by reason. Three are dialect-blind —
#: two guardrail refusals and ``convert``, which S-0040/D-4 refuses on every
#: dialect — and one is this port's own: ``normalize`` has no Snowflake
#: spelling, so the capability flag refuses it at emit rather than letting it
#: compile clean and die on a function the engine never defined (S-0013/D-2).
COMPILE_REFUSED = {
    "currency_convert_refusal",
    "dirty_corpus",
    "fanout_trap",
    "scd2_mart_refusal",
}

#: The emulator has no relations at all, so every statement that gets past its
#: parser dies here. That is the *good* outcome for this lane: the rendering
#: was accepted as Snowflake SQL.
_REACHED_PLANNING = re.compile(r"table '[^']*' not found|failed to resolve schema")

#: Constructs the pinned emulator cannot take, each one something the Snowflake
#: port emits. Checked against SQLGlot's Snowflake parser in the same test, so
#: the claim is "the surrogate lacks this", not "this is wrong".
KNOWN_GAPS = {
    # `_quality_flags` on every silver model (S-0033/D-23).
    "an empty array cast to Snowflake's untyped ARRAY": (
        "SELECT CAST(ARRAY_CONSTRUCT() AS ARRAY) AS flags"
    ),
    # What `timestamp` lowers to, and may never stop lowering to (S-0013/D-1).
    "the zoneless timestamp type": (
        "SELECT CAST('2026-01-02 03:04:05' AS TIMESTAMP_NTZ) AS occurred_at"
    ),
    # What `int` lowers to: Snowflake stores integers as NUMBER(38, 0) and
    # its BIGINT is a synonym for exactly that (S-0013/D-6).
    "Snowflake's fixed-point integer type": "SELECT CAST('7' AS NUMBER(38, 0)) AS n",
}


@pytest.fixture(scope="module")
def surrogate() -> Iterator[Emulator]:
    reason = unavailable()
    if reason:
        pytest.skip(reason)
    with emulator() as client:
        yield client


@pytest.fixture(scope="module")
def corpus() -> tuple[tuple[str, str, str], ...]:
    """``(fixture, artifact path, SQL)`` for the whole shared corpus.

    The shared fixtures rather than Snowflake-native ones (S-0012/D-6): a
    divergence between ports has to present as one fixture behaving
    differently, which a port-native corpus could never show.
    """
    rendered = []
    for name in sorted(set(spec_fixture_names()) - COMPILE_REFUSED):
        for artifact in compile_fixture(name, dialect="snowflake"):
            if artifact.path.endswith(".sql"):
                rendered.append((name, artifact.path, extract_select(artifact.content)))
    return tuple(rendered)


# ....................... #
# The harness itself: connection, submission, polling, canonicalization


def test_the_harness_round_trips_a_seeded_table(surrogate: Emulator) -> None:
    """Values go out as SQL and come back as Python, typed by what the
    emulator declared for each column."""
    # The emulator may be one someone else started and shared, so the table is
    # named for this test run and never for the test.
    table = f"bloomery_canon_{uuid4().hex[:8]}"
    surrogate.rows(f"CREATE TABLE {table} (id VARCHAR, n VARCHAR, ok VARCHAR, day VARCHAR)")
    surrogate.rows(f"INSERT INTO {table} VALUES ('r1', '7', 'true', '2026-01-02')")

    rows = surrogate.rows(
        f"SELECT id, CAST(n AS INT) AS n, CAST(ok AS BOOLEAN) AS ok, "  # noqa: S608 — a name this test minted
        f"CAST(day AS DATE) AS day, CAST('2026-01-02 03:04:05' AS TIMESTAMP) AS ts "
        f"FROM {table}"
    )

    assert rows == (("r1", 7, True, date(2026, 1, 2), datetime(2026, 1, 2, 3, 4, 5)),)


def test_a_null_comes_back_as_none(surrogate: Emulator) -> None:
    assert surrogate.rows("SELECT CAST(NULL AS VARCHAR) AS absent") == ((None,),)


def test_an_asynchronous_statement_is_polled_to_completion(surrogate: Emulator) -> None:
    """Real Snowflake answers ``202`` whenever a statement outruns the request
    timeout, so the polling path is not optional — and a path no test takes is
    a path that works until the day it is needed."""
    answer = surrogate.submit("SELECT 1 AS one", asynchronous=True)

    assert answer.accepted
    assert answer.rows == ((1,),)


# ....................... #
# The corpus


def test_the_port_refuses_exactly_these_fixtures_at_compile() -> None:
    """Nothing reaches an engine that the compiler refused first, so the
    refused set is part of what this lane covers rather than a footnote to
    it."""
    refused = set()
    for name in spec_fixture_names():
        try:
            compile_fixture(name, dialect="snowflake")
        except BloomeryError:
            refused.add(name)

    assert refused == COMPILE_REFUSED


def test_every_rendered_statement_is_answered_by_the_surrogate(
    surrogate: Emulator, corpus: tuple[tuple[str, str, str], ...]
) -> None:
    """Every statement the corpus renders for Snowflake is submitted, and each
    refusal is either the emulator having no relations or the emulator's own
    parser — never a rendering no Snowflake parser accepts.

    A statement SQLGlot's Snowflake parser also refuses is the failure this
    test exists to catch: that would be bloomery rendering SQL the dialect
    does not have, which no amount of emulator immaturity explains.
    """
    planned: list[str] = []
    gaps: list[str] = []
    for name, path, sql in corpus:
        answer = surrogate.submit(sql)
        if answer.accepted:
            planned.append(f"{name}/{path}")
            continue
        assert answer.message is not None, f"{name}/{path}: refused with no reason"
        if _REACHED_PLANNING.search(answer.message):
            planned.append(f"{name}/{path}")
            continue
        try:
            sqlglot.parse(sql, read="snowflake")
        except SqlglotError as broken:
            pytest.fail(
                f"{name}/{path} is refused by the emulator and by SQLGlot's own "
                f"Snowflake parser — emulator: {answer.message}; SQLGlot: {broken}"
            )
        gaps.append(f"{name}/{path}")

    # A parser that stopped accepting everything would otherwise read as a
    # long, quiet list of gaps.
    assert planned, f"no statement reached the emulator's planner; {len(gaps)} gaps"


def test_the_measured_gaps_are_still_gaps(surrogate: Emulator) -> None:
    """Each pinned gap is refused by the emulator and accepted by SQLGlot's
    Snowflake parser.

    Red here is not a regression: it is a gap closing, and the lane saying so
    is what lets S-0013/D-5 be decided on counted defects rather than on when
    somebody last looked.
    """
    for description, statement in KNOWN_GAPS.items():
        sqlglot.parse_one(statement, read="snowflake")
        answer = surrogate.submit(statement)
        assert not answer.accepted, f"the emulator now takes {description}: {statement}"


def test_the_surrogate_cannot_host_a_namespace(surrogate: Emulator) -> None:
    """``CREATE SCHEMA`` reports success and creates nothing, which is why no
    model in this corpus can be built rather than merely parsed.

    Stated as its own test because the failure mode is silence: the statement
    answers *"Schema ... successfully created."*, and a harness that trusted
    that answer would report a missing relation later and far from the cause.
    """
    schema = f"bloomery_ns_{uuid4().hex[:8]}"
    created = surrogate.rows(f"CREATE SCHEMA {schema}")

    assert created and "successfully created" in str(created[0][0])
    assert not surrogate.submit(f"CREATE TABLE {schema}.t (id VARCHAR)").accepted
