"""The ``convert`` refusal (RFC 0023 D4/D5).

The transform stays whitelisted and typechecked; what it may not do is reach
SQL. Three things are pinned here: that no (target × dialect) cell emits the
marker, that the refusal sits low enough to cover the *other* SELECTs an
entity produces — the reject table and the replay — and that the token the
transform builds is the token the refusal looks for.

The guardrail consequence D5 makes explicit — `CurrencyMismatch` losing its
escape hatch — is tested beside the rule itself, in
`test_guardrails/test_arithmetic.py`.
"""

from __future__ import annotations

import pytest
from sqlglot import exp

from bloomery import Target, compile_project
from bloomery.dialects import get_dialect
from bloomery.emit import EmitContext
from bloomery.emit.lower import entity_select
from bloomery.emit.lower.silver import reject_select
from bloomery.errors import UnsupportedByTarget
from bloomery.naming import DefaultNaming
from bloomery.transforms import CONVERT_MARKER, DEFAULT_REGISTRY
from support.compiling import load_fixture
from support.plan_ir import column as plan_column
from support.plan_ir import entity as plan_entity

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


def test_the_reject_and_replay_selects_refuse_too() -> None:
    """The refusal is in `_extract_select`, the one place a `ColumnIR.expr`
    becomes SQL — so it covers every SELECT an entity produces, not only its
    model.

    Called directly because the model path refuses first: compiling a project
    can only ever show the first refusal, so it cannot tell a check that runs
    everywhere from one hoisted into `entity_select` alone. Hoisting it is
    exactly the change this would stop being safe under.
    """
    carrier = plan_entity(
        name="payment",
        key=("payment_id",),
        columns=(
            plan_column("payment_id", required=True),
            plan_column("amount_usd", expr=f"{CONVERT_MARKER}(amount, 'USD')"),
        ),
    )
    ctx = EmitContext(
        fingerprint="blm1:test", naming=DefaultNaming(), dialect=get_dialect("duckdb")
    )
    for lowering in (entity_select, reject_select):
        with pytest.raises(UnsupportedByTarget) as excinfo:
            lowering(carrier, ctx)
        assert "amount_usd" in str(excinfo.value)


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
