<!-- torve:managed fuzz — rendered from the corpus; do not edit by hand -->

## Decisions governing `fuzz/`

### S-0008/D-1 — `LOCKED` (Fuzzing the compile boundary)

The harness's expectation tuple is exactly `(BloomeryError,)`, with no exemptions: any other exception crossing `load_project`, `compile_project` or the planner is a finding, and the tuple is never widened to make a run green

- Paths: `fuzz/_harness.py`
- Consequence: A boundary escape can only be closed by a fix that translates the exception into a `BloomeryError` or by a recorded decision in `pages/docs/reference/errors.md`; the harness is never the place a finding goes away
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0008/D-2 — `LOCKED` (Fuzzing the compile boundary)

The CLI oracle is that `main(argv)` never returns the reserved internal exit code, not that it returns one of the ok, refused or usage codes

- Paths: `fuzz/fuzz_cli.py`
- Consequence: A genuine internal error is reported as exactly that rather than as a generic out-of-range code, and the target has one assertion whose failure needs no interpretation
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0008/D-3 — `LOCKED` (Fuzzing the compile boundary)

Widening the expectation tuple, or adding a caught exception to any target, carries the same review bar as editing `pages/docs/reference/errors.md`, and must land with either a fix translating the exception into a `BloomeryError` or a recorded decision that the escape is intended

- Paths: `fuzz/**`
- Consequence: A finding can never be closed by editing the harness alone; the reviewer sees the taxonomy change the harness change implies, and the error reference and the tuple cannot drift apart
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0008/D-4 — `LOCKED` (Fuzzing the compile boundary)

Every confirmed finding becomes a checked-in test under an existing tier before the fuzz corpus is relied on to hold it

- Paths: `fuzz/**`
- Consequence: The deliverable of a fuzz run is a test in `tests/`, not a file in the corpus directory; a phase is unfinished while a confirmed finding exists only as a corpus entry
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0008/D-5 — `ASSUMED` (Fuzzing the compile boundary)

A finding expressible as a Hypothesis strategy over model objects goes to the property tier instead of gaining a fuzz target

- Paths: `fuzz/**`
- Consequence: The lane stays the text layer and the accept/refuse boundary, and the number of targets stays small enough that each one is read before it is trusted

### S-0008/D-8 — `ASSUMED` (Fuzzing the compile boundary)

Targets are built in the order the evidence puts them — parse doors, then the CLI and the spec layer, then the promise targets, then the planner — and none is written before the previous one has run

- Paths: `fuzz/**`
- Consequence: If the lane is cut short, what survives is the target the evidence says pays most, and each target's oracle is proven against a real defect before the next one is written

### S-0008/D-9 — `ASSUMED` (Fuzzing the compile boundary)

No phase's acceptance command runs a fuzz target: acceptance runs the test files the phase owns, and the lane is invoked by a person through `just`

- Paths: `fuzz/**`
- Consequence: A phase can be judged in a sandbox with no Docker and no time budget for mutation, and the sabotage proof that a target catches its own known defect is a step the executor performs and logs rather than a gate the battery runs

<!-- /torve:managed -->
