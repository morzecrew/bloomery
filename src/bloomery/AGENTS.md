<!-- torve:managed src/bloomery — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/`

### S-0004/D-1 — `LOCKED` (Observability: logging and a warnings channel)

No handler, ever: the library's only logging configuration act is attaching a `NullHandler` to the `bloomery` logger at package import, and it never adds, removes or configures a handler, a format or a level on a logger it does not own

- Paths: `src/bloomery/__init__.py` `pyproject.toml`
- Consequence: A library that installs a handler fights its embedder, and reversing this reaches every caller in the process; the level stays at `NOTSET` deliberately, which is the only way a caller's own `setLevel` on the `bloomery` logger can work from outside
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-1`, no log entry owed)

### S-0004/D-2 — `LOCKED` (Observability: logging and a warnings channel)

A log record never carries nondeterminism of bloomery's making — no timestamp, id or counter the compiler invented — and is built only from values the pipeline already holds: stage names, counts, fingerprints and source paths

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: A record's timestamp exists only if the caller's handler adds one, on the caller's side of the I/O boundary; the pre-commit bans on the clock and the id generator get no exemption for a logging call site
- Check: `uv run pytest tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0004/D-2`, no log entry owed)

### S-0004/D-4 — `ASSUMED` (Observability: logging and a warnings channel)

Two levels only, to start — `INFO` for one bounded record per stage per compile and `DEBUG` for per-entity and per-artifact detail — and no record at `WARNING` or above anywhere, because that severity belongs to the advisory channel

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The INFO budget is pinned not to grow with the project, which is what "safe to leave on in production" has to mean to be worth saying; a third level costs a log line rather than a contract, which is why this is not `LOCKED`
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-4`, no log entry owed)

### S-0004/D-5 — `LOCKED` (Observability: logging and a warnings channel)

Nothing important is ever only logged: anything a caller must act on is a value they receive — a refusal or an advisory — and a log record is a second copy at most

- Paths: `src/bloomery/evidence.py`
- Consequence: It is the whole argument for the advisory channel existing; without it the channel is decoration, and it is also why there is no log record for an advisory at all
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-5`, no log entry owed)

### S-0004/D-6 — `OPEN` (Observability: logging and a warnings channel)

Whether `compile_project` grows a report carrying artifacts plus advisories, or stays artifacts-only with callers who want advisories calling `evaluate`, is deliberately undecided and needs a consumer rather than a guess

- Paths: `src/bloomery/compile.py`
- Consequence: Until a consumer asks, `compile_project` returns artifacts and nothing else; the field on `SpecEvidence` is useful under either answer and ships first, so neither answer is foreclosed

### S-0004/D-7 — `LOCKED` (Observability: logging and a warnings channel)

An advisory is not a refusal that lost its nerve: the bar is that the spec is legal, the compiled artifacts are correct, and there is still something the author would want to know, and anything where the numbers could be wrong stays a refusal

- Paths: `src/bloomery/evidence.py`
- Consequence: A review that finds an advisory where a refusal belongs should treat it as a defect; this does not soften "refuse rather than answer wrongly" and nothing may be moved from the refusal side to the advisory side under it
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-7`, no log entry owed)

### S-0004/D-8 — `ASSUMED` (Observability: logging and a warnings channel)

Deprecation is `warnings.warn(..., BloomeryDeprecationWarning)` at the old call site, naming the replacement and the removal release, best-effort once per process per spelling by an explicit module-level guard that records after emitting — and it is the only use of the `warnings` module under `src/bloomery/`

- Paths: `src/bloomery/errors.py`
- Consequence: The guard bounds how often bloomery emits and cannot show a warning a caller's `ignore` filter hides; two threads hitting a spelling's first use concurrently may emit twice, and a caller needing a hard once gets it from their own filter configuration
- Check: `uv run pytest tests/unit/test_deprecation.py -q` (shadow; runs as `decision:S-0004/D-8`, no log entry owed)

### S-0004/D-10 — `ASSUMED` (Observability: logging and a warnings channel)

The advisory vocabulary is a closed enum with no free-text constructor, and every member has a row in the reference's advisory table while every documented code is constructible — checked in both directions

- Paths: `src/bloomery/evidence.py` `pages/docs/reference/errors.md` `tests/unit/test_docs_floor.py`
- Consequence: Adding an advisory is a reviewed change that lands its documentation row with it; a documented code no path can construct fails the census, which is what blocks the deprecated-spelling advisory until a spelling is actually deprecated
- Check: `uv run pytest tests/unit/test_docs_floor.py -q` (shadow; runs as `decision:S-0004/D-10`, no log entry owed)

### S-0004/D-11 — `ASSUMED` (Observability: logging and a warnings channel)

Advisories are a sorted, deduplicated tuple under the declared key `(code.value, source_path or "", message)`, applied in exactly one place, and the `Advisory` dataclass is deliberately not orderable

- Paths: `src/bloomery/evidence.py`
- Consequence: A missing source path normalizes to the empty string for ordering while staying `None` on the value; the dataclass's own field order disagrees with the key, so making the type orderable reintroduces both a silent disagreement and a `TypeError` on a legal pair
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-11`, no log entry owed)

### S-0004/D-12 — `ASSUMED` (Observability: logging and a warnings channel)

Advisories are computed by a pure function of the same values every other evidence field is derived from, called by `evaluate`, with no accumulator threaded through the pipeline and no ordering dependence on when a stage ran, and are reported at every partial width

- Paths: `src/bloomery/evidence.py`
- Consequence: An advisory derived from an input is computed and correct whether or not a stage refused, so withholding it from a refused project makes `advisories` the one field that is empty for a reason the stage reached cannot explain
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-12`, no log entry owed)

### S-0004/D-13 — `ASSUMED` (Observability: logging and a warnings channel)

Modules obtain their stage logger by the documented name literally — `bloomery.spec`, `bloomery.resolve`, `bloomery.guardrails`, `bloomery.emit`, `bloomery.runtime`, `bloomery.planner` — and never through `getLogger(__name__)`

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The two idioms ship different stable sets, and `__name__` would make the documented names a strict subset of the real ones; tuning works either way through the hierarchy, so what differs is only which names are the promise
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-13`, no log entry owed)

### S-0004/D-15 — `ASSUMED` (Observability: logging and a warnings channel)

A new field on `SpecEvidence` is appended after whatever field is last at the time, and a positional-construction test that supplies every pre-existing field by position lands with it, alongside a test pinning the field count

- Paths: `src/bloomery/evidence.py`
- Consequence: "Additive" holds positionally only for an appended field, and a field inserted earlier silently rebinds positional construction; a test that stops short of the insertion point passes in both worlds and pins nothing
- Check: `uv run pytest tests/unit/test_advisories.py -q` (shadow; runs as `decision:S-0004/D-15`, no log entry owed)

### S-0004/D-16 — `OPEN` (Observability: logging and a warnings channel)

What makes a quality rule "unstrengthened" — the vocabulary the second advisory candidate names and this codebase does not have — is decided at implementation against the `QualityRule` subclasses in `src/bloomery/spec/quality.py`, and the decision is logged

- Paths: `src/bloomery/evidence.py`
- Consequence: The advisory cannot be built before the term means something checkable, and the definition chosen fixes both what the code reports and what its documentation row can say; getting it wrong produces an advisory that fires on correct specs, which D-7 forbids

### S-0008/D-7 — `OPEN` (Fuzzing the compile boundary)

Whether each of the two narrow-handler sites gains `RecursionError` or a depth limit raising a named error — decided per site from its reproduction, and logged either way

- Paths: `src/bloomery/evidence.py` `src/bloomery/resolve/steps.py`
- Consequence: A depth limit raising a named error adds a class to `src/bloomery/errors.py` and an entry to `pages/docs/reference/errors.md`; widening the catch adds neither, and the two sites may legitimately get different answers

### S-0012/D-4 — `LOCKED` (Validating a dialect port against an engine we cannot run)

No engine driver, cloud SDK or Spark session enters `src/bloomery`; live harnesses live in `tests/support/` and their drivers are test-only dependency groups, never installed for `uv add bloomery`

- Paths: `src/bloomery/**` `tests/support/**` `pyproject.toml`
- Consequence: A cloud port adds a port module and a test harness and nothing else to the install path, so the package stays a pure compiler and its dependency closure stays free of a JVM and four vendor SDKs
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

## Invariants holding over `src/bloomery/`

- **S-0004/I-1**: Compiling the corpus with a capturing handler at DEBUG on the `bloomery` logger and with no handler at all produces byte-identical artifacts, and the listening run demonstrably captured records
  - Paths: `src/bloomery/**`
  - Check: `uv run pytest tests/unit/test_determinism_guard.py -q`
- **S-0004/I-2**: The package installs exactly one `NullHandler`, sets no level, leaves propagation alone, survives a reload without accumulating a second handler, and emits no record at `WARNING` or above over a real compile
  - Paths: `src/bloomery/**`
  - Check: `uv run pytest tests/unit/test_logging_posture.py -q`

<!-- /torve:managed -->
