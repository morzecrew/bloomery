"""The DuckDB half of the chains differential (S-0092/D-6, S-0092/D-4).

Three things a single transform cannot prove, all lowered by the build step
and all held here to :mod:`support.reference`'s **exact** answer:

- a **chain** of up to three built-ins, whose reference is the composition of
  its steps' references — the widen-then-narrow case in particular, where a
  composer that narrowed between the steps would drop a digit the reference
  keeps;
- a **recipe's** ``/`` over two integer operands, whose dividend is cast to the
  widened decimal before the division and whose quotient is narrowed once, to
  the declared type ``ROUND_HALF_UP`` — never at the dividend's scale first;
- a **mart's** time bucket, ``DATE_TRUNC(days|week|month|quarter|year, ts)`` of
  a zoneless UTC timestamp as a ``date``, checked at the first instant of an
  ISO week, a quarter and a year, and on a leap day.

The comparison is exact (:mod:`support.engine_differences` is consulted as
usual, though no row names any of these); a disagreement fails, printing the
input and both answers. The PostgreSQL half runs under ``tests/engines/``
against a session-scoped container; this half is the one every pull request
guards.
"""

from __future__ import annotations

import functools
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import duckdb
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bloomery import Target, compile_project, load_project
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import StringType, render_type
from support.execution import materialize, warehouse
from support.reference import (
    BUCKET_INSTANTS,
    BUCKET_UNITS,
    CHAIN_CASES,
    OVERFLOW,
    RECIPE_OPERANDS,
    ChainCase,
    bucket,
    fold,
    recipe_quotient,
)

pytestmark = pytest.mark.property

#: How DuckDB is named in failure messages.
ENGINE = "duckdb"

#: The sentinel for "the engine refused the row", against which an
#: :data:`OVERFLOW` reference is matched.
_RAISED = object()

#: The declared type the recipe case narrows to.
_RECIPE_DECLARED = (12, 4)


# ----------------------- #
# Render a chain, and compile the one-entity fixture that carries it


def _render_arg(value: str | int) -> str:
    return json.dumps(value) if isinstance(value, str) else str(value)


def _render_step(step: tuple[str, tuple[str | int, ...]]) -> str:
    name, args = step
    if not args:
        return name
    return f"{{{name}: [{', '.join(_render_arg(arg) for arg in args)}]}}"


def _render_chain(chain: tuple[tuple[str, tuple[str | int, ...]], ...]) -> str:
    return ", ".join(_render_step(step) for step in chain)


def _terminal_type(chain: tuple[tuple[str, tuple[str | int, ...]], ...]) -> str:
    """The chain's declared output type, walked over the registry's
    *declarations* only — none of the reference's value semantics come from
    here."""
    current = StringType()
    for name, args in chain:
        current = DEFAULT_REGISTRY[name].output_type(current, args)
    return render_type(current)


def _entity_mapping_sources(chain: tuple[tuple[str, tuple[str | int, ...]], ...]) -> dict[str, str]:
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
def _chain_compiled(chain: tuple[tuple[str, tuple[str | int, ...]], ...]) -> tuple[str, str]:
    """``(silver select, the CREATE TABLE for bronze.raw__probe)``."""
    project = load_project(_entity_mapping_sources(chain))
    artifacts = compile_project(
        project, target=Target.SQLMESH, dialect=ENGINE, catalog=None, steps=None
    )
    silver = next(a for a in artifacts if a.path.endswith("silver/probe.sql"))
    select = silver.content.split(");", 1)[1].strip()
    table = "CREATE TABLE bronze.raw__probe (id VARCHAR, value VARCHAR)"
    return select, table


def _connect() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET TimeZone = 'UTC'")
    connection.execute("CREATE SCHEMA bronze")
    connection.execute("CREATE SCHEMA silver")
    return connection


# ----------------------- #
# The recipe fixture: a catalog recipe dividing two integer fields


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
    from bloomery import load_catalog

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
    table = (
        "CREATE TABLE bronze.raw__probe (id VARCHAR, num VARCHAR, den VARCHAR)"
    )
    return select, table


# ----------------------- #
# The bucket fixture: a mart with one date role over a zoneless UTC timestamp


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


def _run_buckets(instant: datetime) -> dict[str, date]:
    connection = warehouse()
    try:
        connection.execute("CREATE TABLE bronze.raw__probe (id VARCHAR, paid_at VARCHAR)")
        connection.execute(
            "INSERT INTO bronze.raw__probe VALUES (?, ?)", ["probe", instant.isoformat()]
        )
        materialize(connection, _bucket_artifacts())
        columns = ", ".join(f"paid_{unit}" for unit in BUCKET_UNITS)
        row = connection.execute(f"SELECT {columns} FROM gold.mart_probes").fetchone()
        assert row is not None
        return dict(zip(BUCKET_UNITS, row, strict=True))
    finally:
        connection.close()


# ----------------------- #
# The exact comparison (D-4)


def _assert_exact(name: str, source: Any, produced: Any, expected: Any) -> None:
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


def _run_mapping(select: str, table: str, source: Any, columns: str) -> Any:
    """Seed one row and read the declared column, or ``_RAISED`` if the engine
    refused it."""
    connection = _connect()
    try:
        connection.execute(table)
        connection.execute(
            f"INSERT INTO bronze.raw__probe VALUES ({columns})", source
        )
        try:
            result = connection.execute(select)
            row = result.fetchone()
        except duckdb.Error:
            return _RAISED
        assert row is not None
        names = [column[0] for column in result.description]
        return row[names.index("value" if "value" in names else "quotient")]
    finally:
        connection.close()


# ----------------------- #
# The differential


@pytest.mark.parametrize("case", CHAIN_CASES, ids=lambda case: case.name)
@given(data=st.data())
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_a_chain_equals_the_composition_of_its_steps(case: ChainCase, data: Any) -> None:
    source = data.draw(case.source)
    expected = fold(case.chain, source)
    select, table = _chain_compiled(case.chain)
    produced = _run_mapping(select, table, ["probe", source], "?, ?")
    _assert_exact(case.name, source, produced, expected)


@given(pair=RECIPE_OPERANDS)
@settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_a_recipe_dividing_two_integers_equals_the_widened_quotient(
    pair: tuple[int, int],
) -> None:
    """The quotient is taken at the widened dividend scale and narrowed once to
    the declared scale ``ROUND_HALF_UP`` (S-0092/D-6)."""
    dividend, divisor = pair
    expected = recipe_quotient(dividend, divisor, *_RECIPE_DECLARED)
    select, table = _recipe_compiled()
    produced = _run_mapping(
        select, table, ["probe", str(dividend), str(divisor)], "?, ?, ?"
    )
    _assert_exact("recipe_quotient", pair, produced, expected)


@pytest.mark.parametrize("instant", BUCKET_INSTANTS, ids=lambda instant: instant.isoformat())
def test_a_time_bucket_lands_on_the_same_date_as_the_reference(instant: datetime) -> None:
    """The first instant of an ISO week, a quarter and a year, and a leap day
    (S-0092/D-6)."""
    produced = _run_buckets(instant)
    for unit in BUCKET_UNITS:
        expected = bucket(unit, instant)
        assert produced[unit] == expected, (
            f"mart bucket paid_{unit} for {instant.isoformat()} on {ENGINE} landed "
            f"on {produced[unit]!r}, the reference says {expected!r} (S-0092/D-6)"
        )


# ----------------------- #
# The battery's own teeth


def test_a_wrong_composed_reference_fails_naming_the_input_and_both_answers() -> None:
    """A chain reference is only a check if a wrong one fails."""
    case = next(c for c in CHAIN_CASES if c.name == "widen_then_narrow")
    source = "12.5000"
    produced = _run_mapping(*_chain_compiled(case.chain), ["probe", source], "?, ?")
    with pytest.raises(AssertionError) as caught:
        _assert_exact(case.name, source, produced, Decimal("0.00"))

    message = str(caught.value)
    assert repr(source) in message
    assert repr(produced) in message


def test_the_recipe_widens_the_dividend_before_dividing_and_narrows_once() -> None:
    """The reference states the widening and the single narrowing (S-0092/D-6)."""
    # 123456789 fits decimal(38,9) but not decimal(12,4) (8 integer digits):
    # the dividend is widened, so the quotient 61728394.5 fits and is kept.
    assert recipe_quotient(123456789, 2, 12, 4) == Decimal("61728394.5000")
    # A finite quotient narrower than the declared scale pads to it.
    assert recipe_quotient(1, 8, 12, 4) == Decimal("0.1250")
    # A quotient past the declared integer digits overflows rather than rounds.
    assert recipe_quotient(10**8, 1, 12, 4) is OVERFLOW