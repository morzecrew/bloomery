<!-- torve:managed tests/fixtures/semantic_corpus/006-two-grains-one-request/bloomery/branches — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/006-two-grains-one-request/bloomery/branches/`

### S-0055/D-11 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Measures partition by owning mart, from `measure_owners` — closing D7.** The emitter, Cube and the coverage precheck already agree on which mart serves a measure, cheapest `cost_hint` then lexicographic; a planner that chose its own partition would be a second owner of that answer, and a partition disagreeing with the emitter's is the divergence class this codebase keeps paying for. The tie-break D7 asked for is therefore inherited rather than invented, and one measure belongs to exactly one branch by construction.

- Paths: `src/bloomery/planner/coverage.py` `src/bloomery/planner/metricflow_planner.py` `tests/fixtures/semantic_corpus/006-two-grains-one-request/bloomery/branches/marts.yaml`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
