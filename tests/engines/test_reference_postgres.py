"""The PostgreSQL half of the transform differential (S-0092/D-2, S-0092/D-4).

Every built-in transform is compiled onto one field of a one-entity fixture,
its silver SQL is run against a real PostgreSQL 16 container, and the row's
value is required to equal :mod:`support.reference`'s **exact** answer — NULLs,
boundaries and the typed setup included. The comparison is exact except where a
:mod:`support.engine_differences` row, or a PostgreSQL row beside the container,
names a difference; a disagreement no row names fails, printing the input, the
engine's answer and the reference's.

The reference is the second, independent statement of each transform's
semantics (D-1); this module holds PostgreSQL to it. The DuckDB half, in
``tests/property/``, is the one every pull request guards and carries the
argument for the three self-checks — this half runs on a session-scoped
container (Docker required) and rides the engine job, so it repeats only the
one that would let the register silently stop applying.

The engine job's schedule widens to the ``nightly`` Hypothesis profile; a pull
request runs the ``ci`` profile (S-0092/D-5).
"""

from __future__ import annotations

import functools
import json
from datetime import date, datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import psycopg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.emit import ArtifactKind
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import StringType, render_type
from support.compiling import extract_select
from support.engine_differences import DIFERENCES, Difference
from support.postgres import POSTGRES_DIFFERENCES, postgres
from support.reference import (
    BUCKET_INSTANTS,
    BUCKET_UNITS,
    CASES,
    CHAIN_CASES,
    OVERFLOW,
    RECIPE_OPERANDS,
    ROLLUP_BRONZE_COLUMNS,
    ROLLUP_FILTERED_VALUE,
    ROLLUP_METRICS,
    ROLLUP_RELATION,
    ROLLUP_SOURCES,
    Case,
    ChainCase,
    Step,
    bucket,
    fold,
    recipe_quotient,
    rollup,
    rollup_bronze_rows,
)

pytestmark = pytest.mark.engine("postgres")

#: The sentinel for "the engine refused the row", against which an
#: :data:`OVERFLOW` reference is matched.
_RAISED = object()

#: How PostgreSQL is named in the differences register and in failure messages.
ENGINE = "postgres"

#: The register this half consults: the shared rows plus PostgreSQL's own.
REGISTER: tuple[Difference, ...] = DIFERENCES + POSTGRES_DIFFERENCES


# ----------------------- #
# One-entity fixture, built from a case


def _render_arg(value: str | int) -> str:
    return json.dumps(value) if isinstance(value, str) else str(value)


def _render_step(step: Step) -> str:
    name, args = step
    if not args:
        return name
    return f"{{{name}: [{', '.join(_render_arg(arg) for arg in args)}]}}"


def _render_chain(chain: tuple[Step, ...]) -> str:
    return ", ".join(_render_step(step) for step in chain)


def _terminal_type(chain: tuple[Step, ...]) -> str:
    """The chain's declared output type, as the entity field spells it.

    Walked over the registry's *declarations* only — the same claim the
    compiler typechecks against; none of the reference's value semantics come
    from here.
    """
    current = StringType()
    for name, args in chain:
        current = DEFAULT_REGISTRY[name].output_type(current, args)
    return render_type(current)


def _sources(case: Case) -> dict[str, str]:
    fixture = case.fixture
    fields = "".join(
        f"\n      {name}: {{type: {kind}}}" for name, kind in fixture.extra_fields
    )
    entity = (
        "spec_version: 1\n"
        "entities:\n"
        "  probe:\n"
        "    grain: one row per probe\n"
        "    key: [probe_id]\n"
        "    fields:\n"
        "      probe_id: {type: string}\n"
        f'      value: {{type: "{_terminal_type(case.chain)}"}}'
        f"{fields}\n"
    )
    extra = "".join(f"\n{line}" for line in fixture.extra_mapping)
    mapping = (
        "mapping_version: 1\n"
        "source: raw__probe\n"
        "target: probe\n"
        "key:\n"
        '  probe_id: {from: "$.id", transform: [to_string]}\n'
        "fields:\n"
        f"  value: {{{fixture.value_prefix}from: \"$.value\", "
        f"transform: [{_render_chain(case.chain)}]}}"
        f"{extra}\n"
    )
    return {"entity_model": entity, "mapping": mapping}


@functools.lru_cache(maxsize=None)
def _compiled(transform: str) -> tuple[str, tuple[str, ...]]:
    """``(silver select, seed statements)`` for one case."""
    case = next(c for c in CASES if c.transform == transform)
    fixture = case.fixture
    catalog = load_catalog(fixture.catalog) if fixture.catalog is not None else None
    project = load_project(_sources(case))
    artifacts = compile_project(
        project, target=Target.SQLMESH, dialect=ENGINE, catalog=catalog, steps=None
    )
    silver = next(a for a in artifacts if a.path.endswith("silver/probe.sql"))
    select = silver.content.split(");", 1)[1].strip()
    columns = ", ".join(
        ["id VARCHAR", "value VARCHAR"]
        + [f"{name} {kind}" for name, kind, _ in fixture.extra_columns]
    )
    setup = fixture.seed_sql + (f"CREATE TABLE bronze.raw__probe ({columns})",)
    return select, setup


#: Dropped and recreated before every drawn example, so each row starts in a
#: fresh pair of schemas and nothing another example left behind is read.
_RESET = (
    "DROP SCHEMA IF EXISTS bronze CASCADE",
    "DROP SCHEMA IF EXISTS silver CASCADE",
    "CREATE SCHEMA bronze",
    "CREATE SCHEMA silver",
)


def _run(connection: psycopg.Connection, case: Case, source: str | None) -> Any:
    """Seed one row and read the silver value, or ``_RAISED`` if the engine
    refused it (which an :data:`OVERFLOW` reference demands)."""
    select, setup = _compiled(case.transform)
    fixture = case.fixture
    for statement in (*_RESET, *setup):
        connection.execute(statement)
    extra = [fixed for _, _, fixed in fixture.extra_columns]
    placeholders = ", ".join(["%s"] * (2 + len(extra)))
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO bronze.raw__probe VALUES ({placeholders})",  # noqa: S608 — SQL we built
            ["probe", source, *extra],
        )
        try:
            cursor.execute(select)
            row = cursor.fetchone()
        except psycopg.Error:
            return _RAISED
        assert row is not None
        names = [column.name for column in cursor.description or ()]
        return row[names.index("value")]


# ----------------------- #
# Comparison (D-4), and the register (D-3)


def _zoneless_utc(value: Any) -> Any:
    """A timestamp as its zoneless UTC wall clock (D-4)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _difference_for(transform: str, source: Any) -> Difference | None:
    """The first register row licensing an answer for this case, or ``None``.

    The shared :func:`support.engine_differences.difference_for` searches DuckDB
    rows only; this half searches both registers (S-0092/D-3).
    """
    for row in REGISTER:
        if row.engine == ENGINE and row.transform == transform and row.predicate(source):
            return row
    return None


def _mismatch(case: Case, source: Any, produced: Any, expected: Any) -> str:
    return (
        f"{case.transform} on {ENGINE} disagreed with the reference for input "
        f"{source!r}: the engine answered {produced!r}, the reference says "
        f"{expected!r} (S-0092/D-4)"
    )


def assert_matches(
    case: Case,
    source: Any,
    produced: Any,
    expected: Any,
    *,
    differences: tuple[Difference, ...] = REGISTER,
) -> None:
    """The exact comparison, minus the differences ``differences`` names (D-3).

    ``produced`` is ``_RAISED`` when the engine refused the row; an
    :data:`OVERFLOW` reference requires exactly that, and any other engine
    refusal — or a value where the reference says one must be raised — is a
    failure.
    """
    if expected is OVERFLOW:
        if produced is _RAISED:
            return
        msg = (
            f"{case.transform} on {ENGINE} answered {produced!r} for input "
            f"{source!r}, but the reference says the value overflows its declared "
            "type and the engine must raise (S-0092/D-1)"
        )
        raise AssertionError(msg)

    if produced is _RAISED:
        msg = (
            f"{case.transform} on {ENGINE} refused input {source!r}, but the "
            f"reference says {expected!r} (S-0092/D-4)"
        )
        raise AssertionError(msg)

    # psycopg hands a ``jsonb`` column back already parsed, so — unlike the
    # DuckDB half, where the engine returns JSON as text — ``json_path`` needs
    # no decoding here; only the timestamp is normalised.
    engine_answer = _zoneless_utc(produced)
    if engine_answer == expected:
        return

    row = _difference_for(case.transform, source)
    if row is not None and row in differences and row.held_to(engine_answer, expected):
        return

    raise AssertionError(_mismatch(case, source, engine_answer, expected))


# ----------------------- #
# The differential


def _ids(case: Case) -> str:
    return case.transform


@pytest.mark.parametrize("case", CASES, ids=_ids)
@given(data=st.data())
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_postgres_answers_every_builtin_exactly_as_the_reference_does(
    postgres: psycopg.Connection, case: Case, data: Any
) -> None:
    source = data.draw(case.source)
    expected = case.reference(source)
    produced = _run(postgres, case, source)
    assert_matches(case, source, produced, expected)


# ----------------------- #
# The fixture's own guarantees (D-2)


def test_the_container_fixture_is_session_scoped() -> None:
    """One ``postgres:16-alpine`` container per session (S-0092/D-2), not one
    per drawn example.

    The fixture's marker is the statement; a regression to function scope — a
    fresh container for every input — has to fail here rather than go
    unnoticed. ``_fixture_function_marker`` is the name pytest 9's
    ``@pytest.fixture`` gives the marker it attaches to the wrapped function.
    """
    assert postgres._fixture_function_marker.scope == "session"


def test_the_session_time_zone_is_utc(postgres: psycopg.Connection) -> None:
    """The container's session time zone is UTC (S-0092/D-2).

    Every zoneless-UTC timestamp comparison in the differential (S-0081) reads
    this wall clock; a dropped ``SET TIME ZONE`` would make those comparisons
    engine-local without failing anywhere else.
    """
    with postgres.cursor() as cursor:
        cursor.execute("SHOW TIME ZONE")
        row = cursor.fetchone()
    assert row == ("UTC",)


# ----------------------- #
# The register, and the battery's own teeth


def test_a_wrong_reference_value_fails_naming_the_input_and_both_answers() -> None:
    case = next(c for c in CASES if c.transform == "trim")
    with pytest.raises(AssertionError) as caught:
        assert_matches(case, "  padded  ", "padded", "SHOUTING")

    message = str(caught.value)
    assert repr("  padded  ") in message
    assert repr("padded") in message
    assert repr("SHOUTING") in message


def test_postgres_is_held_to_a_named_difference_and_no_other() -> None:
    """An out-of-range ``split_part`` is the one difference PostgreSQL is
    allowed; take the row away and the same disagreement must fail, so the row
    cannot silently stop applying."""
    case = next(c for c in CASES if c.transform == "split_part")

    # The row licenses PostgreSQL's '' where the portable reading is NULL.
    assert_matches(case, "a", "", None)

    with pytest.raises(AssertionError) as caught:
        assert_matches(case, "a", "", None, differences=DIFERENCES)

    message = str(caught.value)
    assert repr("a") in message
    assert repr("") in message


# ----------------------- #
# Chains, recipes and time buckets (S-0092/D-6)


def _chain_sources(chain: tuple[Step, ...]) -> dict[str, str]:
    entity = (
        "spec_version: 1\n"
        "entities:\n"
        "  probe:\n"
        "    grain: one row per probe\n"
        "    key: [probe_id]\n"
        "    fields:\n"
        "      probe_id: {type: string}\n"
        f'      value: {{type: "{_terminal_type(chain)}"}}\n'
    )
    mapping = (
        "mapping_version: 1\n"
        "source: raw__probe\n"
        "target: probe\n"
        "key:\n"
        '  probe_id: {from: "$.id", transform: [to_string]}\n'
        "fields:\n"
        f'  value: {{from: "$.value", transform: [{_render_chain(chain)}]}}\n'
    )
    return {"entity_model": entity, "mapping": mapping}


@functools.lru_cache(maxsize=None)
def _chain_compiled(chain: tuple[Step, ...]) -> tuple[str, str]:
    """``(silver select, the CREATE TABLE for bronze.raw__probe)``."""
    project = load_project(_chain_sources(chain))
    artifacts = compile_project(
        project, target=Target.SQLMESH, dialect=ENGINE, catalog=None, steps=None
    )
    silver = next(a for a in artifacts if a.path.endswith("silver/probe.sql"))
    select = silver.content.split(");", 1)[1].strip()
    table = "CREATE TABLE bronze.raw__probe (id VARCHAR, value VARCHAR)"
    return select, table


def _run_chain(
    connection: psycopg.Connection, chain: tuple[Step, ...], source: str | None
) -> Any:
    select, table = _chain_compiled(chain)
    for statement in (*_RESET, table):
        connection.execute(statement)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO bronze.raw__probe VALUES (%s, %s)", ["probe", source]
        )
        try:
            cursor.execute(select)
            row = cursor.fetchone()
        except psycopg.Error:
            return _RAISED
        assert row is not None
        names = [column.name for column in cursor.description or ()]
        return row[names.index("value")]


_RECIPE_CATALOG = """
catalog_version: 1
vertical: probe
canonical_fields:
  num: {entity: probe, type: int, recipes: [{id: direct, requires: [num]}]}
  den: {entity: probe, type: int, recipes: [{id: direct, requires: [den]}]}
  quotient:
    entity: probe
    type: decimal(12,4)
    recipes:
      - {id: divide_ints, requires: [num, den], expr: "num / den"}
"""

_RECIPE_SOURCES = {
    "entity_model": (
        "spec_version: 1\n"
        "entities:\n"
        "  probe:\n"
        "    grain: one row per probe\n"
        "    key: [probe_id]\n"
        "    fields:\n"
        "      probe_id: {type: string}\n"
        "      num: {type: int, canonical: num}\n"
        "      den: {type: int, canonical: den}\n"
        '      quotient: {type: "decimal(12,4)", canonical: quotient}\n'
    ),
    "mapping": (
        "mapping_version: 1\n"
        "source: raw__probe\n"
        "target: probe\n"
        "key:\n"
        '  probe_id: {from: "$.id", transform: [to_string]}\n'
        "fields:\n"
        '  num: {from: "$.num", transform: [to_int]}\n'
        '  den: {from: "$.den", transform: [to_int]}\n'
        "  quotient:\n"
        "    recipe: divide_ints\n"
        '    from: {num: "$.num", den: "$.den"}\n'
    ),
}


@functools.lru_cache(maxsize=None)
def _recipe_compiled() -> tuple[str, str]:
    project = load_project(_RECIPE_SOURCES)
    artifacts = compile_project(
        project,
        target=Target.SQLMESH,
        dialect=ENGINE,
        catalog=load_catalog(_RECIPE_CATALOG),
        steps=None,
    )
    silver = next(a for a in artifacts if a.path.endswith("silver/probe.sql"))
    select = silver.content.split(");", 1)[1].strip()
    table = "CREATE TABLE bronze.raw__probe (id VARCHAR, num VARCHAR, den VARCHAR)"
    return select, table


def _run_recipe(connection: psycopg.Connection, pair: tuple[int, int]) -> Any:
    dividend, divisor = pair
    select, table = _recipe_compiled()
    for statement in (*_RESET, table):
        connection.execute(statement)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO bronze.raw__probe VALUES (%s, %s, %s)",
            ["probe", str(dividend), str(divisor)],
        )
        try:
            cursor.execute(select)
            row = cursor.fetchone()
        except psycopg.Error:
            return _RAISED
        assert row is not None
        names = [column.name for column in cursor.description or ()]
        return row[names.index("quotient")]


_BUCKET_SOURCES = {
    "entity_model": (
        "spec_version: 1\n"
        "entities:\n"
        "  probe:\n"
        "    grain: one row per probe\n"
        "    key: [probe_id]\n"
        "    fields:\n"
        "      probe_id: {type: string}\n"
        "      paid_at: {type: timestamp}\n"
    ),
    "mapping": (
        "mapping_version: 1\n"
        "source: raw__probe\n"
        "target: probe\n"
        "key:\n"
        '  probe_id: {from: "$.id", transform: [to_string]}\n'
        "fields:\n"
        "  paid_at:\n"
        '    from: "$.paid_at"\n'
        "    transform: [{parse_ts: ISO8601}]\n"
        "    zone_in: UTC\n"
    ),
    "marts": (
        "marts_version: 1\n"
        "marts:\n"
        "  probes:\n"
        "    grain: probe\n"
        "    base: probe\n"
        "    flatten:\n"
        "      - {date: paid_at, role: paid}\n"
    ),
}


@functools.lru_cache(maxsize=None)
def _bucket_artifacts() -> tuple[Any, ...]:
    project = load_project(_BUCKET_SOURCES)
    return compile_project(
        project, target=Target.SQLMESH, dialect=ENGINE, catalog=None, steps=None
    )


#: Bronze, silver and gold — the mart case needs the third schema.
_RESET_ALL = (*_RESET, "DROP SCHEMA IF EXISTS gold CASCADE", "CREATE SCHEMA gold")


def _materialize(
    connection: psycopg.Connection, artifacts: tuple[Any, ...]
) -> None:
    """CREATE TABLE <namespace>.<relation> AS <the artifact's SELECT> — silver
    before gold, because mart SELECTs read the silver relations, and gold sorted
    by path so a rollup is built after the mart it names."""
    models = sorted(
        (a for a in artifacts if a.kind is ArtifactKind.MODEL),
        key=lambda a: (
            PurePosixPath(a.path).parent.name != "silver",
            PurePosixPath(a.path),
        ),
    )
    for artifact in models:
        path = PurePosixPath(artifact.path)
        connection.execute(
            f'CREATE TABLE {path.parent.name}."{path.stem}" AS '
            f"{extract_select(artifact.content)}"
        )


def _run_buckets(connection: psycopg.Connection, instant: datetime) -> dict[str, date]:
    for statement in _RESET_ALL:
        connection.execute(statement)
    connection.execute("CREATE TABLE bronze.raw__probe (id VARCHAR, paid_at VARCHAR)")
    connection.execute(
        "INSERT INTO bronze.raw__probe VALUES (%s, %s)", ["probe", instant.isoformat()]
    )
    _materialize(connection, _bucket_artifacts())
    columns = ", ".join(f"paid_{unit}" for unit in BUCKET_UNITS)
    row = connection.execute(f"SELECT {columns} FROM gold.mart_probes").fetchone()
    assert row is not None
    return dict(zip(BUCKET_UNITS, row, strict=True))


def _assert_exact(name: str, source: Any, produced: Any, expected: Any) -> None:
    """The chain/recipe comparison: exact, printing both answers on a
    disagreement (S-0092/D-4)."""
    if expected is OVERFLOW:
        if produced is _RAISED:
            return
        msg = (
            f"{name} on {ENGINE} answered {produced!r} for input {source!r}, but "
            "the reference says the value overflows its declared type and the "
            "engine must raise (S-0092/D-1)"
        )
        raise AssertionError(msg)
    if produced is _RAISED:
        msg = (
            f"{name} on {ENGINE} refused input {source!r}, but the reference says "
            f"{expected!r} (S-0092/D-4)"
        )
        raise AssertionError(msg)
    if produced != expected:
        msg = (
            f"{name} on {ENGINE} disagreed with the reference for input "
            f"{source!r}: the engine answered {produced!r}, the reference says "
            f"{expected!r} (S-0092/D-4)"
        )
        raise AssertionError(msg)


@pytest.mark.parametrize("case", CHAIN_CASES, ids=lambda case: case.name)
@given(data=st.data())
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_postgres_answers_every_chain_exactly_as_the_reference_does(
    postgres: psycopg.Connection, case: ChainCase, data: Any
) -> None:
    source = data.draw(case.source)
    expected = fold(case.chain, source)
    produced = _run_chain(postgres, case.chain, source)
    _assert_exact(case.name, source, produced, expected)


@given(pair=RECIPE_OPERANDS)
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_postgres_recipe_dividing_two_integers_equals_the_widened_quotient(
    postgres: psycopg.Connection, pair: tuple[int, int]
) -> None:
    expected = recipe_quotient(pair[0], pair[1], 12, 4)
    produced = _run_recipe(postgres, pair)
    _assert_exact("recipe_quotient", pair, produced, expected)


@pytest.mark.parametrize(
    "instant", BUCKET_INSTANTS, ids=lambda instant: instant.isoformat()
)
def test_postgres_time_buckets_match_the_reference(
    postgres: psycopg.Connection, instant: datetime
) -> None:
    produced = _run_buckets(postgres, instant)
    for unit in BUCKET_UNITS:
        expected = bucket(unit, instant)
        assert produced[unit] == expected, (
            f"mart bucket paid_{unit} for {instant.isoformat()} on {ENGINE} landed "
            f"on {produced[unit]!r}, the reference says {expected!r} (S-0092/D-6)"
        )


# ----------------------- #
# Rollup aggregates over generated groups (S-0092/D-7)


#: The metric names the rollup projects, read by name rather than by position.
_ROLLUP_METRICS = tuple(sorted(ROLLUP_METRICS))

#: A group map: key → the metric expression's value on each of its rows. A key
#: with an empty list is the group a filter removed entirely; a key whose list
#: is all ``None`` is the retained all-NULL group (S-0092/D-7).
_ROLLUP_CASES = st.dictionaries(
    st.sampled_from(["A", "B", "C", "D", "E"]),
    st.lists(st.one_of(st.none(), st.integers(-(10**6), 10**6)), max_size=6),
    min_size=1,
    max_size=4,
)


@functools.lru_cache(maxsize=None)
def _rollup_artifacts() -> tuple[Any, ...]:
    """The compiled rollup fixture: silver, the parent mart, and the rollup."""
    project = load_project(dict(ROLLUP_SOURCES))
    return compile_project(
        project, target=Target.SQLMESH, dialect=ENGINE, catalog=None, steps=None
    )


def _run_rollup(
    connection: psycopg.Connection, groups: dict[str, list[int | None]]
) -> dict[str, dict[str, int | None]]:
    """Seed the group map, build the project, and read the rollup as
    ``{group: {metric: value}}``."""
    for statement in _RESET_ALL:
        connection.execute(statement)
    connection.execute(
        f"CREATE TABLE bronze.raw__probe ({ROLLUP_BRONZE_COLUMNS})"
    )
    rows = rollup_bronze_rows(groups)
    if rows:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO bronze.raw__probe VALUES (%s, %s, %s, %s, %s, %s, %s)",
                rows,
            )
    _materialize(connection, _rollup_artifacts())
    columns = ", ".join(_ROLLUP_METRICS)
    result = connection.execute(
        f"SELECT grp, {columns} FROM gold.{ROLLUP_RELATION}"
    ).fetchall()
    return {row[0]: dict(zip(_ROLLUP_METRICS, row[1:], strict=True)) for row in result}


def _assert_rollup(
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


@given(groups=_ROLLUP_CASES)
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_postgres_rollup_groups_equal_the_reference_aggregates(
    postgres: psycopg.Connection, groups: dict[str, list[int | None]]
) -> None:
    produced = _run_rollup(postgres, groups)
    _assert_rollup(groups, produced, rollup(groups))


def test_postgres_an_all_null_group_counts_zero_and_sums_to_null(
    postgres: psycopg.Connection,
) -> None:
    """``COUNT(expr)`` skips NULL, so a retained all-NULL group is present and
    counts 0 with NULL sum, min and max (S-0092/D-7)."""
    groups = {"A": [None, None, None], "B": [3, 5]}
    produced = _run_rollup(postgres, groups)

    assert produced["A"] == {"n": 0, "total": None, "lo": None, "hi": None}
    assert produced["B"] == {"n": 2, "total": 8, "lo": 3, "hi": 5}
    assert produced == rollup(groups)


def test_postgres_a_group_a_filter_removes_has_no_row(
    postgres: psycopg.Connection,
) -> None:
    """A group whose every row is filtered out before the mart has no row; the
    reference states that absence, not a zero (S-0092/D-7).

    The group's row **is** in bronze — the fixture's quarantine rule is what
    removes it (S-0092/D-7). Asserted here so the absence is the filter acting
    on a row that existed, not a row that was never seeded."""
    groups = {"A": [1, 2], "GONE": []}
    seeded = rollup_bronze_rows(groups)
    produced = _run_rollup(postgres, groups)

    assert any(
        row[0] == "g1.r0" and row[1] == "GONE" and row[2] == str(ROLLUP_FILTERED_VALUE)
        for row in seeded
    )
    assert "GONE" not in produced
    assert produced == rollup(groups) == {"A": {"n": 2, "total": 3, "lo": 1, "hi": 2}}