# Guardrails

This page explains the checks that refuse plausible-but-wrong arithmetic: expressions
that parse, typecheck, survive code review, and produce a number that is wrong. Seven
arithmetic guardrails run as a pure stage over the draft IR after typechecking; six
raise, one deliberately does not. They target the bug class where the formula is right,
the data is right, and the answer is 3× wrong.

A second family joined the same stage with data quality: refusals of `quality:`,
`dedupe:`, `quarantine:` and `reconcile:` declarations that cannot mean anything
(below). Both families share the definition — **a guardrail says the model is wrong**,
decidable from the spec alone, at compile time. What a rule does to a *row* at run time
is [data quality](data-quality.md)'s business, not this stage's.

!!! danger "Errors, never warnings"

    Every guardrail violation is a compile error. There is no severity setting and no
    suppression knob — a knob makes "error" negotiable, and these guardrails exist
    precisely because this class of error gets waved through. All violations across the
    whole project are collected and raised as a single `GuardrailError` aggregate, each
    with a source path, so authors fix a spec in one round trip.

## Unit coherence

Operands of `+` and `-` must share a `unit`. Adding a currency to a count is refused;
so is any additive arithmetic involving a field whose unit is `unknown` — a monetary
column without a `canonical:` link has no metadata, and unknown *poisons* additive
arithmetic rather than silently passing. Multiplication and division are exempt:
currency × count is how extensive quantities work. Violation: `UnitMismatch`.

## Tax basis

`net` and `gross` may never meet in `+`/`-`, and `unknown` alongside a monetary operand
is equally refused. A margin computed as `unit_price - supplier_cost`, where
`supplier_cost` has no catalog link:

```
TaxBasisMismatch at entity_model: entities.order_item.fields.margin
  '-' combines 'unit_price' (tax_basis: net) with 'supplier_cost'
  (tax_basis: unknown — the field has no canonical: link, so no metadata
  propagates). Arithmetic combining unknown with any basis is refused.
  Fix: link 'supplier_cost' to a catalog canonical field carrying tax_basis,
  or add the field to the catalog.
```

The frustration of an early `unknown` refusal is deliberate: it forces catalog linkage
exactly where money math happens.

## Currency

Two operands with *distinct declared* ISO-4217 codes may not meet: `CurrencyMismatch`,
with no escape. Unlike tax basis, an absent code is compatible with anything —
single-currency projects are the common case, and forcing declaration everywhere would
train authors to paste a constant, destroying the signal. Declared-versus-declared is
the bug worth refusing.

`convert` does not waive this rule — there is no token that does, and the one that
used to was removed for buying a compile-time "yes" whose only outcome was a run-time
failure. What [conversion](../reference/transforms.md#currency) offers instead is an
*answer*: it produces a column the catalog declares in the target currency, and two
operands in one currency were never a violation. That needs an `fx_rates:` relation in
the catalog, because a rate is a dated fact and there is nothing to look one up in
otherwise; without it the message says so, and names declaring rates or deriving
upstream as the two ways forward.

## Grain: the fan-out guard

All operands of a derivation must share the derivation's grain, or the expression must
contain an explicit aggregation over the finer grain. An order-grain value joined down
to line grain without aggregation is duplicated once per line, and every downstream
`SUM` overstates it — there is no "distribute evenly" auto-fix, because allocation is a
modeling decision the author must write out. The derivation-level violation is
`GrainMismatch`:

```
GrainMismatch at entity_model: entities.order_item.fields.landed_cost
  '+' combines 'unit_price' (grain: one row per line on an order) with
  'shipping_cost' from entity 'order' (grain: one row per order), reached via
  relationship 'item_of_order' (many_to_one) with no aggregation step.
  Joined to line grain, shipping_cost is duplicated once per line; any SUM over
  landed_cost overstates shipping by the line count.
  Fix: add an explicit aggregation/allocation over 'order_item', or declare the
  derivation on entity 'order'.
```

The same guard also runs where fan-out would actually be *built*: over each mart
definition, at compile time. A measure whose grain differs from the mart's grain is a
`GrainViolation` at the declaration site —

```
GrainViolation at entity_model: marts.order_items.measures.shipping_cost
  measure 'shipping_cost' has grain 'order' (one row per order), coarser than the
  mart's grain 'order_item' (one row per line on an order). Flattened into the mart
  it is duplicated once per line; any SUM overstates shipping by the line count.
  Fix: remove it from this mart's measures, or serve it from an order-grain mart
  (e.g. marts.orders).
```

— and a `flatten:` step whose relationship is not `many_to_one` or `one_to_one` is
`FanoutRisk`, because a one-to-many flatten multiplies the mart's own rows. The
`fanout_trap` fixture used to produce a 3×-wrong sum at execution time; it now fails at
compile time, and the execution assertion is kept because it documents why the compile
error exists.

## Additivity

Additivity classes are enforced, not advisory:

- A `non_additive` metric (a ratio, an average) may **never** be materialized as a
  stored number — not as a column, not as a stored aggregate — because a stored average
  re-aggregates wrongly. Only its additive components may be stored; the ratio is
  recomputed at query time. Storing one is `AdditivityViolation`:

  ```
  AdditivityViolation at metrics: metrics.average_order_value
    metric is non_additive (ratio: net_revenue / order_count) and may not be
    materialized as a stored number — a stored average re-aggregates wrongly.
    Fix: store the additive components (net_revenue, order_count) and emit the
    ratio as a calculated measure; the Cube emitter does this automatically.
  ```

- A `non_additive` metric declared without a `RatioSpec` (or equivalent additive
  decomposition) is `NonAdditiveWithoutComponents`: with nothing additive to recompute
  from, the metric could only ever be answered by storing it — which the first rule
  forbids.
- A `semi_additive` metric may only be aggregated over dimensions other than its
  policy's `over:` dimension. Summing an inventory balance across time is refused.
- A mart that carries measures must declare at least one date role —
  `MartMissingTimeDimension` otherwise. Every measure in the emitted MetricFlow
  semantic model needs an aggregation time dimension, and without this compile-time
  check the downstream failure is obscure.

Two numbers make the stakes concrete, and both are hard-coded in the execution suite.
An inventory balance of 100, 80, and 90 over three days, filtered to that range, is
**90 — not 270**: semi-additive over time means "last value", not "sum". An average
order value over one store with 10 orders / 100,000 revenue and another with 100
orders / 200,000 is **2727.27 — never 6000** (the average of the two stored averages)
**and never 12000** (another plausible mis-aggregation): non-additive means recomputed
from summed components at the requested grain, every time.

Note the division of labor: the additivity *policy* — these compile-time refusals —
lives in bloomery. The additivity *lowering* — generating the windowed SQL for a `last`
balance or the `SUM(num)/NULLIF(SUM(den), 0)` for a ratio — is delegated to the
embedded MetricFlow backend, and the numbers above are asserted by executing its
generated SQL. MetricFlow lowers additivity; it does not stop you from modeling it
wrongly. That refusal stays here.

## Path conflict: the guardrail that does not raise

When a field has both a direct source column and a satisfiable recorded derivation, any
silent choice is wrong — the two can disagree, and whichever the compiler picked, the
discrepancy would become invisible. So the compiler emits **both**: the derived column
under the field's name (the recipe is the recorded, auditable decision), a
`<name>__direct` shadow column carrying the direct value, and a reconciliation audit
that surfaces row-level disagreement in the target engine.

This is not a missing error — it is the one guardrail where the correct refusal targets
the *silence*, not the spec. Both paths are individually valid, so there is nothing for
the author to fix at compile time; raising would force them to delete information to
make the error go away, which is strictly worse than measuring the disagreement.

On an entity in the [data-quality system](data-quality.md) the shadow is cast the same way
every other column is — NULL on failure, not produce-or-raise — so a direct value that will
not cast lands as NULL and the reconciliation audit reports the row as a disagreement,
which it is. It used to abort the run with an engine conversion error naming neither the
column nor the check.

On an entity [merged from several sources](../how-to/merge-sources.md#a-direct-path-on-a-merged-entity)
the shadow is projected per branch, from that mapping's own path, so the audit compares
each row against the direct value its own source carried. What is refused there is
*disagreement about whether the conflict exists*: every mapping producing the column
records a path, or none does.

## Range sanity

Optional per-field `assert:` clauses — `min`, `max`, `not_null`, `enum` membership,
`regex` — lower into audit artifacts that run in the target engine. The guardrail stage
validates each clause statically against the field's logical type: `min`/`max` on a
string field, or a `regex` on a numeric one, is `AssertLoweringError` — an assertion
that can never run is a silent hole in the audit net.

## Data-quality declarations

Declaring what happens to a bad *row* is run-time work, but declaring it **incoherently**
is a model error, so these refusals live here:

| Refusal | What the spec got wrong |
|---|---|
| `DedupeTieBreakMissing` | `keep: latest_by` with no `tie_break` — rows sharing a timestamp make the winner arbitrary, and a nondeterministic model makes backfills disagree with the runs they replace |
| `DedupeDispositionConflict` | A `coercible` rule weaker than `fail` on a column the dedupe order reads; an uncastable value there leaves the order undefined, so the weaker disposition is a contradiction rather than a preference |
| `QuarantineRetentionMissing` | A rule can quarantine but no `quarantine:` block says for how long. Reject rows hold raw source payloads — this is the sort of thing that is trivial now and a legal problem in eighteen months |
| `IngestionMetadataMissing` | An entity using `quarantine:`/`dedupe:` whose mapping neither maps nor acknowledges `_load_id`, `_ingested_at`, `_source_row_id` |
| `RedactionConflict` | A `redact:` path the mapping also reads — you cannot both require a field and destroy it at write time, because replay re-runs the mapping against `raw` |

Nine more refuse as bare `GuardrailError`s, without a class of their own: a `pattern`
rule one of the shipped dialect ports has no regex surface for; a `dedupe` clause
ordering by a column the entity does not declare; a `referential` rule whose `via` names
no relationship, one whose `via` names a relationship declared *from* another entity, and
one pointing back at its own entity; `unknown_member` on a non-string foreign key and
`unknown_member` on a composite one; a malformed or unresolvable `reconcile` side; and a
project metric colliding with a name the quality mart owns. The design authority names
exactly five new leaves, and minting more would put names in `bloomery.errors` no RFC
decided on — so these carry their argument in the message instead. The
[errors reference](../reference/errors.md#data-quality-refusals-without-their-own-class)
lists each with its trigger.

Where the regex refusals happen is worth being precise about, because most of them are
not this stage's. A lookahead — legal under Postgres's POSIX ARE, an aborted run under
RE2 on DuckDB and Trino — never reaches the guardrail stage at all: `pattern` speaks a
closed portable subset, so lookaround, backreferences, atomic groups, inline flags and
`\A`/`\Z` are refused by name at **parse**, as a `SpecParseError`, alongside the missing
anchors that would otherwise let `[0-9]{5}` accept `abc12345xyz`. What is left for this
stage is the narrower, mechanical question a compiler that never executes SQL can
honestly answer: does each shipped dialect declare a regex surface at all, and does the
pattern text reach that dialect's SQL unchanged. The portability claim itself is carried
by the subset, not by the round trip — but the principle is the arithmetic guards'
applied to text, and it still costs an author one edit where not refusing costs someone
a quarter of rows judged by a rule nobody wrote.

The grain and additivity guards are the highest-value part of the package; the
[wide-mart gold layer](wide-marts.md) shows how the mart design makes the same
guarantees structural at query time, and [Determinism](determinism.md) explains why
every one of these refusals is exactly reproducible.
