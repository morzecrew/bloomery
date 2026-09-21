<!-- torve:managed tests/unit/test_resolve — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_resolve/`

### S-0002/D-6 — `ASSUMED` (Multi-project composition) — implementation: partial

Lineage node ids gain a project component for imported nodes only; a local node keeps its `<kind>.<name>` spelling

- Paths: `src/bloomery/resolve/graph.py` `src/bloomery/resolve/lineage.py` `src/bloomery/guardrails/lineage.py` `tests/unit/test_resolve/test_lineage.py` `tests/unit/test_guardrails/test_lineage.py`
- Consequence: Every existing id and every published citation stays valid — a node name is public surface and `bloomery lineage --node metric.gross_revenue` is a documented invocation — while two projects' graphs can be composed without collision

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-7 — `ASSUMED` (Spec layer and error model)

`materialization` is explicit-with-derived-default (settles original open question #4); the resolved value is IR-recorded and diffable.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/entity.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0020/D-1 — `ASSUMED` (Intermediate representation and determinism contract)

IR is frozen stdlib dataclasses (slots), not Pydantic — validation happens at build, value semantics matter after.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py` `tests/unit/test_resolve/test_build.py`

### S-0020/D-4 — `ASSUMED` (Intermediate representation and determinism contract)

All IR collections are tuples with explicit lexicographic sort, except authored-order fields (`key`, transform chains, recipe aliases, `partition_by`).

- Paths: `src/bloomery/ir/lower.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/dedupe.py` `src/bloomery/quality/lower.py` `src/bloomery/resolve/build.py` `tests/unit/test_quality/test_dedupe_and_reject.py` `tests/unit/test_resolve/test_build.py`

### S-0022/D-2 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

The compiler never chooses a recipe. The mapping's recorded `recipe:` id is validated — id exists on the catalog field, every `requires` name bound by the mapping's `from` aliases (exactly) — else `ResolutionError`. Choice happens upstream; the compiler reproduces it (determinism + auditability, spec §3.4). Consequence: catalog evolution can invalidate recorded choices, and that is a loud error, not a silent re-choice.

- Paths: `src/bloomery/evidence.py` `src/bloomery/guardrails/operands.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/catalog.json` `tests/golden/schema/mapping.json` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_resolve/test_recipes.py`

### S-0022/D-4 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

Any cycle in the DAG raises `CircularDerivation` (a `ResolutionError` subclass) naming the full cycle path, rotated to the lexicographically smallest node for stable messages.

- Paths: `src/bloomery/errors.py` `src/bloomery/resolve/order.py` `tests/unit/test_resolve/test_order.py`

### S-0022/D-5 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

Emission order is a topological sort with ties broken lexicographically by node name — implemented once in resolve; all consumers take the order from `Resolution`. This is the package's main determinism hazard, contained here.

- Paths: `src/bloomery/resolve/order.py` `tests/unit/test_resolve/test_resolution.py`

### S-0022/D-6 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

`Resolution` = reachable metrics, unreachable metrics + reasons, per-field provenance (`direct` | `recipe:<id>` | `tenant-native`), topo order — all tuples, explicitly sorted. `resolve(project, catalog)` is a pure function, no I/O, and public API.

- Paths: `src/bloomery/resolve/resolution.py` `tests/unit/test_resolve/test_resolution.py`

### S-0022/D-7 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

All cross-spec reference validation lives here, not parse (S-0019/D-4): mapping targets, `canonical:` links, relationship endpoints, metric template refs. All failures are `ResolutionError`s with source paths, batched per stage; later checks run only on a reference-clean graph.

- Paths: `src/bloomery/errors.py` `src/bloomery/resolve/refs.py` `tests/unit/test_resolve/test_refs.py`

### S-0025/D-13 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

(Reverses D6) Bloomery owns the date dimension: one catalog definition emits both the SQLMesh `gold.dim_date` model and the MetricFlow time-spine declaration (S-0030 R1). D6's demand-gate is satisfied — MetricFlow is the demand.

- Paths: `src/bloomery/emit/lower/marts.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/metrics.py` `tests/execution/test_marts.py` `tests/fixtures/ecom_basic/catalog.yaml` `tests/golden/schema/catalog.json` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_fixtures.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_metrics.py`

### S-0027/D-6 — `ASSUMED` (Marts and role-playing dimensions)

Mart flattening is resolved at IR build (`bloomery/marts/`, pure): consumers see the wide schema, never the recipe. `ProjectIR.marts` is fingerprint-covered.

- Paths: `src/bloomery/marts/flatten.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py`

### S-0027/D-9 — `ASSUMED` (Marts and role-playing dimensions)

(Amended for `_bloomery-metricflow-pivot.md`) Marts are the emission source for MetricFlow semantic models — one mart = exactly one semantic model (S-0030 R1); a measure-carrying mart must declare a date role (`MartMissingTimeDimension` otherwise). Marts and role-playing are *more* load-bearing after the pivot, not less.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/marts/flatten.py` `src/bloomery/quality/mart.py` `src/bloomery/resolve/graph.py` `tests/fixtures/ecom_basic/marts.yaml` `tests/fixtures/quality_precedence/entity_model.yaml` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_fixtures.py` `tests/unit/test_quality/test_mart.py` `tests/unit/test_resolve/test_graph.py`

### S-0033/D-21 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Ingestion metadata contract: entities using `quarantine` or `dedupe` require bronze `_load_id`, `_ingested_at`, `_source_row_id` (a stable per-source-row identity supplied by the ingestion layer, **NOT NULL and unique per source row** — data properties no compiler can check, so the lowering emits a generated **blocking audit** on the metadata columns: a null or duplicated `_source_row_id` stops the run); column absence is the new compile error `IngestionMetadataMissing` (`GuardrailError` leaf, `errors.py` per S-0019/D-3). `reject_id` = sha256 over the length-prefixed utf-8 **pair** (`source_relation`, `_source_row_id`) — canonical serialization per the S-0020 canon-bytes doctrine. This supersedes the triple this row first carried (this round's own earlier decision): `_load_id` is removed from the identity and becomes an attribute (the latest observing load) — re-deliveries of the same source row across loads must land on the **same** reject row (that is what `first_seen`/`last_seen` track); a per-load identity would mint a new row per retry and violate replay idempotence. A re-delivery updates `last_seen`/`_load_id`/`failed_rules` on the existing row.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/quality.py` `src/bloomery/quality/catalogue.py` `src/bloomery/quality/dedupe.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/common.py` `src/bloomery/transforms/_builtins.py` `tests/e2e/test_dbt_parse.py` `tests/e2e/test_sqlmesh_project.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_dedupe_and_audits.py` `tests/execution/test_merged_cleaning.py` `tests/execution/test_zoneless_utc.py` `tests/fixtures/dirty/README.md` `tests/fixtures/semi_additive_inventory/mapping.yaml` `tests/support/execution.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_trino.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_spec/test_entity.py`

### S-0034/D-11 — `ASSUMED` (The step registry: referenced implementations)

Steps are IR and DAG citizens: `StepIR` nodes (ref, version, kind, determinism, `runtime_lock`, typed inputs/outputs) in a new `ProjectIR.steps` tuple (S-0020 amendment) and first-class `step.<ref>` DAG nodes (S-0022 amendment). Fingerprint coverage is the whole mechanism: any manifest change — `runtime_lock` included — shifts `project_fingerprint`; `plan()` sees an ordinary structural IR diff (no special-casing); the S-0031 hydration cache self-invalidates via `HydrationKey.spec_fingerprint`, no new key component.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/graph.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_resolve/test_graph.py`

### S-0034/D-50 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **Tier 1 has a spec surface: a mapping references a macro, in two shapes.** D26 refused a wired `sql_macro` because none existed, so the docs described a splice that could not happen. A field mapping gains a third shape beside `from:` and `recipe:` — `step: ref@version` with `from:` binding the columns it consumes — and a transform chain gains a `{step: ref@version}` link, so Tier 0 and Tier 1 compose on one field (the field shape binds a *raw* source path, so without the link no whitelist transform can run before the macro). A macro is referenced **inline**, never wired in `steps:`: it writes no relation, so it has no output to bind there, and one wiring per ref (D13) would make a macro usable in exactly one mapping with one parameter set — the pressure that produces `fuzzy_score_strict`, which is the fork §5.7 exists to refuse. Parameters are therefore supplied at the call site. The splice happens at **lowering**, so the macro is part of `ColumnIR.expr`, the model stays one query, and lineage sees through it — which moved `macro_expression` from `emit.steps` down to `bloomery.steps.splice` (emit sits *above* resolve, so the emitter could not own a splice the lowering needs), taking `parameter_literal` with it now both SQL tiers need the same typed literal. Consequence found by the type gate rather than by reading: the field-mapping union grew a third member, and five sites assumed two — a macro binds aliases like a recipe and has no chain, so they test an `ALIAS_BOUND` pair.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/splice.py` `tests/unit/test_resolve/test_edge_shapes_offcorpus.py` `tests/unit/test_steps/test_splice.py`

### S-0034/D-51 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **A macro declares its signature; it is never read off its body.** The first cut inferred the signature from the body's `:name` placeholders. That is the third appearance of one temptation, and it is refused for the third time — D43 refused fabricating references from matching key columns, D49 refused auto-linking canonical fields by name. The deciding argument is the ladder itself: Tier 0's `TransformSpec` declares `input_domain` **and** `output_type`, so a macro declaring neither would be the one tier whose inputs nothing checks, while §5.1's table claims Tier 1 can *parse and typecheck*. `StepManifest` gains `accepts: {column: type}` — a separate key from `inputs:`, which is relation-shaped for table steps, because one key meaning two things by kind reads fine only to whoever wrote it. The output type needs no new field: a macro has exactly one output of exactly one column (D18b). This buys three things. The **body** is checked against the declaration once, at the registry, where a disagreement is the platform's bug rather than a puzzle handed to every call site. The **call site** is checked against the declaration, so the message names what the macro expects instead of only which placeholder was unfilled. And a **chain** is typechecked *around* the link: the run before it against what it accepts, the run after it from what it produces — implemented as segments queued into the ordinary batch stage, so S-0023/D-2's one-aggregate property survives for chains containing a macro. Named cost, recorded rather than discovered: a genuinely polymorphic macro (`COALESCE(:a, :b)` over any type) must now pick a concrete type. Tier 0 carries the identical constraint through `input_domain`, so it is consistent rather than a new tax — but it is a real limit. A chain link must accept exactly one column, since a chain carries one running value; a two-column macro is refused there and pointed at the field shape.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/mapping.py` `tests/golden/schema/mapping.json` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_declared_zone.py` `tests/unit/test_schema.py`

### S-0039/D-5 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`stage_reached` is mandatory to read**, stated first in the docstring and tested on the ambiguous case: an empty `unreachable` means "nothing unreachable" only at `COMPLETE`, and means "never computed" at `PARSE`. Without it the empty tuple is ambiguous in exactly the way that produces a wrong conclusion.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/resolve/build.py` `tests/unit/test_cli.py` `tests/unit/test_resolve/test_lineage.py`

### S-0039/D-11 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`UnreachableMetric` is extended, not redeclared, and the IR version moves with it.** The draft declared a new dataclass of that name in `evidence.py`; `ir/nodes.py:552` already has one, on `ProjectIR.unreachable` — the very tuple `SpecEvidence` projects. Two same-named public types differing by a field is a trap with no upside, so the IR type gains `via: tuple[str, ...] = ()` and is re-exported. The default does **not** make this free: the encoder writes each dataclass's field *count* and names, so any spec with an unreachable metric re-fingerprints and `bloomery_ir_version` goes 4 → 5. The draft's `name` → `metric` rename was measured at the identical cost; it is dropped for buying only a synonym, not for being expensive.

- Paths: `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_reach.py`

### S-0041/D-1 — `LOCKED` (Deterministic union merge)

Several mappings may target one entity; they are merged with `UNION ALL`. This replaces the refusal at `resolve/build.py:849` and keeps the promise its message makes. Consequence: `EntityIR` gains a set of source mappings where it had one, and every consumer reading "the mapping" of an entity must be revisited.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-3 — `LOCKED` (Deterministic union merge)

Mappings are unioned in **lexicographic order of source name**, so the emitted artifact is byte-identical across processes. Row order is explicitly **not** claimed — `UNION ALL` is a bag, and nothing downstream may depend on source order.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `tests/unit/test_determinism_guard.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-4 — `LOCKED` (Deterministic union merge)

Every mapping must produce the entity's **full declared key** and **every required field**. A partial key makes the union meaningless; a NULL-filled required field is a broken contract silently created by the merge.

- Paths: `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-6 — `LOCKED` (Deterministic union merge)

The union is the **first** silver stage: union → dedupe → rules. A rule evaluated per source would judge rows the merged relation does not contain, which is the same argument that fixed dedupe-before-rules in S-0033.

- Paths: `src/bloomery/emit/lower/silver.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-9 — `ASSUMED` (Deterministic union merge)

Change classification needs no new class — but adding a mapping to a single-source entity is **two** `ADDITIVE` changes, rows and the `_source` column, not one. `_source` exists only on merged entities (D7), so the column set does depend on mapping count; emitting it everywhere to avoid that would churn every golden in the corpus for a constant. Verify the removal rows during implementation: dropping to one mapping removes `_source`, and anything reading it must trip the existing contract check.

- Paths: `tests/unit/test_plan/test_diff.py` `tests/unit/test_resolve/test_build.py`

### S-0041/D-12 — `LOCKED` (Deterministic union merge)

`(target, source)` is **unique**: two mappings for one entity may not read the same source relation. Lexicographic ordering needs a total order and two branches on one relation tie, which would leave branch order undefined, `_source` ambiguous, and the collision audit unable to name a branch. Consequence: reading one relation twice is expressed as one mapping with a filter, not two mappings.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-23 — `ASSUMED` (Deterministic union merge)

**Answers D10 (`OPEN`) — `scd: type2` plus multi-source is refused.** The expected answer, and D14 makes it cheap: the collision audit would fire on every key holding versions from two sources, and distinguishing a version from a collision needs the validity columns S-0040/phase-2-the-as-of-join proposes and does not build. Refused with a message naming that dependency, so the refusal routes rather than merely blocks.

- Paths: `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_build.py`

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-33 — `LOCKED` (Deterministic union merge)

**Every mapping of an entity opts into the quality system, or none does; disagreement is refused (P2a).** `opts_in(entity, mapping)` is a disjunction over one mapping's field-level `quality:` blocks, so two mappings can disagree about whether the entity joined the system at all — and the same predicate selects `_try_cast_shape`, so the disagreement reaches column lowering and not only rule generation. This is not the "where is it computed" question D32 answers; it is two contradictory statements by an author, and the honest response to those is a refusal naming both source paths. It also settles a **fourth** per-mapping coupling D29 did not enumerate: `_repair_bodies` (`resolve/build.py`) reads `mapping.fields[<column>].quality[].repair`, so two mappings may name different repair recipes for one column. Under agreement that is the same refusal rather than a fifth case — and the spliced body itself is invariant, since it reads the *produced* column, not a source path. Consequence: `lower_quality` may go on taking one `Mapping`. Agreement is what makes any of them the same answer, and the refusal — not a merge rule — is what makes that safe.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/build.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_resolve/test_build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-36 — `ASSUMED` (Deterministic union merge)

**Answers D28 — `direct:` is allowed on a merged entity when *every* mapping records one for the column, and refused when they disagree.** D28 refused the combination outright and handed P2 a choice between "one shadow projection per source with a null-safe audit" and "a coverage rule in D4's shape". Measured with the refusal disabled against two mappings that *agree*, the null-safe audit is answering the wrong question: the shadow column is duplicated on the entity **and on every branch**, the reconcile audit is emitted twice, and each branch carries the other's extraction — `shop__items` projecting `$.unit_price` off a relation that does not have it. That is not a NULL-shadow problem, it is `Derivation` being built per mapping while `_shadow` returns one projection: the same per-mapping-fact-on-a-shared-node shape D26 split for `expr` and D32 for the rule inputs. So the coverage rule is the answer and the null-safe audit is unnecessary under it — under agreement no branch's shadow is NULL for want of a path, and the reconcile check keeps the meaning it has on one source: the recipe-derived value against the direct value *that row's own mapping* extracted, which is D32's principle applied to a second reader. Consequence: `Derivation` carries its source relation, `path_conflict_amendments` fans out per source like every other lowering, and disagreement is refused by D33's pattern rather than tolerated. D28's row stands unamended — its refusal is correct until this one is executed, and what it predicted is the thing this has to be read against. *Added by execution 2026-09-03 — see logs/T-0012.md (F-8), which carries the probe output.*

- Paths: `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `tests/execution/test_path_conflict.py` `tests/fixtures/path_conflict_merged/entity_model.yaml` `tests/fixtures/path_conflict_merged/mapping_legacy.yaml` `tests/golden/test_sqlmesh_duckdb.py` `tests/unit/test_fixtures.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_resolution.py`

### S-0048/D-2 — `LOCKED` (Lineage)

**`Graph`, `Edge`, `Lineage` and `Direction` join `bloomery.__all__`, and `Resolution` gains `graph` with no default.** A traversal returning a sub-DAG is unusable if its return type is private, and `Node`/`NodeKind` are already public — the surface is being completed. No default on the field because a `Resolution` without its graph is not a state this design wants representable. Consequence: both types are bound by `stability.md`'s SemVer rule from this point, and hand-constructed `Resolution`s in tests break loudly rather than silently carrying an empty graph.

- Paths: `src/bloomery/resolve/resolution.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0048/D-6 — `ASSUMED` (Lineage)

**The edge-label vocabulary is closed at eight labels and nine `(label, src kind, dst kind)` triples, read off the builders and pinned by a test keyed on the triple.** The first draft of §5.3 was compiled from the 22 fixtures, and that method cost two entries: `_step_edges` emits `step_input` at three sites and the corpus reaches one, so both `step → step` forms were missing; and `_mapping_edges` labels a Tier 1 `sql_macro` field `step:<ref@version>`, which no fixture declares, so the label itself was missing. Consequence: the corpus is a witness to this table, never its source, and a guard keyed on the label alone is specifically the one that cannot catch a new shape of a label it already knows. Depart if a label turns out to be constructed dynamically anywhere, which would make the closed set a lie rather than a contract.

- Paths: `src/bloomery/resolve/graph.py` `tests/unit/test_resolve/test_edge_vocabulary.py` `tests/unit/test_resolve/test_lineage.py`

### S-0048/D-7 — `ASSUMED` (Lineage)

**`_field_provenance` stays as it is, and a test pins that it agrees with the graph.** Measured: 146 entries, 0 mismatches. Unifying them is right and re-decides S-0047/D-8 from inside this document, which the corpus's amendment rules forbid. Consequence: two accounts of one fact ship deliberately, with the check that makes the eventual unification a refactor instead of a rediscovery.

- Paths: `tests/unit/test_resolve/test_lineage_agreement.py`

### S-0049/D-1 — `LOCKED` (Mapping identity)

**The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (S-0019/source-paths). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/common.py` `src/bloomery/spec/mapping.py` `tests/property/test_schema_agreement.py` `tests/unit/test_resolve/test_resolution.py` `tests/unit/test_spec/test_mapping.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0049/D-4 — `ASSUMED` (Mapping identity)

**The identity stays out of the IR, the fingerprint and every artifact.** It is a coordinate for an assessment, and S-0020's determinism argument is about what reaches output. Consequence: a rename moves a report and nothing else; if a future change wants mapping identity in the IR, D1's rename cost has to be re-argued there, because a filename in a fingerprint makes a rename a rebuild.

- Paths: `tests/unit/test_resolve/test_resolution.py`

### S-0049/D-7 — `OPEN` (Mapping identity)

**Whether `FieldProvenance` sorts by `(entity, field, mapping)` or `(entity, mapping, field)`.** §5.4 argues the first — a field's answers stay adjacent — but the second groups a reader's attention by document, which is what they will edit. Execution decides against the corpus, and logs it: whichever reads better on `multi_source`'s four collapsed facts is the answer, and that is a thing to look at rather than reason about.

- Paths: `src/bloomery/resolve/resolution.py` `tests/unit/test_resolve/test_resolution.py`

### S-0050/D-3 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**Derived inputs are unioned into `requires_metrics` by the template merge, never written twice by the author.** The DAG, reachability, cycle detection and `depends_on` then need no change at all. The reference checker reads the spec model before the merge and validates the inputs there; both callers use one helper on the spec model, so the set of metrics a derived metric depends on has exactly one definition.

- Paths: `src/bloomery/resolve/metrics.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/metrics.py` `tests/unit/test_resolve/test_metrics.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-6 — `LOCKED` (Loose ends inside shipped subsystems)

The node-id collision is **refused**, not re-spelled. `Node.name` and the `lineage --node` argument are published surface, and the resolve API is not covered by the emitted-artifact stability caveat. Locks the bare `<entity>.<field>` spelling in: changing it later is a breaking change to every stored lineage id, which is exactly what this row buys.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/timeline.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0059/D-8 — `ASSUMED` (Loose ends inside shipped subsystems)

The reservation is checked in one place over every entity name the graph can see, authored and step-synthesized alike, rather than at each of the two sites that mint names. One quantifier, one message.

- Paths: `src/bloomery/guardrails/lineage.py` `tests/unit/test_guardrails/test_lineage.py` `tests/unit/test_resolve/test_graph.py`

### S-0066/D-1 — `LOCKED` (Declared input currency for conversion)

**A conversion's input currency must be a declared or derived fact; an unknown input is refused.** This is the whole document: an assertion that nothing can check is indistinguishable from a fact, and the difference is a wrong number that passes every existing guard. Locked because relaxing it — accepting `from` as its own evidence — restores exactly the situation S-0053/D-3 was written against, and because the refusal is what makes R009 mean anything.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `tests/unit/test_resolve/test_currency_convert.py` `tests/unit/test_semantic/test_denomination.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-3 — `LOCKED` (Declared input currency for conversion)

**The column's currency is what the chain's *last* conversion produces.** The existing per-marker check refuses a correct two-hop chain (§3), and bridging through a major currency is how minor pairs convert in practice. Locked because the guarantee the check buys is a property of where the chain ends, and any rule reading an intermediate step is reading a currency the column is never in.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_currency_convert.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0067/D-6 — `OPEN` (Stable node identity across renames)

Whether node identity is a write-once `id:` or a one-shot `renamed_from:` in S-0024/D-3's shape (§10). Recorded rather than assumed: the codebase already chose the second answer for fields, and a document that does not say why nodes differ is one that looks like it did not know.

- Paths: `src/bloomery/resolve/timeline.py` `tests/unit/test_resolve/test_timeline.py`

### S-0069/D-4 — `LOCKED` (Definition supersession and change attribution)

Attribution runs over the dependency closure, not the named node. The single-node answer is the one `git log` already gives badly.

- Paths: `src/bloomery/resolve/timeline.py` `tests/unit/test_resolve/test_timeline.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0072/D-2 — `LOCKED` (Marts in the lineage graph)

The graph stays a **RESOLVE**-stage product, built from authored documents. No mart edge may require the flattener's output. This is what keeps `bloomery lineage` able to answer on a project that does not compile — which is when the question is most worth asking — and reversing it moves the graph out of `Resolution`, whose reachability report is computed from it.

- Paths: `src/bloomery/resolve/graph.py` `tests/unit/test_resolve/test_graph.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0072/D-5 — `ASSUMED` (Marts in the lineage graph)

A rollup is a `mart` node, with a `rollup`-labelled edge from its parent. S-0065/D-10 refuses a rollup that takes a mart's name, so one namespace is safe; row 14 keeps rollups out of *planner* walks, and a lineage node is not one.

- Paths: `tests/unit/test_resolve/test_graph.py`

<!-- /torve:managed -->
