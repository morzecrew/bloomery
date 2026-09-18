<!-- torve:managed tests/engines — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/engines/`

### S-0012/D-1 — `LOCKED` (Validating a dialect port against an engine we cannot run)

An emulator, a surrogate engine or a compatible-wire shim is evidence, never the oracle: the real engine's own compiler is the dialect oracle, and no rung below the authoritative ones may be quoted as engine conformance

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: A cloud port's acceptance is the authoritative rung's, so a port whose only green lanes are local has not been validated and a review says so; the local lanes stay worth running as the fast signal, and stay unable to close the port
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-2 — `LOCKED` (Validating a dialect port against an engine we cannot run)

Rung 4 carries a `surrogate` marker distinct from `engine`, so a lane backed by an emulator, a Spark session or a Postgres shim cannot select or report as the engine matrix does

- Paths: `pyproject.toml` `tests/engines/**`
- Consequence: The marker table gains a ninth entry when the first surrogate lane lands, and `engine(name)` keeps meaning Docker plus the real engine; a CI log distinguishes the two without anyone reading a test body
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-3 — `LOCKED` (Validating a dialect port against an engine we cannot run)

The authoritative compile rung exists for every cloud port, because every one of the four engines has one — `EXPLAIN USING JSON`, a dry run, `EXPLAIN`, `EXPLAIN EXTENDED` and `DESCRIBE QUERY` — and a port without it has no authoritative layer at all

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: Each of the four ports owes a compile lane over the shared corpus before it can be called validated, and the lane costs a parse rather than a scan; the absence of a container stops being a blocker for any of them
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-6 — `ASSUMED` (Validating a dialect port against an engine we cannot run)

All six rungs run the shared fixture corpus rather than a per-engine one; a port-native fixture is added alongside, never instead, where an engine surface has no shared analogue

- Paths: `tests/fixtures/**` `tests/engines/**`
- Consequence: A divergence presents as one fixture behaving differently across ports, which is comparable; departing means an engine surface with genuinely no shared analogue, such as `VARIANT` or `SUPER`

<!-- /torve:managed -->
