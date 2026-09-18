<!-- torve:managed src/bloomery/spec — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/spec/`

### S-0004/D-2 — `LOCKED` (Observability: logging and a warnings channel)

A log record never carries nondeterminism of bloomery's making — no timestamp, id or counter the compiler invented — and is built only from values the pipeline already holds: stage names, counts, fingerprints and source paths

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: A record's timestamp exists only if the caller's handler adds one, on the caller's side of the I/O boundary; the pre-commit bans on the clock and the id generator get no exemption for a logging call site
- Check: `uv run pytest tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0004/D-2`, no log entry owed)

### S-0004/D-4 — `ASSUMED` (Observability: logging and a warnings channel)

Two levels only, to start — `INFO` for one bounded record per stage per compile and `DEBUG` for per-entity and per-artifact detail — and no record at `WARNING` or above anywhere, because that severity belongs to the advisory channel

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The INFO budget is pinned not to grow with the project, which is what "safe to leave on in production" has to mean to be worth saying; a third level costs a log line rather than a contract, which is why this is not `LOCKED`
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-4`, no log entry owed)

### S-0004/D-13 — `ASSUMED` (Observability: logging and a warnings channel)

Modules obtain their stage logger by the documented name literally — `bloomery.spec`, `bloomery.resolve`, `bloomery.guardrails`, `bloomery.emit`, `bloomery.runtime`, `bloomery.planner` — and never through `getLogger(__name__)`

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The two idioms ship different stable sets, and `__name__` would make the documented names a strict subset of the real ones; tuning works either way through the hierarchy, so what differs is only which names are the promise
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-13`, no log entry owed)

### S-0007/D-1 — `LOCKED` (Dimension algebra)

Every relation is declared, never inferred — not from column names, not from cardinality, not from the data. One `GROUP BY` would answer `determines:` exactly, and from a single load of a source that has no counterexample yet; an inference cannot be told from a declaration once written down

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py` `src/bloomery/semantic/closure.py`
- Consequence: A relation has exactly the standing of a declared `many_to_one`: the compiler reads what an author wrote and never looks at a row, so nothing in the closure or the spec models may consult data or guess from a name
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-3 — `LOCKED` (Dimension algebra)

A dimension is not an entity. Modelling `city` and `state` as entities with a declared `many_to_one` would reuse R002 exactly and is rejected: it taxes a two-column fact with a grain, a key and a mapping, and it puts every hierarchy level into the lineage graph as a node nobody builds

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/semantic/closure.py`
- Consequence: The column-to-column determination needs its own fact and its own closure; the entity-keyed machinery is not extended to carry it, and a project with a five-level geography gains no entities
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0007/D-4 — `ASSUMED` (Dimension algebra)

Determination is a lattice, not a list. A column may determine several others independently, and `postcode` determining both `state` and `delivery_zone` is the ordinary case rather than the exotic one

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py`
- Consequence: `determines:` is a set of names on the determinant and is transitively closed by the compiler; departing means an ordered-levels spelling, which is smaller, cannot express a lattice, and restates the same fact on every mart that carries the columns

### S-0007/D-5 — `ASSUMED` (Dimension algebra)

`role_of:` generalizes `DateRoleStep` rather than replacing it. A date's roles expand into buckets, which is a date-specific elaboration, so the two coexist

- Paths: `src/bloomery/spec/marts.py` `src/bloomery/ir/nodes.py`
- Consequence: Existing projects with `flatten: [{date: …, role: …}]` compile unchanged and the general role is additive beside them; departing means absorbing dates into the general vocabulary, which touches every existing project

### S-0007/D-6 — `OPEN` (Dimension algebra)

Whether `determines:` lives on the entity model or on the catalog's canonical field. A determination is a property of values rather than of a feed, which argues for the catalog; the entity model is where fields are otherwise described. The executor decides against the shape of both and logs it

- Paths: `src/bloomery/spec/entity.py` `src/bloomery/spec/catalog.py`
- Consequence: The placement decides where the parse, the cycle refusal and the transitive closure live, and whether a determination is stated once per catalog field or once per entity that maps it

### S-0007/D-8 — `OPEN` (Dimension algebra)

Whether `same_as:` is needed at all. The in-project case is derivable from `role_of:` and the cross-project case has no consumer until multi-project composition reaches its emitted-reference phase. If both hold, this relation is not built

- Paths: `src/bloomery/spec/marts.py`
- Consequence: Phase 3 exists only if this resolves that the relation is needed; resolving it the other way retires the relation and the document can complete on the first two phases

<!-- /torve:managed -->
