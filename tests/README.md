# Test suite

Six tiers, fastest first (RFC 0009). All tiers exercise one shared fixture corpus under
`tests/fixtures/`, loaded only through the public `load_project`/`load_catalog` API.

| Tier | Directory | Marker | In `just test` | Needs Docker | What it proves |
| --- | --- | --- | --- | --- | --- |
| 1 Unit | `unit/` (mirrors `src/bloomery`) | `unit` | ✅ | — | parse errors, typing, resolution, guardrail triggers |
| 2 Golden | `golden/` | `golden` | ✅ | — | checked-in artifacts per (fixture × target × dialect), byte-compared |
| 3 Property | `property/` | `property` | ✅ | — | Hypothesis invariants over generated valid projects |
| 4 Execution | `execution/` | `execution` | ✅ | — | compiled SQL runs on in-process DuckDB; `Decimal` assertions; fan-out regression |
| 5 Engine matrix | `engines/` | `engine(<name>)` | opt-in | ✅ | tier-4 assertions against real engines via testcontainers |
| 6 Target e2e | `e2e/` | `e2e` | opt-in | ✅ | artifacts are valid *input to the target* (sqlmesh replan is a no-op, `dbt parse`, cube `/meta`) |

`perf` marks the bench lane (`bench/`, RFC 0009 §5.9): the hydration budgets
of RFC 0014 — 50 ms cold / 10 ms warm, median over ≥20 iterations with a
documented 3× CI multiplier, plus a 3× model-size info point. Excluded from
`just test`; run it with `uv run pytest tests/bench -m perf` (scheduled lane
in CI).

## Running

```bash
just test                          # tiers 1–4 (-m "not engine and not e2e and not perf")
just test-all                      # everything except perf (Docker required)
just test tests/unit               # one tier / path
uv run pytest -m 'engine'          # tier 5 only
uv run pytest -m e2e               # tier 6 only
just snapshot-update               # regenerate goldens (tier 2)
just coverage                      # tiers 1–4 with the coverage floors enforced
                                   # (80 overall; bloomery/guardrails/ at 100% branch — RFC 0009 D9)
```

## Conventions

- Markers are strict (`--strict-markers --strict-config`): register new ones in
  `pyproject.toml` before use.
- `tests/unit` mirrors `src/bloomery` module-for-module.
- `fixtures/` holds YAML spec projects only (no Python); `golden/` holds checked-in
  artifacts. Golden diffs are reviewed like source code — an unexplained golden diff
  fails review.
- Shared helpers (Hypothesis strategies, seeding, artifact extraction) live in `support/`.

This table will be extended as the tiers land with their milestones (RFC 0009 §12).
