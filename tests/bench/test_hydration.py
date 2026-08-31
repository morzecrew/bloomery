"""Hydration budgets (RFC 0014 §5.5/§6, RFC 0009 §5.9 — the bench lane's
single asserted entry): **50 ms cold** (bytes → ``parse_raw`` + lookup) and
**10 ms warm** (an L1 hit, including keying), asserted as medians over ≥20
iterations with the documented relaxed **3× CI multiplier**, on a
reference-tenant manifest (~30 semantic models / ~90 metrics) built
programmatically through the real emitter. A 3× model-size point (~90
models) is recorded as info — it keeps V3's roughly-linear extrapolation
honest as tenants grow, without asserting on it.

Marked ``perf``: excluded from ``just test``. It now genuinely **runs** in two
places (RFC 0025 D13) — informational on the nightly CI lane, and blocking on a
release-candidate job in ``release.yaml``. That sentence used to say "run in
the scheduled lane" while no workflow ran the ``perf`` marker at all: the only
mention of it in CI was the expression excluding it, so these assertions had
never executed anywhere but a developer's terminal.

The blocking copy is on the *release* rather than on every PR because a budget
is a ceiling, not a per-commit signal, and because ``just test`` excludes this
lane — a gate that only ever ran on a schedule could fire after the tag, which
satisfies the ratchet on paper and enforces nothing.

Measured on the tree that wired it up (30-model reference tenant, median of
25): **cold 10.8 ms** against the 150 ms ceiling, **warm 7.9 ms** against 30 ms,
and the 3× size point at 35.2 ms. The headroom is the point (D4): an
order-of-magnitude regression fails, and a slow shared runner does not.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable

import pytest

from bloomery.ir import (
    ColumnIR,
    DateDimensionIR,
    DimensionRef,
    EntityIR,
    MartColumnIR,
    MartDimensionIR,
    MartIR,
    Materialization,
    MetricIR,
    ProjectIR,
    SCDKind,
    SourceColumnIR,
    SourceIR,
    SqlExpr,
    Additivity,
)
from bloomery.naming import DefaultNaming
from bloomery.runtime import LruManifestHydrator, build_manifest_bytes, hydrate_manifest
from bloomery.typing import DateType, DecimalType, StringType

pytestmark = pytest.mark.perf

NAMING = DefaultNaming()
RUNS = 25
CI_MULTIPLIER = 3  # documented relaxed multiplier (RFC 0014 §6)
COLD_BUDGET_MS = 50 * CI_MULTIPLIER
WARM_BUDGET_MS = 10 * CI_MULTIPLIER

MEASURES_PER_MODEL = 3
DIMS_PER_MODEL = 5


def _column(name: str, type_: object) -> ColumnIR:
    return ColumnIR(
        name=name,
        type=type_,  # type: ignore[arg-type]
        canonical=None,
        unit=None,
        tax_basis=None,
        renamed_from=None,
        required=name == "pk",
    )


def _model(index: int) -> tuple[EntityIR, MartIR, list[MetricIR]]:
    entity_name = f"entity_{index:02d}"
    columns = sorted(
        [
            _column("pk", StringType()),
            _column("event_date", DateType()),
            *(_column(f"col_{k}", DecimalType(12, 4)) for k in range(MEASURES_PER_MODEL)),
            *(_column(f"dim_{d}", StringType()) for d in range(DIMS_PER_MODEL)),
        ],
        key=lambda c: c.name,
    )
    entity = EntityIR(
        name=entity_name,
        grain=f"one row per {entity_name}",
        key=("pk",),
        scd=SCDKind.TYPE1,
        materialization=Materialization.FULL,
        partition_by=(),
        columns=tuple(columns),
        sources=(
            SourceIR(
                relation=f"src__{entity_name}",
                # RFC 0024 D26: the lowered expression hangs off the source, one
                # per entity column, so a manifest built without these is
                # narrower than any the emitter produces.
                columns=tuple(SourceColumnIR(name=c.name, expr=SqlExpr(c.name)) for c in columns),
            ),
        ),
    )
    mart_columns = [
        MartColumnIR(name=c.name, type=c.type, source_entity=entity_name, source_column=c.name)
        for c in columns
    ] + [
        MartColumnIR(
            name=f"event_{bucket}",
            type=DateType(),
            source_entity=entity_name,
            source_column="event_date",
            ref=DimensionRef(dimension=bucket, role="event"),
        )
        for bucket in ("day", "week", "month", "quarter", "year")
    ]
    mart_columns.sort(key=lambda c: c.name)
    metric_names = tuple(f"metric_{index:02d}_{k}" for k in range(MEASURES_PER_MODEL))
    mart = MartIR(
        name=f"mart_{index:02d}",
        grain=entity_name,
        base=entity_name,
        columns=tuple(mart_columns),
        measures=metric_names,
        dimensions=tuple(
            MartDimensionIR(
                ref=c.ref if c.ref is not None else DimensionRef(dimension=c.name),
                column=c.name,
            )
            for c in mart_columns
        ),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
    )
    metrics = [
        MetricIR(
            name=metric_names[k],
            grain=entity_name,
            additivity=Additivity.ADDITIVE,
            agg="sum",
            expr=SqlExpr(f"col_{k}"),
            ratio=None,
            semi_additive=None,
            description=f"Synthetic metric {k} on mart_{index:02d}, for hydration benchmarks.",
        )
        for k in range(MEASURES_PER_MODEL)
    ]
    return entity, mart, metrics


def synthetic_ir(n_models: int) -> ProjectIR:
    """A reference tenant built from real IR nodes, emitted by the real
    emitter (RFC 0009 §5.9): ``n_models`` marts × 3 measures × 6 dims."""
    entities: list[EntityIR] = []
    marts: list[MartIR] = []
    metrics: list[MetricIR] = []
    for index in range(n_models):
        entity, mart, model_metrics = _model(index)
        entities.append(entity)
        marts.append(mart)
        metrics.extend(model_metrics)
    return ProjectIR(
        entities=tuple(sorted(entities, key=lambda e: e.name)),
        metrics=tuple(sorted(metrics, key=lambda m: m.name)),
        marts=tuple(sorted(marts, key=lambda m: m.name)),
        date_dimension=DateDimensionIR(
            name="dim_date", grain="day", start_year=2020, end_year=2030
        ),
    )


def _median_ms(fn: Callable[[], object], runs: int = RUNS) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def test_cold_hydration_stays_inside_the_budget(
    record_property: Callable[[str, object], None],
) -> None:
    ir = synthetic_ir(30)
    payload = build_manifest_bytes(ir, naming=NAMING)
    record_property("payload_kb_30_models", round(len(payload) / 1024, 1))
    median = _median_ms(lambda: hydrate_manifest(payload))
    record_property("cold_median_ms_30_models", round(median, 2))
    assert median < COLD_BUDGET_MS, (
        f"cold hydration {median:.1f} ms exceeds {COLD_BUDGET_MS} ms "
        f"(50 ms budget × {CI_MULTIPLIER} CI multiplier)"
    )


def test_warm_lru_hit_stays_inside_the_budget(
    record_property: Callable[[str, object], None],
) -> None:
    ir = synthetic_ir(30)
    hydrator = LruManifestHydrator(NAMING)
    hydrator.get(ir)  # populate — the miss is the cold path, not under test
    median = _median_ms(lambda: hydrator.get(ir))
    record_property("warm_median_ms_30_models", round(median, 2))
    assert hydrator.misses == 1  # everything after the first call hit L1
    assert median < WARM_BUDGET_MS, (
        f"warm L1 hit {median:.1f} ms exceeds {WARM_BUDGET_MS} ms "
        f"(10 ms budget × {CI_MULTIPLIER} CI multiplier)"
    )


def test_triple_size_point_is_recorded_as_info(
    record_property: Callable[[str, object], None],
) -> None:
    """The 3× model-size point (RFC 0014 §5.5/§6): recorded, not asserted —
    it keeps the roughly-linear extrapolation V3 measured honest."""
    ir = synthetic_ir(90)
    payload = build_manifest_bytes(ir, naming=NAMING)
    median = _median_ms(lambda: hydrate_manifest(payload), runs=RUNS)
    record_property("payload_kb_90_models", round(len(payload) / 1024, 1))
    record_property("cold_median_ms_90_models", round(median, 2))
    assert median > 0  # info point — the budgets above are the assertions
