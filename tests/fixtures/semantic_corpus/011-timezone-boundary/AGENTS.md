<!-- torve:managed tests/fixtures/semantic_corpus/011-timezone-boundary — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/011-timezone-boundary/`

### S-0056/D-5 — `ASSUMED` (Production-style semantic bug corpus)

**A new proof rule names the cases it converts from refusal to acceptance.** The corpus is the design gate: a rule that converts nothing has no demonstrated purpose, and a rule that converts a case without supplying a correct result and proof fails review. Not `LOCKED` because a soundness fix may legitimately convert *nothing* while still being necessary.

- Paths: `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/009-null-denominator/problem.md` `tests/fixtures/semantic_corpus/011-timezone-boundary/problem.md`

### S-0056/D-7 — `OPEN` (Production-style semantic bug corpus)

*Superseded by D10.* **Which tier runs the corpus.** Execution (DuckDB) covers most cases; the SCD2 and timezone cases may need the Docker-gated engine tier, which is excluded from the default suite — and a corpus that does not run by default is a corpus that rots. Decide per case, and if any case cannot run in the default suite, say so where the case lives.

- Paths: `tests/fixtures/semantic_corpus/011-timezone-boundary/problem.md`

<!-- /torve:managed -->
