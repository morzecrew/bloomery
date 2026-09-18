# Semantic capability matrix

What each system does with each case of the semantic bug corpus, from a reproduction that is
checked in beside it. Read [`README.md`](README.md) first: a cell is a property of a **tested
configuration**, never of a product, and the six values have precise meanings.

- **Last checked:** 2026-09-18 (every dbt Core bundle; MetricFlow's `009` and `011`);
  2026-09-15 (MetricFlow's `002`, `005`, `008`). Each bundle's `README.md` pins its own date
  and version, and those are what a cell rests on.
- **Coverage:** 25 rows — one per *expectation*, not one per case. RFC 0042's twelve cases
  pin between one and three apiece, because a case is typically refused in one shape and
  planned correctly in another, and a column that answered only one of those would say
  nothing. bloomery is filled for all 25; MetricFlow for 11; dbt Core for the same 11;
  SQLMesh and Cube for none.

## Columns

| Column | Version | Evidence |
|---|---|---|
| **bloomery** | this tree | `tests/fixtures/semantic_corpus/<case>/expected/semantic_outcome.json`, executed by `tests/execution/test_semantic_corpus.py` in the default suite |
| **MetricFlow** | `0.212.0` | [`metricflow/<case>/`](metricflow/) — manifest authored as YAML, rendered against DuckDB `1.5.5` |
| **dbt Core** | `1.12.3` | [`dbt/<case>/`](dbt/) — a dbt project with `semantic_models:` and `metrics:`, built by `dbt-duckdb` `1.11.0` against DuckDB `1.5.5`; no `dbt-metricflow`, no dbt Cloud |
| **SQLMesh** | `0.236.1` resolved, unrun | — |
| **Cube** | not installed | — |

The last two are **`UNKNOWN` in every row**. They are listed rather than written out as fifty
identical cells, and nothing about a row's blank in those columns means anything other than
that nobody has run it. SQLMesh is a resolved dependency of this repository, so a bundle for
it can be written without installing anything; Cube needs a runtime this repository does not
carry, and by RFC 0043 §5 it earns a column when someone will maintain the reproduction.

## The table

| Case | Expectation | bloomery | MetricFlow `0.212.0` | dbt Core `1.12.3` |
|---|---|---|---|---|
| `001-order-shipping-fanout` | `refinement` | `NATIVE-PREVENT` <br> `GrainMismatch`, RFC 0006 D5 | `UNKNOWN` | `UNKNOWN` |
| `001-order-shipping-fanout` | `representation` | `NATIVE-PREVENT` <br> `GrainViolation`, RFC 0010 D2 | `UNKNOWN` | `UNKNOWN` |
| `001-order-shipping-fanout` | `rollup` | `NATIVE-PLAN` <br> RFC 0010 D2 | `UNKNOWN` | `UNKNOWN` |
| `002-average-of-averages` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D2 | `NOT-REPRESENTED` <br> returns `55.0`; validator clean | `NOT-REPRESENTED` <br> parse clean; no metric SQL, a project model returns `55.00000000` |
| `002-average-of-averages` | `decomposed` | `NATIVE-PLAN` <br> RFC 0006 D6 | `NATIVE-PLAN` <br> `ratio` metric returns `32.5` | `CUSTOM` <br> `ratio` metric accepted, renders nothing; model returns `32.50000000` |
| `003-scd2-unqualified-join` | `unanchored` | `NATIVE-PREVENT` <br> `HistoricalFanout`, RFC 0023 D1 | `UNKNOWN` | `UNKNOWN` |
| `003-scd2-unqualified-join` | `anchored` | `NATIVE-PLAN` <br> RFC 0023 D8 | `UNKNOWN` | `UNKNOWN` |
| `004-currency-mix` | `mixed` | `NATIVE-PREVENT` <br> `CurrencyMismatch`, RFC 0006 D4 | `UNKNOWN` | `UNKNOWN` |
| `004-currency-mix` | `mislabelled` | `NATIVE-PREVENT` <br> `ResolutionError`, R009 | `UNKNOWN` | `UNKNOWN` |
| `004-currency-mix` | `converted` | `NATIVE-PLAN` <br> R009 | `UNKNOWN` | `UNKNOWN` |
| `005-semi-additive-balance` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D1 | `NOT-REPRESENTED` <br> returns `320.0000`; validator clean | `NOT-REPRESENTED` <br> parse clean; a project model returns `320.0000` |
| `005-semi-additive-balance` | `declared` | `NATIVE-PLAN` <br> R015 | `NATIVE-PLAN` <br> `non_additive_dimension` returns `170.0000` | `CUSTOM` <br> `non_additive_dimension` accepted, renders nothing; model returns `170.0000` |
| `006-two-grains-one-request` | `branches` | `NATIVE-PLAN` <br> R010 | `UNKNOWN` | `UNKNOWN` |
| `007-distinct-users-fanout` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D2 | `UNKNOWN` | `UNKNOWN` |
| `007-distinct-users-fanout` | `declared` | `NATIVE-PLAN` <br> RFC 0038 D1 | `UNKNOWN` | `UNKNOWN` |
| `008-ratio-rollup` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, RFC 0038 D2 | `NOT-REPRESENTED` <br> returns `3.5`; validator clean | `NOT-REPRESENTED` <br> parse clean; a project model returns `3.5` |
| `008-ratio-rollup` | `declared` | `NATIVE-PLAN` <br> R012 | `NATIVE-PLAN` <br> `ratio` metric returns `3.25` | `CUSTOM` <br> `ratio` metric accepted, renders nothing; model returns `3.25` |
| `009-null-denominator` | `declared` | `NATIVE-PREVENT` <br> `UndeclaredRatioRows`, R019 | `NOT-REPRESENTED` <br> returns `4.0`; validator clean | `NOT-REPRESENTED` <br> parse clean; the rows a ratio is over are an optional input `filter` |
| `009-null-denominator` | `inclusive` | `NATIVE-PLAN` <br> R019 | `NATIVE-PLAN` <br> `ratio` metric returns `4.0` | `CUSTOM` <br> `ratio` metric accepted, renders nothing; model returns `4.0` |
| `009-null-denominator` | `restricted` | `NATIVE-PLAN` <br> R012 | `NATIVE-PLAN` <br> input-measure `filter` returns `3.0` | `CUSTOM` <br> input-measure `filter` accepted, renders nothing; model returns `3.0` |
| `010-many-to-many-bridge` | `bridged` | `NATIVE-PREVENT` <br> `GrainViolation`, RFC 0010 D2 | `UNKNOWN` | `UNKNOWN` |
| `010-many-to-many-bridge` | `per_order` | `NATIVE-PLAN` <br> R011 | `UNKNOWN` | `UNKNOWN` |
| `011-timezone-boundary` | `zoneless` | `NATIVE-PREVENT` <br> `UndeclaredZone`, R018 | `NOT-REPRESENTED` <br> returns `40.00`; validator clean | `NOT-REPRESENTED` <br> parse clean; a project model returns `40.00` |
| `011-timezone-boundary` | `anchored` | `NATIVE-PLAN` <br> R011 | `CUSTOM` <br> zone conversion as SQL in a dimension `expr`; returns `140.00` | `CUSTOM` <br> zone conversion as SQL in a model; renders nothing for the metric; returns `140.00` |
| `012-rollup-recounts-identities` | `rolled` | `NATIVE-PREVENT` <br> `UnprovableRollup`, R013 | `UNKNOWN` | `UNKNOWN` |
| `012-rollup-recounts-identities` | `detail` | `NATIVE-PLAN` <br> R008 | `UNKNOWN` | `UNKNOWN` |

## Reading the MetricFlow column

Eleven cells, five cases, and they say three things.

**Where the correct model was asked for, `0.212.0` was native and right in four of the five
cases.** A `ratio` metric rebuilds a quotient from its operands at the requested grain;
`non_additive_dimension` with `window_choice: max` reduces a daily snapshot to its last value
before aggregating across accounts; a `filter` on a ratio's input measures restricts both
operands to the same rows, which is `009`'s `restricted` reading at `3.0`. All return the
corpus's number with no project-authored SQL. `005` is the strongest: the semantics are
declared, not approximated.

**Where the wrong model was asked for, nothing stopped it, in all five.** The naive manifest
passes MetricFlow's own `SemanticManifestValidator` with **0 errors and 0 warnings**, plans,
and returns the corpus's `naive` number. In `005` the two measures sit in the same semantic
model over the same column and differ only by one block; in `009` the two ratios differ only
by two filters; in `011` the two time dimensions differ only by a zone conversion in an
`expr` — each pair indistinguishable to the validator, opposite in meaning.

That is what `NOT-REPRESENTED` names here: not that MetricFlow is careless, but that the
fact which would make the naive model refusable — *this stored column is already an
aggregate*, *this ratio is over rows with no denominator*, *this wall clock was written in
this zone* — has no place in the manifest to be stated. The schemas are closed
(`additionalProperties: False`), so this is checkable rather than a failure to find it; each
bundle's `sources.md` prints the key set it searched. A system cannot check a claim its
vocabulary cannot express.

**`011`'s `anchored` cell is the column's first `CUSTOM`, and the distinction it turns on is
the point of having six values.** MetricFlow returns the right `140.00` — but what makes it
right is a dialect-specific string the author wrote into a dimension's `expr`, which
MetricFlow passes through without knowing it is a zone conversion. That is a different fact
from `002`'s `ratio` metric, where the semantics are the system's and the author only names
them, and the cell says so rather than scoring both as a win.

**Two manifest keys look relevant to these two cases and were measured rather than
reasoned about.** `fill_nulls_with` reads as though it answered a null denominator and
`join_to_timespine` as though it answered a period boundary; both are about a time-spine
join — which *periods* appear in a result — and neither is about which rows a ratio is over
or which instant a stored wall clock denotes. `009`'s bundle declares `fill_nulls_with: 0` on
the denominator and records what it changes: nothing, `4.0` either way. A key that looks
relevant is not a cell until it has been run.

**The comparison is between vocabularies, and that cuts both ways.** bloomery's
`NATIVE-PREVENT` cells are not it being more careful with the same information: they exist
because its spec *requires* the declaration — of additivity, of the rows a ratio is over, of
the zone a wall clock was written in — so there is something to be wrong about and therefore
something to refuse. A manifest that never asks the question cannot
answer it wrongly either. What the rows compare is which facts each system makes an author
state, not which system is more diligent about facts they both hold.

This is the evidence behind the sentence in
[`pages/docs/concepts/guardrails.md`](../pages/docs/concepts/guardrails.md), "MetricFlow
lowers additivity; it does not stop you from modeling it wrongly." Both halves are now
measured rather than asserted.

## Reading the dbt Core column

Eleven cells, the same five cases, and they say three things — one of which is about this
column's relationship to the one beside it.

**dbt Core `1.12.3` parses metrics; in this configuration it does not answer them.** All
sixteen `dbt compile --select metric:<name>` invocations across the five bundles render no
SQL: `Nothing to do.` The metrics are real to dbt — `dbt list --resource-type metric` prints
them and they reach the manifest — but the engine that turns one into a query ships
separately, as `dbt-metricflow`, and is not installed here. So every row where the correct
model was asked for is `CUSTOM`: the corpus's number was produced by a model the project
author wrote, in every case. Nothing in these cells says a metric *cannot* be answered — only
that in this configuration, no command did.

**Where the wrong model was asked for, nothing stopped it, in all five — and this is not an
independent observation.** At this version dbt Core's semantic vocabulary *is* the
`metricflow_semantic_interfaces` one: `dbt/artifacts/resources/v1/metric.py` imports
`MetricType` from that package, and `dbt/contracts/graph/semantic_manifest.py` runs its
`SemanticManifestValidator` while parsing. A reader comparing the `NOT-REPRESENTED` cells in
these two columns is looking at one vocabulary measured in two configurations, not two
findings that agree.

Each of these bundles probes the point rather than asserting it. `already_aggregated` on a
measure, `already_a_rate` on a measure, and `time_zone` beside a time dimension's granularity
are all refused by dbt's own parser — `Additional properties are not allowed`, `is not valid
under any of the given schemas` — so the key sets are closed and the absence is a property of
the vocabulary rather than of the search. The `005` bundle probes nothing, because there the
key exists: `non_additive_dimension` states the fact and stating it is optional, which is a
different way for a naive model to go unchallenged.

**One difference between the two columns is the vocabulary itself, at the versions pinned.**
`fill_nulls_with: 0` in a `ratio` metric's denominator — which MetricFlow `0.212.0` accepted,
changing nothing — is rejected outright by dbt Core `1.12.3`'s parser. The packages move
independently, and the cells pin the version each was measured at for exactly this reason.

**The comparison is between vocabularies, here too.** bloomery's `NATIVE-PREVENT` rows
against this column's `NOT-REPRESENTED` ones are not a diligence gap: bloomery's spec
*requires* the declaration — of additivity, of the rows a ratio is over, of the zone a wall
clock was written in — so there is a claim on the page that can be false and therefore
refused, while a dbt project that is never asked has stated nothing to be wrong about. And
`CUSTOM` against MetricFlow's `NATIVE-PLAN` is a fact about which package renders the SQL in
the configuration measured, not about which system models the semantics better. What the
rows compare is which facts each system makes an author state, not which system is more
diligent about facts they both hold.

**What this column does not cover is `UNKNOWN` and stays that way.** dbt Core with
`dbt-metricflow` installed, and the hosted dbt Semantic Layer, were not run: neither has a
bundle, so neither has a cell. The seven cases with no dbt bundle are `UNKNOWN` for the same
reason.

## Where bloomery loses

**No rows, at the time of writing.** That is a statement about this corpus and nothing
wider: it holds over twelve cases somebody chose, and the next case added is as likely to
open a gap as to close one. A matrix with an empty column here is a matrix whose cases have
been answered, not a compiler that cannot be wrong.

Two rows sat here and both moved, which is what the column is for:

- **`011-timezone-boundary` / `zoneless`** — now `NATIVE-PREVENT` (RFC 0074, R018).
- **`009-null-denominator` / `declared`** — now `NATIVE-PREVENT` (RFC 0075, R019), and the
  case gained an `inclusive` arm: `4.00` was the wrong answer to "what does it cost to move
  a parcel" and is the right one to a question an author can now write down.

Each was pinned `unguarded` while it was open, so the wrong number was asserted rather than
tolerated, and the row is what made the gap citable until the rule landed.
