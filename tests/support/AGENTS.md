<!-- torve:managed tests/support — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/support/`

### S-0012/D-1 — `LOCKED` (Validating a dialect port against an engine we cannot run)

An emulator, a surrogate engine or a compatible-wire shim is evidence, never the oracle: the real engine's own compiler is the dialect oracle, and no rung below the authoritative ones may be quoted as engine conformance

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: A cloud port's acceptance is the authoritative rung's, so a port whose only green lanes are local has not been validated and a review says so; the local lanes stay worth running as the fast signal, and stay unable to close the port
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-3 — `LOCKED` (Validating a dialect port against an engine we cannot run)

The authoritative compile rung exists for every cloud port, because every one of the four engines has one — `EXPLAIN USING JSON`, a dry run, `EXPLAIN`, `EXPLAIN EXTENDED` and `DESCRIBE QUERY` — and a port without it has no authoritative layer at all

- Paths: `tests/engines/**` `tests/support/**`
- Consequence: Each of the four ports owes a compile lane over the shared corpus before it can be called validated, and the lane costs a parse rather than a scan; the absence of a container stops being a blocker for any of them
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0012/D-4 — `LOCKED` (Validating a dialect port against an engine we cannot run)

No engine driver, cloud SDK or Spark session enters `src/bloomery`; live harnesses live in `tests/support/` and their drivers are test-only dependency groups, never installed for `uv add bloomery`

- Paths: `src/bloomery/**` `tests/support/**` `pyproject.toml`
- Consequence: A cloud port adds a port module and a test harness and nothing else to the install path, so the package stays a pure compiler and its dependency closure stays free of a JVM and four vendor SDKs
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
