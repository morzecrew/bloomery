# dbt Core × 009-null-denominator

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here
  measures, a categorical dimension, `simple` metrics and two `ratio` metrics, one of them
  with a `filter` on each input. Commands run: `dbt build`, `dbt list`, `dbt compile`,
  `dbt parse`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement.
- **Case:** [`tests/fixtures/semantic_corpus/009-null-denominator`](../../../tests/fixtures/semantic_corpus/009-null-denominator) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

One of three shipments was cancelled after the carrier had charged for it: it cost `40.00`
and moved no parcels. Cost per parcel over all three rows is `4.00`; over the rows that moved
something it is `3.00`. Both are answers to questions somebody might ask, and the quotient
does not say which. **Using dbt Core's documented feature set, is a ratio that does not state
which rows it is over prevented before it returns a number — and what does dbt Core itself
produce for either reading?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `cost_per_parcel_inclusive` | `type: ratio`, cost over parcels, every row | `4.00` |
| `cost_per_parcel_restricted` | the same ratio with `filter: "{{ Dimension('shipment__moved_parcels') }}"` on both inputs | `3.00` |

## What was observed

`dbt build` finds **4 metrics and 1 semantic model** and completes with `PASS=4 WARN=0
ERROR=0`. dbt's parse-time semantic validation (`dbt/contracts/graph/semantic_manifest.py`)
reports nothing about either ratio: the one that says which rows it is over and the one that
does not are equally acceptable to it.

`dbt compile --select metric:cost_per_parcel_inclusive` and the same for the other three
metrics render **no SQL** — `Nothing to do.` dbt Core parses metrics, lists them and writes
them to the manifest; the engine that turns one into a query ships separately.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`4.0` for the inclusive reading and `3.0` for the restricted one. Both are the corpus's own —
`expected/result.json` pins `4.00` and `3.00`.

The probe is the last line, and it is the one place this column differs from MetricFlow's at
the version each pins. `fill_nulls_with: 0` on a ratio metric's denominator — the key
MetricFlow `0.212.0` accepted in the same position, changing nothing — is refused by dbt Core
`1.12.3`'s parser:

```text
Parsing Error: at path ['type_params']['denominator']:
{'name': 'parcels', 'fill_nulls_with': 0} is not valid under any of the given schemas
```

## What that supports, and what it does not

It supports three cells. Which rows a ratio is over is **not a fact the ratio carries** in
this feature set: it is expressed, if at all, as a filter the author writes on each input, so
a ratio that states nothing is not a claim dbt declines to check — it is not a claim at all.
That is the `declared` row. Both the inclusive and the restricted readings were reached
**only through project-authored SQL**, because in this configuration no dbt Core command
renders a metric, so both are `CUSTOM` rather than `NATIVE-PLAN`.

It does **not** support any statement about dbt beyond this configuration and this version —
in particular, the probe says what dbt Core `1.12.3`'s parser does with `fill_nulls_with` in
the denominator position of a `ratio` metric, and nothing about the key elsewhere or at
another version. It says nothing about dbt Core with `dbt-metricflow` installed, or about the
dbt Semantic Layer service: neither was run here.
