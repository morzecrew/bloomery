<!-- torve:managed src/bloomery/planner — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/planner/`

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

### S-0004/D-13 — `ASSUMED` (Observability: logging and a warnings channel)

Modules obtain their stage logger by the documented name literally — `bloomery.spec`, `bloomery.resolve`, `bloomery.guardrails`, `bloomery.emit`, `bloomery.runtime`, `bloomery.planner` — and never through `getLogger(__name__)`

- Paths: `src/bloomery/spec/project.py` `src/bloomery/resolve/build.py` `src/bloomery/compile.py` `src/bloomery/runtime/hydration.py` `src/bloomery/planner/metricflow_planner.py`
- Consequence: The two idioms ship different stable sets, and `__name__` would make the documented names a strict subset of the real ones; tuning works either way through the hierarchy, so what differs is only which names are the promise
- Check: `uv run pytest tests/unit/test_logging_posture.py -q` (shadow; runs as `decision:S-0004/D-13`, no log entry owed)

<!-- /torve:managed -->
