<!-- torve:managed tests/fixtures/semantic_corpus/011-timezone-boundary — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/011-timezone-boundary/`

### S-0056/D-5 — `ASSUMED` (Production-style semantic bug corpus)

**A new proof rule names the cases it converts from refusal to acceptance.** The corpus is the design gate: a rule that converts nothing has no demonstrated purpose, and a rule that converts a case without supplying a correct result and proof fails review. Not `LOCKED` because a soundness fix may legitimately convert *nothing* while still being necessary.

- Paths: `tests/fixtures/semantic_corpus/007-distinct-users-fanout/problem.md` `tests/fixtures/semantic_corpus/009-null-denominator/problem.md` `tests/fixtures/semantic_corpus/011-timezone-boundary/problem.md`

### S-0076/D-1 — `LOCKED` (Declared source timezone)

**A zone is declared, never inferred.** Not from the column name, not from a project default, not from the values. An inferred zone is indistinguishable from a declared one once written down, and the failure it produces is a five-hour shift with full compiler blessing. Locked because every cheaper alternative is a way of making the wrong answer easier to reach than today.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-3 — `LOCKED` (Declared source timezone)

**`zone_in: UTC` is a declaration, not a no-op.** A feed whose wall clocks really are UTC says so. Today that claim is made by silence and silence cannot be checked; the key's only job is to turn an unfalsifiable default into a sentence somebody wrote.

- Paths: `src/bloomery/semantic/denomination.py` `src/bloomery/spec/mapping.py` `src/bloomery/transforms/_builtins.py` `src/bloomery/typing/types.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0076/D-9 — `ASSUMED` (Declared source timezone)

R018 decides a comparison against a literal instant over the IR expression: `_pinned_columns` walks a metric's whole `expr` tree for `=`, `!=`, `<`, `<=`, `>`, `>=` or `BETWEEN` whose operands hold an entity column beside a string literal or a literal cast to `TIMESTAMP`; a metric `filter` on an entity column is the same site

- Paths: `src/bloomery/guardrails/zone.py` `tests/unit/test_guardrails/test_zone.py` `tests/fixtures/semantic_corpus/011-timezone-boundary/**`
- Consequence: The rule's surface is the one the design claims, corpus case 011's zoneless arm is refused with `UndeclaredZone` at its comparison, and two columns compared with each other never fire

<!-- /torve:managed -->
