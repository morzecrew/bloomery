# dbt Core × 011-timezone-boundary

- **System:** dbt Core `1.12.3`, with the `dbt-duckdb` `1.11.0` adapter against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** a dbt project — `sources:`, models, and the `semantic_models:` and
  `metrics:` blocks dbt parses into its manifest (`dbt/contracts/graph/unparsed.py`), here two
  time dimensions with `expr`, two measures, and a `simple` metric with a `filter` on its
  input measure. Commands run: `dbt build`, `dbt list`, `dbt compile`, `dbt parse`.
- **Hosted features:** none, and none reachable. `dbt-metricflow` is not installed and no dbt
  Cloud or dbt Semantic Layer service is involved, so nothing here queries a metric. What dbt
  Core alone does with the definitions is the whole measurement.
- **Case:** [`tests/fixtures/semantic_corpus/011-timezone-boundary`](../../../tests/fixtures/semantic_corpus/011-timezone-boundary) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`corpus__orders.placed_at` is a local wall clock with no zone on it. The store runs on
`America/New_York`, which is written in the source system's documentation and nowhere in its
data: an order placed at 21:30 on 31 January local is a February order in UTC. **Using dbt
Core's documented feature set, is a metric that reads the wall clock at face value prevented
before it returns a number — and what does dbt Core itself produce for either reading?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `february_revenue_zoneless` | a time dimension over `cast(placed_at as timestamp)` | the wrong answer, `40.00` |
| `february_revenue_anchored` | a time dimension whose `expr` carries the zone conversion | the right one, `140.00` |

## What was observed

`dbt build` finds **2 metrics and 1 semantic model** and completes with `PASS=4 WARN=0
ERROR=0`. The two time dimensions differ only by a dialect-specific string inside `expr`, and
dbt's parse-time semantic validation (`dbt/contracts/graph/semantic_manifest.py`) has nothing
to say about either.

`dbt compile --select metric:february_revenue_anchored` and the same for the zoneless metric
render **no SQL** — `Nothing to do.` dbt Core parses metrics, lists them and writes them to
the manifest; the engine that turns one into a query ships separately.

The two numbers in `observed.txt` therefore come from **models this project's author wrote**:
`40.00` for the face-value reading and `140.00` for the anchored one, the second carrying
`at time zone 'America/New_York' at time zone 'UTC'` in its `where` clause. Both are the
corpus's own.

The probe is the last line. Declaring the zone where a time dimension's granularity is
declared — `time_zone: America/New_York` — is rejected by dbt's own parser:

```text
Parsing Error: at path ['dimensions'][0]['type_params']:
{'time_granularity': 'day', 'time_zone': 'America/New_York'} is not valid under any of the
given schemas
```

## What that supports, and what it does not

It supports two cells. The zone a stored wall clock was written in has **no representation**
in this feature set: `UnparsedDimensionTypeParams` carries `time_granularity` and
`validity_params`, the probe shows a third key is refused, and a zoneless timestamp is
therefore indistinguishable from an anchored one to anything reading the manifest.

The right answer was reached **only through project-authored SQL** — and twice over. No dbt
Core command renders a metric in this configuration, so the number comes from a model; and
what makes that model right is a dialect-specific conversion the author wrote, which dbt
passes through without knowing it is a zone conversion. The anchored row is `CUSTOM` on both
counts.

It does **not** support any statement about dbt beyond this configuration and this version.
It says nothing about dbt Core with `dbt-metricflow` installed, or about the dbt Semantic
Layer service: neither was run here. The engine those paths use is MetricFlow, measured in
its own column at `0.212.0`, where this case's anchored row is also `CUSTOM` and for the
second of those two reasons.
