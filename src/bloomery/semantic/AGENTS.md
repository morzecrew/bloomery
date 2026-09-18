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

<!-- /torve:managed -->
