<!-- torve:managed tests/fixtures/currency_convert — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/currency_convert/`

### S-0040/D-11 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

The FX rate relation declares **both** interval ends (`valid_from` and `valid_to`), never `valid_from` alone. One end is not an interval: a fact row would match every rate at or before its anchor and the conversion would fan out. Deriving the upper bound with `LEAD(valid_from)` is rejected — it makes every conversion a window function over the whole rate table, and it extends the newest rate to infinity, so a stale feed converts at last week's rate instead of failing. Consequence: a gap in the rate table is a *miss*, taking D9's `unknown_member` disposition, rather than silently resolving to a neighbour.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/execution/test_currency_convert.py` `tests/fixtures/currency_convert/catalog.yaml` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_quality/test_lower.py` `tests/unit/test_spec/test_catalog.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
