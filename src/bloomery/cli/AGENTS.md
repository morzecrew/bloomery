<!-- torve:managed src/bloomery/cli — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/cli/`

### S-0004/D-9 — `OPEN` (Observability: logging and a warnings channel)

CLI verbosity is a handler and not a channel: if `--verbose` lands it attaches a stderr `StreamHandler` at INFO to the `bloomery` logger and sets that logger's level to match, restoring both the handler and the prior level in a `finally` around the whole of `main`, and adds no second instrumentation path

- Paths: `src/bloomery/cli/__init__.py`
- Consequence: A logger left at `NOTSET` defers to the root's default `WARNING` and would drop the very records the handler exists to show; without the restore, a refusal or a `KeyboardInterrupt` leaves an embedder with a mutated global logger

### S-0005/D-1 — `LOCKED` (Semantic proof IR and closed-world checking)

Unknown is not safe: a proof obligation is closed only by a `Declared`, `Derived` or narrowly specified `ImportedVerified` fact. `InferredHeuristic` and `Unknown` may inform a diagnostic and never an acceptance, and the line is drawn in one place — `Provenance.closes` — rather than at each call site

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/semantic/closure.py` `src/bloomery/semantic/additivity.py` `src/bloomery/semantic/denomination.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/cli/render.py`
- Consequence: A rule that closes on a guess accepts an unsafe project silently, and a second copy of the closure test that drifted would not look like a safety change in review; the reading surface inherits the same line, because a renderer that presents an unclosed proof as evidence makes the same claim the checker refused to
- Check: `uv run pytest tests/unit/test_semantic/test_proof.py::test_only_declared_derived_and_imported_close_an_obligation tests/unit/test_semantic/test_proof.py::test_one_heuristic_leaf_makes_the_whole_proof_unclosed tests/unit/test_semantic/test_proof.py::test_a_proof_resting_on_nothing_is_not_closed -q` (shadow; runs as `decision:S-0005/D-1`, no log entry owed)

### S-0005/D-2 — `LOCKED` (Semantic proof IR and closed-world checking)

The primary internal representation is a proof or a refusal, never a boolean: every entry point that answers a semantic question returns the derivation or the structured failure, and a caller reads which question failed off the judgement

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/semantic/closure.py` `src/bloomery/semantic/additivity.py` `src/bloomery/semantic/denomination.py` `src/bloomery/cli/render.py`
- Consequence: A boolean discards the derivation, so every consumer downstream — the explain surface, the per-case rule pinning the bug corpus needs, a refusal's smallest failed obligation — has to reconstruct it from the answer, and a surface that reconstructs can agree with the answer without resting on it
- Check: `uv run pytest tests/unit/test_semantic/test_proof.py::test_both_halves_carry_the_same_surface -q` (shadow; runs as `decision:S-0005/D-2`, no log entry owed)

### S-0005/D-5 — `ASSUMED` (Semantic proof IR and closed-world checking)

Rules are named, individually documented and independently testable, registered once in a module constant, and a rule identifier is never minted at a call site

- Paths: `src/bloomery/semantic/proof.py` `tests/unit/test_semantic/**` `src/bloomery/cli/render.py`
- Consequence: The alternative — one monolithic checker returning a tree — passes the same tests and cannot answer which rule admitted a given acceptance, which the bug corpus requires of every case it pins; a registry a test asserts against also means a removed identifier fails rather than disappearing
- Check: `uv run pytest tests/unit/test_semantic/test_proof.py::test_every_rule_is_documented_and_uniquely_identified tests/unit/test_semantic/test_proof.py::test_a_rule_id_is_never_minted_at_a_call_site -q` (shadow; runs as `decision:S-0005/D-5`, no log entry owed)

### S-0005/D-6 — `LOCKED` (Semantic proof IR and closed-world checking)

Proof serialization is deterministic: canonical premise order, stable rule identifiers, no memory addresses, no timestamps, no dependence on traversal order, and premises and facts sorted on construction rather than trusted in arrival order

- Paths: `src/bloomery/semantic/proof.py` `src/bloomery/planner/semantic_plan.py` `src/bloomery/cli/render.py` `tests/unit/test_determinism_guard.py`
- Consequence: Equivalent authored ordering produces equivalent proof serialization, so a golden or a continuous-integration assertion over a derivation is a statement about the design rather than about the order a dictionary happened to iterate in
- Check: `uv run pytest tests/unit/test_semantic/test_proof.py::test_premise_order_is_canonical_not_construction_order tests/unit/test_semantic/test_proof.py::test_serialization_carries_nothing_that_varies_between_processes -q` (shadow; runs as `decision:S-0005/D-6`, no log entry owed)

### S-0019/D-6 — `ASSUMED` (Spec layer and error model)

Parse-stage errors are batched per document (all failures reported at once).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/build.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/common.py` `src/bloomery/spec/project.py` `src/bloomery/typing/check.py` `tests/unit/test_cli.py` `tests/unit/test_evidence.py` `tests/unit/test_resolve/test_build.py` `tests/unit/test_resolve/test_refs.py` `tests/unit/test_spec/test_mapping.py` `tests/unit/test_spec/test_project.py` `tests/unit/test_spec/test_sql_text.py`

### S-0019/D-8 — `ASSUMED` (Spec layer and error model)

Catalog is passed separately from `Project` (vertical-level vs tenant-level), matching spec §8's `compile_project(..., catalog=...)`.

- Paths: `src/bloomery/cli/io.py` `src/bloomery/schema.py` `src/bloomery/spec/catalog.py` `src/bloomery/spec/project.py` `tests/property/test_schema_agreement.py`

### S-0020/D-5 — `ASSUMED` (Intermediate representation and determinism contract)

Floats are banned in IR and emission; `Decimal`/int only.

- Paths: `src/bloomery/cli/serialize.py` `src/bloomery/emit/lower/reconcile.py` `src/bloomery/emit/steps.py` `src/bloomery/ir/fingerprint.py` `src/bloomery/ir/nodes.py` `src/bloomery/planner/request.py` `src/bloomery/quality/predicates.py` `src/bloomery/resolve/steps.py` `src/bloomery/spec/common.py` `src/bloomery/spec/marts.py` `src/bloomery/spec/metrics.py` `src/bloomery/spec/quality.py` `src/bloomery/steps/manifest.py` `src/bloomery/steps/splice.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/execution/test_as_of_join.py` `tests/execution/test_currency_convert.py` `tests/execution/test_fanout_trap.py` `tests/execution/test_marts.py` `tests/execution/test_period_over_period.py` `tests/execution/test_rollup.py` `tests/fixtures/semantic_corpus/002-average-of-averages/naive.sql` `tests/golden/schema/entity_model.json` `tests/golden/schema/mapping.json` `tests/golden/schema/marts.json` `tests/support/planning.py` `tests/support/semantic_corpus.py` `tests/unit/test_cli.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_planner/test_request.py` `tests/unit/test_quality/test_edges.py` `tests/unit/test_spec/test_metrics.py` `tests/unit/test_spec/test_quality.py` `tests/unit/test_steps/test_lowering.py` `tests/unit/test_steps/test_manifest_and_registry.py` `tests/unit/test_typing/test_types.py`

### S-0037/D-4 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**Six CLI commands, each a pure shell over one public function**, adding no logic of their own. Exit codes distinguish refusal (`1`) from usage error (`2`), because a refusal is a *correct* outcome and scripts must be able to tell. `--format json` returns the same structures the Python API does, so the CLI is not a second lossier surface.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/render.py` `src/bloomery/cli/serialize.py` `tests/unit/test_cli.py`

### S-0037/D-5 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**`bloomery/cli/io.py` is the only module in the package permitted to touch the filesystem**, added to S-0036's purity allowlist as a named carve-out with a stated reason, and enforced one-directional by import-linter: the CLI may import the library, no library module may import the CLI. The shell reads paths; the library still only ever sees strings, so the no-I/O invariant is preserved *and made structurally obvious* rather than merely asserted.

- Paths: `src/bloomery/__init__.py` `src/bloomery/cli/io.py` `tests/unit/test_import_contracts.py`

### S-0037/D-6 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**No new runtime dependency.** `argparse` from the standard library, hand-rolled table rendering. A dependency on `rich`/`typer` would be a real cost for cosmetics in a library whose dependency discipline is one of its properties.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/render.py` `tests/unit/test_cli.py`

### S-0037/D-12 — `ASSUMED` (Authoring ergonomics: schema export, CLI, fix suggestions)

**The purity carve-out is one file, not the CLI package.** Only `bloomery/cli/io.py` is allowlisted; `render.py` and the argument parser stay under the guard. A package-wide exemption would let any CLI module open a file while §5.3's tree still claimed one did — the guard and the document disagreeing, which is worse than no guard. The import direction is enforced separately, at package granularity, because it answers a different question.

- Paths: `src/bloomery/cli/io.py` `tests/unit/test_purity_guard.py`

### S-0039/D-2 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**Refusals are a return value, not an exception**, because a refusal on a draft spec is a normal outcome that a caller wants *alongside* the analysis that completed — not instead of it. `evaluate()` never raises `BloomeryError` — **except `InvariantViolated`**, which subclasses it but reports a bloomery bug rather than a spec refusal, and so propagates (decision 7). Programming errors outside the hierarchy propagate too; the catch is narrow by construction.

- Paths: `src/bloomery/cli/serialize.py`

### S-0039/D-5 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`stage_reached` is mandatory to read**, stated first in the docstring and tested on the ambiguous case: an empty `unreachable` means "nothing unreachable" only at `COMPLETE`, and means "never computed" at `PARSE`. Without it the empty tuple is ambiguous in exactly the way that produces a wrong conclusion.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/resolve/build.py` `tests/unit/test_cli.py` `tests/unit/test_resolve/test_lineage.py`

### S-0039/D-8 — `ASSUMED` (`SpecEvidence`: spec analysis as a first-class output)

**`bloomery resolve` (S-0037) is re-pointed at `evaluate()`** when this lands, gaining refusal reporting, as an amendment to that RFC rather than a new command. A spec author mid-draft wants reachability *and* refusals in one output.

- Paths: `src/bloomery/cli/__init__.py` `tests/unit/test_cli.py`

### S-0047/D-1 — `LOCKED` (The unresolved-work report)

**The report is derived; no spec surface changes.** §3 measured that a `canonical:`-linked field with no mapping is a legal, complete spec whose metric is reported unreachable — including when the field is `required:`. "Undecided" is therefore already expressible, and a marker would be a second spelling of it. Consequence: this RFC touches no document kind, no `spec_version`, and no parser.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/evidence.py` `src/bloomery/resolve/reach.py` `src/bloomery/resolve/recipes.py` `src/bloomery/resolve/resolution.py` `src/bloomery/spec/catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-2 — `LOCKED` (The unresolved-work report)

**`options` is enumerated in catalog order and never sorted, ranked or scored.** Enumerating what the catalog declares is a projection; ordering is where a preference would hide. `Recipe`'s docstring makes catalog order *authored* ("ordered by reliability"), so re-sorting — alphabetically included — destroys information rather than normalizing it. Consequence: this is a deliberate exception to the sort-every-collection habit, and it needs the §6 test with a non-alphabetical catalog or the exception is untested.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/evidence.py` `tests/unit/test_unresolved.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0047/D-7 — `OPEN` (The unresolved-work report)

**Whether the human CLI table prints open decisions.** JSON gets them by construction. The table is a summary (S-0037/D-4), and this is either the most useful line `bloomery resolve` could print or the one that turns a summary into a dump. Whoever builds this decides and logs it.

- Paths: `src/bloomery/cli/render.py` `tests/unit/test_cli.py`

### S-0048/D-1 — `LOCKED` (Lineage)

**`lineage()` returns the reachable sub-DAG, never enumerated paths.** Path count is exponential in graph width; sub-DAG size is bounded by the graph, which is what makes the return type's size predictable from an input the caller already holds. A caller wanting paths enumerates them from the sub-DAG under its own budget. Consequence: the common "show me the chain" rendering is the caller's fold over the sub-DAG rather than a library product, and any future path API must carry a budget parameter rather than inheriting this one's silence.

- Paths: `src/bloomery/cli/render.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0054/D-7 — `OPEN` (Safe rollup planner and SemanticPlan IR)

**Whether `SemanticPlan` lowers to the existing `QueryPlan`, replaces it, or sits beside it.** Three shapes with different migration costs and different answers to "what does `bloomery plan` print". P1 exists partly to answer this from contact with the code; log the decision with what P1 found.

- Paths: `src/bloomery/cli/__init__.py`

### S-0057/D-2 — `LOCKED` (`bloomery check` and imported semantic provenance)

**Only `Declared`, `Derived` and narrowly specified `ImportedVerified` facts close a proof obligation.** `InferredHeuristic` produces advisories and never acceptance. This is S-0005/D-1 restated at the import boundary, which is the one place where relaxing it would be most tempting and least visible — a foreign artifact is exactly where a guessed default enters wearing a fact's clothes.

- Paths: `src/bloomery/cli/__init__.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0057/D-7 — `OPEN` (`bloomery check` and imported semantic provenance)

**Whether `check` is a new command or `resolve` gaining an exit-code contract.** The surfaces overlap substantially and two near-identical commands is its own defect; so is overloading a command whose current output people already parse. Decide it against what `resolve` actually prints today, and log the decision.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/render.py`

### S-0063/D-1 — `LOCKED` (Exposures and downstream consumers)

Exposures are **declared**, never discovered. Discovery needs a network and credentials; S-0020 forbids both, and a compiler that reads a BI tool is a different program.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0067/D-1 — `LOCKED` (Stable node identity across renames)

Identity is declared, never inferred. No similarity heuristic over names, SQL or column sets decides that two nodes are the same node; a wrong guess here rewrites history rather than raising an error.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/guardrails/lineage.py` `src/bloomery/ir/nodes.py` `src/bloomery/plan/model.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0067/D-3 — `LOCKED` (Stable node identity across renames)

Absence of `id:` reproduces today's behaviour byte for byte. A feature that changes artifacts for projects that did not ask for it is not optional.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/plan/diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0068/D-1 — `LOCKED` (As-of compile over spec history)

Spec time and data time are separate axes. `--as-of` resolves specs and reaches no emitted SELECT; S-0003's problem is not this one.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/resolve/build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0068/D-2 — `LOCKED` (As-of compile over spec history)

An unresolvable instant is refused. Falling back to the working tree produces a confidently wrong artifact set, which is the defect this document removes.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/resolve/build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0068/D-3 — `LOCKED` (As-of compile over spec history)

Reconstruction is promised within one compiler version. Across versions the specs may resolve and the emitted bytes still differ, and pretending otherwise makes the fingerprint a lie.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/resolve/build.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0068/D-6 — `LOCKED` (As-of compile over spec history)

The resolver sits on the caller's side of S-0020's boundary and the compiler entry point gains no I/O. A history feature that moved that line would trade the determinism guarantee for a convenience, and every other document in this corpus is written on top of it.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/resolve/build.py`
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

### S-0070/D-1 — `LOCKED` (Consumer-declared evidence strictness)

A fact's grade is derived from how the compiler obtained it and can never be written in a spec. A declared grade is an unchecked claim about a claim.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/semantic/proof.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0070/D-2 — `LOCKED` (Consumer-declared evidence strictness)

This sits above S-0005's floor and never below it. No annotation here makes a project compile that would otherwise be refused.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/errors.py` `src/bloomery/semantic/proof.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0071/D-1 — `LOCKED` (Completing the semantic plan)

**The completion criterion is `QueryPlan.semantic` becoming non-optional**, not the node count. A phase that adds nodes and leaves the field optional has changed nothing a caller can depend on and nothing S-0058/the-planner-claim can be published against. Locked because it is the whole purpose: every other row here is a means to it, and a plan-shaped deliverable that stops short would read as done.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/planner/result.py` `src/bloomery/planner/semantic_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0073/D-2 — `LOCKED` (Caller-assembled spec history)

No `--as-of` on any command. The flag would oblige bloomery to know what a history is — which store, which instant-to-version mapping, what to do when it is ambiguous — and none of those is a question about compiling. `--steps` is the same question already answered this way (S-0034/purity-the-registry-is-a-compile-input).

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/io.py` `src/bloomery/spec/project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0073/D-3 — `LOCKED` (Caller-assembled spec history)

S-0068 is rejected, not deferred. An unscheduled design still shapes the documents that cite it, and two already cite this one.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/io.py` `src/bloomery/spec/project.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-1 — `LOCKED` (Spec timeline)

bloomery never parses, sorts or compares the labels. Order is positional and the caller owns it. Parsing instants would make this project the owner of timezone and resolution semantics over data it did not produce, and every one of those questions is answerable in the caller's store and unanswerable here.

- Paths: `src/bloomery/cli/render.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-2 — `LOCKED` (Spec timeline)

History is caller-assembled and consumed once, in order. Inherited from S-0073/D-1; restated because this is the document a reader lands on when they want the feature, and the constraint has to be where they look.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/lineage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-3 — `LOCKED` (Spec timeline)

The delta vocabulary is S-0069's and is never restated here. Two tables describing one thing is the drift this corpus has paid for before.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/lineage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-6 — `ASSUMED` (Spec timeline)

The CLI command takes spec directories positionally, like `plan`. It resolves nothing, so S-0073/D-2 is untouched.

- Paths: `src/bloomery/cli/__init__.py`

### S-0074/D-11 — `LOCKED` (Spec timeline)

**A history entry carries the `Project`, not the `ProjectIR`.** The IR does not retain the authored `id:` — S-0067 substitutes it while building node ids and keeps only names, because a field in the IR would move every fingerprint and break that document's D3. A timeline handed only IRs cannot match by id, which makes row 5 unimplementable; taking the spec side fixes it at the source, and the IR P2 needs is derivable from the same pair. Locked because reversing it silently reduces identity to name matching, which is the failure this feature exists to avoid.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/plan/diff.py` `src/bloomery/resolve/lineage.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0075/D-4 — `LOCKED` (Mechanical imports and per-relationship provenance)

**Two relationships are the same relationship when `(from, to, via)` match, and a cardinality disagreement between an imported and a declared one refuses naming both.** S-0057/D-4 mandates the refusal and leaves the predicate undefined, which makes it unimplementable. Not `name`: an importer generates names and an author picks them, so name equality reports every import as a conflict and every renamed import as none. Agreement on the same triple is not a contradiction and is accepted silently.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/imports.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
