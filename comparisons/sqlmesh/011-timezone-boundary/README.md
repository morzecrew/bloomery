# SQLMesh × 011-timezone-boundary

- **System:** SQLMesh `0.236.1`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-18.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, two `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/011-timezone-boundary`](../../../tests/fixtures/semantic_corpus/011-timezone-boundary) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

The source publishes a local wall-clock timestamp with no zone on it; the store runs on
`America/New_York`. `o1` was placed at 21:30 on 31 January local, which is 02:30 on 1
February UTC. **Using SQLMesh's documented feature set, can the zone a wall clock was written
in be stated — and what does February's revenue come to either way?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `february_revenue_zoneless` | a February window over `silver.orders.placed_at`, taken at face value | the wrong answer, `40.00` |
| `february_revenue_anchored` | the same window over `silver.orders_anchored.placed_at_utc` | the right one, `140.00` |

## What was observed

`sqlmesh info` finds **2 models**, the plan applies both, and `sqlmesh audit` finds **0
audits**. Both metrics load and render, and both return the corpus's numbers: `40.00` and
`140.00`. Nothing distinguishes the two: one compares a `TIMESTAMP` against `TIMESTAMP`
literals and the other a `TIMESTAMPTZ` against `TIMESTAMPTZ` literals, and both are
well-typed SQL SQLMesh has no opinion about.

What makes the anchored one right is a line in a model this project's author wrote:

```sql
placed_at AT TIME ZONE 'America/New_York' AS placed_at_utc
```

a dialect-specific conversion SQLMesh parses, renders and materialises without knowing it is
a zone conversion or that the column it produces denotes a different instant from the one
beside it.

The probe is the last line. Adding a `time_zone` key to the `MODEL` block — the fact that
would make the zoneless reading refusable — is rejected by SQLMesh's own loader:

```text
Error: Failed to load model from file '<scratch>/probe/models/orders.sql':: Invalid field
name present in the MODEL block: 'time_zone'
```

The nearest keys in the vocabulary were read rather than guessed at, and neither is about
data: `cron_tz` is the zone a model's **schedule** is interpreted in, and the `time_column` of
an incremental kind carries a column and a **format string**, with no zone in either.

## What that supports, and what it does not

It supports two cells. The fact that a stored wall clock **was written in a particular zone**
has no representation in this feature set: `ModelMeta`'s keys describe scheduling, storage,
grain, references, audits and columns; `MetricMeta`'s five carry a SQL expression and its
dialect; the probe shows an invented key is refused. And the right number was reached here
**only through project-authored SQL**, in a model.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. A project could convert in the metric's expression or in an upstream ingest instead;
both are the same kind of author-written SQL, and neither was run here.
