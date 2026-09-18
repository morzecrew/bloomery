<!-- torve:managed src/bloomery/cli — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/cli/`

### S-0004/D-9 — `OPEN` (Observability: logging and a warnings channel)

CLI verbosity is a handler and not a channel: if `--verbose` lands it attaches a stderr `StreamHandler` at INFO to the `bloomery` logger and sets that logger's level to match, restoring both the handler and the prior level in a `finally` around the whole of `main`, and adds no second instrumentation path

- Paths: `src/bloomery/cli/__init__.py`
- Consequence: A logger left at `NOTSET` defers to the root's default `WARNING` and would drop the very records the handler exists to show; without the restore, a refusal or a `KeyboardInterrupt` leaves an embedder with a mutated global logger

<!-- /torve:managed -->
