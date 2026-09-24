<!-- torve:managed tests/unit/test_semantic — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_semantic/`

### S-0005/D-5 — `ASSUMED` (Semantic proof IR and closed-world checking)

Rules are named, individually documented and independently testable, registered once in a module constant, and a rule identifier is never minted at a call site

- Paths: `src/bloomery/semantic/proof.py` `tests/unit/test_semantic/**` `src/bloomery/cli/render.py`
- Consequence: The alternative — one monolithic checker returning a tree — passes the same tests and cannot answer which rule admitted a given acceptance, which the bug corpus requires of every case it pins; a registry a test asserts against also means a removed identifier fails rather than disappearing
- Check: `uv run pytest tests/unit/test_semantic/test_proof.py::test_every_rule_is_documented_and_uniquely_identified tests/unit/test_semantic/test_proof.py::test_a_rule_id_is_never_minted_at_a_call_site -q` (shadow; runs as `decision:S-0005/D-5`, no log entry owed)

### S-0030/D-9 — `ASSUMED` (MetricFlow backend: manifest emitter and planner adapter)

`RowPolicy` stays a value object, applied as an additional where-constraint always prepended to user filters. The row-policy-survives-every-path AST test survives verbatim and stays merge-blocking, now explicitly covering ratio/semi-additive/cumulative requests (multiple subqueries — the predicate must appear in every scan). V4 verifies MetricFlow pushes constraints into inner scans; if not, that is a security defect and the escape hatch is per-tenant filtered node relations (a change to D3's emitter, not the approach).

- Paths: `src/bloomery/planner/explain.py` `src/bloomery/planner/filters.py` `src/bloomery/planner/policy.py` `tests/unit/test_planner/test_filters.py` `tests/unit/test_planner/test_row_policy.py` `tests/unit/test_semantic/test_plan.py`

### S-0039/D-3 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**Partial analysis is the point**: the pipeline runs to the first refusing stage and reports the prefix. "Seven metrics reachable, two blocked on `cogs`, one refusal at `mappings/crm.yaml`" is unavailable today at any price, and is the most useful sentence bloomery can produce about a spec it will not compile. This is the only new behaviour in the RFC, and the pipeline already supports it — stages are already sequential and already batch.

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `tests/unit/test_evidence.py` `tests/unit/test_semantic/test_ratio_rows.py`

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-2 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (S-0027/D-4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0053/D-1 — `LOCKED` (Measure semantic types and additivity algebra)

**The aggregation vocabulary is a closed typed set, never a target-interpreted string.** `Additive`, `SemiAdditive`, `NonAdditive`, `Ratio`, `DistinctCount`, `Snapshot`. Locked because the planner, the proof rules and every emitter branch on it: an open string set makes each target the authority for what a measure means, which is the arrangement this whole sequence exists to end. Staging the *implementation* across releases is fine; encoding a future class as a string is not.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/fixtures/semantic_corpus/005-semi-additive-balance/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/005-semi-additive-balance/problem.md` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/unit/test_guardrails/test_additivity.py` `tests/unit/test_semantic/test_rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0054/D-2 — `LOCKED` (Safe rollup planner and SemanticPlan IR)

**A `SemanticPlan` whose multiplicity-changing nodes do not reference a proof is invalid IR, not merely unexplained.** The distinction decides whether the check can be skipped under time pressure. Every join that can duplicate a row carries its authorization or the plan does not typecheck.

- Paths: `src/bloomery/semantic/plan.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0054/D-4 — `LOCKED` (Safe rollup planner and SemanticPlan IR)

**Target lowering may not introduce an unproven multiplicity-changing join; a target that cannot represent the plan refuses that target.** Rewriting rather than refusing is how a semantics-preserving plan becomes a wrong number in one emitter and not the others — the divergence class this codebase has paid for repeatedly, and here it would be invisible because the plan was proven.

- Paths: `src/bloomery/planner/semantic_plan.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-2 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Branch uniqueness at the result grain is structural, from the preceding aggregate node, never inferred from data.** An inferred uniqueness is a data-dependent fact standing in for a proof, which S-0005/D-1 refuses by name; here it would silently re-admit the multiplicity the branch split removed.

- Paths: `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/plan.py` `src/bloomery/semantic/proof.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-12 — `ASSUMED` (Rollup marts and pre-aggregations)

**The grain half of §5.2's obligation is discharged by R008, not by R006.** §5.2 calls it a functional-dependency question, written before the source was a mart. `GrainRef` admits only entity *key* columns — `_unknown` in `semantic/closure.py` refuses every other determinant — and a rollup's target is a set of mart columns, of which `customer_segment` is not a key and a date-role bucket like `ordered_month` is not an entity column at all. Nothing needs re-deriving: every column of a mart is determined by that mart's grain, so grouping by a subset partitions rows the mart already proved. What is left is the aggregation-class question, which is the whole of R013.

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/unit/test_semantic/test_rollup.py`

### S-0066/D-1 — `LOCKED` (Declared input currency for conversion)

**A conversion's input currency must be a declared or derived fact; an unknown input is refused.** This is the whole document: an assertion that nothing can check is indistinguishable from a fact, and the difference is a wrong number that passes every existing guard. Locked because relaxing it — accepting `from` as its own evidence — restores exactly the situation S-0053/D-3 was written against, and because the refusal is what makes R009 mean anything.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `tests/unit/test_resolve/test_currency_convert.py` `tests/unit/test_semantic/test_denomination.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0071/D-3 — `LOCKED` (Completing the semantic plan)

**Every node that makes a claim ships with the rule that closes it, in the same change.** `check()` asks the node whether it claims, so a node landing with `claims = False` is exempt from proof permanently and invisibly. A node and its rule are one unit of work; splitting them is how the exemption gets introduced as temporary.

- Paths: `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
