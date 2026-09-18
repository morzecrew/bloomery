<!-- torve:managed tests/fixtures/currency_convert_per_row — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/currency_convert_per_row/`

### S-0066/D-4 — `ASSUMED` (Declared input currency for conversion)

**`from` is kept and checked rather than dropped.** It is derivable everywhere once D1 holds, and it stays because a conversion whose source currency is not at the call site costs every future reader a lookup. Not `LOCKED` because the redundancy is a judgement about readability against ceremony, and execution may find the double declaration is a nuisance in practice — if so, depart with the migration note, since removing it is a spelling change rather than a semantic one.

- Paths: `tests/fixtures/currency_convert_per_row/mapping.yaml`

### S-0066/D-10 — `OPEN` (Declared input currency for conversion)

**How a per-row conversion spells its source currency.** §5.1's example wrote `{convert: [*, USD, paid_at]}`, and `*` is not an ISO-4217 code — resolution refuses it on the code format before the per-row refusal is reached, so the example was uncopyable and the question it stood in for was never asked. With the input declared on the field, `from` is derivable and the two-argument spelling is the obvious candidate; keeping a three-argument form would need something to write in the first slot that is not a currency. Decide with P2's lowering, which is the first code that reads it. Added by execution 2026-09-07 — see `logs/T-0025.md` (`logs/T-0025.md`) (D162).

- Paths: `tests/fixtures/currency_convert_per_row/mapping.yaml`

<!-- /torve:managed -->
