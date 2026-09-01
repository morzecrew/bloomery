"""Compile-path scale budgets (RFC 0009 §5.9): the whole pipeline — YAML text
through ``load_project``, resolution, guardrails, lowering and SQLMesh
emission — timed at 100, 500 and 1000 entities.

Until this file, the bench lane was hydration alone and the largest project
any test compiled was ~90 entities: "hundreds of entities" was an unknown that
was not even recorded as unknown. The project here is synthetic and uniform —
one mapped source per entity, a decimal, a timestamp — because the question is
how cost *scales*, not what one artful project costs.

Budgets follow the hydration lane's convention: asserted as medians, ceilings
set an order of magnitude above the measurement so a slow shared runner does
not fail the nightly while a superlinear regression cannot hide. The 500-entity
point is recorded as info only — it exists to keep the linear extrapolation
honest, not to gate.

Marked ``perf``: excluded from ``just test``; informational on the nightly CI
lane and blocking on the release-candidate job.

Measured on the tree that wired it up (median of 5/3/3): **100 entities
264 ms**, **500 entities 1.28 s**, **1000 entities 2.54 s** — ~2.6 ms per
entity, linear across the decade.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable

import pytest

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.perf

#: (entities, repetitions, ceiling in seconds — None records without gating).
POINTS: tuple[tuple[int, int, float | None], ...] = (
    (100, 5, 3.0),
    (500, 3, None),
    (1000, 3, 30.0),
)


def _sources(n: int) -> dict[str, str]:
    entity_lines = ["spec_version: 1", "entities:"]
    documents: dict[str, str] = {}
    for i in range(n):
        entity_lines += [
            f"  event_{i}:",
            f"    grain: one row per event_{i}",
            "    key: [event_id]",
            "    fields:",
            "      event_id: {type: string, required: true}",
            "      kind: {type: string}",
            "      amount: {type: 'decimal(12,2)'}",
            "      occurred_at: {type: timestamp}",
        ]
        documents[f"mapping_{i}.yaml"] = "\n".join(
            [
                "mapping_version: 1",
                f"source: raw__events_{i}",
                f"target: event_{i}",
                "key:",
                '  event_id: {from: "$.id", transform: [to_string]}',
                "fields:",
                '  kind: {from: "$.kind"}',
                '  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}',
                '  occurred_at: {from: "$.ts"}',
            ]
        )
    documents["entity_model.yaml"] = "\n".join(entity_lines)
    return documents


@pytest.mark.parametrize(("entities", "reps", "ceiling"), POINTS)
def test_compile_scales_linearly_to_a_thousand_entities(
    entities: int,
    reps: int,
    ceiling: float | None,
    record_property: Callable[[str, object], None],
) -> None:
    documents = _sources(entities)
    durations: list[float] = []
    for _ in range(reps):
        started = time.perf_counter()
        artifacts = compile_project(
            load_project(documents), target=Target.SQLMESH, dialect="duckdb"
        )
        durations.append(time.perf_counter() - started)
    assert len(artifacts) == entities  # the pipeline actually ran, per entity
    median = statistics.median(durations)
    record_property(f"compile_median_ms_{entities}_entities", round(median * 1000, 1))
    if ceiling is not None:
        assert median < ceiling, (
            f"{entities} entities took a median {median:.2f}s against the"
            f" {ceiling:.0f}s ceiling — the compile path has regressed by an"
            " order of magnitude, not drifted"
        )
