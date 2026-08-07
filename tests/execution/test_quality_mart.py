"""``gold.mart_data_quality`` over a dirty run (RFC 0016 §5.8, D12).

§5.8's claim is not "there is an observability table". It is that quality
observability is an **ordinary semantic surface**: a mart with measures and a
date role like any other, so "quarantine rate by entity" is a plain
``MetricRequest`` rather than a bespoke endpoint. This module tests the claim
in both halves — the counts are the ones the run actually produced, and the
rate is answered *through the planner*, which is the only way to prove the
second half rather than restate it.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest
from support.dirty import FIXTURE, build_corpus
from support.planning import fixture_ir, make_planner, quantized

from bloomery import MetricRequest, Op, OrderSpec, Predicate
from bloomery.quality import QUALITY_MART_COLUMNS, QUALITY_METRICS, parse_side

pytestmark = pytest.mark.execution

PLANNER = make_planner()


@pytest.fixture(scope="module")
def corpus_run() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = build_corpus()
    yield connection
    connection.close()


def _mart(conn: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], tuple[int, ...]]:
    return {
        (entity, rule): (evaluated, failed, quarantined, deduped)
        for entity, rule, evaluated, failed, quarantined, deduped in conn.execute(
            "SELECT entity, rule, rows_evaluated, rows_failed, rows_quarantined, rows_deduped "
            "FROM gold.mart_data_quality"
        ).fetchall()
    }


def test_the_mart_carries_the_declared_schema_and_nothing_more(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """§5.8's schema, with the divergence the RFC records: no per-customer
    scoping column. Namespace scoping through ``NamingPolicy`` is the only
    seam of that shape in the package (D12), so a column appearing here would
    be a hard-invariant break, not a feature."""
    columns = tuple(
        name
        for (name,) in corpus_run.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'gold' AND table_name = 'mart_data_quality' "
            "ORDER BY column_name"
        ).fetchall()
    )
    assert columns == QUALITY_MART_COLUMNS


def test_every_rule_of_every_entity_reports_exactly_one_row(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """ "Every rule evaluation emits a row" — one, not one per firing and not
    none for a rule that never fired. A rule silently absent from the mart is a
    rule nobody can see stop working."""
    rules = {
        (entity, rule)
        for entity, rule in corpus_run.execute(
            "SELECT entity, rule FROM gold.mart_data_quality"
        ).fetchall()
    }
    total = corpus_run.execute("SELECT COUNT(*) FROM gold.mart_data_quality").fetchone()
    assert total == (len(rules),)
    declared = {
        (entity.name, rule.name)
        for entity in fixture_ir(FIXTURE).entities
        for rule in entity.quality
    }
    # A reconcile check is a rule evaluation too (§5.3); its ``entity`` is the
    # left side's, which the grammar spells inside the aggregate call.
    reconciles = {
        (parse_side(check.left).entity, check.name)  # type: ignore[union-attr]
        for check in fixture_ir(FIXTURE).reconcile
    }
    assert rules == declared | reconciles


@pytest.mark.parametrize(
    ("entity", "rule", "counts"),
    [
        # 12 of 20 numerics quarantine on the implicit coercible rule; the flag
        # beside it fires on 15 and diverts none, which is what `flag` means.
        ("dirty_number", "amount_coercible", (20, 12, 12, 0)),
        ("dirty_number", "amount_text_pattern", (20, 15, 0, 0)),
        # Membership, not coercion: 14 of 18 enum specimens are outliers.
        ("dirty_status", "status_in_enum", (18, 14, 14, 0)),
        ("dirty_status", "status_text_in_set", (18, 14, 0, 0)),
        # The dedupe leg: three losers, reported against every rule of the
        # entity because it is a per-entity count, not a per-rule one.
        ("dirty_key", "order_id_present", (11, 1, 1, 3)),
        # `unknown_member` keeps the row, so it fails and quarantines nothing.
        ("dirty_ref", "ref_of_customer_referential", (16, 6, 0, 0)),
        # A rule that fires on nothing still reports itself.
        ("dirty_name", "name_unique", (22, 0, 0, 0)),
    ],
)
def test_the_counts_are_what_the_run_actually_did(
    corpus_run: duckdb.DuckDBPyConnection, entity: str, rule: str, counts: tuple[int, ...]
) -> None:
    assert _mart(corpus_run)[(entity, rule)] == counts


def test_rows_evaluated_is_the_survivors_of_dedupe_on_both_sides_of_the_split(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """The denominator, pinned: rules are evaluated over rows that survived
    dedupe — the ones in the entity **and** the ones the split diverted. A
    denominator that counted only survivors would make the quarantine rate
    shrink as quarantining got worse."""
    for entity in ("dirty_number", "dirty_key", "dirty_status"):
        sides = corpus_run.execute(
            f"SELECT (SELECT COUNT(*) FROM silver.{entity})"
            f"     + (SELECT COUNT(*) FROM silver.{entity}__reject WHERE resolved_at IS NULL)"
        ).fetchone()
        evaluated = {
            value
            for (value,) in corpus_run.execute(
                "SELECT DISTINCT rows_evaluated FROM gold.mart_data_quality "
                "WHERE entity = ? AND rows_deduped IS NOT NULL AND rule NOT LIKE '%matches_row'",
                [entity],
            ).fetchall()
        }
        assert sides is not None
        assert evaluated == {sides[0]}, entity


def test_the_quarantine_rate_is_a_plain_metric_request_by_entity(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """§7.5's claim, proved rather than asserted in prose: the rate is a ratio
    metric over two additive measures, so it is correct at every grouping — and
    it is answered by the ordinary planner, over the ordinary mart, with no
    quality-specific code path anywhere in the request."""
    assert "quality_quarantine_rate" in QUALITY_METRICS
    request = MetricRequest(
        metrics=("quality_quarantine_rate",),
        dimensions=("entity",),
        order_by=(OrderSpec(field="entity"),),
    )
    plan = PLANNER.plan(fixture_ir(FIXTURE), request, dialect="duckdb")
    rates = dict(corpus_run.execute(plan.sql).fetchall())

    counts = _mart(corpus_run)
    for entity in ("dirty_number", "dirty_status", "dirty_key"):
        evaluated = sum(row[0] for (name, _rule), row in counts.items() if name == entity)
        quarantined = sum(row[2] for (name, _rule), row in counts.items() if name == entity)
        assert quantized(rates[entity]) == quantized(Decimal(quarantined) / Decimal(evaluated))


def test_the_rate_is_a_ratio_so_it_stays_correct_when_the_grouping_changes(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """A stored rate column would not survive this: filtering to one
    disposition must recompute the ratio over that slice, not average
    pre-computed rates."""
    request = MetricRequest(
        metrics=("quality_quarantine_rate",),
        dimensions=("entity",),
        filters=(Predicate("disposition", Op.EQ, ("quarantine",)),),
        order_by=(OrderSpec(field="entity"),),
    )
    plan = PLANNER.plan(fixture_ir(FIXTURE), request, dialect="duckdb")
    scoped = dict(corpus_run.execute(plan.sql).fetchall())

    counts = _mart(corpus_run)
    dispositions = dict(
        corpus_run.execute(
            "SELECT entity || '|' || rule, disposition FROM gold.mart_data_quality"
        ).fetchall()
    )
    evaluated = sum(
        row[0]
        for (entity, rule), row in counts.items()
        if entity == "dirty_status" and dispositions[f"{entity}|{rule}"] == "quarantine"
    )
    quarantined = sum(
        row[2]
        for (entity, rule), row in counts.items()
        if entity == "dirty_status" and dispositions[f"{entity}|{rule}"] == "quarantine"
    )
    assert quantized(scoped["dirty_status"]) == quantized(Decimal(quarantined) / Decimal(evaluated))


def test_the_run_context_is_the_engines_and_never_a_clock_bloomery_read(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """``run_date`` comes from the target's ``@execution_ds`` macro and
    ``run_id`` is declared-but-NULL because the pinned target exposes no macro
    for it (§5.8). bloomery reads no clock (RFC 0003), so a value here that
    depended on when the suite ran would be the invariant breaking."""
    rows = corpus_run.execute(
        "SELECT DISTINCT run_id IS NULL, run_date FROM gold.mart_data_quality"
    ).fetchall()
    assert len(rows) == 1
    is_null, run_date = rows[0]
    assert is_null is True
    assert str(run_date) == "2024-01-03"  # the harness's pinned stand-in, not "today"


def test_reject_tables_are_never_a_mart_base(corpus_run: duckdb.DuckDBPyConnection) -> None:
    """D15/§7.4: the mart reports *counts* over reject rows; the rows
    themselves — raw payloads, different retention — are never exposed through
    a ``MetricRequest``. No mart in the project is built over a reject table."""
    del corpus_run
    bases = {mart.base for mart in fixture_ir(FIXTURE).marts}
    assert not any(base.endswith("__reject") for base in bases)
