# Guardrails and evidence

Read what a guardrail refused, what bloomery proved and on which facts, and close an
open decision that leaves a metric unreachable. Covers `requires_evidence`.

## The claim, and its edge

> bloomery does not prove truth. It proves preservation of declared semantics.

Declare `shipping` an order-grain measure in dollars and every representation or plan
that would silently make it mean something else is refused. If it is really per-parcel,
or holds euros, nothing catches it: that is a wrong declaration. bloomery never sees
source values, never judges a business definition, and never reads a constraint nobody
wrote down. Whether data actually has the cardinality you declared is run-time work for
[quality rules](quality-rules.md), not the compiler.

A target accepting an artifact (SQLMesh planning it, Cube loading it) is not evidence
either. Semantic acceptance happens before any target is rendered.

## Guardrails: errors, never warnings

A guardrail says **the model is wrong**, decidable from the spec alone, at compile time.
There is no severity setting and no suppression. Every violation across the project is
collected into one aggregate error, each with a source path, so one round trip fixes
the spec. Fix the spec; never look for a knob.

| Refusal | What the spec got wrong | Usual fix |
|---|---|---|
| `UnitMismatch` | `+`/`-` over different units, or over a field whose unit is `unknown` | link the field to a catalog canonical with a `unit` |
| `TaxBasisMismatch` | `net` meets `gross`, or `unknown` meets money, in `+`/`-` | link the field to a canonical carrying `tax_basis` |
| `CurrencyMismatch` | two *declared* different currencies meet | convert into a column the catalog declares in one currency (needs `fx_rates:`) |
| `GrainMismatch` | a derivation mixes grains with no aggregation | aggregate or allocate explicitly, or declare it on the coarser entity |
| `GrainViolation` | a mart measure coarser than the mart's grain | serve it from a mart at its own grain |
| `FanoutRisk` | a `flatten:` through `one_to_many` | flatten the other way, or build a mart at the finer grain |
| `AdditivityViolation` | a `ratio`/`non_additive` metric stored as a column | store its components, rename the column |
| `NonAdditiveWithoutComponents` | `non_additive` with nothing additive to recompute from | declare it as a ratio of additive metrics |
| `InvalidMetricShape` | `ratio:` without `additivity: ratio`, or the reverse | write both halves together |
| `FalseAdditivityClaim` | `avg`, `median`, `count_distinct` declared additive; `distinct_count` over anything but `count_distinct` | declare the true class |
| `MartMissingTimeDimension` | a mart with measures and no date role | add `{date: …, role: …}` to `flatten:` |
| `AssertLoweringError` | `min`/`max` on a string, `regex` on a number | match the assert to the field's type |

An absent currency is compatible with anything; only declared-versus-declared is
refused. Multiplication and division are exempt from unit coherence (currency × count is
how extensive quantities work).

### Ratios over rows with a zero denominator

`SUM(num) / NULLIF(SUM(den), 0)` guards a zero *total*. A row with a zero denominator
still contributes its numerator, so bloomery refuses a ratio until you say which answer
you mean. A denominator that counts rows over a required column needs nothing; otherwise
restrict both operands identically, declare the denominator positive with a
`quarantine` or `fail` rule, or say the zeros belong in the answer:

```yaml fragment
cost_per_parcel:
  additivity: ratio
  ratio: {numerator: carrier_cost, denominator: parcels, includes_zero_denominator: true}
```

A numerator and denominator restricted to different row sets are refused whatever the
zeros do.

### The guardrail that does not raise

A field with both a direct source column and a recorded derivation emits **both**: the
derived column under the field's name, a `<field>__direct` shadow, and a reconciliation
audit that reports disagreeing rows in the target engine. Nothing to fix at compile
time; read the audit.

## Proofs: what was established, and from what

A guardrail's silence only says nothing it looks for went wrong. A proof names the rule
that admitted something and the facts under it, and `bloomery explain` prints it:

```console
$ bloomery explain specs/ --metrics line_discount,shipping_count
```

```text
Evidence (2 locked, 2 assumed)
  ASSUMED branch:order_items
          order_items is aggregated to the requested grain before the join, so it holds
          one row per key
  LOCKED  mart:order_items.line_discount
          line_discount is a measure of order_items, whose grain is order_item
```

| Grade | Means |
|---|---|
| `LOCKED` | an author declared it, or it follows necessarily from a declaration |
| `ASSUMED` | the compiler obtained it soundly: a proof rule, a propagation, an exact read of an imported artifact, a fact from an upstream project |
| `OPEN` | closes nothing; a project resting on one does not compile |

`ASSUMED` is not doubt. Do not declare things just to turn a grade `LOCKED`. Heuristic
and unknown facts never close an obligation: a refusal can mean "unsafe" or "no rule
covers this yet", and both come out as a refusal rather than a guess.

A declared entity `key:` is a `LOCKED` premise, and the build checks it: an entity with
a key and no `dedupe:` gets a blocking `<entity>_key_unique` audit.

## Requiring declared evidence

A mart or exposure that someone signs off can refuse anything the compiler worked out
for itself:

```yaml spec=exposures
exposures_version: 1
exposures:
  exec_dashboard:
    kind: dashboard
    owner: finance@example.com
    depends_on:
      metrics: [net_revenue]
    requires_evidence: locked
```

On a mart write `requires_evidence: locked` beside `measures:`. The default `assumed` is
byte-identical to omitting the key; there is no `open`. An exposure's requirement reaches
every mart under `depends_on.marts` **and** every mart carrying a metric under
`depends_on.metrics`, because the planner picks the serving mart per request.

What a strict consumer refuses, and the repair each refusal names:

- a column carried by a relationship with `imported_from:`: author the relationship here
  and drop `imported_from:`, or relax to `assumed`;
- an entity, mart or metric imported from an upstream project: relax here, or put
  `requires_evidence: locked` on the upstream's own mart.

Use it on few consumers (a statutory finance mart), never on exploration marts: the
cheapest fix for a wall of refusals is deleting the requirement everywhere.

## Close an open decision

A metric is unreachable because a canonical field it needs is unavailable. bloomery
names the gap and the catalog's options; choosing is yours.

```console
$ bloomery resolve specs/
$ bloomery resolve specs/ --format json
```

The loop: read the report, make the one edit its first entry names, recompile, repeat.
It terminates, because recipes bind alias slots to source paths, never to other
canonical fields.

| `gap` | Means | Edit |
|---|---|---|
| `unlinked` | no entity field carries `canonical: <name>` | declare the field on the entity the report names, with `canonical:` |
| `unmapped` | a field carries the link, no mapping produces it | add the field to a mapping with a `recipe:` and its `from:` slots |

Fixing `unlinked` moves the decision to `unmapped`; that is expected. The `from:` keys
must be exactly the recipe's `requires`. `options` come in catalog order, which the
catalog author ranked; bloomery never picks, and sorting them destroys that order.

```python
from bloomery import evaluate, load_catalog, load_project

evidence = evaluate(load_project(sources), catalog=load_catalog(catalog_text))
for decision in evidence.unresolved:
    print(decision.canonical, decision.gap.value, decision.entity, decision.field)
    print("  blocks", decision.blocks, "options", [o.id for o in decision.options])
```

Read `stage_reached` before trusting an empty `unresolved`. It is also empty when a
resolve-stage refusal (an unknown recipe id, unbound `requires`) stopped the round, on a
merged entity (the report will not guess which mapping to edit), and when no metric
needs the field. `evidence.provenance` says, per mapped field, whether it is direct, a
recipe (with its id), or unlinked, and which mapping it came from.

## Published pages

- [Guardrails](https://morzecrew.github.io/bloomery/latest/concepts/guardrails/)
- [What bloomery proves](https://morzecrew.github.io/bloomery/latest/concepts/what-bloomery-proves/)
- [Close an open decision](https://morzecrew.github.io/bloomery/latest/how-to/close-an-open-decision/)
