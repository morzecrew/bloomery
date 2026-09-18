<!-- torve:managed tests/fixtures/quality_precedence — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/quality_precedence/`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0033/D-18 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/predicates.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-19 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Three-valued logic: each rule defines a violation predicate and fires only when it is definitively TRUE — NULL-involved comparisons evaluating to SQL `UNKNOWN` do **not** fire (`not_null`/`coercible` own nulls; declare them if nulls are invalid). Applies to `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` — a NULL fk is not an orphan. Corrects Document 5's referential lowering: the bare `COALESCE(fk, '__unknown__')` sketch was wrong (it maps a NULL fk to the unknown member); the lowering is `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END`.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/predicates.py` `tests/fixtures/quality_precedence/mapping_dups.yaml` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-20 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction *given the metadata contract* (D21): `_source_row_id` is declared **NOT NULL and unique per source row**, an ingestion-layer obligation enforced at run time by a generated blocking audit on the metadata columns (a data property, not compile-checkable). Null ordering pinned: `NULLS LAST` on **every** sort key including `_source_row_id` (defense in depth — DESC defaults to NULLS FIRST on several engines, so an illegally-null identity must still lose, never win).

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_dedupe_and_reject.py`

### S-0033/D-22 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Replay merge semantics: replay applies the **same dedupe ordering** as the pipeline — a replayed candidate merges by entity key and wins/loses against an incumbent by the dedupe total order (recency, tie-breaks, `_source_row_id`); multiple rejects resolving to one key are ordered the same way. The per-entity replay batch is one atomic MERGE (transactionality is the executing engine's; bloomery emits the artifact); idempotence follows from the total order — re-running replay re-derives the same winners — and is defined over **semantic state** (winners merged, `resolved_at` transitions), observability columns excluded: `last_seen` updates only when a row is actually re-evaluated.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_quality_precedence.py` `tests/execution/test_replay_to_bronze.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0064/D-3 — `ASSUMED` (Declared source freshness)

Durations reuse `quarantine.retention`'s grammar and validator. One spelling of a duration across the spec surface.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/spec/quality.py` `tests/fixtures/quality_precedence/mapping_codes.yaml`

<!-- /torve:managed -->
