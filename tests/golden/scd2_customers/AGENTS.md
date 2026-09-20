<!-- torve:managed tests/golden/scd2_customers — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/golden/scd2_customers/`

### S-0079/D-3 — `ASSUMED` (Determinations reach the IR and the rollup lowering) — implementation: none

The fifteen fingerprint-bearing golden fixture directories are regenerated with `uv run pytest tests/golden --snapshot-update` and reviewed like source. The whole of the expected diff is the `-- fingerprint: blm1:…` header line; a SQL body that moves, or a diff in a directory that carries no fingerprint, is a defect and not a snapshot to accept

- Paths: `tests/golden/ecom_basic/**` `tests/golden/identity_resolution/**` `tests/golden/minimal/**` `tests/golden/multi_source/**` `tests/golden/multi_source_quality/**` `tests/golden/non_additive_aov/**` `tests/golden/path_conflict/**` `tests/golden/path_conflict_merged/**` `tests/golden/quality_precedence/**` `tests/golden/role_playing_dates/**` `tests/golden/roles_of_one_dimension/**` `tests/golden/rollup_mart/**` `tests/golden/scd2_customers/**` `tests/golden/semi_additive_inventory/**` `tests/golden/step_resolution/**`
- Consequence: `tests/golden/refusals`, `tests/golden/multi_mart_refusal`, `tests/golden/period_over_period` and `tests/golden/schema` carry no fingerprint header and must not move; they are the control that says the bump reached the header and nothing else

<!-- /torve:managed -->
