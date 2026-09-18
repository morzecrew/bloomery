<!-- torve:managed tests/fixtures/semantic_corpus/001-order-shipping-fanout/data — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/001-order-shipping-fanout/data/`

### S-0056/D-2 — `LOCKED` (Production-style semantic bug corpus)

**Every case is hand-checkable — 3–20 rows, deterministic, order-independent.** A corpus case a reviewer cannot verify by eye is a test asserting whatever the implementation did on the day it was written, which is the failure mode this corpus is meant to catch in *other* people's pipelines.

- Paths: `tests/fixtures/semantic_corpus/001-order-shipping-fanout/data/rows.sql` `tests/fixtures/semantic_corpus/003-scd2-unqualified-join/problem.md` `tests/fixtures/semantic_corpus/006-two-grains-one-request/data/rows.sql` `tests/unit/test_semantic_corpus_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
