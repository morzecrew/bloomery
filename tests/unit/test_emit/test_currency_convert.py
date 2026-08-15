"""The ``convert`` refusal (RFC 0023 D4/D5).

The transform stays whitelisted and typechecked; what it may not do is reach
SQL. Both halves are tested here — that no (target × dialect) cell emits the
marker, and that removing the refusal is not silently survivable — plus the
guardrail consequence D5 makes explicit: `CurrencyMismatch` no longer has an
escape hatch, so mixed-currency arithmetic is refused at compile rather than
permitted into a run-time failure.
"""

from __future__ import annotations

import pytest
from sqlglot import exp

from bloomery import Target, compile_project
from bloomery.errors import UnsupportedByTarget
from bloomery.transforms import CONVERT_MARKER, DEFAULT_REGISTRY
from support.compiling import load_fixture

pytestmark = pytest.mark.unit

FIXTURE = "currency_convert_refusal"

#: Every cell that lowers a silver SELECT. Cube and MetricFlow are absent on
#: purpose: they emit a semantic layer over column *names*, never the column
#: expressions, so the marker cannot reach them and a refusal there would be
#: refusing something that never happens.
SQL_TARGETS = [Target.SQLMESH, Target.DBT]
DIALECTS = ["duckdb", "postgres", "trino"]


@pytest.mark.parametrize("target", SQL_TARGETS)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_convert_is_refused_on_every_sql_cell(target: Target, dialect: str) -> None:
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=target, dialect=dialect, catalog=catalog)
    message = str(excinfo.value)
    assert "no lowering on any shipped dialect" in message
    assert "join against a dated rate table" in message
    assert excinfo.value.source_path == "entity_model: entities.payment.fields.amount_usd"


def test_the_refusal_names_no_dialect() -> None:
    """It is not a dialect's fault, and the message must not suggest that
    another engine would take it (RFC 0023 §5.2)."""
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.SQLMESH, dialect="trino", catalog=catalog)
    assert "trino" not in str(excinfo.value)


def test_convert_stays_registered_and_typechecked() -> None:
    """RFC 0023 D4: the spec surface does not move. Removing the transform
    would change the exported JSON Schema's enum, which is the change D10
    declined to make on a construct that may return."""
    spec = DEFAULT_REGISTRY["convert"]
    assert spec.arity == 1
    assert [t.__name__ for t in spec.input_domain] == ["DecimalType"]


def test_the_marker_the_transform_builds_is_the_one_emit_refuses_on() -> None:
    """The producer and the refusal share a constant rather than a spelling.

    Two literals would drift silently in the direction that matters: a refusal
    looking for a name nothing produces passes every project, including the
    ones it exists to stop.
    """
    node = DEFAULT_REGISTRY["convert"].builder(exp.column("amount"), "USD")
    assert isinstance(node, exp.Anonymous)
    assert str(node.this).upper() == CONVERT_MARKER
