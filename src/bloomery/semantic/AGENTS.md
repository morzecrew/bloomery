<!-- torve:managed src/bloomery/semantic — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/semantic/`

### S-0007/D-1 — `LOCKED` (Dimension algebra)

Every relation is declared, never inferred — not from column names, not from cardinality, not from the data. One `GROUP BY` would answer `determines:` exactly, and from a single load of a source that has no counterexample yet; an inference cannot be told from a declaration once written down

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py` `src/bloomery/semantic/closure.py`
- Consequence: A relation has exactly the standing of a declared `many_to_one`: the compiler reads what an author wrote and never looks at a row, so nothing in the closure or the spec models may consult data or guess from a name
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-2 — `LOCKED` (Dimension algebra)

A fact with no consumer is not added. Each of the three relations is listed with the rule or surface that reads it, and one that loses its consumer during execution is dropped rather than landed

- Paths: `src/bloomery/semantic/proof.py`
- Consequence: A vocabulary that outruns its rules is a spec surface nobody can be refused by, which is a promise the compiler does not keep; a relation reaching the spec models without its rule reaching `RULES` is the shape this forbids
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-3 — `LOCKED` (Dimension algebra)

A dimension is not an entity. Modelling `city` and `state` as entities with a declared `many_to_one` would reuse R002 exactly and is rejected: it taxes a two-column fact with a grain, a key and a mapping, and it puts every hierarchy level into the lineage graph as a node nobody builds

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/semantic/closure.py`
- Consequence: The column-to-column determination needs its own fact and its own closure; the entity-keyed machinery is not extended to carry it, and a project with a five-level geography gains no entities
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-7 — `OPEN` (Dimension algebra)

Whether R020 requires a determinant of every dropped dimension or merely proves more when one is present. Requiring refuses rollups that are legal today; proving more leaves them where they are and may be the honest answer. Decide with one real rollup corpus in hand

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py`
- Consequence: The strict reading is a new refusal against projects that compile today; the permissive reading changes no existing verdict and only adds a proof where a determinant exists

### S-0017/D-1 — `LOCKED` (Semantic grain model and functional dependencies)

Grain identity is structural, never a display string: a grain is the tuple of its entity determinants, canonicalized and compared structurally, and human-readable names stay available for diagnostics only

- Paths: `src/bloomery/semantic/nodes.py`
- Consequence: Every document downstream compares grains — the rollup proof, the measure's origin, the branch join key — so a string-equality identity here would be re-derived, differently, in four places
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-2 — `LOCKED` (Semantic grain model and functional dependencies)

Refinement is never implicit: a coarser measure is not moved to a finer grain because a join exists, and any future operation that duplicates a measure must be an explicitly named semantic act with its own design, never a fallback

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/semantic/nodes.py`
- Consequence: Shipping at order grain stays unsafe on an order item, and a rollup question whose target is finer than its source is refused as a refinement rather than answered
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-3 — `LOCKED` (Semantic grain model and functional dependencies)

`one_to_many` and `many_to_many` contribute no dependency in the preserving direction, and no heuristic ever contributes one; the closure admits only entity keys, declared `many_to_one` and `one_to_one` relationships, as-of-qualified historical hops, and transitive closure over those

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/semantic/nodes.py` `src/bloomery/semantic/proof.py`
- Consequence: A `one_to_many` read inversely is a `many_to_one` and is admitted as one; read in its declared direction it contributes nothing, and the dependency it did not contribute is kept as a blocked edge so a refusal can name it
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-4 — `ASSUMED` (Semantic grain model and functional dependencies)

The as-of qualification reuses the historical-fanout guardrail's semantic fact rather than restating it

- Paths: `src/bloomery/semantic/historical.py` `src/bloomery/marts/flatten.py`
- Consequence: Two readings of SCD2 validity in one compiler is the divergence this project has paid for before — one body, two callers

### S-0017/D-5 — `ASSUMED` (Semantic grain model and functional dependencies)

The rollup question is directional — a relation over source grain, target grain and context — and is not graph reachability

- Paths: `src/bloomery/semantic/closure.py`
- Consequence: Undirected reachability would accept an order rolling up to an order item on the strength of an edge existing, which D-2 refuses

### S-0017/D-6 — `ASSUMED` (Semantic grain model and functional dependencies)

Closure output carries a derivation per member, not a boolean

- Paths: `src/bloomery/semantic/nodes.py` `src/bloomery/semantic/closure.py`
- Consequence: A proof tree can be built from the closure and a case can be pinned to a rule, both without asking the closure a second question

### S-0017/D-7 — `LOCKED` (Semantic grain model and functional dependencies)

Determinism on the compiler's own terms: sorted tuples, no sets where order can reach output, byte-stable serialization across processes and hash seeds

- Paths: `src/bloomery/semantic/**`
- Consequence: A sort key over a value a set deduplicated has to be total over that value, or the tie is decided by the hash seed; the blocked-edge tuple was exactly that defect and the determinism guard's corpus now carries the shape that exposes it
- Check: `uv run pytest tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0017/D-7`, no log entry owed)

### S-0017/D-9 — `LOCKED` (Semantic grain model and functional dependencies)

The grain model is derived from the project IR, never stored in it: a grain is computed on demand from an entity's declared key and adds no field to any IR node

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/ir/nodes.py`
- Consequence: The IR version does not move, no project fingerprint moves and no golden moves, which is what turns preserve-observable-behaviour from an argument into a diff; verified by compiling every fixture, target and dialect on both sides of the branch — 251 cells, byte-identical
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-10 — `ASSUMED` (Semantic grain model and functional dependencies)

The as-of fact lives in one function in the semantic package, and the mart guard reads it from there

- Paths: `src/bloomery/semantic/historical.py` `src/bloomery/marts/flatten.py`
- Consequence: Anything in this sequence that needs to know whether a historical hop is qualified calls that function; the anchor states it distinguishes are finer than the two sentences the mart needed, which is what a blocked edge carries

### S-0017/D-12 — `ASSUMED` (Semantic grain model and functional dependencies)

Nothing is cached; the dependency set is exposed separately from the closure so a caller with many questions builds the set once without the model holding state

- Paths: `src/bloomery/semantic/closure.py`
- Consequence: A caller that wants speed builds the set once rather than asking the model to remember

### S-0017/D-14 — `ASSUMED` (Semantic grain model and functional dependencies)

A cardinality-expanding refusal is classified by undirected connectivity over the relationship graph, on the refusal path only

- Paths: `src/bloomery/semantic/closure.py`
- Consequence: The classification runs after the closure has already refused and can turn one refusal into a better-worded one and nothing else

### S-0017/D-15 — `ASSUMED` (Semantic grain model and functional dependencies)

`many_to_many` names a cardinality this tree does not have — the cardinality enum is `many_to_one`, `one_to_one` and `one_to_many` — so the prose and D-3 describe a member no spec can declare and no IR can carry

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/semantic/closure.py`
- Consequence: Nothing was built for it and their text stands as written: this row is the correction, not an edit to them

### S-0017/D-16 — `LOCKED` (Semantic grain model and functional dependencies)

A versioned entity's declared key does not identify one of its rows, so it contributes no entity-key dependency, and a rollup *out of* such a grain is refused; a historical row is reached by an anchored hop and by nothing else, which is why the as-of basis determines the whole target row rather than only the joined key

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/semantic/nodes.py`
- Consequence: Without it a versioned entity's key reads as determining every historical column it carries, with an empty derivation, and every rollup built on that is a number computed over however many versions a key happens to have
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-17 — `ASSUMED` (Semantic grain model and functional dependencies)

The refusal list gains two members, and one of them is not about history: an anchor supplied for a relation that keeps no versions is its own refusal rather than an unqualified historical path, and a source grain naming a versioned entity is its own refusal too

- Paths: `src/bloomery/semantic/nodes.py`
- Consequence: There is no history to be unqualified about in the first case, and the repair is to drop the anchor rather than to fix it or to declare the entity versioned

### S-0017/D-18 — `ASSUMED` (Semantic grain model and functional dependencies)

A refusal names only the edges that are holding *this* question, and two anchors for one relationship are refused rather than resolved

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/semantic/nodes.py`
- Consequence: A historical refusal is narrowed to the hops the relaxed closure walked and a fan-out refusal to the edges whose removal disconnects the two grains, with the full candidate set as the fallback where two parallel edges are jointly the reason and neither is individually critical

### S-0017/D-19 — `LOCKED` (Semantic grain model and functional dependencies)

A dependency carries the whole hop it crossed — the joined column pairs and the instant it read them at — and an ambiguous path is defined over those

- Paths: `src/bloomery/semantic/nodes.py`
- Consequence: One column of the hop cannot tell two relationships joining on overlapping pairs apart, and columns without the instant collapse two hops that join identically and are read as of different dates — a tier as of the order date and a tier as of the ship date are two numbers, and the collapse returned a proof where an ambiguity refusal was owed
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-20 — `LOCKED` (Semantic grain model and functional dependencies)

The dependency basis has four members, not five: composition is not a basis, because a derivation carries the steps it composed, each with its own basis, and the rule that names a composition is reached from a derivation having more than one step

- Paths: `src/bloomery/semantic/nodes.py` `src/bloomery/semantic/proof.py`
- Consequence: What D-3 admits is unchanged — transitive closure is still admitted and still proved. What is removed is a spelling with no producer, and the cost of keeping it was concrete: a consumer guard was written against a basis table holding a row nothing could fill, which made one branch of it unreachable and its provenance row a fiction a test could invent back
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0027/D-2 — `ASSUMED` (Marts and role-playing dimensions)

Measure grain must strictly equal mart grain; coarser or finer is `GrainViolation`. Resolves D2's prose/example contradiction to the strict reading; relaxation is a future additive change.

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/marts/flatten.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/fanout_trap/marts.yaml` `tests/fixtures/fanout_trap/metrics.yaml` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/001-order-shipping-fanout/problem.md` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/expected/semantic_outcome.json` `tests/fixtures/semantic_corpus/010-many-to-many-bridge/problem.md` `tests/golden/refusals/example-wrong-grain.txt` `tests/golden/refusals/fanout_trap.txt` `tests/support/semantic_corpus.py` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic_corpus_guard.py`

### S-0050/D-1 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/additivity.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/resolve/build.py` `src/bloomery/semantic/plan.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_guardrails/test_metrics.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-8 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/explain.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/common.py` `src/bloomery/spec/metrics.py` `tests/execution/test_period_over_period.py` `tests/golden/schema/catalog.json` `tests/golden/schema/metrics.json` `tests/unit/test_emit/test_period_over_period.py` `tests/unit/test_semantic/test_ratio_rows.py` `tests/unit/test_spec/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0050/D-9 — `LOCKED` (Metrics over time: derived metrics, offsets, cumulative windows, metric filters)

**A filter's dimension is checked against every mart listing the metric, at the guardrail stage.** Not at emit: a filter naming a column no mart flattens is a *model* error, decidable from the spec, and it should fail with the batched aggregate every other model error joins. Checking every listing mart rather than the owning one avoids reaching for the ownership rule from a layer below the module that defines it, and is a superset of what correctness needs.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/errors.py` `src/bloomery/guardrails/metrics.py` `src/bloomery/semantic/additivity.py` `tests/fixtures/period_over_period/entity_model.yaml` `tests/unit/test_guardrails/test_metrics.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0054/D-2 — `LOCKED` (Safe rollup planner and SemanticPlan IR)

**A `SemanticPlan` whose multiplicity-changing nodes do not reference a proof is invalid IR, not merely unexplained.** The distinction decides whether the check can be skipped under time pressure. Every join that can duplicate a row carries its authorization or the plan does not typecheck.

- Paths: `src/bloomery/semantic/plan.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0054/D-5 — `ASSUMED` (Safe rollup planner and SemanticPlan IR)

**P1 re-expresses today's accepted requests as `SemanticPlan` with no capability change.** It is what makes the §8 parity suite meaningful — a phase that added capability and re-expression together could not tell a regression from an intended widening. Departing means finding P1 cannot represent something already accepted, which is itself the finding.

- Paths: `src/bloomery/semantic/proof.py`

### S-0055/D-1 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Aggregate, then join — never join, then aggregate and hope.** The whole document exists for this one ordering, and the alternative is the silent double count it names in §1. A later optimization pass may not reorder across it without a preservation proof.

- Paths: `src/bloomery/semantic/plan.py` `tests/engines/test_branch_join_engines.py` `tests/fixtures/semantic_corpus/006-two-grains-one-request/problem.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-2 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Branch uniqueness at the result grain is structural, from the preceding aggregate node, never inferred from data.** An inferred uniqueness is a data-dependent fact standing in for a proof, which S-0005/D-1 refuses by name; here it would silently re-admit the multiplicity the branch split removed.

- Paths: `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/plan.py` `src/bloomery/semantic/proof.py` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-8 — `OPEN` (Multi-grain aggregate-then-join query planning)

**Whether `DistinctCount`, `Snapshot` and `SemiAdditive` enter branch planning at all in P1.** §8 gates them on their proof rules being independently sound. Decide per class, with the corpus case each one converts, rather than as a group.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_planner/test_coverage.py`

### S-0055/D-9 — `LOCKED` (Multi-grain aggregate-then-join query planning)

*(its SQL spelling superseded by D18; the route it decides stands.)* **The branch join is bloomery's own SQL, over N single-mart requests MetricFlow renders unchanged.** Each branch is exactly a request the parity corpus accepts today — carrying R008 and the single-mart proof it already has — and bloomery wraps the branch results in a join of its own — written here as `FULL OUTER JOIN … ON a.k IS NOT DISTINCT FROM b.k` with a coalesced key projection, which **D18 replaces**: PostgreSQL will not plan that spelling, and the composition is a key domain and left joins. What this row decides is the *route* — bloomery composes, MetricFlow renders the branches — and that is unchanged. The alternative was measured, not imagined: handing MetricFlow one multi-metric request makes its `CombineAggregatedOutputsNode` render the same shape, correctly. It is refused because unifying two marts' differently-prefixed flattenings of one dimension (`order__country` against `order_item__order_country`) costs a row-level mart-to-mart join that MetricFlow validates rather than bloomery, and because its filter pushdown reaches into every branch through that join — the duplication D5 refuses on name-match grounds. Both hand the engine the authority for cross-branch identity, which S-0054/D-6 exists to keep in bloomery. `LOCKED` because the route decides the node vocabulary, the public surface and every test written against them.

- Paths: `src/bloomery/planner/compose.py` `src/bloomery/planner/coverage.py` `src/bloomery/planner/metricflow_planner.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/semantic/plan.py` `tests/unit/test_planner/test_compose.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-10 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**What D9 supersedes, and how far.** Retired documents carry no grade and are read as `LOCKED`, so an executor meeting one halts; these are superseded here, by the author, before the branch. S-0027/D-1 "no query-time joins on the common path" and S-0028/D-4 "never join at plan time" hold for **unaggregated rows**, which is the fan-out they were written against, and no longer for a join of branch outputs already unique at the result grain (D2). S-0030/D-6's mart-coverage precheck reads "all measures of **one branch** on one mart" instead of all measures of a request. S-0030/D-1's render-only embedding re-admits exactly one hand-written generator, **above** MetricFlow's output rather than instead of it — S-0054/D-10's "small and provable", and the smallest thing that can be. **S-0030/D-3 is untouched**: no semantic model for a non-mart entity, and D9's route needs none.

- Paths: `src/bloomery/semantic/plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0055/D-14 — `ASSUMED` (Multi-grain aggregate-then-join query planning)

**R010 is minted for the branch join: branch outputs are unique at the result grain, structurally, from the preceding aggregate.** D2 is the claim; a rule id is what an accepted plan cites, and S-0005/D-8 keeps the registry append-only. R011 follows for D12's cross-mart dimension identity if the join node needs its own citation separate from the branches'. S-0056/D-5 then owes each of them a corpus case.

- Paths: `src/bloomery/semantic/plan.py` `src/bloomery/semantic/proof.py`

### S-0057/D-1 — `LOCKED` (`bloomery check` and imported semantic provenance)

**P1 requires no dbt, no SQLMesh, no credentials, no network and no emission.** It is what makes the command usable in pre-commit and on an untrusted CI runner, and every one of those dependencies is easy to acquire accidentally and hard to remove afterwards. The compiler is already pure under S-0020; this keeps the command honest to that.

- Paths: `src/bloomery/evidence.py` `src/bloomery/semantic/rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-3 — `LOCKED` (Rollup marts and pre-aggregations)

No hand-authored `additive_over:` escape hatch, at any point. It is an assertion nothing checks, it would be introduced as temporary, and it would become a second source of truth that disagrees with the proof.

- Paths: `src/bloomery/semantic/rollup.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-4 — `ASSUMED` (Rollup marts and pre-aggregations)

A rollup states the dimensions it **keeps**; what it drops is derived. Stating both is two statements of one fact.

- Paths: `src/bloomery/semantic/rollup.py`

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-12 — `ASSUMED` (Rollup marts and pre-aggregations)

**The grain half of §5.2's obligation is discharged by R008, not by R006.** §5.2 calls it a functional-dependency question, written before the source was a mart. `GrainRef` admits only entity *key* columns — `_unknown` in `semantic/closure.py` refuses every other determinant — and a rollup's target is a set of mart columns, of which `customer_segment` is not a key and a date-role bucket like `ordered_month` is not an entity column at all. Nothing needs re-deriving: every column of a mart is determined by that mart's grain, so grouping by a subset partitions rows the mart already proved. What is left is the aggregation-class question, which is the whole of R013.

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/semantic/rollup.py` `tests/unit/test_semantic/test_rollup.py`

### S-0065/D-13 — `ASSUMED` (Rollup marts and pre-aggregations)

**Superseded by 15.** **P1 admits `additive`, and `ratio` when both operands are carried by the rollup and each is itself admitted.** `semi_additive`, `distinct_count` and `non_additive` are refused, each under its own reason naming its own repair. Phase-scoped, and written as a row so no reader takes it for permanent: a semi-additive measure rolled to a coarser bucket is a `first`/`last` selection rather than a sum, which is a computation this phase does not build. Not an escape hatch — D3 stands, and none of the three becomes admissible by declaring anything.

- Paths: `src/bloomery/semantic/rollup.py`

### S-0066/D-1 — `LOCKED` (Declared input currency for conversion)

**A conversion's input currency must be a declared or derived fact; an unknown input is refused.** This is the whole document: an assertion that nothing can check is indistinguishable from a fact, and the difference is a wrong number that passes every existing guard. Locked because relaxing it — accepting `from` as its own evidence — restores exactly the situation S-0053/D-3 was written against, and because the refusal is what makes R009 mean anything.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `tests/unit/test_resolve/test_currency_convert.py` `tests/unit/test_semantic/test_denomination.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-1 — `LOCKED` (Consumer-declared evidence strictness)

A fact's grade is derived from how the compiler obtained it and can never be written in a spec. A declared grade is an unchecked claim about a claim.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/semantic/proof.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-2 — `LOCKED` (Consumer-declared evidence strictness)

This sits above S-0005's floor and never below it. No annotation here makes a project compile that would otherwise be refused.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/semantic/proof.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-4 — `LOCKED` (Consumer-declared evidence strictness)

The refusal names how the fact was obtained and what to write instead. A message that only says "insufficient evidence" gets worked around by deleting the requirement.

- Paths: `src/bloomery/errors.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/semantic/proof.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-5 — `ASSUMED` (Consumer-declared evidence strictness)

Three grades, not five. The consumer-facing question is "did a human here write this down", and `Provenance`'s finer distinctions do not change a mart's answer to it.

- Paths: `src/bloomery/semantic/proof.py`

### S-0070/D-7 — `LOCKED` (Consumer-declared evidence strictness)

The grades are a total function of `Provenance` and every member maps to exactly one, checked by a test. A second vocabulary that drifted from the first would grade facts by a rule nobody could find.

- Paths: `src/bloomery/semantic/proof.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-2 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A dbt `relationships` test alone imports nothing.** It asserts every value exists in a target column and says nothing about the target being unique, so reading it as `many_to_one` invents the cardinality that makes the edge determine anything — S-0057/D-3's failure, by its own example. `many_to_one` from dbt requires the `relationships` test *and* a `unique`/`primary_key` on the named target. Locked because the tempting version of this importer is the one that skips the second test, and it would be indistinguishable in review from the correct one. Proposed by execution — see `logs/T-0053.md` (`logs/T-0053.md`) (D3, attempt 1).

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-3 — `LOCKED` (Mechanical imports and per-relationship provenance)

**No IR node gains a provenance field.** `project_fingerprint` walks the IR dataclass tree, so a field there moves every fingerprint in the corpus for projects that import nothing — S-0070 row 17's hazard, arriving from the same direction a second time. The fact is read from the authored `EntityModel` at the guardrail stage, the shape `requires_evidence` already uses.

- Paths: `src/bloomery/semantic/proof.py` `tests/unit/test_guardrails/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-10 — `LOCKED` (Mechanical imports and per-relationship provenance)

**A relationship's name is unique across a project.** Nothing made it so and every consumer treats it as a key, each resolving a collision differently and silently: a mart's `via:` takes the first match, `plan` keeps the last of a `{name: rel}` dict, and D1's lookup marked every same-named authored edge as imported. Refused at resolution rather than fixed per reader — the readers are four and the fact is one. Locked because D1's lookup is keyed by that name, so relaxing it reintroduces a wrong refusal rather than an ambiguity. Added by execution 2026-09-13 — see PR #115 review.

- Paths: `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/guardrails/evidence.py` `src/bloomery/semantic/proof.py` `src/bloomery/spec/entity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-1 — `LOCKED` (Declared source timezone)

**A zone is declared, never inferred.** Not from the column name, not from a project default, not from the values. An inferred zone is indistinguishable from a declared one once written down, and the failure it produces is a five-hour shift with full compiler blessing. Locked because every cheaper alternative is a way of making the wrong answer easier to reach than today.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-3 — `LOCKED` (Declared source timezone)

**`zone_in: UTC` is a declaration, not a no-op.** A feed whose wall clocks really are UTC says so. Today that claim is made by silence and silence cannot be checked; the key's only job is to turn an unfalsifiable default into a sentence somebody wrote.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-1 — `LOCKED` (A ratio over one row set)

**bloomery does not choose which rows a ratio is about.** Both readings — per unit over units that exist, and total over units with overheads included — are metrics somebody wants, and the defect is that they are spelled identically. The rule refuses until the author says; it never picks. Locked because every cheaper design is a compiler making a decision about somebody's business, and the wrong one is invisible in the output.

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-3 — `LOCKED` (A ratio over one row set)

**A `flag` disposition does not discharge the positivity premise.** A flagged row stays in the relation, so the range rule asserts nothing about what the ratio sums. The disposition is the premise, not the rule's presence — reading the rule alone would be a proof that is true of a project where the rows are still there.

- Paths: `src/bloomery/semantic/additivity.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-13 — `LOCKED` (A ratio over one row set)

**`repair` does not discharge the positivity premise either.** D3 names only `flag`; this is D3's own sentence applied to the member it did not name. A repaired row stays in the relation carrying a fallback the rule cannot bound, because its recipe is a step and its fallback is whatever the author wrote. Only `quarantine` and `fail` discharge, because only those remove the row. Locked with D3: departing would mean proving a fallback is positive, which needs the step registry's output and is not a compile-time fact — see `logs/T-0063.md` (unlisted, 15:15Z).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-14 — `LOCKED` (A ratio over one row set)

*Superseded by D16.* **A fourth discharge: the denominator counts a column that cannot be NULL.** §5.1's three discharges refuse every ratio in this repository — eight projects, including the two corpus cases §6 calls untouched — and five of the eight are counts, where the premise holds by construction and no declaration could add anything. A count counts the very rows the numerator sums, so a row contributing to the numerator contributes 1. Without this the rule refuses `revenue / order_count`, and §9's claim that a well-declared project is not inconvenienced is false for every project in the tree — see `logs/T-0063.md` (unlisted, 15:40Z).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0077/D-16 — `LOCKED` (A ratio over one row set)

**`count` and `count_distinct` over a column that cannot be null both discharge.** Supersedes D14, which excluded the second on the grounds that a distinct count is about the group rather than the row — true, and not the premise. What R019 refuses is a denominator whose *per-row* contribution can be zero while the numerator's is not, and that is a property of a sum over a numeric column; a count of either kind is at least one for any non-empty row set. The exclusion was admitted wrong on the evidence of the message it produced: "nothing restricts … to rows with a non-zero `customer_id`" about a string column, telling the author to filter `customer_id > 0` — see `logs/T-0063.md` (unlisted, 15:55Z, attempt 2).

- Paths: `src/bloomery/emit/cube/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/semantic/additivity.py` `src/bloomery/spec/quality.py` `tests/fixtures/semantic_corpus/008-ratio-rollup/**` `tests/fixtures/semantic_corpus/009-null-denominator/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
