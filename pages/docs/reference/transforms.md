# Transforms

The closed transform whitelist a mapping's `transform:` chains may draw from — 24
built-ins, each typed with an input domain and an output type. Chains typecheck at
compile: a step whose input type is outside its domain, or a chain whose terminal type
is not assignable to the field's declared type, is a `TypeCheckError`; a name outside
the whitelist is an `UnknownTransformError` naming the closest match.

Chains start at `string` — source extraction yields text — and each step's output
feeds the next step's input. Args are spec-level literals, written as a bare name
(`trim`), a single-arg mapping (`{parse_ts: ISO8601}`), or a list
(`{to_decimal: [12, 4]}`).

## String

| Name | Args | Input → output | Usage |
|---|---|---|---|
| `trim` | — | string → string | `[trim]` — strip surrounding whitespace |
| `upper` | — | string → string | `[upper]` — uppercase |
| `lower` | — | string → string | `[lower]` — lowercase |
| `split_part` | delimiter (str), index (int) | string → string | `[{split_part: ["-", 2]}]` — the nth delimited part |
| `regex_extract` | pattern (str), group (int) | string → string | `[{regex_extract: ["ord-(\\d+)", 1]}]` — capture group |
| `strip_prefix` | prefix (str) | string → string | `[{strip_prefix: "ord-"}]` — remove a leading prefix if present |
| `strip_suffix` | suffix (str) | string → string | `[{strip_suffix: "-eu"}]` — remove a trailing suffix if present |
| `concat` | text (str) | string → string | `[{concat: "-eu"}]` — append a literal |
| `enum_map` | from/to pairs (str…, variadic) | string → string | `[{enum_map: [F, female, M, male]}]` — map values; unmapped values pass through |

## Casts and parses

| Name | Args | Input → output | Usage |
|---|---|---|---|
| `to_string` | — | any → string | `[to_string]` — cast to text |
| `to_int` | — | string, int, decimal, bool → int | `[to_int]` — cast to integer |
| `to_decimal` | precision (int), scale (int) | string, int, decimal → decimal(p, s) | `[{to_decimal: [12, 2]}]` — cast with explicit shape |
| `to_bool` | — | string, int, bool → bool | `[to_bool]` — cast to boolean |
| `parse_ts` | format (str) | string → timestamp | `[{parse_ts: ISO8601}]` — parse a timestamp as a **local wall clock**; `ISO8601` means the engine's native parse, any other string is an explicit format. Text carrying a UTC offset is refused as NULL — see below |
| `parse_date` | format (str) | string → date | `[{parse_date: ISO8601}]` — parse a date |
| `to_utc` | zone (str) | timestamp → timestamp | `[{to_utc: Europe/Paris}]` — interpret a zoneless local timestamp in `zone`; the only door into the always-UTC timestamp type |

### A timestamp that states its own offset

`parse_ts` reads a local wall clock, and `to_utc` is the only door into UTC. So
`2026-01-06T12:00:00+01:00` is text that says something the transform is not allowed to
believe: the spec has already declared what zone this column is written in, and the data
disagrees.

Every engine bloomery targets resolves that disagreement the same silent way — it drops
the offset and keeps `12:00`, an hour off the instant the row actually carries, with
nothing downstream able to see it. bloomery produces **NULL** for such a value instead,
identically on DuckDB, PostgreSQL and Trino.

A NULL is something the rest of the system already knows how to report. On an entity with
a `quality:` block the implicit `coercible` rule flags it and `on_fail: quarantine` sends
the row to the [reject table](../concepts/data-quality.md); for the `_ingested_at`
ingestion-metadata column the generated audit stops the run outright.

Two things it deliberately does **not** do:

- **It does not convert.** Reading the offset would make one declaration mean a local
  clock on one row and an instant on the next, decided by the bytes. Normalise upstream,
  or state the zone once with `to_utc` on a source that has been normalised.
- **It does not refuse `Z`.** `Z` names UTC, which is the zone the `timestamp` type is
  already in, so nothing is lost by dropping it — where a numeric offset loses exactly
  the difference between the wall clock and the instant.

**On upgrade**, a source whose timestamps carry offsets produced plausible, wrong values
before this landed and produces NULLs after it. That is the point of the change, and it
is still a value moving under you: check the affected columns with a `coercible` rule
before you promote the upgrade.

`parse_date: ISO8601` is unaffected — an ISO date has no time and therefore no offset.

## Null handling and JSON

| Name | Args | Input → output | Usage |
|---|---|---|---|
| `coalesce` | fallback (literal) | any → same type | `[{coalesce: 0}]` — replace NULL with a literal |
| `nullif` | sentinel (literal) | any → same type | `[{nullif: "N/A"}]` — turn a sentinel value into NULL |
| `json_path` | path (str) | variant, string → variant | `[{json_path: "$.a.b"}]` — extract from a JSON value |

## Arithmetic

Decimal precision and scale are tracked through arithmetic: `multiply`/`divide` widen
to `decimal(p1+p2, s1+s2)`; crossing the 38-digit precision cap is a loud
`TypeCheckError` telling you to narrow with an explicit `to_decimal` step.

| Name | Args | Input → output | Usage |
|---|---|---|---|
| `multiply` | factor (number) | decimal → widened decimal | `[{multiply: 100}]` — multiply by a literal |
| `divide` | divisor (number) | decimal → widened decimal | `[{divide: 100}]` — divide by a literal |
| `round` | digits (int ≥ 0) | int → int; decimal → decimal(·, digits) | `[{round: 2}]` — round to `digits` decimal places |
| `abs` | — | int, decimal → same type | `[abs]` — absolute value |

## Currency

| Name | Args | Input → output | Usage |
|---|---|---|---|
| `convert` | from (ISO-4217), to (ISO-4217), anchor (column name) | decimal → decimal | Converts an amount between two declared currencies at the rate that was current on the anchor's date |

```yaml
# entity_model.yaml — the converted amount is its own field
amount_usd: {type: "decimal(12,4)", canonical: amount_usd}

# mapping.yaml
amount_usd:
  from: "$.amount"
  transform: [{to_decimal: [12, 4]}, {convert: [EUR, USD, paid_at]}]
```

Everything about that line is declared, and none of it is inferred. The source path
carries no currency, so `from` is written out; the anchor could be guessed from a
mart's date role, and a wrong guess is a plausible number computed against the wrong
day, which is the failure class this project exists to refuse.

The anchor names a `date` or `timestamp` column of the same entity, mapped by a direct
`from:` path — a `fields:` entry or a `key:` one. A recipe or macro anchor is refused
rather than spliced, because its whole derivation would be copied into every converted
column. Both currency codes must be ISO-4217 (three uppercase letters): they are
compared against the rate relation exactly as written, so `eur` would match no rate and
convert every amount to `NULL` rather than failing.

### The rate relation

Conversion reads a table the operator supplies and bloomery never builds. Declare its
shape once, in the catalog:

```yaml
fx_rates:
  relation: fx_rate      # resolved through the naming policy, at the silver layer
  from: from_ccy
  to: to_ccy
  rate: rate
  valid_from: valid_from
  valid_to: valid_to     # required
```

**Both interval ends are required.** One end is not an interval: a payment would match
every rate at or before its date, and the lookup would multiply rather than convert.
Deriving the upper bound with `LEAD(valid_from)` was considered and rejected — it makes
every conversion a window function over the whole rate table, and it extends the newest
rate forward forever, so a stale feed converts at last week's price instead of failing.

A date that no interval covers converts to `NULL`, and that is deliberate: a miss stays
visible, where the nearest neighbouring rate would be a number nobody could tell from a
real one.

### What the rate table has to guarantee

bloomery reads this relation and emits no model for it, so it audits nothing about its
contents. Two properties are the operator's to hold:

- **Intervals for one `(from, to)` pair must not overlap.** The lookup is a scalar
  subquery, so an overlapping feed matches more than one rate and the model fails loudly
  at run time. That is the intended end of the spectrum — every shape that keeps running
  picks one rate silently.
- **A rate must exist for every pair and date you convert.** A code that matches nothing
  converts to `NULL`, whether it is a typo, a currency you have not loaded, or a gap in
  the feed. `convert` refuses a code that is not three uppercase letters, because that
  much is checkable from the spec alone; whether `USD` rates were actually loaded is not.
  Declare a `not_null` quality rule on the converted column if a missing rate should stop
  the run rather than propagate.

Without `fx_rates:` in the catalog, `convert` is refused at emit with
`UnsupportedByTarget` naming the column — the transform stays whitelisted and
typechecked, and the refusal names the declaration that would lift it.

### What this does to `CurrencyMismatch`

Nothing, directly. Two operands with distinct declared ISO-4217 codes still may not
meet, and no token waives that. What conversion adds is a third option where there were
two: write the converted amount into a field the catalog declares in the target
currency, and the arithmetic is same-currency arithmetic, which was never a violation.

The error message names whichever fix is actually available — convert, when the catalog
declares rates; declare rates or derive upstream, when it does not.

## Custom transforms

`register_transform(spec)` adds an extension transform to a process-global overlay —
a deployment-time act, typically an adapter package registering at import. A name
collision with any existing transform, built-in or extension, raises
`TransformRegistrationError`: shadowing a vetted transform silently would defeat the
whitelist. A `TransformSpec` declares the name, arity and per-argument kinds, input
type domain, output type (a fixed type or a function of input type and args), and a
builder that produces a dialect-neutral SQLGlot AST — never string SQL. See the
[API reference](api.md#extension-points).

That AST is neutral because each [dialect](dialects.md) renders it, and two of the
transforms here need different SQL per engine — `to_utc` and `parse_ts` both have
engine-specific behaviour worth reading before you pick a warehouse.

Every transform above produces the type it declares, on all three engines, and the same
page describes the battery that holds that true. One caveat survives it: `divide` is
inexact on DuckDB, which has no exact decimal division — prefer `{multiply: "0.01"}` to
`{divide: 100}` there, as the shipped examples do.
