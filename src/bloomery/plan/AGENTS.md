<!-- torve:managed src/bloomery/plan — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/plan/`

### S-0020/D-1 — `ASSUMED` (Intermediate representation and determinism contract)

IR is frozen stdlib dataclasses (slots), not Pydantic — validation happens at build, value semantics matter after.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py` `tests/unit/test_resolve/test_build.py`

### S-0024/D-1 — `ASSUMED` (Plan: spec diff and change classification)

`ChangeClass` is exactly spec §5.5's five members: ADDITIVE, WIDENING, RENAME, RESTATING, BREAKING. Every diffable difference maps to exactly one.

- Paths: `src/bloomery/plan/model.py`

### S-0024/D-2 — `ASSUMED` (Plan: spec diff and change classification)

`plan(old_ir | None, new_ir)` is a pure structural diff of two `ProjectIR`s — no external lineage, no I/O. `plan(None, ir)` = all ADDITIVE (initial deploy); `plan(ir, ir)` = empty, property-tested (S-0026).

- Paths: `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `tests/unit/test_cli.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_exposures.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_steps/test_step_entities.py`

### S-0024/D-3 — `ASSUMED` (Plan: spec diff and change classification)

Renames are explicit only: `renamed_from: <old>` in the spec (carried as `ColumnIR.renamed_from`, an S-0020 amendment). No heuristic inference — determinism and auditability beat convenience. A stale annotation (old name absent from `old`, including `old is None`) raises `RenameTargetMissing` (`PlanError`), which forces the annotation to be dropped after one applied plan.

- Paths: `src/bloomery/errors.py` `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py` `src/bloomery/spec/entity.py` `tests/fixtures/evolution_v3/entity_model.yaml` `tests/golden/schema/entity_model.json` `tests/property/test_plan_properties.py` `tests/unit/test_plan/test_diff.py` `tests/unit/test_plan/test_evolution.py`

### S-0024/D-5 — `ASSUMED` (Plan: spec diff and change classification)

Expand/contract is enforced in this stage: dropping/narrowing a field referenced by a metric reachable in `new`, or by an old-reachable metric that vanished in the same plan, raises `ContractViolation` (`PlanError`). Deprecation must land in a prior version. This is the stage's only refusal — BREAKING changes are classified and returned, not raised.

- Paths: `pages/docs/how-to/evolve-a-spec.md` `src/bloomery/errors.py` `src/bloomery/plan/diff.py`

### S-0024/D-6 — `ASSUMED` (Plan: spec diff and change classification)

`Plan` = ordered `Change` tuple + `BackfillScope` + `downstream_impact` (from `MetricIR.depends_on`) + `has_changes`/`breaking` conveniences. All ordering lexicographic per S-0020 — plans are byte-comparable.

- Paths: `src/bloomery/plan/model.py` `tests/unit/test_plan/test_exposures.py`

### S-0024/D-7 — `ASSUMED` (Plan: spec diff and change classification)

Entity-level `grain`/`key`/`scd`/`materialization` changes are BREAKING at the entity subject (they redefine the row); column diffs are still reported alongside. Type changes follow the S-0021 lattice: widening = WIDENING, narrowing (incl. optional→required) and new required fields = BREAKING.

- Paths: `src/bloomery/plan/diff.py` `tests/fixtures/evolution_v5/entity_model.yaml` `tests/unit/test_plan/test_diff.py`

### S-0033/D-2 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`OnFail = flag | quarantine | fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/spec/quality.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-11 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

S-0024 amendment (dated when implemented): quality rule add/remove/change, disposition changes in both directions, and dedupe changes classify `RESTATING`; `Plan` gains `replay_scope` alongside `backfill_scope` — `quarantine → flag` needs replay, not just backfill.

- Paths: `src/bloomery/plan/model.py`

### S-0033/D-51 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **A disposition is diffed as the author wrote it, not as it routes.** `disposition()` answers a routing question and correctly maps `unknown_member` onto `FLAG` — the row is kept either way — but `plan()` asks a different question, and the collapse made `unknown_member ⇄ flag` invisible: zero changes, `has_changes` False, no backfill, while the emitted SQL gains or loses its `'__unknown__'` CASE and every stored fk restates. D11 requires disposition changes classified in **both** directions, so the diff compares the authored label (`on_missing` for `referential`, `on_fail` otherwise). Replay follows D52 from the routing disposition: `unknown_member → quarantine` starts diverting, so there is nothing yet to replay; `quarantine → unknown_member`/`flag` stops diverting, so the diverted rows replay.

- Paths: `src/bloomery/plan/diff.py`

### S-0033/D-52 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **`replay_scope` names an entity only where quarantined rows can come back.** The shipped rule fired on *any* change to a formerly-quarantining rule, which named the entity for `quarantine → fail` and for a **narrowed** bound — contradicting §5.7's own "a tightening needs a backfill and no replay", and, under `fail`, feeding a replay runner rows that trip the new blocking audit and halt the pipeline. Replay now requires the old disposition to have been `quarantine` **and** one of: the rule is gone; its disposition is now `flag` (`unknown_member` included, D19); or its parameters relaxed. Relaxation is decided from the params where they are ordered (`range`/`length` bounds) or a set (`in_enum`/`in_set` membership, D49's two families together); where they are not — an unorderable `pattern` regex, an `expression` — it is **undecidable**, and the undecidable case reports the replay: a no-op MERGE is cheaper than a row stranded in quarantine, which is what §5.6's "drop plus recoverability" forbids.

- Paths: `src/bloomery/plan/diff.py` `src/bloomery/plan/model.py`

### S-0034/D-6 — `ASSUMED` (The step registry: referenced implementations)

`runtime_lock` is part of step identity: a dependency bump changes the step fingerprint and classifies `RESTATING`, triggering backfill (S-0024 amendment). Invisible — and wrong — without the lock.

- Paths: `src/bloomery/plan/diff.py` `tests/unit/test_plan/test_step_changes.py`

### S-0034/D-11 — `ASSUMED` (The step registry: referenced implementations)

Steps are IR and DAG citizens: `StepIR` nodes (ref, version, kind, determinism, `runtime_lock`, typed inputs/outputs) in a new `ProjectIR.steps` tuple (S-0020 amendment) and first-class `step.<ref>` DAG nodes (S-0022 amendment). Fingerprint coverage is the whole mechanism: any manifest change — `runtime_lock` included — shifts `project_fingerprint`; `plan()` sees an ordinary structural IR diff (no special-casing); the S-0031 hydration cache self-invalidates via `HydrationKey.spec_fingerprint`, no new key component.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/graph.py` `tests/unit/test_plan/test_step_changes.py` `tests/unit/test_resolve/test_graph.py`

### S-0036/D-7 — `ASSUMED` (Lowering decomposition)

**`plan/diff.py` is split on the same axis if it decomposes cleanly, and left whole if it does not** (§5.3), with the finding recorded either way. Two clean splits are worth more than one clean and one contrived. `classify.py` and `scope.py` are the parts worth isolating regardless: the ChangeClass table decides what gets backfilled and is currently interleaved with the walking that feeds it.

- Paths: `src/bloomery/plan/diff.py`

### S-0041/D-14 — `LOCKED` (Deterministic union merge)

**P1 refuses `dedupe:` and `quarantine:` on a merged entity** (§5.6). The boundary is drawn at those two block-level declarations because it is exact, not approximate: every use of the per-source row identity in the silver lowering sits behind one of them — the reject projection, the conservation audit, the dedupe sort key, the replay merge — and the `on_fail: fail` audit path references it zero times. A merged entity may still carry field and row rules (`flag`/`fail`), `assert:`, `references:` and `coverage:`. Consequence: P1 ships the union to entities with no dedupe and no quarantine, which is the shape the `multi_source` fixture needs, and the two blocks return in P2.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/plan/diff.py` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_plan/test_diff.py` `tests/unit/test_quality/test_reconcile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-26 — `ASSUMED` (Deterministic union merge)

**Answers D25 (`OPEN`) — option (a), and D25's blast-radius figure was wrong by an order of magnitude.** The lowered expression moves to a new column-grained `SourceColumnIR` on `SourceIR`; `ColumnIR` keeps the schema (§5.7). D25 said "37 `.columns` read sites" and estimated the cost from that; measured, **exactly 8 sites read a `ColumnIR` lowering field, in 3 files** — `plan/diff.py` (`renamed_from` ×4, `recipe_id`, `expr.sql`) and `emit/lower/silver.py` (`expr.ast()` ×2). Four of those eight are `renamed_from`, which D25 mis-assigned to the lowering half and which is declared on the EntityModel `Field`, so it does not move at all. The 37 was a count of `.columns` readers, and `.columns` readers are overwhelmingly *schema* readers — they survive untouched, which is the whole point of the split. **Real cost: two constructors where there was one, and four call sites.** The golden churn stands regardless — the IR shape moves and D17 bumps the version.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/operands.py` `src/bloomery/guardrails/stage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/facets.py` `src/bloomery/resolve/steps.py` `src/bloomery/resolve/timeline.py` `tests/bench/test_hydration.py` `tests/support/ir_factory.py` `tests/support/plan_ir.py` `tests/unit/test_emit/test_cube.py` `tests/unit/test_emit/test_dbt.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_facets.py` `tests/unit/test_unresolved.py`

### S-0041/D-32 — `LOCKED` (Deterministic union merge)

**A rule's per-mapping dependency is projected as a branch-local column; the rule stays entity-grained (P2a).** The mechanism is not invented here — `coercible` already reads projected `_src_<rule>_<n>` aliases (`quality/predicates.py:source_alias`) rather than inline JSONPaths, because the raw paths live one level down in the extract SELECT, and P1 turned that projection site into `_branch_select`. So a fact only one branch knows already has a way to reach a rule the merged relation evaluates once. **D6 is not violated, and the reading that says it is — that projecting a verdict per branch just *is* "a rule evaluated per source" — mistakes what D6 argues.** D6 argues from the *row population* — "a rule evaluated per source would judge rows the merged relation does not contain" — and the union is `ALL`, so a branch-projected **scalar** verdict judges exactly the rows the union contains. Dedupe runs after the union and may drop a row; that row's flag is then unused, which is not a wrong answer. **The boundary is `WINDOWED_KINDS`** (`quality/predicates.py`, currently `{unique}`): a windowed verdict depends on the population and so may not be computed per branch — and it does not need to be, since its inputs are the produced column values, which D26's split already makes mapping-invariant. Consequence: `coercible` sheds its per-source alias set for one branch-computed boolean ("every source path *this branch* read was non-null"), which collapses the arity problem at the level where arity is known; `in_enum` takes the same shape rather than a second mechanism, its admissible set being the branch's own `enum_map` chain. **The tempting wrong fix is recorded so it is not re-proposed:** NULL-filling a missing `_src_` alias to make the arities agree renders `is_not_null` false, the conjunction never fires, and the rule silently stops checking on that branch — the failure D28 refuses by name, a check that quietly stops checking being worse than one that is absent.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/quality/lower.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/build.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/fixtures/multi_source_quality/mapping_legacy.yaml` `tests/support/quality_rules.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_quality/test_predicates.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0051/D-2 — `LOCKED` (The reject table on a merged entity)

**`source_relation`, `mapping`, `mapping_version` and `reject_id` are projected per union branch.** They are true of a branch and were only ever true of a model because there was one branch. `reject_id` moves with them out of necessity rather than symmetry: its first argument is the branch's relation name, which the union erases. Consequence: `reject_select` reads four more columns off the extract subquery and reads no `SourceIR` at all.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/plan/diff.py` `tests/engines/test_merged_cleaning_engines.py` `tests/execution/test_merged_cleaning.py` `tests/unit/test_plan/test_diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-7 — `LOCKED` (Exposures and downstream consumers)

(Row 2A of the RFC's table.) `affected_exposures` walks marts as well as metrics. The metric-only walk is the shortcut that omits exactly the mart-only exposure, and an impact report that is confidently incomplete is worse than none.

- Paths: `src/bloomery/plan/diff.py` `tests/unit/test_plan/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0064/D-5 — `ASSUMED` (Declared source freshness)

No default threshold. A source with no block gets none; a guessed six hours would emit an assertion nobody made.

- Paths: `src/bloomery/plan/diff.py`

### S-0067/D-1 — `LOCKED` (Stable node identity across renames)

Identity is declared, never inferred. No similarity heuristic over names, SQL or column sets decides that two nodes are the same node; a wrong guess here rewrites history rather than raising an error.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0067/D-3 — `LOCKED` (Stable node identity across renames)

Absence of `id:` reproduces today's behaviour byte for byte. A feature that changes artifacts for projects that did not ask for it is not optional.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/plan/diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0069/D-1 — `LOCKED` (Definition supersession and change attribution)

The delta is stated in spec vocabulary, never as a text diff of emitted SQL. A reader who has to decide which textual differences are semantic is doing the compiler's job.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0069/D-2 — `LOCKED` (Definition supersession and change attribution)

Superseded versions are related, never overwritten. History that replaces cannot answer the question the feature exists for.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0069/D-3 — `LOCKED` (Definition supersession and change attribution)

The compiler never attributes a change to data. "No definition change" is the complete and correct answer when the definition did not change.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-2 — `LOCKED` (Spec timeline)

History is caller-assembled and consumed once, in order. Inherited from S-0073/D-1; restated because this is the document a reader lands on when they want the feature, and the constraint has to be where they look.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/lineage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-3 — `LOCKED` (Spec timeline)

The delta vocabulary is S-0069's and is never restated here. Two tables describing one thing is the drift this corpus has paid for before.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/lineage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-11 — `LOCKED` (Spec timeline)

**A history entry carries the `Project`, not the `ProjectIR`.** The IR does not retain the authored `id:` — S-0067 substitutes it while building node ids and keeps only names, because a field in the IR would move every fingerprint and break that document's D3. A timeline handed only IRs cannot match by id, which makes row 5 unimplementable; taking the spec side fixes it at the source, and the IR P2 needs is derivable from the same pair. Locked because reversing it silently reduces identity to name matching, which is the failure this feature exists to avoid.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/lineage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
