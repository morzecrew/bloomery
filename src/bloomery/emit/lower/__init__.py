"""Lowering: a spec becomes SQL, once, for every target.

S-0025 splits the ports on **assembly** — targets differ in how they write a
model file and share how a spec becomes SQL. This package is that shared half,
and it imports no target: lowering reaching into an emitter inverts the port
design and is how a change made for one target starts quietly constraining
another. Enforced as "Lowering is target-independent" in `pyproject.toml`.

Split by pipeline stage rather than by target (S-0036/D-1), in dependency
order:

* `predicates` — literal spellings and audit predicates. The base; imports no
  sibling.
* `silver` — the entity SELECT: extract, rules, routing, dedupe, reject,
  replay, and the audits over them (S-0033). One stage rather than the
  `select` + `quality` pair S-0036/split-by-stage-not-by-target sketched, because extract is not
  separable: it is level 1 of the same nested SELECT, and fourteen functions
  of the rule pipeline are built from it.
* `reconcile` — reconcile models, coverage checks and mart asserts.
* `quality_mart` — rule evaluations as a gold model.
* `marts` — mart flattening, the date dimension, measure ownership (S-0027).
* `rollups` — the aggregate body of a rollup mart (S-0065). Beside `marts`
  rather than above it: it renders a relation over a *built* parent and reads
  nothing the flattener produces.

Stages compose downward and never sideways or upward, enforced rather than
agreed ("Lowering stages compose downward"). This module is the surface
emitters import; importing a stage directly works and carries no promise
(S-0035/D-6).
"""

from bloomery.emit.lower.marts import (
    dim_date_select,
    mart_select,
    measure_metrics,
    measure_owners,
)
from bloomery.emit.lower.predicates import (
    as_of_conditions,
    audit_predicate,
    column_type,
    enum_literal,
    mart_column_type,
    metric_filter_sql,
    text_literal,
)
from bloomery.emit.lower.quality_mart import quality_mart_select
from bloomery.emit.lower.reconcile import (
    coverage_audit_name,
    coverage_audit_select,
    coverage_owner,
    mart_assert_name,
    mart_assert_select,
    reconcile_audit_blocking,
    reconcile_audit_predicate,
    reconcile_audit_select,
    reconcile_keys,
    reconcile_relation,
    reconcile_select,
)
from bloomery.emit.lower.rollups import (
    ROLLUP_AGGREGATES,
    rollup_measures,
    rollup_select,
)
from bloomery.emit.lower.silver import (
    COLLISION_COUNT_COLUMN,
    REJECT_KEY,
    ROW_ID_COUNT_COLUMN,
    THIS_MODEL,
    collision_audit,
    collision_audit_select,
    conservation_audit,
    conservation_audit_select,
    entity_select,
    fail_audits,
    ingestion_audit_predicate,
    metadata_audit_select,
    reject_incremental_select,
    reject_relation,
    reject_select,
    reject_when_matched,
    replay_statements,
    step_output_select,
)

# ----------------------- #

__all__ = [
    "REJECT_KEY",
    "ROLLUP_AGGREGATES",
    "rollup_measures",
    "rollup_select",
    "COLLISION_COUNT_COLUMN",
    "ROW_ID_COUNT_COLUMN",
    "THIS_MODEL",
    "as_of_conditions",
    "audit_predicate",
    "column_type",
    "collision_audit",
    "collision_audit_select",
    "conservation_audit",
    "conservation_audit_select",
    "coverage_audit_name",
    "coverage_audit_select",
    "coverage_owner",
    "dim_date_select",
    "entity_select",
    "enum_literal",
    "fail_audits",
    "ingestion_audit_predicate",
    "mart_assert_name",
    "mart_assert_select",
    "mart_column_type",
    "mart_select",
    "measure_metrics",
    "measure_owners",
    "metadata_audit_select",
    "metric_filter_sql",
    "quality_mart_select",
    "reconcile_audit_blocking",
    "reconcile_audit_select",
    "reconcile_audit_predicate",
    "reconcile_keys",
    "reconcile_relation",
    "reconcile_select",
    "reject_relation",
    "reject_incremental_select",
    "reject_select",
    "step_output_select",
    "text_literal",
    "reject_when_matched",
    "replay_statements",
]
