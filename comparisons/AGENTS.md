<!-- torve:managed comparisons — rendered from the corpus; do not edit by hand -->

## Decisions governing `comparisons/`

### S-0006/D-1 — `LOCKED` (Evidence-based semantic capability matrix)

A cell claims a property of a tested configuration, never a property of a product: every claim names the version, the date, the feature set and the configuration it was measured under, and a universal statement of the form "system X cannot do Y" is refused wherever it appears

- Paths: `comparisons/**`
- Consequence: A bundle that pins no version and no date is not evidence, and a sentence that generalises a measured cell is rewritten rather than softened; the phrasing is the only thing standing between a measurement and marketing
- Check: `uv run pytest tests/unit/test_comparisons_floor.py::test_bundle_pins_a_version_and_a_date tests/unit/test_comparisons_floor.py::test_sources_cite_only_the_feature_set_this_bundle_uses -q` (shadow; runs as `decision:S-0006/D-1`, no log entry owed)

### S-0006/D-2 — `LOCKED` (Evidence-based semantic capability matrix)

No cell is filled from reputation or memory; an unrun cell says `UNKNOWN`, which is an honest value and the default

- Paths: `comparisons/**`
- Consequence: A column with no bundle is listed as `UNKNOWN` in every row rather than omitted, so "nobody has run it" and "it has nothing to say" stay distinguishable
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0006/D-3 — `LOCKED` (Evidence-based semantic capability matrix)

bloomery is evaluated by the same standard as every other column, including where it loses: if it requires a custom step, a runtime audit, or cannot represent a case, the cell says so

- Paths: `comparisons/MATRIX.md` `comparisons/README.md`
- Consequence: An omitted caveat scores as effectively as a wrong cell, so the asymmetry that makes bloomery's wins possible is stated beside them rather than left for the reader to infer; a cell edited in bloomery's favour is refused by a test rather than by review
- Check: `uv run pytest tests/unit/test_comparisons_floor.py::test_matrix_rows_are_the_corpus_cases -q` (shadow; runs as `decision:S-0006/D-3`, no log entry owed)

### S-0006/D-4 — `ASSUMED` (Evidence-based semantic capability matrix)

Rows are the cases of the semantic bug corpus under `tests/fixtures/semantic_corpus/`, not a separately invented taxonomy; a row the matrix needs and the corpus does not carry is a missing corpus case first

- Paths: `comparisons/MATRIX.md` `tests/unit/test_comparisons_floor.py`
- Consequence: Departing means the matrix needs a row no corpus case covers — in which case the case is what is missing, and it belongs in the corpus document before it belongs here
- Check: `uv run pytest tests/unit/test_comparisons_floor.py::test_matrix_rows_are_the_corpus_cases -q` (shadow; runs as `decision:S-0006/D-4`, no log entry owed)

### S-0006/D-9 — `LOCKED` (Evidence-based semantic capability matrix)

Reproduction bundles live in this repository, at `comparisons/<system>/<case>/`, and the matrix is `comparisons/MATRIX.md` beside them

- Paths: `comparisons/**`
- Consequence: In-repo is what makes D-5 enforceable: a documentation sentence points at an `observed.txt` the reader has already cloned, and a gate can read the version a cell pins. The gate that reads `comparisons/` is written for it rather than inherited from `src`, and never lints a third party's configuration
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0006/D-10 — `ASSUMED` (Evidence-based semantic capability matrix)

A cell returns to `UNKNOWN` when the version it pins stops matching what the reproduction resolves, or when its check date leaves a twelve-month window — and the rule is a gate, not a sentence

- Paths: `comparisons/**` `tests/unit/test_comparisons_floor.py`
- Consequence: For a system this repository does not resolve as a dependency only the date half applies, and the bundle says so; the window is bounded at both ends, because a bound tested from one side let a future-dated bundle pass the gate whose purpose is noticing that a cell has stopped being current
- Check: `uv run pytest tests/unit/test_comparisons_floor.py -q` (shadow; runs as `decision:S-0006/D-10`, no log entry owed)

### S-0006/D-11 — `ASSUMED` (Evidence-based semantic capability matrix)

The matrix itself is `comparisons/MATRIX.md`, beside the bundles it cites — not a page under `pages/docs/`

- Paths: `comparisons/MATRIX.md`
- Consequence: A documentation page reads from this table; the table is evidence and is not bound by D-5, which a table whose honest state is mostly `UNKNOWN` could not satisfy on the day it is created

### S-0006/D-12 — `ASSUMED` (Evidence-based semantic capability matrix)

bloomery's column cites the semantic corpus — the pinned outcome of each case and the test that executes it — rather than duplicating it as a bundle of its own

- Paths: `comparisons/MATRIX.md` `comparisons/README.md`
- Consequence: A second bloomery account is the split D-4 exists to prevent arriving from the other side; the README states plainly that bloomery's evidence has a different shape and why, and a test refuses a matrix cell edited away from the outcome the corpus pins

### S-0006/D-13 — `LOCKED` (Evidence-based semantic capability matrix)

A cell compares which semantic facts a system's vocabulary requires an author to state — never how carefully a system checks facts both systems hold — and the matrix says so in prose beside every column it fills

- Paths: `comparisons/MATRIX.md`
- Consequence: `NATIVE-PREVENT` printed beside `NOT-REPRESENTED` is a difference in what can be said; without the sentence it reads as a scoreboard, which is this document's non-goal
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
