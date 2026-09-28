<!-- torve:managed tests/execution — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/execution/`

### S-0003/D-3 — `LOCKED` (Replay on a historical entity)

The acceptance for this design is an as-of join finding the recovered row, never a row being present in the entity relation

- Paths: `tests/e2e/test_dbt_parse.py` `tests/execution/test_replay_to_bronze.py`
- Consequence: Present-and-invisible is the exact failure this design exists to remove, and a row-count assertion cannot tell the two apart — it passes against the defect
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0023/D-5 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Grain guard: derivation operands must share the derivation's grain or the expression must contain an explicit aggregation over the finer grain. No automatic allocation. `fanout_trap` (S-0026) is the numeric proof.

- Paths: `src/bloomery/guardrails/grain.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/catalog.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/unit/test_guardrails/test_grain.py`

### S-0023/D-10 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Mart-level fan-out guard runs at compile time (_bloomery-changes.md D2, S-0027): `GrainViolation` (a measure whose grain is coarser than the mart's grain listed in a finer-grain mart's `measures`) and `FanoutRisk` (a `flatten:` step whose `via:` relationship is not `many_to_one`/`one_to_one`) are `GuardrailError` leaves, batched like the rest. `fanout_trap` now fails at compile time; its execution assertion is kept because it documents why the compile error exists.

- Paths: `src/bloomery/guardrails/grain.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_as_of_join.py` `tests/execution/test_fanout_trap.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/unit/test_guardrails/test_stage.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0026/D-12 — `ASSUMED` (Testing strategy and fixture corpus)

The corpus grows to fourteen fixtures (D7): `role_playing_dates`, `semi_additive_inventory` (the former `semi_additive`, renamed and extended), `non_additive_aov`, and `multi_mart_refusal` join the spec §7.7 set; `fanout_trap` now proves the compile-time `GrainViolation` (S-0023) and keeps its execution-level wrong-sum proof.

- Paths: `tests/execution/test_marts.py` `tests/fixtures/role_playing_dates/entity_model.yaml`

### S-0026/D-20 — `ASSUMED` (Testing strategy and fixture corpus)

**Semi-additive fixture seed erratum (V2, 2026-08-07 — `spikes/metricflow/VERIFICATION.md` (`spikes/metricflow/VERIFICATION.md`)):** the pivot's paired assertions ("unscoped Jan 1–3 → 90" and "Jan 3 → A 90 + B 40 = 130") are unsatisfiable on one seed — with B=40 on Jan 3 the global MAX date is Jan 3, so the unscoped 3-day answer is 130. `semi_additive_inventory` keeps 100/80/90 as **warehouse-A** balances (A-scoped 3-day → 90), B=40 on Jan 3 (global Jan-3 and unscoped 3-day → 130), and asserts by-month over three months → three rows (issue #241 fixed in metricflow 0.211.0). Month-grain DuckDB results are `TIMESTAMP`s — normalized in the test helper. §5.3/§5.10 amended accordingly; the row-policy AST test asserts "predicate in every scan", not a fixed subquery count.

- Paths: `tests/execution/test_planner_numbers.py`

### S-0028/D-6 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Every dimension reference in `MetricRequest`/`FilterExpr`/`OrderSpec` parses into a `DimensionRef` (S-0027); unqualified reference to a multi-role dimension → `AmbiguousDimension` naming the roles. The planner reads flattened mart columns — no joins, so role-playing needs no planner logic.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/request.py` `tests/execution/test_planner_numbers.py`

### S-0028/D-12 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering correctness (§5.4's semantics — 90-not-270, 130 across warehouses, 2727.27) is now asserted by **execution tests against MetricFlow-generated SQL** (S-0026/planner-test-obligations-rfcs-0011-0013), not by unit tests of our own lowering code — no such code exists under S-0030.

- Paths: `tests/execution/test_planner_numbers.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0032/D-11 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

Rendering: one `where_constraints` entry per `Clause`; `AnyOf` **always** parenthesized (`policy AND a OR b` leaks every row matching `b`); policy first via `RowPolicy.as_clause()` (renaming `as_filter()`; `RowPolicy` stays single-predicate, its op space narrowing with `Op` — `between`/`contains` policies are invalid post-migration, and range policies move into the request filters or become gte-only/lte-only policies); all shipped S-0030/filters-the-highest-risk-surface safety rules unchanged and merge-blocking; `Explanation.filters` built from `Clause` objects, never from parsing SQL.

- Paths: `src/bloomery/planner/explain.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/policy.py` `tests/execution/test_planner_filters.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-12 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`gold.mart_data_quality` is an ordinary semantic model (`run_date` as time dimension); quarantine rate is a `MetricRequest`. Reject tables are never exposed through `MetricRequest`. Deliberate divergence: no `tenant_id` column (Document 5 §7.5 has one) — hard invariant #3 and the tenant guard forbid it; `NamingPolicy` namespaces are the only tenant seam.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/quality/mart.py` `tests/execution/test_quality_mart.py` `tests/unit/test_guardrails/test_quality.py`

### S-0033/D-18 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Disposition precedence for a row failing multiple rules — severity order `fail > quarantine > flag`: any failing `fail` rule stops the run (blocking audit); else any failing `quarantine` rule diverts the row, with **all** failed rule names recorded in the reject's `failed_rules` (flag-level failures included); else flags accumulate in `_quality_flags`. Deterministic for every combination — no compile-time rejection of rule/disposition combinations needed.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/predicates.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_predicates.py`

### S-0033/D-20 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Dedupe is a total order: after `field` DESC and the `tie_break` columns, the final sort key is the stable source-row identity `_source_row_id` — the winner is unique by construction *given the metadata contract* (D21): `_source_row_id` is declared **NOT NULL and unique per source row**, an ingestion-layer obligation enforced at run time by a generated blocking audit on the metadata columns (a data property, not compile-checkable). Null ordering pinned: `NULLS LAST` on **every** sort key including `_source_row_id` (defense in depth — DESC defaults to NULLS FIRST on several engines, so an illegally-null identity must still lose, never win).

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py` `tests/unit/test_quality/test_dedupe_and_reject.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-22 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Replay merge semantics: replay applies the **same dedupe ordering** as the pipeline — a replayed candidate merges by entity key and wins/loses against an incumbent by the dedupe total order (recency, tie-breaks, `_source_row_id`); multiple rejects resolving to one key are ordered the same way. The per-entity replay batch is one atomic MERGE (transactionality is the executing engine's; bloomery emits the artifact); idempotence follows from the total order — re-running replay re-derives the same winners — and is defined over **semantic state** (winners merged, `resolved_at` transitions), observability columns excluded: `last_seen` updates only when a row is actually re-evaluated.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_quality_precedence.py` `tests/execution/test_replay_to_bronze.py` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/support/precedence.py`

### S-0033/D-32 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `fail` rule's audit reads the pre-route population.** Routing is stage 6 and an audit runs after the model is built, so an audit over `@this_model` sees only the rows the split kept — a row failing a `fail` rule *and* a `quarantine` rule was diverted and the run carried on, inverting D18's severity order. The body is a query over the staged extract (the same rows the routing predicate is evaluated over), which stays inside D29's two-relation scope limit because `referential` cannot carry `fail` (D6). Consequences: every kind lowers through the same `violation` predicate (retiring a `coercible`-at-`fail` special case that had silently redefined the rule as `not_null`), and FAIL-disposition rule names are recorded in **both** `failed_rules` and `_quality_flags`, so the quality mart's `rows_failed` is no longer structurally zero for the rules whose firing matters most.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/execution/test_quarantine_replay.py` `tests/unit/test_emit/test_dbt.py`

### S-0033/D-53 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The portable regex subset is an allowlist, closed by construction.** It had been a seven-prefix denylist plus `re.compile`, which accepts every construct nobody listed — verified on DuckDB: a backreference (`(a)\1`), an atomic group (`(?>abc)`), a possessive quantifier (`a*+`) and `\A\d+\Z` all parsed clean and *aborted the run*, while `[[:alpha:]]` and `(?i)` were accepted with divergent meaning. The scanner now names what it accepts — literals, `.`, character classes with ranges and negation, `\d`/`\w`/`\s` and their negations, the anchors `^`/`$`, the quantifiers `* + ? {n} {n,} {n,m}`, alternation, and non-capturing groups `(?:…)` — and refuses everything else *by name*, including anything unrecognized. Refused with reasons: capturing groups (a rule is a boolean match and captures nothing, and numbered groups are what backreferences read — write `(?:…)`), backreferences, atomic groups, possessive and lazy quantifiers, lookaround, named groups, inline flags, comments and conditionals, POSIX classes/collating elements/equivalence classes (locale-defined on Postgres, fixed on RE2), `\A`/`\Z`/`\b`/`\G`, property and character-code escapes, and `\D`/`\W`/`\S` *inside* a bracket expression (an error in ARE, legal in RE2). Two divergences are accepted and stated rather than pretended away: `.` excludes newline on RE2 and includes it on ARE; `\d`/`\w`/`\s` are ASCII on RE2 and locale-defined on ARE. Loosening a refusal later is backward-compatible; tightening one is not (S-0027/risks), so the subset starts small.

- Paths: `tests/execution/test_pattern_anchoring.py`

### S-0033/D-54 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **Anchoring is the author's, enforced at parse.** §5.3 called `pattern` "anchored" and nothing enforced it, so `[0-9]{5}` matched `abc12345xyz` — every SQL regex predicate is a substring match. The alternative was anchoring implicitly at lowering; author-written anchors win because the spec then says what it means (a reader of the YAML sees the whole-value match), because an implicit rewrite would silently change the meaning of a pattern an author deliberately wrote unanchored, and because the refusal is decidable from the spec alone, which puts it at parse (D13). Every **top-level alternative** must carry its own pair — `^a$

- Paths: `tests/execution/test_pattern_anchoring.py`

### S-0033/D-67 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A `fail` rule's audit covers two populations, not one.** D32 moved the body off `@this_model` and onto the pre-route staged extract, which fixed the precedence inversion and, in the same move, stopped covering the rows *already in the entity*. That population is not empty and is not reachable from bronze: a **replayed** row is merged in from the reject table, and its bronze source has aged out of the incremental window by construction — that is the entire premise of `replay_scope` (§5.7). Reproduced end to end: after a widening plus a replay, a row sat in silver whose own `_quality_flags` recorded the blocking rule firing while that rule's audit reported **zero** violating rows — a model contradicting its own data, which is worse than an unchecked population because it reads as coverage. The body is now `pre-route extract UNION @this_model`, exactly two relations, inside D29's limit (`referential` cannot carry `fail`, D6). `UNION` rather than `UNION ALL`: the ordinary violator is in both populations and reporting it twice says nothing extra. The entity leg reads the **recorded** verdict — `_quality_flags` carries FAIL names since D32 — rather than re-deriving the predicate over model columns, which is forced: over the model the coercion marker's source conjuncts are gone and `coercible` would silently re-define itself as `not_null`, the very special case D32 retired. Recorded price: the leg covers rows evaluated under the *current* spec, and a rule added or renamed classifies RESTATING (D11), whose backfill is what re-derives the flags. Replay deliberately does **not** filter `fail` rules out of its MERGE — refusing to merge them would be quarantine outranking fail again, the inversion D32 exists to prevent; the row lands, and the audit is what stops the next run.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/execution/test_quarantine_replay.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_dbt.py`

### S-0033/D-68 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A quality-mart count is 0 on an empty partition, not NULL.** `SUM(CASE WHEN … THEN 1 ELSE 0 END)` answers 0 for a partition that has rows and matches none of them, and **NULL** for one with no rows at all — `SUM` over zero rows has nothing to sum, which the helper's own docstring denied. An entity with rules whose source delivered nothing this run (a first plan, a partition ahead of the data, an ordinary Tuesday) therefore published mart rows whose every measure was NULL, `rows_quarantined` among them — the numerator D34 exists to make correct. A NULL measure does not read as a small number: it drops out of the `SUM` behind `quality_quarantine_rate`, so the rate answers over a population smaller than the one it names. `COALESCE(…, 0)` around every count, and the docstring made true.

- Paths: `src/bloomery/emit/lower/quality_mart.py` `tests/execution/test_quality_mart.py`

### S-0033/D-69 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A replay loser says why it is still out.** D22's `_one_winner_per_key` keeps one candidate per entity key and the MERGE keeps the better of candidate and incumbent, so a candidate that now **passes every rule** can be left behind by either. D36's third statement then re-derives `failed_rules` for every still-unresolved row, and for that row the honest re-derivation is *empty*: `resolved_at IS NULL, failed_rules = []` reads as "quarantined for these reasons: none", on a row that will lose the contest for as long as it exists and can only leave by retention. The re-evaluation now records the reserved entry `(superseded)` — parenthesised for D34's reason, since rule names are `[a-z0-9_]+` at parse and at generation (D23), so no authored or generated name can collide with it. It is recorded exactly when the row passes routing, which, read together with the statement's own `resolved_at IS NULL` filter, has one meaning: admitted by every rule and still not in the entity, so another row won its key. The alternative — keeping the stale `failed_rules` — was rejected as a lie: those rules no longer fire, and a reject row that names rules the current spec acquits is exactly the ageing account D36 closed. The row stays **unresolved**: a superseded reject is the replay-side analogue of a deduped row, and resolving it would claim into the conservation accounting that *this* bronze row reached the entity, when a different one did.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/reject.py` `tests/execution/test_quality_precedence.py`

### S-0033/D-70 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix; escape hatch built by D88)* **`last_seen` is one clock — the data's.** It was written as the row's `_ingested_at` (the reject model, D36) and advanced to `CURRENT_TIMESTAMP` by replay's re-evaluation stamp: two meanings in one column, so no reader could say what a value in it was. §5.6 states both halves and settles neither, so the decision is made here. `last_seen` is **the latest delivery's `_ingested_at`** — when the source last delivered this row — and replay's third statement no longer touches it. The deciding argument is retention: §5.6 measures unresolved reject rows *from* `last_seen`, so a column a replay run advances makes an unresolved row immortal for as long as replay keeps running — §9's "quarantine as a PII lake" with its stated mitigation removed. The engine-clock reading cannot instead be pushed onto the write path either: the reject model is a MODEL query, and a clock call there breaks §6's idempotence and backfill-equivalence gates. What is lost, stated: the reject table no longer records *when* a row was last re-evaluated. What records it is `failed_rules`, re-derived from that evaluation — the clause §5.6 names first. A separate `last_evaluated_at` column is the escape hatch if that loss ever bites; it is named, not built, because it is a schema addition and §5.6's schema is this RFC's. This also strengthens D22: replay's third statement is now byte-for-byte idempotent, so the "observability columns excluded" caveat covers `resolved_at`'s timestamp alone. *(D88 built the escape hatch and re-widened that caveat to two columns — the statement stamps `last_evaluated_at`, so it is idempotent over semantic state again rather than byte-for-byte.)*

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_quality_precedence.py`

### S-0033/D-89 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **Mart-level checks are assertions, not quality rules. §10's open question is settled by the disposition model.** §8 deferred them as "blurs into reconciliation" and §10 asked "reconcile-shaped or new surface?" — the answer is neither, and what decides it is not taste. §5.9 draws the boundary at what a verdict *does*: a quality rule disposes of a **row**. A mart row is derived — no `_source_row_id`, no bronze payload, no reject table, no replay — so there is nothing to quarantine, nothing to repair, and nothing to bring back; and a `reconcile` compares *two sides*, which "no month has zero revenue" is not. What is left is D4's other half, "alert me", so `assert:` on a mart declares `{measure, agg, by, min/max, on_fail}` and lowers to an audit the mart model names. `quarantine` and `repair` are absent from its `on_fail` rather than lowered to something weaker, so an author who wanted routing learns it at the surface instead of from a mart that silently only alerts; `fail`/`flag` map to blocking/non-blocking exactly as `reconcile.on_fail` does (D38). The aggregate vocabulary is deliberately the *same tuple* the reconcile grammar uses — both compute one number over a column so a human can be told it is wrong, and two lists that mean the same thing drift. Bounds ride in `params` as text through the D57 carrier, for the same reason. **Resolution is against the flattened column set**, not the base entity's: `ordered_month` exists only because a `date:` step made it, and it is precisely the column §10's example groups by. **The body** is `SELECT <by…>, <agg>(<measure>) FROM @this_model [GROUP BY <by…>] HAVING <bound comparison>` — the value beside the group, because a failure a human must open the warehouse to understand gets ignored. A bare `HAVING` with no `GROUP BY` is the whole-mart form; both shapes were executed on DuckDB, postgres 16 and `trinodb/trino:483` rather than read out of three manuals, and all three agree. **What it cannot see, stated rather than implied:** D19 reaches the mart, so every aggregate but `count` is NULL over an empty group and the assertion stays silent — which is also why an assertion cannot notice a month that is *entirely missing*: no row means no group at all. `count` is the exception and is the one shape that catches an empty mart. Closing the missing-period case needs a join against the date spine, a coverage check with its own dependency, and it is named here rather than half-built. **dbt refuses a project carrying one**, sharing `refuse_steps`' message shape (**amended by D94**: this row said "dbt and Cube", and the Cube half was already obsolete when it was written — S-0034/D-52 had split the blanket Cube refusal on the argument that Cube builds no relation for anything, and Cube compiles the *entire* quality surface, quarantine and reject tables included, without a murmur; refusing this one check would single it out): neither has the audit form, and compiling clean while the declared gate does not exist is the failure D83 caught in the dialect ports. **Cost recorded:** `MartIR` gains a field, and the canonical encoder covers each node's field *names and count*, so every fingerprint in the corpus moves — the churn §12 budgets, spent deliberately. The fixture carrying the demonstration is `quality_precedence` rather than `ecom_basic`, because an assertion makes a project uncompilable for two targets and `ecom_basic` is the fixture those targets' goldens are built on.

- Paths: `src/bloomery/emit/base.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/execution/test_quality_precedence.py` `tests/fixtures/quality_precedence/marts.yaml` `tests/golden/schema/marts.json`

### S-0034/D-16 — `ASSUMED` (The step registry: referenced implementations)

Multi-output emission resolved — **supersedes the draft §10 entry and its execute-exactly-once constraint** (recorded honestly: that constraint is dropped, not satisfied): each declared output gets its own generated wrapper model, each executing the step and returning its own output; safe **for correctly declared steps** — nondeterministic steps are compile-refused and seeded steps re-execute with the same recorded seed (pure/seeded ⇒ identical results); residual risk recorded: a *misdeclared* step slips the compile check and, under N executions, can produce disagreeing sibling outputs within one run (behavioral gates catch run-to-run, not intra-run, divergence) — accepted for v1, with a cross-output consistency audit named as the demand-gated mitigation. `assert_step_contract` runs in every wrapper against **all** declared outputs, catching partial-output lies wherever the run starts. The N-executions-for-N-outputs cost is documented; a single-execution staging optimization is a demand-gated, named escape hatch — not built.

- Paths: `src/bloomery/emit/steps.py` `src/bloomery/resolve/steps.py` `src/bloomery/steps/manifest.py` `tests/execution/test_step_consistency.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_steps/test_emission.py`

### S-0034/D-40 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13; detection mechanism superseded by D43)* **The cross-output consistency audit is built, not demand-gated.** D16 named it as the mitigation for the one risk one-wrapper-per-output creates and left it to demand. The risk deserves better: N independent executions of a step *misdeclared* as `pure` can produce disagreeing siblings **within a single run** — a `customer_xref` referencing `canonical_id`s the `customer` execution never minted — and nothing else in the project can see that. Every behavioural gate compares run to run; `assert_step_contract` cannot help either, because each output is individually valid. It became more pressing once D36 let these outputs feed marts and metrics, since a disagreement now propagates into numbers. Detection is structural and needs no new spec surface: wherever one output carries another's declared `key`, the reference must resolve. *(Superseded by D43: inferring the relationship from matching key columns fabricates it from coincidence. References are **declared** — `StepOutput.references` — and an implementation must not raise an audit from an inferred match. The NULL-key exclusion and the single-output rule below both survive.)* NULL keys are excluded on S-0033's three-valued discipline — a row with no key value says nothing, and failing a blocking audit on it would punish the ordinary case. A single-output step emits nothing, because an audit with nothing to compare is noise that trains people to ignore the ones that matter. Executed against DuckDB with a seeded orphan rather than read: the audit returns the orphan and stays empty on a consistent run.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/execution/test_identity_resolution.py`

### S-0034/D-43 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13 re-audit)* **References between sibling outputs are declared, never inferred.** D40 detected them structurally — one output carrying another's key columns. That fabricates relationships from coincidence: two outputs both keyed `id` earned a *mutual* pair of blocking audits asserting their id sets are identical, which fails every run on correct data and is the exact failure that teaches people to ignore audits. `StepOutput` gains `references: {column: sibling}`, validated against the sibling's single-column key. Inferring a relationship nobody declared is what S-0023 exists to refuse, and it does not become acceptable because the inference is cheap. Also fixed here: the audit read the *authored* relation while every other step path routes through the naming policy — D34's bug on the audit side, reopened because D34 shipped without a scoping-policy test — and audit names are now prefixed `step_`, with a general path-uniqueness guard over the whole artifact list, since S-0033's `<entity>_<rule>` audits share the namespace and two artifacts at one path compiled clean.

- Paths: `tests/execution/test_identity_resolution.py`

### S-0040/D-11 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/execution/test_currency_convert.py` `tests/fixtures/currency_convert/catalog.yaml` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_spec/test_catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-5 — `LOCKED` (Deterministic union merge)

A key appearing in more than one source is refused by a generated **blocking** audit (`on_fail: fail`), not configurable to `flag` or `quarantine`. Overlap is either duplication or a shared key space by accident, and both are refusals. The message names the identity-resolution step as the escape hatch. Consequence: bloomery's union is for disjoint key sets, permanently — matching stays a step, and S-0038 is not reopened.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_replan.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_examples.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-13 — `LOCKED` (Deterministic union merge)

The collision audit reads the **union output, before dedupe**, and groups by **every** declared key column. Reading `silver.order` would let dedupe collapse the colliding rows before the audit counts them — the audit would be checking the one relation guaranteed not to contain what it looks for. Grouping by a partial key would merge distinct composite keys and block valid data, which on a blocking audit is the worst failure available.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_emit/test_quality_artifacts.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-34 — `LOCKED` (Deterministic union merge)

**Artifact shape varies with mapping count; `_source` stays merged-only (P2b).** The question D7 and D15 both defer, answered once for the provenance column, the metadata audit body and the collision audit together. The metadata audit becomes `PARTITION BY _source, _source_row_id` on a merged entity and stays `PARTITION BY _source_row_id` elsewhere. **The cost is a new precedent, stated here rather than discovered later:** until now the *set* of emitted artifacts varied with a spec, never a generated **body**. The alternative — `_source` on every entity, one uniform audit body, mapping count invisible in the artifacts — buys a reader the property that a merged entity looks like any other, and costs a corpus-wide golden re-stamp plus a constant column on every single-source silver model, which is precisely what D9 declined to pay on measured grounds. Continuing that decision is cheaper than reversing it, and reversing it buys nothing but uniformity. **A third option is named only to close it:** making `_source_row_id` globally unique in bronze would dissolve the question, and it does so by relocating the problem into S-0033/D-21's ingestion contract and breaking every table already landed under it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-35 — `LOCKED` (Deterministic union merge)

**`_source` joins the dedupe sort key, immediately ahead of `_source_row_id` (P2b).** `dedupe_sort_columns` ends in the row identity, and its totality argument is "no two rows can compare equal *given the D21 metadata contract*" — an identity unique per **source relation**. On a merged entity two rows from different sources sharing an entity key therefore compare equal and the survivor is undefined. That shape is what D5's collision audit refuses, but an audit runs *after* the model materialises, so the window is real and the totality argument would be leaning on a blocking check in a different artifact. Adding `_source` restores it structurally and locally, for one extra sort term on merged entities only (D34). It is the same defense-in-depth already pinned into that exact column by `NULLS LAST`, against an illegally-null identity the audit also catches. Consequence: where two rows would have compared equal, the survivor is the lexicographically-later source — arbitrary as business logic, deterministic as an artifact, and reachable only in the run the collision audit then stops.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/quality/dedupe.py` `tests/execution/test_merged_cleaning.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0045/D-5 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/postgres.py` `tests/engines/test_postgres_spellings.py` `tests/engines/test_type_conformance.py` `tests/execution/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-1 — `LOCKED` (The reject table on a merged entity)

**S-0033/D-10 stands: one reject table per entity, merged or not.** Its stated ground — per-mapping tables multiply into the small-file problem and make replay N-way — is a statement about the number of *relations*, and this design adds none. D10 answered a different question and its answer is still right. Consequence: S-0041/D-16's lock is discharged by keeping the decision, not by overturning it, and any future proposal for a per-mapping table argues against D10 as it always had to.

- Paths: `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/entity_model.yaml`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-2 — `LOCKED` (The reject table on a merged entity)

**`source_relation`, `mapping`, `mapping_version` and `reject_id` are projected per union branch.** They are true of a branch and were only ever true of a model because there was one branch. `reject_id` moves with them out of necessity rather than symmetry: its first argument is the branch's relation name, which the union erases. Consequence: `reject_select` reads four more columns off the extract subquery and reads no `SourceIR` at all.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/plan/diff.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_plan/test_diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-3 — `LOCKED` (The reject table on a merged entity)

**Replay filters each branch to `source_relation = '<branch>'`.** Without it a mapping's extraction runs over another mapping's payload and returns NULLs rather than raising — a silent wrong answer, which is the failure class this project refuses. The filter is sound because `(target, source)` is unique (S-0041/D-12), so the literal names exactly one branch.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/execution/test_merged_cleaning.py` `tests/golden/test_sqlmesh_dialects.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0056/D-1 — `LOCKED` (Production-style semantic bug corpus)

**The inclusion rule is "valid SQL, wrong answer" — not "bad data".** It is what separates this corpus from `tests/fixtures/dirty/`, and the separation is the point of both: one holds values bloomery can see are wrong, the other holds values that are all fine while the number is not. A case admitted for the wrong reason dilutes the only thing this corpus proves.

- Paths: `tests/execution/test_semantic_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0056/D-3 — `LOCKED` (Production-style semantic bug corpus)

**Each case pins a machine-readable outcome against a stable rule ID, not prose.** Prose is golden-tested only where diagnostics are already a public contract. This is what lets S-0005's rules cite cases and S-0006's matrix cite both without either restating the other.

- Paths: `tests/execution/test_semantic_corpus.py` `tests/support/semantic_corpus.py` `tests/unit/test_semantic_corpus_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-6 — `ASSUMED` (Rollup marts and pre-aggregations)

The acceptance evidence is S-0056's semantic bug corpus plus an execution-tier comparison against the same request computed from silver. A golden proves nothing here.

- Paths: `tests/execution/test_rollup.py`

<!-- /torve:managed -->
