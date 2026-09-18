<!-- torve:managed src/bloomery/ir — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/ir/`

### S-0007/D-5 — `ASSUMED` (Dimension algebra)

`role_of:` generalizes `DateRoleStep` rather than replacing it. A date's roles expand into buckets, which is a date-specific elaboration, so the two coexist

- Paths: `src/bloomery/spec/marts.py` `src/bloomery/ir/nodes.py`
- Consequence: Existing projects with `flatten: [{date: …, role: …}]` compile unchanged and the general role is additive beside them; departing means absorbing dates into the general vocabulary, which touches every existing project

### S-0017/D-9 — `LOCKED` (Semantic grain model and functional dependencies)

The grain model is derived from the project IR, never stored in it: a grain is computed on demand from an entity's declared key and adds no field to any IR node

- Paths: `src/bloomery/semantic/closure.py` `src/bloomery/ir/nodes.py`
- Consequence: The IR version does not move, no project fingerprint moves and no golden moves, which is what turns preserve-observable-behaviour from an argument into a diff; verified by compiling every fixture, target and dialect on both sides of the branch — 251 cells, byte-identical
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0017/D-15 — `ASSUMED` (Semantic grain model and functional dependencies)

`many_to_many` names a cardinality this tree does not have — the cardinality enum is `many_to_one`, `one_to_one` and `one_to_many` — so the prose and D-3 describe a member no spec can declare and no IR can carry

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/semantic/closure.py`
- Consequence: Nothing was built for it and their text stands as written: this row is the correction, not an edit to them

<!-- /torve:managed -->
