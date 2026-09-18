<!-- torve:managed src/bloomery/marts — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/marts/`

### S-0017/D-4 — `ASSUMED` (Semantic grain model and functional dependencies)

The as-of qualification reuses the historical-fanout guardrail's semantic fact rather than restating it

- Paths: `src/bloomery/semantic/historical.py` `src/bloomery/marts/flatten.py`
- Consequence: Two readings of SCD2 validity in one compiler is the divergence this project has paid for before — one body, two callers

### S-0017/D-10 — `ASSUMED` (Semantic grain model and functional dependencies)

The as-of fact lives in one function in the semantic package, and the mart guard reads it from there

- Paths: `src/bloomery/semantic/historical.py` `src/bloomery/marts/flatten.py`
- Consequence: Anything in this sequence that needs to know whether a historical hop is qualified calls that function; the anchor states it distinguishes are finer than the two sentences the mart needed, which is what a blocked edge carries

### S-0017/D-13 — `ASSUMED` (Semantic grain model and functional dependencies)

The mart's grain refusal stays on grain-string equality until a planner has exercised this substrate

- Paths: `src/bloomery/marts/flatten.py`
- Consequence: The only thing the mart path takes from this document is the as-of fact; its grain comparison is untouched, and the unit tier pins the decision as well as the behaviour so a later silent migration is visible

<!-- /torve:managed -->
