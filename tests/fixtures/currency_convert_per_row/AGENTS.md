<!-- torve:managed tests/fixtures/currency_convert_per_row — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/currency_convert_per_row/`

### S-0066/D-4 — `ASSUMED` (Declared input currency for conversion)

**`from` is kept and checked rather than dropped.** It is derivable everywhere once D1 holds, and it stays because a conversion whose source currency is not at the call site costs every future reader a lookup. Not `LOCKED` because the redundancy is a judgement about readability against ceremony, and execution may find the double declaration is a nuisance in practice — if so, depart with the migration note, since removing it is a spelling change rather than a semantic one.

- Paths: `tests/fixtures/currency_convert_per_row/mapping.yaml`

### S-0066/D-10 — `ASSUMED` (Declared input currency for conversion)

A per-row conversion keeps the three-argument spelling, `{convert: [currency_code, USD, paid_at]}`: the first slot names the column that `currency_in: {column: …}` declares. Resolution checks it against the declaration as it checks a literal code, and skips the ISO-4217 format check for that slot only.

- Paths: `tests/fixtures/currency_convert_per_row/mapping.yaml`

<!-- /torve:managed -->
