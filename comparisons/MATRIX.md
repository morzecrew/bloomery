# Semantic capability matrix

What each system does with each case of the semantic bug corpus, from a reproduction that is
checked in beside it. Read [`README.md`](README.md) first: a cell is a property of a **tested
configuration**, never of a product, and the six values have precise meanings.

- **Last checked:** 2026-09-15.
- **Coverage:** 25 rows — one per *expectation*, not one per case. RFC 0042's twelve cases
  pin between one and three apiece, because a case is typically refused in one shape and
  planned correctly in another, and a column that answered only one of those would say
  nothing. bloomery is filled for all 25; MetricFlow for 6; dbt Core, SQLMesh and Cube for
  none.

## Columns

| Column | Version | Evidence |
|---|---|---|
| **bloomery** | this tree | `tests/fixtures/semantic_corpus/<case>/expected/semantic_outcome.json`, executed by `tests/execution/test_semantic_corpus.py` in the default suite |
| **MetricFlow** | `0.212.0` | [`metricflow/<case>/`](metricflow/) — manifest authored as YAML, rendered against DuckDB `1.5.5` |
| **dbt Core** | `1.12.3` resolved, unrun | — |
| **SQLMesh** | `0.236.1` resolved, unrun | — |
| **Cube** | not installed | — |

The last three are **`UNKNOWN` in every row**. They are listed rather than written out as
seventy-five identical cells, and nothing about a row's blank in those columns means
anything other than that nobody has run it. dbt Core and SQLMesh are resolved dependencies
of this repository, so a bundle for either can be written without installing anything; Cube
needs a runtime this repository does not carry, and by RFC 0043 §5 it earns a column when
someone will maintain the reproduction.

## The table

| Case | Expectation | bloomery | MetricFlow `0.212.0` |
|---|---|---|---|
| `001-order-shipping-fanout` | `refinement` | `NATIVE-PREVENT` <br> `GrainMismatch`, RFC 0006 D5 | `UNKNOWN` |
| `001-order-shipping-fanout` | `representation` | `NATIVE-PREVENT` <br> `GrainViolation`, RFC 0010 D2 | `UNKNOWN` |
| `001-order-shipping-fanout` | `rollup` | `NATIVE-PLAN` <br> RFC 0010 D2 | `UNKNOWN` |
| `002-average-of-averages` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D2 | `NOT-REPRESENTED` <br> returns `55.0`; validator clean |
| `002-average-of-averages` | `decomposed` | `NATIVE-PLAN` <br> RFC 0006 D6 | `NATIVE-PLAN` <br> `ratio` metric returns `32.5` |
| `003-scd2-unqualified-join` | `unanchored` | `NATIVE-PREVENT` <br> `HistoricalFanout`, RFC 0023 D1 | `UNKNOWN` |
| `003-scd2-unqualified-join` | `anchored` | `NATIVE-PLAN` <br> RFC 0023 D8 | `UNKNOWN` |
| `004-currency-mix` | `mixed` | `NATIVE-PREVENT` <br> `CurrencyMismatch`, RFC 0006 D4 | `UNKNOWN` |
| `004-currency-mix` | `mislabelled` | `NATIVE-PREVENT` <br> `ResolutionError`, R009 | `UNKNOWN` |
| `004-currency-mix` | `converted` | `NATIVE-PLAN` <br> R009 | `UNKNOWN` |
| `005-semi-additive-balance` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D1 | `NOT-REPRESENTED` <br> returns `320.0000`; validator clean |
| `005-semi-additive-balance` | `declared` | `NATIVE-PLAN` <br> R015 | `NATIVE-PLAN` <br> `non_additive_dimension` returns `170.0000` |
| `006-two-grains-one-request` | `branches` | `NATIVE-PLAN` <br> R010 | `UNKNOWN` |
| `007-distinct-users-fanout` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D2 | `UNKNOWN` |
| `007-distinct-users-fanout` | `declared` | `NATIVE-PLAN` <br> RFC 0038 D1 | `UNKNOWN` |
| `008-ratio-rollup` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D2 | `NOT-REPRESENTED` <br> returns `3.5`; validator clean |
| `008-ratio-rollup` | `declared` | `NATIVE-PLAN` <br> R012 | `NATIVE-PLAN` <br> `ratio` metric returns `3.25` |
| `009-null-denominator` | `declared` | **`NOT-REPRESENTED`** <br> RFC 0042 D5 | `UNKNOWN` |
| `009-null-denominator` | `restricted` | `NATIVE-PLAN` <br> R012 | `UNKNOWN` |
| `010-many-to-many-bridge` | `bridged` | `NATIVE-PREVENT` <br> `GrainViolation`, RFC 0010 D2 | `UNKNOWN` |
| `010-many-to-many-bridge` | `per_order` | `NATIVE-PLAN` <br> R011 | `UNKNOWN` |
| `011-timezone-boundary` | `zoneless` | **`NOT-REPRESENTED`** <br> RFC 0042 D5 | `UNKNOWN` |
| `011-timezone-boundary` | `anchored` | `NATIVE-PLAN` <br> R011 | `UNKNOWN` |
| `012-rollup-recounts-identities` | `rolled` | `NATIVE-PREVENT` <br> `UnprovableRollup`, R013 | `UNKNOWN` |
| `012-rollup-recounts-identities` | `detail` | `NATIVE-PLAN` <br> R008 | `UNKNOWN` |

## Reading the MetricFlow column

Six cells, three cases, and they say two different things.

**In all three, where the correct model was asked for, `0.212.0` was native and right.** A
`ratio` metric rebuilds a quotient from its operands at the requested grain;
`non_additive_dimension` with `window_choice: max` reduces a daily snapshot to its last value
before aggregating across accounts. Both return the corpus's `correct` number with no
project-authored SQL. `005` is the strongest of the three: the semantics are declared, not
approximated.

**In all three, where the wrong model was asked for, nothing stopped it.** The naive manifest
passes MetricFlow's own `SemanticManifestValidator` with **0 errors and 0 warnings**, plans,
and returns the corpus's `naive` number. In `005` the two measures sit in the same semantic
model over the same column and differ only by one block — indistinguishable to the validator,
opposite in meaning.

That is what `NOT-REPRESENTED` names here: not that MetricFlow is careless, but that the
fact which would make the naive model refusable — *this stored column is already an
aggregate* — has no place in the manifest to be stated. The measure schema is closed, so
this is checkable rather than a failure to find it; each bundle's `sources.md` prints the
key set. A system cannot check a claim its vocabulary cannot express.

**The comparison is between vocabularies, and that cuts both ways.** bloomery's
`NATIVE-PREVENT` cells are not it being more careful with the same information: they exist
because its spec *requires* an additivity declaration, so there is something to be wrong
about and therefore something to refuse. A manifest that never asks the question cannot
answer it wrongly either. What the rows compare is which facts each system makes an author
state, not which system is more diligent about facts they both hold.

This is the evidence behind the sentence in
[`pages/docs/concepts/guardrails.md`](../pages/docs/concepts/guardrails.md), "MetricFlow
lowers additivity; it does not stop you from modeling it wrongly." Both halves are now
measured rather than asserted.

## Where bloomery loses

Two rows, both `NOT-REPRESENTED`, both meaning bloomery compiles the request and returns a
number that is wrong:

- **`009-null-denominator` / `declared`** — a ratio whose denominator can be zero or null.
- **`011-timezone-boundary` / `zoneless`** — a daily aggregate over timestamps with no zone
  anchor.

They are pinned as `unguarded` in the corpus and run in the default suite that way, so the
wrong number is asserted rather than tolerated. Neither has been measured on any other
column, so nothing here says another system does better — only that bloomery does not do
this yet.
