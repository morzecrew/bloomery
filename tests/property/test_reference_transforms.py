"""The DuckDB half of the transform differential (S-0092/D-2, S-0092/D-4).

Every built-in transform is compiled onto one field of a one-entity fixture,
its silver SQL is run against DuckDB, and the row's value is required to equal
:mod:`support.reference`'s **exact** answer — NULLs, boundaries and the typed
setup included. The comparison is exact except where
:mod:`support.engine_differences` names a difference; a disagreement no row
names fails, printing the input and both answers.

The reference is the second, independent statement of each transform's
semantics (D-1). This module holds it to the engine, and holds the *battery*
honest with three tests that would pass trivially if the comparison were
toothless: one that a wrong reference value fails, one that an unlisted
difference fails, and one that every built-in — ``json_path`` and ``convert``
among them — actually has a case.

The PostgreSQL 16 half runs under ``tests/engines/`` against a session-scoped
container; the DuckDB half here is the one every pull request guards.
"""

from __future__ import annotations

import functools
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import duckdb
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.spec.mapping import TransformStep
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import StringType, render_type
from support.engine_differences import DIFERENCES, Difference, difference_for
from support.reference import CASES, JSON_NULL, OVERFLOW, SEMANTICS, Case, Step

pytestmark = pytest.mark.property

#: The sentinel for "the engine refused the row", against which an
#: :data:`OVERFLOW` reference is matched.
_RAISED = object()

#: How DuckDB is named in the differences table and in failure messages.
ENGINE = "duckdb"


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
        "  probe_id: {from: \"$.id\", transform: [to_string]}\n"
        "fields:\n"
        f"  value: {{{fixture.value_prefix}from: \"$.value\", "
        f"transform: [{_render_chain(case.chain)}]}}"
        f"{extra}\n"
    )
    return {"entity_model": entity, "mapping": mapping}


@functools.lru_cache(maxsize=None)
def _compiled(transform: str) -> tuple[str, tuple[str, ...]]:
    """``(silver select, connection setup statements)`` for one case."""
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
    setup = (
        ("CREATE SCHEMA bronze", "CREATE SCHEMA silver")
        + fixture.seed_sql
        + (f"CREATE TABLE bronze.raw__probe ({columns})",)
    )
    return select, setup


def _run(case: Case, source: str | None) -> Any:
    """Seed one row and read the silver value, or ``_RAISED`` if the engine
    refused it (which an :data:`OVERFLOW` reference demands)."""
    select, setup = _compiled(case.transform)
    fixture = case.fixture
    connection = duckdb.connect()
    try:
        connection.execute("SET TimeZone = 'UTC'")
        for statement in setup:
            connection.execute(statement)
        extra = [fixed for _, _, fixed in fixture.extra_columns]
        placeholders = ", ".join("?" * (2 + len(extra)))
        connection.execute(
            f"INSERT INTO bronze.raw__probe VALUES ({placeholders})",
            ["probe", source, *extra],
        )
        try:
            result = connection.execute(select)
            row = result.fetchone()
        except duckdb.Error:
            return _RAISED
        assert row is not None
        names = [column[0] for column in result.description]
        return row[names.index("value")]
    finally:
        connection.close()


# ----------------------- #
# Comparison (D-4), and the differences table (D-3)


def _zoneless_utc(value: Any) -> Any:
    """A timestamp as its zoneless UTC wall clock (D-4)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _engine_value(case: Case, produced: Any) -> Any:
    """The engine's raw value in the reference's vocabulary.

    A JSON ``null`` comes back as the JSON text ``'null'`` and a missing path as
    SQL NULL; the first is :data:`JSON_NULL`, the second stays ``None``, so a
    compiler that swapped them would fail (S-0092/D-1).
    """
    if case.transform == "json_path" and isinstance(produced, str):
        parsed = json.loads(produced)
        return JSON_NULL if parsed is None else parsed
    return _zoneless_utc(produced)


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
    differences: tuple[Difference, ...] = DIFERENCES,
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

    engine_answer = _engine_value(case, produced)
    if engine_answer == expected:
        return

    row = difference_for(ENGINE, case.transform, source)
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
def test_duckdb_answers_every_builtin_exactly_as_the_reference_does(
    case: Case, data: Any
) -> None:
    source = data.draw(case.source)
    expected = case.reference(source)
    produced = _run(case, source)
    assert_matches(case, source, produced, expected)


# ----------------------- #
# The battery's own teeth


def test_every_builtin_has_a_reference_and_a_case() -> None:
    """``json_path`` and ``convert`` included: a built-in with no case would
    leave this whole module silent about it (S-0092/D-2)."""
    builtins = set(DEFAULT_REGISTRY)
    assert {"json_path", "convert"} <= builtins
    assert {case.transform for case in CASES} == builtins
    assert set(SEMANTICS) == builtins


def test_a_non_text_input_is_reached_through_its_typed_setup() -> None:
    """``abs`` and friends take a decimal, not text, so their chain opens with
    the setup that produces one — and the reference applies the same setup."""
    for case in CASES:
        target = DEFAULT_REGISTRY[case.transform]
        if StringType in target.input_domain:
            continue
        assert len(case.chain) >= 2, case.transform
        assert case.chain[0][0] != case.transform, case.transform
        assert case.chain[-1][0] == case.transform, case.transform

    from support.reference import fold

    assert fold((("to_decimal", (12, 4)), ("abs", ())), "-3.5000") == Decimal("3.5000")


def test_a_wrong_reference_value_fails_naming_the_input_and_both_answers() -> None:
    case = next(c for c in CASES if c.transform == "trim")
    with pytest.raises(AssertionError) as caught:
        assert_matches(case, "  padded  ", "padded", "SHOUTING")

    message = str(caught.value)
    assert repr("  padded  ") in message
    assert repr("padded") in message
    assert repr("SHOUTING") in message


def test_a_difference_no_row_names_fails_naming_the_input_and_both_answers() -> None:
    """An out-of-range ``split_part`` is a difference the table names; take the
    row away and the same disagreement must fail."""
    case = next(c for c in CASES if c.transform == "split_part")

    # The row licenses DuckDB's '' where the portable reading is NULL.
    assert_matches(case, "a", "", None)

    with pytest.raises(AssertionError) as caught:
        assert_matches(case, "a", "", None, differences=())

    message = str(caught.value)
    assert repr("a") in message
    assert repr("") in message
    assert "None" in message