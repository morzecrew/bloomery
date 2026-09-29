# Semantic capability matrix

What each system does with each case of the semantic bug corpus, from a reproduction that is
checked in beside it. Read [`README.md`](README.md) first: a cell is a property of a **tested
configuration**, never of a product, and the six values have precise meanings.

- **Last checked:** 2026-09-29 (the MetricFlow, dbt Core and SQLMesh bundles for `001`,
  `003`, `004`, `006`, `007`, `010` and `012`); 2026-09-28 (the other five MetricFlow
  bundles, re-run on `0.213.0`, and the other five SQLMesh bundles, re-run on `0.236.2`, with
  every observation unchanged); 2026-09-18 (the other five dbt Core bundles). Each bundle's
  `README.md` pins its own date and version, and those are what a cell rests on.
- **Coverage:** 26 rows — one per *expectation*, not one per case. S-0056's twelve cases
  pin between one and three apiece, because a case is typically refused in one shape and
  planned correctly in another, and a column that answered only one of those would say
  nothing. bloomery is filled for all 26; MetricFlow for all 26; dbt Core for 24, with
  `001`'s `refinement` and `004`'s `mislabelled` left unrun by their bundles; SQLMesh for 25,
  with `001`'s `refinement` run but not answered; Cube for none.

## Columns

| Column | Version | Evidence |
|---|---|---|
| **bloomery** | this tree | `tests/fixtures/semantic_corpus/<case>/expected/semantic_outcome.json`, executed by `tests/execution/test_semantic_corpus.py` in the default suite |
| **MetricFlow** | `0.213.0` | [`metricflow/<case>/`](metricflow/) — manifest authored as YAML, rendered against DuckDB `1.5.5` |
| **dbt Core** | `1.12.3` | [`dbt/<case>/`](dbt/) — a dbt project with `semantic_models:` and `metrics:`, built by `dbt-duckdb` `1.11.0` against DuckDB `1.5.5`; no `dbt-metricflow`, no dbt Cloud |
| **SQLMesh** | `0.236.2` | [`sqlmesh/<case>/`](sqlmesh/) — `MODEL` and `METRIC` DDL in a project with one `duckdb` gateway, planned and rendered against DuckDB `1.5.5`; no Tobiko Cloud |
| **Cube** | not installed | — |

The last is **`UNKNOWN` in every row**. It is listed rather than written out as twenty-six
identical cells, and nothing about a row's blank in that column means anything other than
that nobody has run it. Cube needs a runtime this repository does not carry, and by S-0006
§5 it earns a column when someone will maintain the reproduction.

## The table

| Case | Expectation | bloomery | MetricFlow `0.213.0` | dbt Core `1.12.3` | SQLMesh `0.236.2` |
|---|---|---|---|---|---|
| `001-order-shipping-fanout` | `refinement` | `NATIVE-PREVENT` <br> `GrainMismatch`, S-0023/D-5 | `NOT-REPRESENTED` <br> a line-grain view returns `57.0000`; validator clean. The same derivation through the normalized models is refused as a fan-out join | `UNKNOWN` <br> not run: no counterpart declared in the bundle | `UNKNOWN` <br> SQLMesh's own join to a line column renders SQL DuckDB refuses; no number, and no grain check |
| `001-order-shipping-fanout` | `representation` | `NATIVE-PREVENT` <br> `GrainViolation`, S-0027/D-2 | `NOT-REPRESENTED` <br> a line-grain view returns `27.0000`; validator clean | `NOT-REPRESENTED` <br> build clean; a project model returns `27.0000` | `NOT-REPRESENTED` <br> returns `27.0000`; plan and audit clean |
| `001-order-shipping-fanout` | `rollup` | `NATIVE-PLAN` <br> S-0027/D-2 | `NATIVE-PLAN` <br> `sum` on the order model returns `9.0000` | `CUSTOM` <br> metric accepted, renders nothing; model returns `9.0000` | `NATIVE-PLAN` <br> metric over the order model returns `9.0000` |
| `002-average-of-averages` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, S-0053/D-2 | `NOT-REPRESENTED` <br> returns `55.0`; validator clean | `NOT-REPRESENTED` <br> parse clean; no metric SQL, a project model returns `55.00000000` | `NOT-REPRESENTED` <br> returns `55.0`; plan and audit clean |
| `002-average-of-averages` | `decomposed` | `NATIVE-PLAN` <br> S-0023/D-6 | `NATIVE-PLAN` <br> `ratio` metric returns `32.5` | `CUSTOM` <br> `ratio` metric accepted, renders nothing; model returns `32.50000000` | `NATIVE-PLAN` <br> derived metric returns `32.5` |
| `003-scd2-unqualified-join` | `unanchored` | `NATIVE-PREVENT` <br> `HistoricalFanout`, S-0040/D-1 | `NOT-REPRESENTED` <br> the history declared with a `primary` entity returns `600.0000`; validator clean | `NOT-REPRESENTED` <br> `validity_params` accepted, not read by the model; a key-only model join returns `600.0000` | `NOT-REPRESENTED` <br> returns `600.0000` by business key; no slot for a validity interval |
| `003-scd2-unqualified-join` | `anchored` | `NATIVE-PLAN` <br> S-0040/D-8 | `NATIVE-PLAN` <br> `natural` entity with `validity_params` returns `300.0000` | `CUSTOM` <br> `validity_params` accepted, renders nothing; model returns `300.0000` | `CUSTOM` <br> as-of predicate in an author-written model; returns `300.0000` |
| `004-currency-mix` | `mixed` | `NATIVE-PREVENT` <br> `CurrencyMismatch`, S-0023/D-4 | `NOT-REPRESENTED` <br> returns `157.5000`; validator clean | `NOT-REPRESENTED` <br> build clean; `currency` on a measure refused by the parser; model returns `157.5000` | `NOT-REPRESENTED` <br> returns `157.5000`; plan and audit clean |
| `004-currency-mix` | `mislabelled` | `NATIVE-PREVENT` <br> `ResolutionError`, R009 | `NOT-REPRESENTED` <br> validator clean; returns `None` only because the rate relation has no `JPY` row | `UNKNOWN` <br> not run: no native conversion construct to mislabel | `NOT-REPRESENTED` <br> plans and runs clean |
| `004-currency-mix` | `converted` | `NATIVE-PLAN` <br> R009 | `CUSTOM` <br> conversion as a SQL view; returns `172.5000` | `CUSTOM` <br> conversion as SQL in a model; returns `172.5000` | `CUSTOM` <br> conversion as SQL in a model; returns `172.5000` |
| `005-semi-additive-balance` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, S-0053/D-1 | `NOT-REPRESENTED` <br> returns `320.0000`; validator clean | `NOT-REPRESENTED` <br> parse clean; a project model returns `320.0000` | `NOT-REPRESENTED` <br> returns `320.0000`; plan and audit clean |
| `005-semi-additive-balance` | `declared` | `NATIVE-PLAN` <br> R015 | `NATIVE-PLAN` <br> `non_additive_dimension` returns `170.0000` | `CUSTOM` <br> `non_additive_dimension` accepted, renders nothing; model returns `170.0000` | `CUSTOM` <br> a project model selects the last day; the metric over it returns `170.0000` |
| `006-two-grains-one-request` | `branches` | `NATIVE-PLAN` <br> R010 | `NATIVE-PLAN` <br> two metrics return `16.0000` and `6.0000` | `CUSTOM` <br> metrics accepted, render nothing; model returns `16.0000` and `6.0000` | `NATIVE-PLAN` <br> two metrics return `16.0000` and `6.0000` |
| `007-distinct-users-fanout` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, S-0053/D-2 | `NOT-REPRESENTED` <br> `sum` over a view of daily counts returns `4`; validator clean | `NOT-REPRESENTED` <br> build clean; a project model returns `4` | `NOT-REPRESENTED` <br> returns `4`; plan and audit clean |
| `007-distinct-users-fanout` | `declared` | `NATIVE-PLAN` <br> S-0053/D-1 | `NATIVE-PLAN` <br> `count_distinct` returns `3` | `CUSTOM` <br> `count_distinct` accepted, renders nothing; model returns `3` | `NATIVE-PLAN` <br> `COUNT(DISTINCT ...)` returns `3` |
| `008-ratio-rollup` | `naive` | `NATIVE-PREVENT` <br> `FalseAdditivityClaim`, S-0053/D-2 | `NOT-REPRESENTED` <br> returns `3.5`; validator clean | `NOT-REPRESENTED` <br> parse clean; a project model returns `3.5` | `NOT-REPRESENTED` <br> returns `3.5`; plan and audit clean |
| `008-ratio-rollup` | `declared` | `NATIVE-PLAN` <br> R012 | `NATIVE-PLAN` <br> `ratio` metric returns `3.25` | `CUSTOM` <br> `ratio` metric accepted, renders nothing; model returns `3.25` | `NATIVE-PLAN` <br> derived metric returns `3.25` |
| `009-null-denominator` | `declared` | `NATIVE-PREVENT` <br> `UndeclaredRatioRows`, R019 | `NOT-REPRESENTED` <br> returns `4.0`; validator clean | `NOT-REPRESENTED` <br> parse clean; the rows a ratio is over are an optional input `filter` | `NOT-REPRESENTED` <br> returns `4.0`; an `accepted_range` audit fails on the row, not on the metric |
| `009-null-denominator` | `inclusive` | `NATIVE-PLAN` <br> R019 | `NATIVE-PLAN` <br> `ratio` metric returns `4.0` | `CUSTOM` <br> `ratio` metric accepted, renders nothing; model returns `4.0` | `NATIVE-PLAN` <br> derived metric returns `4.0` |
| `009-null-denominator` | `restricted` | `NATIVE-PLAN` <br> R012 | `NATIVE-PLAN` <br> input-measure `filter` returns `3.0` | `CUSTOM` <br> input-measure `filter` accepted, renders nothing; model returns `3.0` | `CUSTOM` <br> `CASE WHEN` in each operand, author-written; returns `3.0` |
| `010-many-to-many-bridge` | `bridged` | `NATIVE-PREVENT` <br> `GrainViolation`, S-0027/D-2 | `NOT-REPRESENTED` <br> a bridge-grain view returns `250.00`; validator clean. The path through the bridge is refused as a fan-out join | `NOT-REPRESENTED` <br> build clean; a project model returns `250.00` | `NOT-REPRESENTED` <br> returns `250.00`; plan and audit clean |
| `010-many-to-many-bridge` | `per_order` | `NATIVE-PLAN` <br> R011 | `NATIVE-PLAN` <br> `sum` on the order model returns `150.00` | `CUSTOM` <br> metric accepted, renders nothing; model returns `150.00` | `NATIVE-PLAN` <br> metric over the order model returns `150.00` |
| `011-timezone-boundary` | `zoneless` | `NATIVE-PREVENT` <br> `UndeclaredZone`, R018 | `NOT-REPRESENTED` <br> returns `40.00`; validator clean | `NOT-REPRESENTED` <br> parse clean; a project model returns `40.00` | `NOT-REPRESENTED` <br> returns `40.00`; plan and audit clean |
| `011-timezone-boundary` | `anchored` | `NATIVE-PLAN` <br> R011 | `CUSTOM` <br> zone conversion as SQL in a dimension `expr`; returns `140.00` | `CUSTOM` <br> zone conversion as SQL in a model; renders nothing for the metric; returns `140.00` | `CUSTOM` <br> zone conversion as SQL in a model; returns `140.00` |
| `012-rollup-recounts-identities` | `rolled` | `NATIVE-PREVENT` <br> `UnprovableRollup`, R013 | `NOT-REPRESENTED` <br> `sum` over the rollup returns `4`; validator clean | `NOT-REPRESENTED` <br> build clean; a project model returns `4` | `NOT-REPRESENTED` <br> returns `4`; plan and audit clean |
| `012-rollup-recounts-identities` | `detail` | `NATIVE-PLAN` <br> R008 | `NATIVE-PLAN` <br> `count_distinct` returns `3` | `CUSTOM` <br> `count_distinct` accepted, renders nothing; model returns `3` | `NATIVE-PLAN` <br> `COUNT(DISTINCT ...)` returns `3` |

## Reading the MetricFlow column

Twenty-six cells, all twelve cases. The five measured first — `002`, `005`, `008`, `009`,
`011` — say three things; the seven measured on 2026-09-29 add three more, at the end.

**Where the correct model was asked for, `0.213.0` was native and right in four of the first
five cases.** A `ratio` metric rebuilds a quotient from its operands at the requested grain;
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

**Of the seven later cases, every correct reading but one plans natively.** `001`'s rollup,
`006`'s two grains in one request, `007`'s and `012`'s distinct counts and `010`'s revenue per
order are each aggregated in the semantic model that declares them, with no project SQL.
`003`'s `anchored` cell is the column's clearest native win: a `natural` entity with start
and end `validity_params` joins each order to the version in force at its date. The one
exception is `004`'s `converted`, which is `CUSTOM`: the rate join is a view the author
wrote, because no key in the manifest names a currency.

**A structural refusal fires in two cases, and the cells do not count it.** Asked for an
order-grain measure by a line (`001`) or a promotion (`010`), `0.213.0` refuses to plan
before any SQL: a `primary` → `foreign` hop is among its invalid entity joins, and the
message says fan-out join support is pending. That rule reads entity types, not the measure,
and a relation that already carries the copy — one `CREATE VIEW` — validates clean and
returns the corpus's wrong number. Each bundle maps the row to that relation, so the cell is
`NOT-REPRESENTED`: no key states the grain a value originates at.

**Where the history is declared wrongly, the cell turns on an optional declaration.** In
`003` the same table declared with a `primary` entity is a claim that the key is unique,
which the validator accepts without reading the data and answers `600.0000`. The type-2
fact has a native representation; nothing requires choosing it. That is the same shape as
`005`'s optional `non_additive_dimension`, and the cell reads it the same way.

**The comparison is between vocabularies, and that cuts both ways.** bloomery's
`NATIVE-PREVENT` cells are not it being more careful with the same information: they exist
because its spec *requires* the declaration — of additivity, of the rows a ratio is over, of
the zone a wall clock was written in, of the grain a value originates at, of a column's
currency — so there is something to be wrong about and therefore something to refuse. A manifest that never asks the question cannot
answer it wrongly either. What the rows compare is which facts each system makes an author
state, not which system is more diligent about facts they both hold.

This is the evidence behind the sentence in
[`pages/docs/concepts/guardrails.md`](../pages/docs/concepts/guardrails.md), "MetricFlow
lowers additivity; it does not stop you from modeling it wrongly." Both halves are now
measured rather than asserted.

## Reading the dbt Core column

Twenty-four cells over all twelve cases, and two `UNKNOWN`: `001`'s `refinement` and
`004`'s `mislabelled` were not modelled by their bundles, which say so, and supply no evidence
for either. The cells say three things — one of which is about this column's relationship to
the one beside it.

**dbt Core `1.12.3` parses metrics; in this configuration it does not answer them.** Every
`dbt compile --select metric:<name>` invocation across the twelve bundles renders no
SQL: `Nothing to do.` The metrics are real to dbt — `dbt list --resource-type metric` prints
them and they reach the manifest — but the engine that turns one into a query ships
separately, as `dbt-metricflow`, and is not installed here. So every row where the correct
model was asked for is `CUSTOM`: the corpus's number was produced by a model the project
author wrote, in every case. Nothing in these cells says a metric *cannot* be answered — only
that in this configuration, no command did.

**Where the wrong model was asked for, nothing stopped it, in all twelve cases — and this is not an
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
the vocabulary rather than of the search. `004` adds `currency` on a measure, refused the
same way; the labels it carries under free-form `meta` were accepted and bore on nothing. The
`005` bundle probes nothing, because there the key exists: `non_additive_dimension` states
the fact and stating it is optional, which is a different way for a naive model to go
unchallenged. `003` is the same shape: `validity_params` on a `natural` entity states the
type-2 fact and `dbt build` accepts it, but the join that counts every version is a model's
SQL, and nothing in the run related that SQL to the declared window — so the `unanchored`
cell is `NOT-REPRESENTED` beside a history that is, in the semantic model, represented.

**One difference between the two columns is the vocabulary itself, at the versions pinned.**
`fill_nulls_with: 0` in a `ratio` metric's denominator — which MetricFlow `0.213.0` accepted,
changing nothing — is rejected outright by dbt Core `1.12.3`'s parser. The packages move
independently, and the cells pin the version each was measured at for exactly this reason.

**The comparison is between vocabularies, here too.** bloomery's `NATIVE-PREVENT` rows
against this column's `NOT-REPRESENTED` ones are not a diligence gap: bloomery's spec
*requires* the declaration — of additivity, of the rows a ratio is over, of the zone a wall
clock was written in, of the grain a value originates at, of a column's currency — so there
is a claim on the page that can be false and therefore refused, while a dbt project that is
never asked has stated nothing to be wrong about. And
`CUSTOM` against MetricFlow's `NATIVE-PLAN` is a fact about which package renders the SQL in
the configuration measured, not about which system models the semantics better. What the
rows compare is which facts each system makes an author state, not which system is more
diligent about facts they both hold.

**What this column does not cover is `UNKNOWN` and stays that way.** dbt Core with
`dbt-metricflow` installed, and the hosted dbt Semantic Layer, were not run: neither has a
bundle, so neither has a cell. Whether an engine that renders metrics would refuse `001`'s
or `010`'s fan-out, as MetricFlow's planner did, is therefore not something this column
says.

## Reading the SQLMesh column

Twenty-five cells over all twelve cases, and one `UNKNOWN`: `001`'s `refinement`, which the
bundle ran and which returned no number either way. The first five cases measured say four
things; the seven measured on 2026-09-29 add three more, at the end.

**SQLMesh `0.236.2` both declares metrics and answers them, in this configuration.** A
`METRIC (...)` block carries a SQL expression; `sqlmesh rewrite "SELECT METRIC(x) FROM
__semantic.__table"` turns it into a query, collecting the aggregates into a subquery over the
model they name and composing derived metrics outside it; the query returns the corpus's
number. That is the difference from the dbt Core column beside it, where in the measured
configuration no command renders a metric at all — and it is a difference between two
configurations, not a verdict about two products.

**Where the correct model was asked for, the cells split, and the line between them is
stated rather than felt.** `NATIVE-PLAN` is a bare aggregate of a model column composed by
SQLMesh's derived metrics — `002`'s quotient of a sum and a count, `008`'s revenue over items,
`009`'s inclusive ratio — where the re-aggregation at the requested grain is the rewriter's
work. `CUSTOM` is where the cell rests on SQL this project's author wrote and SQLMesh carries
through without knowing what it means: a `WHERE` clause in a model that performs `005`'s
semi-additive reduction, a `CASE WHEN` inside each operand for `009`'s restricted rows, an
`AT TIME ZONE` conversion in a model for `011`.

**Where the wrong model was asked for, nothing stopped it, in the first five.** Each naive metric
loads, plans and returns the corpus's wrong number with nothing reported. The vocabulary is
the reason and it is a closed one: `MetricMeta` accepts `name`, `dialect`, `expression`,
`description` and `owner`, the `MODEL` block's key set is closed too, and each bundle's
`observed.txt` ends with SQLMesh refusing an invented key — `already_aggregated`,
`already_a_rate`, `denominator_rows` on a metric, `non_additive_dimension` and `time_zone` on
a model. `expression` says what SQL to run and `dialect` says which SQL it is; neither says
what the number means, so there is no claim for SQLMesh to check.

**One native runtime check does fire, and it does not move a cell.** `009`'s bundle declares a
built-in `accepted_range` audit on `parcels`, and it fails on the cancelled shipment in both
the plan and `sqlmesh audit`. The cell stays `NOT-REPRESENTED` because what the audit rejects
is a legitimate row rather than a wrong metric: it fires identically whichever of the two
readings the project asked for, and satisfying it means deleting real data. The run is in
`observed.txt` and the reasoning is in that bundle's `sources.md`, so a reader who weighs it
differently can see exactly what was run. Note also that neither the MetricFlow nor the dbt
Core column was measured against its own test surface, so this is a difference in what was
run, not a difference between the systems.

Two smaller findings are recorded rather than reasoned about. A metric whose expression is a
compound of aggregates — `SUM(a) / SUM(b)` in one block instead of two — renders SQL DuckDB
refuses at this version, so a ratio is written as a derived metric; `009`'s `observed.txt`
carries the refusal. And `cron_tz` and an incremental kind's `time_column`, the two keys that
read as though they might carry a zone, were read: the first is about when a model runs, the
second pairs a column with a format string.

**Of the seven later cases, the correct readings are native wherever a metric names the model
that stores its column.** `001`'s rollup, `006`'s two grains, `007`'s and `012`'s distinct
counts and `010`'s revenue per order are each a bare aggregate the rewriter places in a
subquery over its own model before any join. `003`'s `anchored` and `004`'s `converted` are
`CUSTOM`: an as-of predicate and a dated rate join, each in a model the author wrote, which
SQLMesh plans without knowing what it selects.

**Their wrong readings went unchallenged too, and the probes say why.** A fan-out in an
author-written model (`001`, `010`), a history joined on its business key (`003`), euros
added to dollars (`004`), summed daily distinct counts (`007`, `012`) — each loads, plans and
returns the corpus's wrong number. `unit` on a metric, and `currency` and `additive` on a
model, are refused as invented keys. `grain` states which columns identify a row, not where
each other column originates.

**Where SQLMesh builds a join itself, two runs render SQL that does not answer.** Asked for
`001`'s shipping by line, the rewriter compares an order key with the line model's composite
grain, and DuckDB's binder refuses it; asked for `010`'s revenue by promotion, it joins on the
wrong pair of columns and returns an unlabelled total. Neither is a grain check, and neither
cell reads it as one: `001`'s `refinement` stays `UNKNOWN` because no number came back, and
`010`'s `bridged` rests on the author-written bridge-grain model, as the bundle maps it.

**The comparison is between vocabularies, here too.** bloomery's `NATIVE-PREVENT` rows
against this column's `NOT-REPRESENTED` ones are not a diligence gap: bloomery's spec
*requires* the declaration — of additivity, of the rows a ratio is over, of the zone a wall
clock was written in, of the grain a value originates at, of a column's currency, of the
interval a version is valid over — so there is a claim on the page that can be false and
therefore refused, while a SQLMesh project states a SQL expression and has made no claim to be wrong
about. And this column's `NATIVE-PLAN` cells against dbt Core's `CUSTOM` ones are a fact about
which package renders the SQL in the configuration measured. What the rows compare is which
facts each system makes an author state, not which system is more diligent about facts they
both hold.

**What this column does not cover is `UNKNOWN` and stays that way.** Tobiko Cloud, SQLMesh's
linter rules, its dbt adapter and any engine other than DuckDB were not run: none has a
bundle, so none has a cell. Nor were the SCD type-2 model kinds, which `003`'s bundle names
as unrun.

## Where bloomery loses

**No rows, at the time of writing** — including after the seven cases measured on
2026-09-29, where no column's cell is better than bloomery's. The nearest is `003`'s
`anchored`, where MetricFlow's `natural` entity plans the as-of join as natively as bloomery
does. That is a statement about this corpus and nothing wider: it holds over twelve cases
somebody chose, and the next case added is as likely to
open a gap as to close one. A matrix with an empty column here is a matrix whose cases have
been answered, not a compiler that cannot be wrong.

Two rows sat here and both moved, which is what the column is for:

- **`011-timezone-boundary` / `zoneless`** — now `NATIVE-PREVENT` (S-0076 R018).
- **`009-null-denominator` / `declared`** — now `NATIVE-PREVENT` (S-0077 R019), and the
  case gained an `inclusive` arm: `4.00` was the wrong answer to "what does it cost to move
  a parcel" and is the right one to a question an author can now write down.

Each was pinned `unguarded` while it was open, so the wrong number was asserted rather than
tolerated, and the row is what made the gap citable until the rule landed.

One caveat sits beside a win rather than in a row. `001`'s `refinement` refusal reads an
operand's home entity from the catalog, so a project compiled without one gets no refusal
and the fan-out compiles clean (the case's `problem.md`). MetricFlow's refusal of the same
line-grain derivation through normalized models reads entity types and needs no catalog.
