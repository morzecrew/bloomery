<!-- torve:managed pages/docs/reference — rendered from the corpus; do not edit by hand -->

## Decisions governing `pages/docs/reference/`

### S-0004/D-10 — `ASSUMED` (Observability: logging and a warnings channel)

The advisory vocabulary is a closed enum with no free-text constructor, and every member has a row in the reference's advisory table while every documented code is constructible — checked in both directions

- Paths: `src/bloomery/evidence.py` `pages/docs/reference/errors.md` `tests/unit/test_docs_floor.py`
- Consequence: Adding an advisory is a reviewed change that lands its documentation row with it; a documented code no path can construct fails the census, which is what blocks the deprecated-spelling advisory until a spelling is actually deprecated
- Check: `uv run pytest tests/unit/test_docs_floor.py -q` (shadow; runs as `decision:S-0004/D-10`, no log entry owed)

### S-0033/D-30 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12; closed by D84)* **Postgres cannot host quality-carrying entities.** `coercible` needs a real NULL-on-failure cast (`DialectFeature.TRY_CAST`); sqlglot renders `TRY_CAST` on Postgres as a plain `CAST`, which aborts the run instead of marking the row, so the dialect declares the feature gap and compiling a quality-carrying entity for it raises `UnsupportedByTarget` — loud, never a silent degradation into an aborted run. Consequence for §6's dialect matrix: there is no Postgres dirty-corpus tier to add until either sqlglot renders a real `TRY_CAST` or the lowering grows a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus. Named as the escape hatch, not built.

- Paths: `pages/docs/reference/errors.md` `src/bloomery/emit/lower/silver.py`

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

<!-- /torve:managed -->
