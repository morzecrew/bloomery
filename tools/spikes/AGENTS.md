<!-- torve:managed tools/spikes — rendered from the corpus; do not edit by hand -->

## Decisions governing `tools/spikes/`

### S-0003/D-9 — `ASSUMED` (Replay on a historical entity) — implementation: partial

The two targets fail the old merge differently: on dbt it lands silently with a NULL interval, and on SQLMesh it does not land at all — the entity is a view over a physical snapshot table and the write is refused outright by the engine

- Paths: `src/bloomery/emit/sqlmesh/__init__.py` `tools/spikes/rfc0060_sqlmesh.py`
- Consequence: Nothing about the refusal changes — the pair was refused either way, for a reason that holds on both — but a claim that both targets fail silently is not true, and a reader's sense of how urgent this is should follow the loud failure rather than the quiet one

### S-0003/D-10 — `ASSUMED` (Replay on a historical entity) — implementation: partial

A correction arriving by this route adds a version and closes the previous one; it does not rewrite history

- Paths: `src/bloomery/emit/lower/silver.py` `tools/spikes/rfc0060_dbt.py`
- Consequence: Measured on both targets by changing an existing row's value in bronze and re-running: each closes the standing version, opens a new one and retains the old. Routing through the framework means taking the framework's answer, so the question is answered by the route rather than chosen

<!-- /torve:managed -->
