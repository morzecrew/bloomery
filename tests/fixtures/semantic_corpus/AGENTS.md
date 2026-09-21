<!-- torve:managed tests/fixtures/semantic_corpus — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/semantic_corpus/`

### S-0005/D-4 — `ASSUMED` (Semantic proof IR and closed-world checking) — implementation: partial

Capability grows monotonically — the safe queries of one release are a subset of the next — except where a prior rule is found unsound, in which case correctness wins and the narrowing is a breaking change carrying an explicit note rather than a quiet withdrawal

- Paths: `src/bloomery/semantic/proof.py` `tests/fixtures/semantic_corpus/**` `CHANGELOG.md`
- Consequence: A new rule ships with positive and adversarial tests showing the boundary it admits, so a reader can see what was widened; a project that compiled last release and refuses in this one is either a documented soundness fix or a defect, and the note is what tells them apart

### S-0006/D-8 — `ASSUMED` (Evidence-based semantic capability matrix)

Cube's pre-aggregation matching is a row this matrix owes, and by D-4 it is a case the semantic corpus must carry before the row can be measured

- Paths: `tests/fixtures/semantic_corpus/**`
- Consequence: A rollup bloomery proves safe and Cube declines to use is wasted; one Cube uses that bloomery did not prove is a wrong number by Cube's reasoning rather than bloomery's, and only a tested configuration can tell which happens

### S-0056/D-8 — `LOCKED` (Production-style semantic bug corpus)

**A third outcome, `unguarded` — it compiles, and the planner returns the naive number — and §8's gate read in both directions.** Two of the phase-one cases were neither refused nor correct: an average and a snapshot balance both declared `additivity: additive` compile clean, because nothing verifies that an `additive` claim is true. With only "refuse" and "prove" available such a case can be written as a fiction or left out, and leaving it out drops exactly the cases S-0053 exists to convert. So a new rule names the cases it converts from refusal to acceptance *and* the ones it converts from unguarded to refused. Locked because the word is the corpus's whole claim to being a design gate rather than a transcript, and every case's vocabulary rests on it — see `logs/T-0018.md` (D096).

- Paths: `tests/fixtures/dirty/**` `tests/fixtures/fanout_trap/**` `tests/fixtures/semantic_corpus/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0056/D-12 — `LOCKED` (Production-style semantic bug corpus)

**An expectation's outcome is defined by the number the planner returns, asserted by running the SQL bloomery rendered.** The first execution ran the two hand-written queries as standalone SQL and planned nothing, so `accepted` and `unguarded` asserted identically and the difference rested on whether the cited RFC was still in the `rfcs` directory (since retired) — a fact about the repository, not about the case. That proxy would have passed a mis-modelled case, and did: case 002's naive metric over line-grain rows returns the *right* answer, because an average over lines is right, and the average-of-averages bug needs an average already taken. Locked because it is the difference between the corpus asserting behaviour and asserting its own bookkeeping — see `logs/T-0018.md` (D101), where it is logged as this task's one `drift`.

- Paths: `tests/fixtures/dirty/**` `tests/fixtures/fanout_trap/**` `tests/fixtures/semantic_corpus/**`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
