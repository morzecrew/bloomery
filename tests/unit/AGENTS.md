<!-- torve:managed tests/unit — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/`

### S-0004/D-3 — `LOCKED` (Observability: logging and a warnings channel)

Logging is not load-bearing: no test may assert behaviour through log output, and no code path may branch on logger state, with `isEnabledFor` used purely to skip expensive message assembly as the one sanctioned read

- Paths: `tests/unit/test_logging_posture.py` `tests/unit/test_determinism_guard.py`
- Consequence: This is what keeps the channel deletable; a test that reads a log makes the log an API, and it is the rule a later change is most tempted to bend
- Check: `uv run pytest tests/unit/test_determinism_guard.py tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-3`, no log entry owed)

### S-0004/D-10 — `ASSUMED` (Observability: logging and a warnings channel)

The advisory vocabulary is a closed enum with no free-text constructor, and every member has a row in the reference's advisory table while every documented code is constructible — checked in both directions

- Paths: `src/bloomery/evidence.py` `pages/docs/reference/errors.md` `tests/unit/test_docs_floor.py`
- Consequence: Adding an advisory is a reviewed change that lands its documentation row with it; a documented code no path can construct fails the census, which is what blocks the deprecated-spelling advisory until a spelling is actually deprecated
- Check: `uv run pytest tests/unit/test_docs_floor.py -q` (shadow; runs as `decision:S-0004/D-10`, no log entry owed)

### S-0006/D-4 — `ASSUMED` (Evidence-based semantic capability matrix)

Rows are the cases of the semantic bug corpus under `tests/fixtures/semantic_corpus/`, not a separately invented taxonomy; a row the matrix needs and the corpus does not carry is a missing corpus case first

- Paths: `comparisons/MATRIX.md` `tests/unit/test_comparisons_floor.py`
- Consequence: Departing means the matrix needs a row no corpus case covers — in which case the case is what is missing, and it belongs in the corpus document before it belongs here
- Check: `uv run pytest tests/unit/test_comparisons_floor.py::test_matrix_rows_are_the_corpus_cases -q` (shadow; runs as `decision:S-0006/D-4`, no log entry owed)

### S-0006/D-10 — `ASSUMED` (Evidence-based semantic capability matrix)

A cell returns to `UNKNOWN` when the version it pins stops matching what the reproduction resolves, or when its check date leaves a twelve-month window — and the rule is a gate, not a sentence

- Paths: `comparisons/**` `tests/unit/test_comparisons_floor.py`
- Consequence: For a system this repository does not resolve as a dependency only the date half applies, and the bundle says so; the window is bounded at both ends, because a bound tested from one side let a future-dated bundle pass the gate whose purpose is noticing that a cell has stopped being current
- Check: `uv run pytest tests/unit/test_comparisons_floor.py -q` (shadow; runs as `decision:S-0006/D-10`, no log entry owed)

<!-- /torve:managed -->
