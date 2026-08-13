"""``gold.mart_data_quality`` and the reconcile artifacts (RFC 0016 §5.3,
§5.8).

The claim under test is "an **ordinary** semantic model": the same gold
namespace, the same mart shape, the same planner path — so quarantine rate is
a plain ``MetricRequest`` and nothing downstream needs to know the mart is
bloomery-owned. The two deliberate divergences the RFC records are asserted
here too: the schema carries no per-customer scoping column, and reject rows
themselves stay off the semantic layer entirely (§7.4).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlglot import exp, parse_one
from support.compiling import compile_fixture, extract_select, fixture_sources, load_fixture
from support.plan_ir import entity as plan_entity
from support.plan_ir import project as plan_project
from support.plan_ir import quality_rule as plan_rule
from support.planning import fixture_ir, fixture_mart

from bloomery import MetricRequest, Target, build_project_ir, compile_project, load_project
from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind, EmitContext
from bloomery.emit.dbt import DbtEmitter
from bloomery.emit.lower import quality_mart_select
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import DedupeIR, OnFail, ProjectIR, SCDKind
from bloomery.naming import DefaultNaming, PrefixNaming
from bloomery.planner.coverage import check
from bloomery.quality import (
    ENTITY_GRAIN_ROW,
    QUALITY_MART,
    QUALITY_MART_COLUMNS,
    QUALITY_METRICS,
    REJECT_SUFFIX,
    RunContext,
    is_quality_mart,
)

pytestmark = pytest.mark.unit

FIXTURE = "semi_additive_inventory"

#: RFC 0016 §5.8's schema, plus the ``run`` date role's buckets (RFC 0010 D9 —
#: a measure-carrying mart declares a date role, and this one is no exception).
EXPECTED_COLUMNS = (
    "disposition",
    "entity",
    "mapping",
    "rows_deduped",
    "rows_evaluated",
    "rows_failed",
    "rows_quarantined",
    "rule",
    "run_date",
    "run_day",
    "run_id",
    "run_month",
    "run_quarter",
    "run_week",
    "run_year",
)


def _quality_model() -> str:
    artifact = next(
        a for a in compile_fixture(FIXTURE) if a.path == "models/gold/mart_data_quality.sql"
    )
    assert artifact.kind is ArtifactKind.MODEL  # an ordinary model, not a bespoke kind
    return artifact.content


# ....................... #
# Shape


def test_the_mart_carries_exactly_the_rfc_schema() -> None:
    mart = fixture_mart(FIXTURE, QUALITY_MART)
    assert tuple(column.name for column in mart.columns) == EXPECTED_COLUMNS
    assert QUALITY_MART_COLUMNS == EXPECTED_COLUMNS
    assert is_quality_mart(mart)


def test_the_emitted_select_projects_exactly_those_columns() -> None:
    select = parse_one(extract_select(_quality_model()), dialect="duckdb")
    assert isinstance(select, exp.Select)
    assert tuple(p.alias_or_name for p in select.expressions) == EXPECTED_COLUMNS


def test_the_schema_carries_no_per_customer_scoping_column() -> None:
    """The RFC 0016 §5.8 divergence from Document 5 §7.5: namespace scoping via
    ``NamingPolicy`` is the only seam of that shape in the package (hard
    invariant #3), so the mart gets a namespace, never a column."""
    forbidden = {"tenant", "tenant_id", "customer_id", "account_id", "org_id"}
    assert not forbidden & set(EXPECTED_COLUMNS)
    default = compile_fixture(FIXTURE)
    project, catalog = load_fixture(FIXTURE)
    scoped = compile_project(
        project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog, naming=PrefixNaming("acme")
    )
    assert any(a.path == "models/gold/mart_data_quality.sql" for a in default)
    # The scoped build differs only in namespace — the schema is identical.
    assert any(a.path == "models/acme_gold/mart_data_quality.sql" for a in scoped)


def test_one_row_per_rule_evaluation_plus_one_per_reconcile_check() -> None:
    """…plus one **accounting row** per quality-carrying entity, carrying the
    counts that describe the population rather than any one rule (§5.8, and
    :data:`~bloomery.quality.ENTITY_GRAIN_ROW`). Repeating those on every rule
    row is what made ``SUM(rows_evaluated)`` return a multiple of the truth."""
    ir = fixture_ir(FIXTURE)
    quality_entities = [entity for entity in ir.entities if entity.quality]
    expected = (
        sum(len(entity.quality) for entity in ir.entities)
        + len(ir.reconcile)
        + len(quality_entities)
    )
    select = parse_one(extract_select(_quality_model()), dialect="duckdb")
    branches = [
        node
        for node in select.find_all(exp.Select)
        if any(p.alias_or_name == "rule" and isinstance(p.this, exp.Literal) for p in node.expressions)
    ]
    assert len(branches) == expected
    rules = {p.this.this for branch in branches for p in branch.expressions if p.alias == "rule"}
    assert "stock_level_matches_snapshot" in rules  # the reconcile check's own row
    assert ENTITY_GRAIN_ROW in rules  # the entity's accounting row


def test_each_entitys_population_is_one_cte_not_one_scan_per_rule() -> None:
    select = parse_one(extract_select(_quality_model()), dialect="duckdb")
    ctes = select.find(exp.With)
    assert ctes is not None
    assert [cte.alias for cte in ctes.expressions] == ["_quality_rows_inventory_level"]


def test_the_population_is_the_entity_plus_its_unresolved_rejects() -> None:
    """§6's conservation-law population: a replayed row lives in the entity and
    its reject row is retained as audit history, so excluding resolved rejects
    is what makes a replayed row count once."""
    body = _quality_model()
    assert "FROM silver.inventory_level" in body
    assert "FROM silver.inventory_level__reject" in body
    assert "resolved_at IS NULL" in body


# ....................... #
# The run context: engine-supplied, never a clock


def test_run_date_comes_from_the_engines_macro_and_run_id_is_declared_null() -> None:
    body = _quality_model()
    assert "CAST(@execution_ds AS DATE) AS run_date" in body
    assert "CAST(NULL AS TEXT) AS run_id" in body
    # Declared-but-NULL is only honest if it says what the caller supplies.
    assert "supplied by the executing engine's run context" in body


def test_no_clock_reaches_the_emitted_sql() -> None:
    body = _quality_model()
    for banned in ("CURRENT_DATE", "CURRENT_TIMESTAMP", "NOW()"):
        assert banned not in body


def test_dbt_refuses_the_quality_mart() -> None:
    """RFC 0016 §5.4 puts the quality mart in SQLMesh's set: it counts rows in
    the reject tables and reconcile models, which dbt does not build, so
    emitting it there would produce a mart of zeroes.

    Driven against the emitter directly because ``compile_project`` cannot
    reach this branch — a project carrying the mart necessarily carries either
    quality rules (hence a quarantine block) or a reconcile list, and both are
    refused earlier. That is exactly why the branch exists: it keeps the
    refusal correct if either of those ever narrows.
    """
    ir = build_project_ir(*load_fixture(FIXTURE))
    context = EmitContext(
        dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="blm1:test"
    )
    with pytest.raises(UnsupportedByTarget, match="counts rule evaluations"):
        DbtEmitter().emit(replace(ir, entities=(), reconcile=()), context)


# ....................... #
# "quarantine rate is a plain MetricRequest" (§5.8)


def test_quarantine_rate_is_served_by_the_quality_mart() -> None:
    ir = fixture_ir(FIXTURE)
    assert set(QUALITY_METRICS) <= {metric.name for metric in ir.metrics}
    covering = check(
        ir,
        MetricRequest(metrics=("quality_quarantine_rate",), dimensions=("entity", "run_month")),
        naming=DefaultNaming(),
    )
    assert covering == QUALITY_MART


def test_the_rate_is_a_ratio_of_two_additive_measures() -> None:
    """A stored rate column would be wrong at every grouping but the one it was
    computed at; a ratio metric over two additive counts is right at all of
    them."""
    ir = fixture_ir(FIXTURE)
    rate = next(m for m in ir.metrics if m.name == "quality_quarantine_rate")
    assert rate.ratio is not None
    assert (rate.ratio.numerator, rate.ratio.denominator) == (
        "quality_rows_quarantined",
        "quality_rows_evaluated",
    )


def test_reject_tables_are_not_exposed_through_metric_requests() -> None:
    """RFC 0016 §7.4: raw payloads under their own retention, a deliberately
    narrow operator surface. Counts *about* them are semantic; the rows are
    not."""
    ir = fixture_ir(FIXTURE)
    assert any(entity.quarantine is not None for entity in ir.entities)  # a reject table exists
    for mart in ir.marts:
        assert not mart.base.endswith(REJECT_SUFFIX)
        assert not mart.name.endswith(REJECT_SUFFIX)
        columns = {column.name for column in mart.columns}
        # None of the reject schema's payload columns is requestable anywhere.
        assert not columns & {"raw", "key_values", "reject_id", "failed_rules"}
    with pytest.raises(Exception, match="unknown dimension"):
        check(
            ir,
            MetricRequest(metrics=("quality_rows_quarantined",), dimensions=("raw",)),
            naming=DefaultNaming(),
        )


# ....................... #
# Reconcile artifacts (§5.3)


def test_a_reconcile_check_emits_a_model_and_a_non_blocking_audit() -> None:
    artifacts = {a.path: a for a in compile_fixture(FIXTURE)}
    model = artifacts["models/silver/stock_level_matches_snapshot__reconcile.sql"]
    audit = artifacts["audits/stock_level_matches_snapshot_reconcile.sql"]
    assert (model.kind, audit.kind) is not None
    assert model.kind is ArtifactKind.MODEL
    assert audit.kind is ArtifactKind.AUDIT
    # Non-blocking: a reconcile failure means the numbers disagree, which is
    # exactly when the comparison table needs to stay readable.
    assert "blocking false" in audit.content
    assert "WHERE NOT within_tolerance" in audit.content
    assert "audits (stock_level_matches_snapshot_reconcile)" in model.content


def test_the_reconcile_model_compares_both_sides_within_tolerance() -> None:
    body = next(
        a.content
        for a in compile_fixture(FIXTURE)
        if a.path.endswith("stock_level_matches_snapshot__reconcile.sql")
    )
    select = parse_one(extract_select(body), dialect="duckdb")
    assert isinstance(select, exp.Select)
    assert tuple(p.alias_or_name for p in select.expressions) == (
        "warehouse_id",
        "stock_date",
        "left_value",
        "right_value",
        "difference",
        "within_tolerance",
    )
    # Outer-ness, which a key present on one side only depends on: an inner
    # join would return fewer rows instead of a failing one, and that key is
    # the loudest disagreement there is. It is spelled as the *union* of both
    # sides' keys with each side hanging off it by a LEFT join, rather than as
    # one FULL join, because postgres refuses to plan a null-safe FULL join
    # (see `test_the_reconcile_model_asks_for_no_full_join`).
    keys = next(cte for cte in select.ctes if cte.alias == "_keys").this
    assert isinstance(keys, exp.Union)
    assert keys.args["distinct"] is True
    assert [join.side for join in select.find_all(exp.Join)] == ["LEFT", "LEFT"]
    # The tolerance reaches SQL as a numeric literal — floats never enter an
    # emission path (RFC 0003 D5).
    assert "<= 0.01" in body
    assert select.find(exp.Sum) is not None


def test_the_reconcile_model_is_grained_by_its_comparison_keys() -> None:
    body = next(
        a.content
        for a in compile_fixture(FIXTURE)
        if a.path.endswith("stock_level_matches_snapshot__reconcile.sql")
    )
    assert "grain (warehouse_id, stock_date)" in body


# ....................... #
# The mart exists only where there is something to report


def test_a_quality_free_project_gains_neither_the_mart_nor_its_metrics() -> None:
    ir = build_project_ir(*load_fixture("ecom_basic"))
    assert QUALITY_MART not in {mart.name for mart in ir.marts}
    assert not set(QUALITY_METRICS) & {metric.name for metric in ir.metrics}


def test_a_project_metric_colliding_with_a_reserved_name_is_refused() -> None:
    sources = dict(fixture_sources(FIXTURE))
    sources["metrics"] = sources["metrics"].replace("  stock_on_hand:", "  quality_rows_failed:")
    sources["metrics"] = sources["metrics"].replace(
        "semi_additive: {over: stock_date, rule: last}", "semi_additive: {over: stock_date, rule: last}"
    )
    sources["marts"] = sources["marts"].replace("[stock_on_hand]", "[quality_rows_failed]")
    _project, catalog = load_fixture(FIXTURE)
    with pytest.raises(Exception, match="reserved names of the quality mart") as excinfo:
        build_project_ir(load_project(sources), catalog)
    assert "quality_rows_failed" in str(excinfo.value)


# ....................... #
# The two shapes no fixture can reach (both need a hand-built IR)


def _rendered(ir: ProjectIR) -> str:
    context = EmitContext(
        dialect=get_dialect("duckdb"), naming=DefaultNaming(), fingerprint="blm1:test"
    )
    return context.dialect.render(quality_mart_select(ir, context, RunContext()))


def test_an_entity_without_a_reject_table_counts_only_its_own_rows() -> None:
    """A quality-carrying entity always ends up with a quarantine block in
    practice (the implicit ``coercible`` rule quarantines, and key fields
    cannot override it) — but the population is defined by what the entity
    *has*, not by that coincidence, so an entity with no reject table simply
    contributes one side of the union."""
    ir = plan_project(entities=(plan_entity(quality=(plan_rule(on_fail=OnFail.FLAG),)),))
    body = _rendered(ir)
    assert "FROM silver.order_item" in body
    assert "__reject" not in body
    # One population: the CTE has a single leg, so nothing is ever marked
    # diverted. (The branches *above* the CTE are unioned like any others —
    # the entity's accounting row and its one rule.)
    assert body.count("AS _quarantined") == 1
    assert "TRUE AS _quarantined" not in body


def test_rows_deduped_is_zero_where_it_cannot_be_measured_honestly() -> None:
    """Without ``dedupe`` nothing is dropped, and for SCD type 2 the stored
    rows are version history rather than one row per source row — so the
    conservation residual would not be a dedupe count. Zero beats a bronze scan
    that produces a number nobody can trust."""
    rule = plan_rule(on_fail=OnFail.FLAG)
    no_dedupe = plan_project(entities=(plan_entity(quality=(rule,)),))
    assert "AS rows_deduped" in _rendered(no_dedupe)
    assert "FROM bronze." not in _rendered(no_dedupe)

    scd2 = plan_project(
        entities=(
            plan_entity(
                quality=(rule,),
                scd=SCDKind.TYPE2,
                dedupe=DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id",)),
            ),
        )
    )
    assert "FROM bronze." not in _rendered(scd2)


def test_a_dedupe_carrying_entity_reports_the_conservation_residual() -> None:
    ir = plan_project(
        entities=(
            plan_entity(
                quality=(plan_rule(on_fail=OnFail.FLAG),),
                dedupe=DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id",)),
            ),
        )
    )
    body = _rendered(ir)
    # bronze rows − the rows that survived the dedupe QUALIFY, both measured
    # over *this* run. Never a residual against the surviving surfaces: the
    # reject table accumulates while the entity is rebuilt, so that form goes
    # negative as soon as bronze's window moves.
    assert "FROM bronze.raw__items" in body
    assert "AS rows_deduped" in body
    assert "ROW_NUMBER() OVER (" in body.split("AS rows_deduped")[0]
    assert "COUNT(*) AS rows_deduped" not in body
