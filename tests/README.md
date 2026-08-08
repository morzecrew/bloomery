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

`chaos` marks the mutation meta-test (`chaos/`, RFC 0016 §6): it deforms the
quality lowering — inverts a comparison, drops a stage, swaps a disposition —
and requires the M12 quality battery to notice each time, running pytest in a
subprocess per mutation. Excluded from `just test` and `just test-all`; run it
with `uv run pytest tests/chaos -m chaos`.

`perf` marks the bench lane (`bench/`, RFC 0009 §5.9): the hydration budgets
of RFC 0014 — 50 ms cold / 10 ms warm, median over ≥20 iterations with a
documented 3× CI multiplier, plus a 3× model-size info point. Excluded from
`just test`; run it with `uv run pytest tests/bench -m perf` (scheduled lane
in CI).

## Running

```bash
just test                          # tiers 1–4 (opt-in markers excluded)
just test-all                      # everything except chaos and perf (Docker required)
just test tests/unit               # one tier / path
uv run pytest -m 'engine'          # tier 5 only
uv run pytest -m e2e               # tier 6 only
uv run pytest tests/chaos -m chaos # the mutation meta-test (RFC 0016 §6)
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
  `support/execution.py` owns the warehouse and the dependency-ordered model sweep —
  every tier-4 module uses it rather than rolling its own; `support/dirty.py` owns the
  dirty corpus's mandated read flags and the disposition lookup that reads **both**
  sides of the quarantine split.
- `tests/conftest.py` exists for one thing: the chaos harness's mutation hook.

This table will be extended as the tiers land with their milestones (RFC 0009 §12).
