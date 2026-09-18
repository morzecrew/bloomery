<!-- torve:managed src/bloomery/cli — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/cli/`

### S-0004/D-9 — `OPEN` (Observability: logging and a warnings channel)

CLI verbosity is a handler and not a channel: if `--verbose` lands it attaches a stderr `StreamHandler` at INFO to the `bloomery` logger and sets that logger's level to match, restoring both the handler and the prior level in a `finally` around the whole of `main`, and adds no second instrumentation path

- Paths: `src/bloomery/cli/__init__.py`
- Consequence: A logger left at `NOTSET` defers to the root's default `WARNING` and would drop the very records the handler exists to show; without the restore, a refusal or a `KeyboardInterrupt` leaves an embedder with a mutated global logger

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

### S-0057/D-7 — `OPEN` (`bloomery check` and imported semantic provenance)

**Whether `check` is a new command or `resolve` gaining an exit-code contract.** The surfaces overlap substantially and two near-identical commands is its own defect; so is overloading a command whose current output people already parse. Decide it against what `resolve` actually prints today, and log the decision.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/cli/render.py`

### S-0065/D-5 — `LOCKED` (Rollup marts and pre-aggregations)

An unprovable rollup is **refused**, never warned about. A rollup is read instead of the detail table, so a wrong one answers quickly and plausibly — the class this project refuses rather than approximates.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/stage.py` `src/bloomery/marts/rollup.py` `src/bloomery/semantic/rollup.py` `tests/fixtures/semantic_corpus/012-rollup-recounts-identities/problem.md` `tests/unit/test_semantic/test_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0067/D-3 — `LOCKED` (Stable node identity across renames)

Absence of `id:` reproduces today's behaviour byte for byte. A feature that changes artifacts for projects that did not ask for it is not optional.

- Paths: `src/bloomery/cli/render.py` `src/bloomery/plan/diff.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0071/D-1 — `LOCKED` (Completing the semantic plan)

**The completion criterion is `QueryPlan.semantic` becoming non-optional**, not the node count. A phase that adds nodes and leaves the field optional has changed nothing a caller can depend on and nothing S-0058/the-planner-claim can be published against. Locked because it is the whole purpose: every other row here is a means to it, and a plan-shaped deliverable that stops short would read as done.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/planner/result.py` `src/bloomery/planner/semantic_plan.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-1 — `LOCKED` (Spec timeline)

bloomery never parses, sorts or compares the labels. Order is positional and the caller owns it. Parsing instants would make this project the owner of timezone and resolution semantics over data it did not produce, and every one of those questions is answerable in the caller's store and unanswerable here.

- Paths: `src/bloomery/cli/render.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0074/D-6 — `ASSUMED` (Spec timeline)

The CLI command takes spec directories positionally, like `plan`. It resolves nothing, so S-0073/D-2 is untouched.

- Paths: `src/bloomery/cli/__init__.py`

### S-0075/D-4 — `LOCKED` (Mechanical imports and per-relationship provenance)

**Two relationships are the same relationship when `(from, to, via)` match, and a cardinality disagreement between an imported and a declared one refuses naming both.** S-0057/D-4 mandates the refusal and leaves the predicate undefined, which makes it unimplementable. Not `name`: an importer generates names and an author picks them, so name equality reports every import as a conflict and every renamed import as none. Agreement on the same triple is not a contradiction and is accepted silently.

- Paths: `src/bloomery/cli/__init__.py` `src/bloomery/imports.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
