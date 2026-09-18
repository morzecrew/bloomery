<!-- torve:managed tests/fixtures/semantic_corpus/009-null-denominator — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/009-null-denominator/`

### S-0056/D-5 — `ASSUMED` (Production-style semantic bug corpus)

**A new proof rule names the cases it converts from refusal to acceptance.** The corpus is the design gate: a rule that converts nothing has no demonstrated purpose, and a rule that converts a case without supplying a correct result and proof fails review. Not `LOCKED` because a soundness fix may legitimately convert *nothing* while still being necessary.

- Paths: `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/009-null-denominator/problem.md` `tests/fixtures/semantic_corpus/011-timezone-boundary/problem.md`

<!-- /torve:managed -->
