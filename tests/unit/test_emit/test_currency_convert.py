"""Currency conversion at emit (RFC 0023 §5.4, D4).

Two states of one construct, and the single line of spec that separates them.
With a catalog that declares ``fx_rates:``, ``convert`` lowers to an as-of rate
subquery on every SQL cell; without one it is refused, because a conversion is
a join against a dated rate table and nothing has said where that table is.

The refusal is what remains of Phase 1's unconditional one. It no longer says
no engine can do this — one can, given rates — so it names the missing
declaration instead.

The guardrail consequence is tested beside the rule itself, in
`test_guardrails/test_arithmetic.py`.
"""

from __future__ import annotations

import pytest
from sqlglot import exp

from bloomery import Target, compile_project
from bloomery.dialects import get_dialect
from bloomery.emit import EmitContext
from bloomery.emit.lower import entity_select
from bloomery.emit.lower.silver import reject_select, replay_statements
from bloomery.errors import InvariantViolated, UnsupportedByTarget
from bloomery.naming import DefaultNaming, PrefixNaming
from bloomery.transforms import CONVERT_MARKER, DEFAULT_REGISTRY
from support.compiling import load_fixture
from support.plan_ir import column as plan_column
from support.plan_ir import entity as plan_entity

from bloomery.ir import FxRatesIR

#: The declaration the fixture's catalog carries, for the direct-call tests.
_FX = FxRatesIR(
    relation="fx_rate",
    from_currency="from_ccy",
    to_currency="to_ccy",
    rate="rate",
    valid_from="valid_from",
    valid_to="valid_to",
)

pytestmark = pytest.mark.unit

REFUSED = "currency_convert_refusal"
CONVERTS = "currency_convert"

#: Every cell that lowers a silver SELECT. Cube and MetricFlow are absent on
#: purpose: they emit a semantic layer over column *names*, never the column
#: expressions, so the marker cannot reach them and a refusal there would be
#: refusing something that never happens.
SQL_TARGETS = [Target.SQLMESH, Target.DBT]
DIALECTS = ["duckdb", "postgres", "trino"]


@pytest.mark.parametrize("target", SQL_TARGETS)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_convert_is_refused_where_no_rate_relation_is_declared(
    target: Target, dialect: str
) -> None:
    project, catalog = load_fixture(REFUSED)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=target, dialect=dialect, catalog=catalog)
    message = str(excinfo.value)
    assert "no rate relation is declared" in message
    assert "fx_rates" in message
    assert excinfo.value.source_path == "entity_model: entities.payment.fields.amount_usd"


@pytest.mark.parametrize("target", SQL_TARGETS)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_convert_lowers_to_a_rate_subquery_on_every_sql_cell(
    target: Target, dialect: str
) -> None:
    """The same spec, one catalog key later. Every cell that lowers a silver
    SELECT emits the rate lookup, and none of them emits the marker."""
    project, catalog = load_fixture(CONVERTS)
    artifacts = compile_project(project, target=target, dialect=dialect, catalog=catalog)
    payment = next(a for a in artifacts if a.path.endswith("payment.sql"))

    assert CONVERT_MARKER not in payment.content
    assert "fx_rate" in payment.content
    assert "fx.rate" in payment.content


def test_the_refusal_names_no_dialect() -> None:
    """It is not a dialect's fault, and the message must not suggest that
    another engine would take it (RFC 0023 §5.2)."""
    project, catalog = load_fixture(REFUSED)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.SQLMESH, dialect="trino", catalog=catalog)
    assert "trino" not in str(excinfo.value)


def test_the_emitted_predicate_is_the_half_open_interval() -> None:
    """Both ends, and the open end spelled `IS NULL` (D11).

    A `valid_from`-only lookup matches every rate at or before the anchor,
    which for a scalar subquery is an error and for a join is a silent
    multiplication. The upper bound is what makes a miss a miss.
    """
    project, catalog = load_fixture(CONVERTS)
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
    sql = " ".join(next(a for a in artifacts if a.path.endswith("payment.sql")).content.split())

    assert "CAST(paid_at AS DATE) >= fx.valid_from" in sql
    assert "fx.valid_to IS NULL OR CAST(paid_at AS DATE) < fx.valid_to" in sql
    assert "fx.from_ccy = 'EUR'" in sql
    assert "fx.to_ccy = 'USD'" in sql


def test_the_anchor_is_lowered_not_referenced_by_name() -> None:
    """What the subquery compares is the anchor's own lowering, not a
    reference to the column it will be projected as.

    Both are projections of one SELECT, and a lateral column alias is a DuckDB
    extension Postgres and Trino reject — so a bare `paid_at` reference would
    resolve against bronze, where the silver name does not exist.
    """
    project, catalog = load_fixture(CONVERTS)
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
    sql = " ".join(next(a for a in artifacts if a.path.endswith("payment.sql")).content.split())

    assert "CAST(paid_at AS DATE) >= fx.valid_from" in sql, sql


def test_the_rate_relation_goes_through_the_naming_policy() -> None:
    """A relation reference inside a column expression is still a relation
    reference: scoping applies to it exactly as it does to a mart's join
    target (RFC 0008 §5.1)."""
    project, catalog = load_fixture(CONVERTS)
    artifacts = compile_project(
        project,
        target=Target.SQLMESH,
        dialect="duckdb",
        catalog=catalog,
        naming=PrefixNaming("acme"),
    )
    sql = next(a for a in artifacts if a.path.endswith("payment.sql")).content

    assert "acme_silver.fx_rate" in sql
    assert "FROM silver.fx_rate" not in sql


def test_the_reject_and_replay_selects_convert_too() -> None:
    """The rewrite is in `_extract_select`, the one place a `ColumnIR.expr`
    becomes SQL — so it covers every SELECT an entity produces, not only its
    model. Replay especially: it re-runs this same expression against the
    reject payload, so a conversion missing there would replay rows at no rate
    at all.

    Called directly because compiling a project shows only the model path,
    which cannot tell a rewrite that runs everywhere from one hoisted into
    `entity_select` alone.
    """
    project, catalog = load_fixture(CONVERTS)
    _ = catalog
    carrier = plan_entity(
        name="payment",
        key=("payment_id",),
        columns=(
            plan_column("payment_id", required=True),
            plan_column(
                "amount_usd",
                expr=f"{CONVERT_MARKER}(amount, 'EUR', 'USD', CAST(paid_at AS DATE))",
            ),
        ),
    )
    ctx = EmitContext(
        fingerprint="blm1:test",
        naming=DefaultNaming(),
        dialect=get_dialect("duckdb"),
        fx_rates=_FX,
    )
    for lowering in (entity_select, reject_select, replay_statements):
        rendered = str(lowering(carrier, ctx))
        assert CONVERT_MARKER not in rendered, lowering.__name__
        assert "fx_rate" in rendered, lowering.__name__


def test_the_reject_and_replay_selects_refuse_too() -> None:
    """The other half of the same claim: with no rates declared, every one of
    those SELECTs refuses rather than emitting the marker."""
    carrier = plan_entity(
        name="payment",
        key=("payment_id",),
        columns=(
            plan_column("payment_id", required=True),
            plan_column(
                "amount_usd",
                expr=f"{CONVERT_MARKER}(amount, 'EUR', 'USD', CAST(paid_at AS DATE))",
            ),
        ),
    )
    ctx = EmitContext(
        fingerprint="blm1:test", naming=DefaultNaming(), dialect=get_dialect("duckdb")
    )
    for lowering in (entity_select, reject_select, replay_statements):
        with pytest.raises(UnsupportedByTarget) as excinfo:
            lowering(carrier, ctx)
        assert "amount_usd" in str(excinfo.value)


def test_convert_stays_registered_and_typechecked() -> None:
    """RFC 0023 D4: the spec surface never moved for the refusal, and the
    grammar change §5.4 forced is additive — three arguments where there was
    one, on a transform that was always in the whitelist."""
    spec = DEFAULT_REGISTRY["convert"]
    assert spec.arity == 3
    assert [t.__name__ for t in spec.input_domain] == ["DecimalType"]


def test_the_marker_the_transform_builds_is_the_one_emit_lowers(
) -> None:
    """The producer and the two consumers share a constant rather than a
    spelling.

    Three literals would drift silently in the direction that matters: a
    resolver or a refusal looking for a name nothing produces passes every
    project, including the ones it exists to stop.
    """
    node = DEFAULT_REGISTRY["convert"].builder(exp.column("amount"), "EUR", "USD", "paid_at")
    assert isinstance(node, exp.Anonymous)
    assert str(node.this).upper() == CONVERT_MARKER


def test_an_unbound_marker_names_its_guarantor() -> None:
    """The invariant the rewrite rests on, stated where it is relied upon.

    `resolve.build` binds both currencies and the lowered anchor into every
    marker it lowers, from `key:` and from `fields:` alike — so by emit a
    marker always carries four expressions. The rewrite indexed the fourth
    directly, which made a marker from anywhere else a bare `IndexError` with
    nothing to say. Two modules were coupled by an invariant neither stated.
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
        fingerprint="blm1:test",
        naming=DefaultNaming(),
        dialect=get_dialect("duckdb"),
        fx_rates=_FX,
    )
    with pytest.raises(InvariantViolated) as excinfo:
        entity_select(carrier, ctx)
    assert "resolve.build" in str(excinfo.value)
