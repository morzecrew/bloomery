<!-- torve:managed tests/fixtures/semantic_corpus/006-two-grains-one-request — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/006-two-grains-one-request/`

### S-0055/D-1 — `LOCKED` (Multi-grain aggregate-then-join query planning)

**Aggregate, then join — never join, then aggregate and hope.** The whole document exists for this one ordering, and the alternative is the silent double count it names in §1. A later optimization pass may not reorder across it without a preservation proof.

- Paths: `src/bloomery/semantic/plan.py` `tests/engines/test_branch_join_engines.py` `tests/fixtures/semantic_corpus/006-two-grains-one-request/problem.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
