<!-- torve:managed tests/unit/test_planner — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_planner/`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0026/D-24 — `ASSUMED` (Testing strategy and fixture corpus)

*(2026-08-10)* **The Cube container and the three-way equivalence tier are built; `QueryPlan.columns` does not name the columns the SQL returns.** §5.2's last tier-6 cell and §5.8's tier-7 both need Cube alive, so one harness pairs it with the Postgres holding the mart it describes — on one network, with the table created from `MartIR` through the Postgres dialect port rather than a hand-written column list, since a third statement of the schema would be free to drift from the two that matter. **Cube loads what bloomery emits**, and the load-bearing assertion is the `meta:` block: S-0025/ports says the emitted `additivity`/`grain`/`semi_additive` is what a consumer audits Cube's behaviour against, which is only true if it survives to the API — no golden can show that, and dropping it from the emitter fails the test that names it. The tier does not stop at `/meta`: it issues a query, because parsing a model and running its measure expression are different claims. **Equivalence** points both engines at one relation by construction — Cube's `sql_table` and the planner's SQL name the same `gold.mart_<name>` under the naming policy — so a difference can only come from the query rather than from two seeding routines kept in step. The corpus is smaller than §5.8's "~40 requests", visibly and deliberately: the *classes* buy the coverage (an additive measure at three grains, an ungrouped request, a ratio recomputed per group, a multi-metric request), each costs a Cube round trip in a nightly lane, and growing it is adding YAML entries. The reference SQL runs on **every** request that declares one rather than only after a disagreement — §5.8 calls it the tiebreaker, and a tiebreaker nobody has ever checked cannot break a tie. `known_divergences.yaml` ships **empty**, with its required shape asserted, because §5.8 holds that a silent divergence is a bug in one of the implementations and a pre-populated file would let the first real one hide among plausible neighbours. The ratio fixture seeds groups of **unequal size** on purpose: a ratio averaged from stored per-row values agrees with a ratio of summed components on equal-sized groups and only on those, so equal groups would let the wrong arithmetic pass. Sabotage-verified — a wrong Cube measure expression fails ten of the fifteen. **The finding.** `QueryPlan.columns` is S-0028's "self-describing envelope", but its dimension descriptors carry the *requested* name (`ordered_month`) while the SQL MetricFlow generates aliases them its own way (`order_item__ordered_day__month`). Positional binding works and is what every consumer in this repo does; binding by name silently finds nothing. Two ways to close it, **neither built** — wrap the generated SQL in an outer SELECT aliasing to the requested names (S-0030's call, since MetricFlow owns the aliasing), or state in S-0028 that the envelope is positional and `name` is the request's word rather than the frame's. Recorded because it was written down nowhere. **One harness trap, recorded because it cost a wrong diagnosis:** Postgres logs "database system is ready to accept connections" *twice* — once on the unix socket while `initdb` runs its scripts, then again for real — so a container waiting on the first occurrence connects during the init shutdown and fails with "server closed the connection unexpectedly". It is a race, so it failed intermittently and read as container-memory pressure; the fix is the `PostgresContainer` class the other engine tiers already use, not fewer containers.

- Paths: `src/bloomery/planner/result.py` `tests/equivalence/test_three_way.py` `tests/support/equivalence.py` `tests/unit/test_planner/test_names.py`

### S-0027/D-8 — `ASSUMED` (Marts and role-playing dimensions)

`cost_hint` (int, default 1) is a tie-breaking scan-cost hint only; selection ties break lexicographically (S-0020 determinism).

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_emit/test_metricflow.py` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-2 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Request/response types verbatim from D1: `TimeGrain`, `FilterExpr`, `OrderSpec`, `MetricRequest` (static shape, dynamic content — what the Query Agent emits; malformed requests fail validation, never execute); `ColumnDescriptor`, `QueryPlan` (sql, self-describing `columns` envelope, mart, warnings, explanation, `fingerprint = sha256(sql)`). All frozen dataclasses.

- Paths: `src/bloomery/planner/names.py` `src/bloomery/planner/request.py` `src/bloomery/planner/result.py` `tests/unit/test_planner/test_request.py`

### S-0028/D-3 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Six-step algorithm: validate (`UnknownMember` with `did_you_mean` via difflib, S-0021/D-4) → mart selection (0 → `UnreachableAtGrain` naming the per-metric grain/mart conflict; 1 → use; N → lowest `cost_hint`, ties lexicographic by mart name) → additivity lowering → SQLGlot AST build → `dialect.render` → `Explanation`.

- Paths: `src/bloomery/errors.py` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-4 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Hard rules: never join at plan time (refusal with reason beats a plausible wrong number); `RowPolicy` predicate parsed via sqlglot into the WHERE conjunction of the AST, never string-appended; `order_by` fields must be requested metrics/dimensions (injection surface); `limit` clamped to `NativePlanner(max_limit=50_000)`, clamping adds a `QueryPlan.warnings` entry.

- Paths: `src/bloomery/planner/compose.py` `src/bloomery/planner/metricflow_planner.py` `src/bloomery/planner/names.py` `src/bloomery/planner/request.py` `tests/unit/test_planner/test_metricflow_planner.py`

### S-0028/D-5 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Additivity lowering per D4 exactly: additive → SUM at requested grain; semi-additive (`SemiAdditivePolicy(over, rule ∈ last/first/avg/max/min)`) → sum across every dimension except `over`, rule along `over` (coarser requested grain: rule within each bucket, then sum); non-additive → never stored/summed, recomputed from additive components (`RatioSpec` → `SUM(num)/NULLIF(SUM(den),0)`); missing components = `NonAdditiveWithoutComponents` at resolution/guardrail stage (S-0023 defense-in-depth).

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `src/bloomery/spec/common.py` `tests/fixtures/non_additive_aov/marts.yaml` `tests/fixtures/non_additive_aov/metrics.yaml` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_planner/test_coverage.py`

### S-0028/D-8 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

`Explanation` is deterministic, generated from the plan, never from an LLM; dataclass + `render()` per D8. Product requirement: every number ships with how it was computed.

- Paths: `src/bloomery/planner/explain.py` `src/bloomery/planner/result.py` `tests/unit/test_planner/test_metricflow_planner.py`

### S-0028/D-9 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Errors: `PlannerError(BloomeryError)` with leaves `UnknownMember`, `UnreachableAtGrain`, `AmbiguousDimension`, `InvalidRequest`, all declared in `bloomery/errors.py` (S-0019/D-3). Planner errors are **not batched** — deviation from compile-time batching, justified: the interactive caller fixes one request, and validation-first means failures are mostly singular.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/request.py` `tests/unit/test_planner/test_request.py`

### S-0028/D-10 — `ASSUMED` (Native planner: MetricRequest → QueryPlan)

Mandatory pre-merge test: row-policy-survives-every-path, asserted on the **parsed AST** (predicate present in every table scan), never on a SQL substring — "a string check passes on `-- tenant_id = 'acme'`" (D1).

- Paths: `tests/unit/test_planner/test_row_policy.py`

### S-0030/D-2 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`MetricRequest`/`QueryPlan`/`ColumnDescriptor`/`Explanation` (S-0028) do **not** change — the stable API the Query Agent binds to. MetricFlow types never cross that boundary; errors are translated (`InvalidQueryException` → `UnknownMember`/`UnreachableAtGrain`/`AmbiguousDimension`). This seam is what makes the backend swappable.

- Paths: `src/bloomery/planner/metricflow_planner.py` `tests/unit/test_planner/test_metricflow_planner.py`

### S-0030/D-7 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`planner/names.py` owns the bidirectional bloomery↔dunder mapping (`{entity}__{dim}`, `{entity}__{time_dim}__{grain}`, `metric_time__{grain}`, `-metric` for desc), keyed on the **primary entity** name (not the semantic model name). Callers never see dunder names. `metric_time` is reserved, rejected at spec validation. Property test: every emitter-produced dimension round-trips through `names.py`.

- Paths: `src/bloomery/planner/names.py` `src/bloomery/planner/result.py` `tests/property/test_metricflow_properties.py` `tests/property/test_planner_properties.py` `tests/unit/test_planner/test_names.py`

### S-0030/D-8 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

Filters (Jinja `where_constraints`) are the highest-risk surface: values never interpolated raw — typed per-dialect literal renderer or bind parameters; dimension names only from validated `DimensionRef`s via `names.py`; values type-checked against the dimension (`FilterTypeMismatch`); `contains`/`like` escape wildcards. Adversarial fuzz property test (injection strings, template syntax, unicode quotes, newlines) asserts parsed-SQL predicate structure unchanged and scanned relations exactly the expected mart — **merge-blocking**. *(Superseded by D16 — see §5.6 note.)*

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/request.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py`

### S-0030/D-9 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`RowPolicy` stays a value object, applied as an additional where-constraint always prepended to user filters. The row-policy-survives-every-path AST test survives verbatim and stays merge-blocking, now explicitly covering ratio/semi-additive/cumulative requests (multiple subqueries — the predicate must appear in every scan). V4 verifies MetricFlow pushes constraints into inner scans; if not, that is a security defect and the escape hatch is per-tenant filtered node relations (a change to D3's emitter, not the approach).

- Paths: `src/bloomery/planner/explain.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/policy.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_row_policy.py` `tests/unit/test_semantic/test_plan.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0032/D-9 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

The §5.3 closed list is the deliverable: eight bloomery-owned refusal types + two app-adapter codes (`UnsupportedFieldCompare`, `UnsupportedQuantifier` — the adapter-owned `APP_UNSUPPORTED`, declared in the table for review completeness but never part of bloomery's export; the reason-code sets are disjoint, though the error *classes* live in `errors.py` so the adapter can raise them), all subclassing new `UnsupportedFilter(PlannerError)` with `.reason` (stable code), `.source_path`, optional `.normalized`. `KNOWN_UNSUPPORTED: frozenset[str]` exported from `bloomery.planner` contains only bloomery-raisable codes — the union raisable by the three parse functions (`parse_filter_json`/`parse_sort_json`/`parse_page_json`); drift-guard test: export == that union, introspected across all three; adapter conformance asserts against `KNOWN_UNSUPPORTED | APP_UNSUPPORTED`. Anything not on the list must translate.

- Paths: `src/bloomery/planner/parse.py` `tests/unit/test_planner/test_parse.py`

### S-0032/D-10 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

`parse.py` is a public feature (Mongo-flavoured grammar front door: `$and`/`$or`/`$not` + field maps, scalar = `$eq` shortcut, array = `$in` shortcut, null = `is_null true`), with `parse_sort_json`/`parse_page_json` for symmetry. Typed constructors remain the primary path. The Forze adapter (~30 lines) lives in the application — out of bloomery scope.

- Paths: `tests/unit/test_planner/test_parse.py`

### S-0032/D-11 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

Rendering: one `where_constraints` entry per `Clause`; `AnyOf` **always** parenthesized (`policy AND a OR b` leaks every row matching `b`); policy first via `RowPolicy.as_clause()` (renaming `as_filter()`; `RowPolicy` stays single-predicate, its op space narrowing with `Op` — `between`/`contains` policies are invalid post-migration, and range policies move into the request filters or become gte-only/lte-only policies); all shipped S-0030/filters-the-highest-risk-surface safety rules unchanged and merge-blocking; `Explanation.filters` built from `Clause` objects, never from parsing SQL.

- Paths: `src/bloomery/planner/explain.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/policy.py` `tests/execution/test_planner_filters.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py`

### S-0035/D-4 — `ASSUMED` (Public surface and stability policy)

**`ColumnDescriptor` gains `sql_alias`, additively** (closes S-0026/D-24). `name` keeps meaning the requested dimension; `sql_alias` carries what the SQL returns. Additive beats the cleaner rename because every consumer binds positionally today and the rename would break them all to satisfy a preference; the recorded defect — by-name binding finding nothing — is closed either way. `Explanation` continues to speak `name`.

- Paths: `src/bloomery/planner/coverage.py` `src/bloomery/planner/result.py` `tests/unit/test_planner/test_names.py`

### S-0050/D-5 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `tests/execution/test_period_over_period.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0054/D-9 — `LOCKED` (Safe rollup planner and SemanticPlan IR)

**P2 produces proof-backed refusals, not query-time joins; §11 is superseded by §11a.** The single-hop rollup §11 asked for has no route to SQL — the manifest emitter pins "never a semantic model for a non-mart entity", so a `PreservingJoin` has no relation to reach and bloomery has no second generator to reach it with — and no route from a spec either: across every buildable fixture, zero marts have an unflattened single hop from their own grain, because `flatten: {via: …}` already settles that join at build time. The capability would be a second mechanism for something this design does once, earlier, with the fan-out proof already discharged. Locked because it re-scopes this document and re-gates S-0055 and S-0065. Added by execution 2026-09-06 — see logs/T-0022.md (D132 and D133, attempt 1).

- Paths: `tests/unit/test_planner/test_coverage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-3 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Derived metrics spanning branches are evaluated after operand rollup.** `SUM(a)/SUM(b)` and a row-level `a/b` aggregated afterwards are different numbers, and this is the concrete reason S-0053/D-2 keeps a ratio as its operands. Reversing either strands the other.

- Paths: `src/bloomery/planner/compose.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/names.py` `src/bloomery/planner/semantic_plan.py` `tests/unit/test_planner/test_compose.py` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-4 — `ASSUMED` (Multi-grain aggregate-then-join query planning)

**Any unknown precondition refuses the whole request rather than the branch.** Partial answers across a multi-grain request are how a caller receives a plausible subset and reads it as the whole. Not `LOCKED` because a partial-result surface with explicit missing-branch semantics is a coherent thing to design later — it is simply not this.

- Paths: `src/bloomery/planner/coverage.py` `tests/unit/test_planner/test_coverage.py`

### S-0055/D-8 — `OPEN` (Multi-grain aggregate-then-join query planning)

**Whether `DistinctCount`, `Snapshot` and `SemiAdditive` enter branch planning at all in P1.** §8 gates them on their proof rules being independently sound. Decide per class, with the corpus case each one converts, rather than as a group.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_planner/test_coverage.py`

### S-0055/D-9 — `LOCKED` (Multi-grain aggregate-then-join query planning)

*(its SQL spelling superseded by D18; the route it decides stands.)* **The branch join is bloomery's own SQL, over N single-mart requests MetricFlow renders unchanged.** Each branch is exactly a request the parity corpus accepts today — carrying R008 and the single-mart proof it already has — and bloomery wraps the branch results in a join of its own — written here as `FULL OUTER JOIN … ON a.k IS NOT DISTINCT FROM b.k` with a coalesced key projection, which **D18 replaces**: PostgreSQL will not plan that spelling, and the composition is a key domain and left joins. What this row decides is the *route* — bloomery composes, MetricFlow renders the branches — and that is unchanged. The alternative was measured, not imagined: handing MetricFlow one multi-metric request makes its `CombineAggregatedOutputsNode` render the same shape, correctly. It is refused because unifying two marts' differently-prefixed flattenings of one dimension (`order__country` against `order_item__order_country`) costs a row-level mart-to-mart join that MetricFlow validates rather than bloomery, and because its filter pushdown reaches into every branch through that join — the duplication D5 refuses on name-match grounds. Both hand the engine the authority for cross-branch identity, which S-0054/D-6 exists to keep in bloomery. `LOCKED` because the route decides the node vocabulary, the public surface and every test written against them.

- Paths: `src/bloomery/planner/compose.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/metricflow_planner.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/plan.py` `tests/unit/test_planner/test_compose.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-12 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**A dimension is the same dimension across branches when its provenance triple matches — `(source_entity, source_column, ref)` — never when its name does.** This is §2's "proven common join key" made checkable, and `_same_source` in `planner/coverage.py` already compares that triple for P2's refusals. A branch that cannot produce a requested dimension by identity gets P2's `not_flattened` refusal and its flatten remediation, never a join to go and fetch it. Name equality is not identity, which is D5's reason applied to the key instead of to the filter.

- Paths: `src/bloomery/planner/compose.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/explain.py` `tests/fixtures/cross_mart_branches/entity_model.yaml` `tests/fixtures/cross_mart_branches/marts.yaml` `tests/unit/test_planner/test_metricflow_planner.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-13 — `ASSUMED` (Multi-grain aggregate-then-join query planning)

*(superseded by D18.)* **Null-safe key equality, one key row per group, no re-aggregation pass.** Groups missing from a branch surface as NULL measures, not as dropped rows, and a NULL group key joins to the other branch's NULL group key rather than failing `NULL = NULL` and splitting in two. MetricFlow's own combine node merges that split afterwards with `GROUP BY COALESCE(…)` and `MAX(…)`; composing the join ourselves means never making the split. `ASSUMED` rather than `LOCKED`: a caller who wants missing groups dropped is asking for an inner join, which is a later option on the same node, not a different design.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/planner/compose.py` `tests/unit/test_planner/test_compose.py`

<!-- /torve:managed -->
