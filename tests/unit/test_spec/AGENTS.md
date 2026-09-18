<!-- torve:managed tests/unit/test_spec — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_spec/`

### S-0019/D-4 — `ASSUMED` (Spec layer and error model)

Parse validates shape and grammar only; reference existence (entities, transforms, canonical fields) is deferred to resolve/typecheck. Consequence: a shape-valid spec with dangling references parses fine — callers must run `resolve` to trust it.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/__init__.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/golden/schema/metrics.json` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0019/D-9 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-changes.md`) A fifth spec kind `marts:` joins the four (S-0027); `semi_additive` metrics carry a typed `SemiAdditivePolicy` and `non_additive` metrics a `RatioSpec` (S-0028/D-5). Spec-layer scope is still shape/grammar only.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_spec/test_metrics.py`

### S-0019/D-10 — `ASSUMED` (Spec layer and error model)

(Amended for `_bloomery-metricflow-pivot.md`) `metric_time` is a reserved dimension/field name, rejected at spec validation with a clear message (S-0030 R4). The `Metric` model reserves optional `cumulative:` (window / grain_to_date) and derived-expression forms lowered per S-0030's mapping table; both are additive spec surface, parse-validated only.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/spec/common.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/golden/schema/catalog.json` `tests/golden/schema/entity_model.json` `tests/golden/schema/marts.json` `tests/golden/schema/metrics.json` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_spec/test_metrics.py`

### S-0019/D-14 — `ASSUMED` (Spec layer and error model)

*(2026-08-12)* **An entity or mart name is an identifier, because it reaches the model envelope and nothing there quotes it.** Both were unconstrained — `entities: dict[str, Entity]`, and marts under `MemberName`, which only rejects reserved words. Field names travel a *different* path and were always safe: they reach SQL through SQLGlot, which quotes them and doubles an inner quote, verified by compiling a field named `amt") OR 1=1 --` and reading the escaped identifier back out. A **relation** name also reaches the SQLMesh `MODEL (...)` block, which is Jinja over pre-rendered strings (D4) and quotes nothing, so an entity named `t"; DROP TABLE x --` emitted `name silver.t"; DROP TABLE x --,` into the model definition verbatim. Fixed at the spec layer with `^[a-z][a-z0-9_]*$` rather than by escaping at the envelope, on the same reasoning that pins `StepRef`: a relation name has no business carrying anything but identifier characters, and a pattern refuses at the source path where the author can act on it instead of silently mangling the artifact. Step output bindings were already covered by `RELATION_PATTERN`; metric names do not become relations. Every name in the fixture corpus already matched, so the constraint documents existing practice rather than narrowing it.

- Paths: `src/bloomery/spec/common.py` `tests/unit/test_spec/test_relation_names.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-3 — `ASSUMED` (Marts and role-playing dimensions)

`flatten` via-steps require declared `many_to_one`/`one_to_one` relationships (else `FanoutRisk`); chains flatten transitively in authored order; prefixes mandatory; collisions are errors, never auto-renames.

- Paths: `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/spec/marts.py` `tests/golden/schema/marts.json` `tests/unit/test_marts/test_flatten.py` `tests/unit/test_spec/test_marts.py`

### S-0032/D-5 — `ASSUMED` (Query vocabulary: filters, sort, pagination)

**D-Q5:** string-carrier scalars — `str` operands on ordering operators are parsed and validated against the resolved dimension's `LogicalType` at request-validation time, before any rendering: invalid → `FilterTypeMismatch`, non-finite → `InvalidLiteral`; **no SQL cast is ever emitted** (rendered literals are already in the dimension's type). `NaN`/`Infinity`/`-Infinity` refused even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added.

- Paths: `src/bloomery/errors.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/parse.py` `src/bloomery/planner/request.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `tests/execution/test_period_over_period.py` `tests/property/test_planner_properties.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-2 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`OnFail = flag | quarantine | fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/spec/quality.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-3 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Coercion failure is a rule: transform chains lower to failure-marker form (`TRY_CAST`-style per dialect); the implicit, overridable `coercible` rule (default `quarantine`) disposes of it. Retires `Mapping.on_unmapped_enum` (S-0019 amendment — absorbed into `in_enum`/`coercible`) and supersedes S-0025/D-7's never-implemented emitter convention with the modeled reject table.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/guardrails/operands.py` `src/bloomery/quality/predicates.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/execution/test_path_conflict.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-6 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Entity-level `dedupe` requires `tie_break` under `keep: latest_by` (nondeterministic winners violate the core invariant); dedupe-referenced fields' `coercible` is forced to `fail`. Row rules `expression` and `referential` (`on_missing ∈ {unknown_member, quarantine, flag}` — `fail` deliberately excluded: orphans are an expected, recoverable data condition; a pipeline-stopping orphan gate is a `reconcile` check; `unknown_member` keeps aggregates correct via a reserved member row and requires a string-typed fk in v1 — the reserved member is the string `'__unknown__'`; a non-string fk with `unknown_member` is a compile-time `GuardrailError` naming the alternatives, typed per-key sentinels rejected); `reconcile` blocks emit model + non-blocking audit.

- Paths: `src/bloomery/errors.py` `src/bloomery/quality/catalogue.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/quality.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0033/D-23 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`_quality_flags` **and** `failed_rules` share one physical contract: rule names identifier-constrained at parse (no escaping in any lowering); the column is never NULL (empty array / empty delimited string per `DialectFeature.ARRAY`); delimited fallback joins with `,` in lexicographic rule-name order; `_quality_ok` generated per shape; flag-set equality across lowerings asserted in the dialect-matrix tier. The reject table's `failed_rules` lowers by exactly this contract — array where `DialectFeature.ARRAY`, else the lexicographic comma-delimited string.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/engines/test_merged_cleaning_engines.py` `tests/unit/test_quality/test_flags.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-87 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-10)* **`repair` lands, its recipe is a registered `sql_macro`, and its marker is its own column. D17 is closed.** D17 gated the disposition on a repair-recipe contract and left §10 asking *inline vs catalog-referenced*. S-0034's step registry answers both at once: a recipe is `ref@version` into the registry — declared signature, `runtime_lock`, determinism tier, trust-then-verify — and D1 already holds that specs reference implementations and never contain them, so an inline recipe would have been a second, weaker copy of all of it reachable only from here. **The lowering.** The recipe is spliced at IR build, where the registry lives, and travels as SQL in the rule's params the way an `expression` rule's body does — so emission needs no registry, and a version or `runtime_lock` bump lands in the IR where the fingerprint and `plan()` see it (measured: a body change classifies RESTATING and puts the entity in `replay_scope`, because the kind's params define neither an ordered interval nor a membership set and D52's undecidable-means-replay applies). The rewrite happens at the **extract** level, inside the column's own projection: `CASE WHEN <violation over the raw expression> THEN <recipe> ELSE <raw> END`. That placement is what makes every other rule see the repaired value with no extra nesting, and it forces both halves to be rewritten to read the column's expression rather than its name, since the column is being defined in the same `SELECT`. **The marker.** `_quality_repairs` is a separate column, which was cubic's condition in review and is the right one: a rule is recorded there when its recipe *ran and worked* — it fired over the value as delivered and no longer fires over the value that replaced it. `_quality_flags` stays empty for a repaired row, so `has_quality_flags` keeps meaning **currently suspect** and no mart already asking that question changes its answer. Unlike the two universal columns it is emitted only where a repair rule exists: §12 budgeted the silver-schema churn once, and a third column empty for every project not using the feature is not worth re-opening every golden and fingerprint for. **`fallback` is required**, for the same reason `on_fail` is (D2): a recipe that ran and failed leaves the rule violated and the row is disposed of exactly as if no repair had been declared — the alternative, a still-broken value landing in silver marked as fixed, is the `drop` this RFC refuses wearing a friendlier name. **Refusals**, each a property of the declaration alone: `repair` on `coercible` (it fires *because* the projection is already NULL, so the recipe would be handed the NULL rather than the text that failed to cast — fixing a value before coercion is a Tier 1 macro in the mapping, and the message says so), on `unique` (a property of a population; no rewrite of one row makes a duplicate unique), on a row rule (no column to rewrite), two repair rules on one column (both rewrite the same projection, so which value survives would depend on authoring order and the second recipe would judge a value the first had changed), a recipe accepting more than one column (a rule has no `from:` map, and inventing one would make a rule a second mapping surface), and a column the dedupe order reads (dedupe runs *before* the field rules per D7, so the winner would be chosen on the value as delivered and then have that value rewritten underneath it — D6's reasoning exactly). Verified by executing the emitted pipeline over three rows — one the recipe fixes, one it cannot, one it must not touch — and by sabotage: disabling the recipe, and dropping the "did it run" conjunct from the marker, each fail the assertion that names them. **Not built:** `gold.mart_data_quality` gains no `rows_repaired`, so repairs are observable in silver and not in the quality mart. Recorded rather than implied — adding a measure changes the mart schema, and no demand has asked for it.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/spec/quality.py` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/steps.json` `tests/unit/test_spec/test_quality.py`

### S-0033/D-95 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-12)* **An `expression` rule is a predicate over the entity's own columns — enforced, not merely documented.** `ExpressionRule.expr` was a bare string, parsed and spliced into the silver model with nothing checking it: the one authored-SQL surface in the framework with no resolution step, while every neighbour has one (`dedupe` columns D47, `reconcile` sides against a closed grammar, mart `assert` measures, recipe aliases exactly, `coverage` endpoints D91). Three refusals, each closing something **measured** rather than imagined. **A subquery**, and the reason is corruption at least as much as access: the qualifier pass that binds a bare column to the extract descends *into* a subquery, so `amt > (SELECT amt FROM other)` was emitted as `_extract.amt > (SELECT _extract.amt FROM other)` — correlated to the outer row, reading nothing from `other`. Executed on DuckDB with `amt` 10 against 1: the author's predicate is true so the rule must not fire, and it fired, flagging a good row — under `quarantine` that diverts it out of silver, which is data loss from a rule that reads correctly in the spec. A row predicate needs no subquery, and one that did could not be trusted to mean what it says; a comparison against another relation is what `reconcile:` is for. **A column the entity does not declare** — D47's own words, "a run-time binder failure on a model that compiled clean". **A qualified reference**, because the extract supplies the qualifier and a written one either names a relation the rule cannot read or shadows bloomery's. **Left open, deliberately:** the function vocabulary. `amt > pg_sleep(10)` still compiles, and narrowing that means giving expression rules a closed function list the way S-0021 gives transform chains one — a design decision about the surface, not a defect anything here demonstrated. Recorded rather than quietly widened, because the difference between "measured and fixed" and "seemed unsafe so I restricted it" is the difference this corpus is written to preserve.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_sql_text.py`

### S-0033/D-96 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-12)* **A `pattern` rule may not nest unbounded repetition, because the cost is invisible from the spec and lands on one engine only.** The portable-subset scanner asked whether a regex *means* the same thing on every dialect (D5) and never what it *costs*. `^(?:a+)+$` passed — capturing groups are already refused, so the audit's first example was wrong, but `(?:…)` is accepted and reaches the engine. That is the textbook catastrophic-backtracking shape: two quantifiers can split one input exponentially many ways, and a non-matching subject makes the matcher try all of them. **Why the spec layer and not the engine.** DuckDB (RE2) and Trino (RE2J) match in linear time and would shrug; **Postgres** backtracks. So the rule passes review on the dialect a developer runs locally and hangs the one production uses — the same "silently means something else on another dialect" failure D5 exists to prevent, with the argument applied to cost rather than meaning. The check is one flag per open group in the existing single-pass scanner: an **unbounded** quantifier (`*`, `+`, `{n,}`) applied to a group whose body matches a **varying** length. The two halves are deliberately different tests, and the first cut got it wrong by using "unbounded" for both — review caught that `^(?:a{1,2})+b$` was still accepted, and measurement confirmed it: matching 26 `a`s takes 0.008s, 24 takes 0.003s, doubling every two characters. A bounded-but-ambiguous body partitions the input exponentially just as an unbounded one does; only a *fixed*-length body (`{n}`, or no quantifier at all) can be split exactly one way. So `?` now marks a body ambiguous without making an outer repetition unbounded. Bounding **either** side still makes it linear: `(?:a+){1,8}` and `(?:[0-9]{3}-)*` both pass. This conservatively refuses `(?:ab?)+`, which is unambiguous in practice — stated rather than hidden, because the alternative is the overlap analysis rejected below. **The gap, recorded rather than papered over:** alternation overlap. `^(?:a

- Paths: `src/bloomery/spec/quality.py` `tests/unit/test_spec/test_quality.py`

### S-0035/D-7 — `ASSUMED` (Public surface and stability policy)

**The four permissive version keys are pinned to `Literal[1]`**, matching `steps_version`. The draft proposed *adding* keys on the belief that four kinds lacked them; every kind already has one, and the key is the document-kind **discriminator** — a document without it cannot be identified at all, so "missing means 1" would break loading rather than preserve it. The real defect is that `spec_version: 99` and `mapping_version: 42` are accepted and silently read as v1, so a spec written for a future bloomery is misread rather than refused. `spec_version` keeps its irregular name: renaming is a breaking change for consistency alone.

- Paths: `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/entity.py` `src/bloomery/spec/exports.py` `src/bloomery/spec/exposures.py` `src/bloomery/spec/imports.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `tests/unit/test_schema.py` `tests/unit/test_spec/test_document_versions.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_exposures.py`

### S-0037/D-10 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**A property test measures schema/parser agreement** rather than assuming it: every fixture validates against its schema, and mutations the parser rejects are checked against the schema too, with divergences recorded as amendments. The schema is a pre-filter, never the authority — two validators over one grammar drift, and undetected drift reads to a user as arbitrariness.

- Paths: `src/bloomery/spec/exports.py` `src/bloomery/spec/imports.py` `tests/property/test_schema_agreement.py` `tests/unit/test_spec/test_exports.py` `tests/unit/test_spec/test_imports.py`

### S-0040/D-11 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/execution/test_currency_convert.py` `tests/fixtures/currency_convert/catalog.yaml` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_spec/test_catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-18 — `LOCKED` (Deterministic union merge)

**`_source` joins `RESERVED_MEMBER_NAMES`.** Every other generated column is reserved — `_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags` — and a generated column that is not is one an author can collide with. Reserved unconditionally, not only on merged entities: a name that is legal until a second mapping arrives is a trap laid for the change that adds one.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `tests/unit/test_spec/test_entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-1 — `LOCKED` (Mapping identity)

**The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (S-0019/source-paths). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_resolution.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-3 — `LOCKED` (Mapping identity)

**`document` is set by the loader and is not part of the YAML vocabulary.** A document declaring its own name is a second source of truth that can disagree with the first. Consequence: `Mapping` cannot be constructed from YAML alone in a test without the loader — which is already how every test builds one.

- Paths: `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_guardrails/test_operands.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-3 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**Derived inputs are unioned into `requires_metrics` by the template merge, never written twice by the author.** The DAG, reachability, cycle detection and `depends_on` then need no change at all. The reference checker reads the spec model before the merge and validates the inputs there; both callers use one helper on the spec model, so the set of metrics a derived metric depends on has exactly one definition.

- Paths: `src/bloomery/resolve/metrics.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/metrics.py` `tests/unit/test_resolve/test_metrics.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-13 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**String values in a metric filter refuse `{` and `}`, at parse.** Both semantic targets template with braces — Jinja on MetricFlow, `{member}` on Cube — and a value carrying one would need per-target neutralization. One refusal beats two escaping rules that can disagree; a curly brace in a filtered dimension value has no BI use worth the divergence. At parse rather than at the guardrail because it is a property of the document alone, which is where S-0019/D-4 draws that line — unlike D9's dimension check, which needs the marts. NUL and floats are refused in the same validator, for the reasons they are refused everywhere else.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/spec/metrics.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-4 — `LOCKED` (Declared source freshness)

`error_after` below `warn_after` is refused. An unreachable warning is a spec that means something other than what it says.

- Paths: `tests/unit/test_spec/test_quality.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0067/D-2 — `LOCKED` (Stable node identity across renames)

The id is opaque. Compared for equality, never parsed, never used to derive a path, a relation name or an ordering.

- Paths: `src/bloomery/spec/project.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
