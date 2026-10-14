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
from datetime import datetime, timezone
from typing import Any

import psycopg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import StringType, render_type
from support.engine_differences import DIFERENCES, Difference
from support.postgres import POSTGRES_DIFFERENCES, postgres
from support.reference import CASES, OVERFLOW, Case, Step

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