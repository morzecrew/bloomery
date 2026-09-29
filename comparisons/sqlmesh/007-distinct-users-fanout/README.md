# SQLMesh × 007-distinct-users-fanout

- **System:** SQLMesh `0.236.2`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-29.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, two `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`, the last for each
  metric alone and for the distinct count grouped by day.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/007-distinct-users-fanout`](../../../tests/fixtures/semantic_corpus/007-distinct-users-fanout) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Three users over two days, and one of them is active on both days. **Using SQLMesh's
documented feature set, is a metric that adds daily distinct counts prevented before it
returns a number — and what does SQLMesh produce for the distinct count itself?**

| Request | How it is modelled | The corpus's number |
|---|---|---|
| `active_users_summed` | `SUM(silver.daily_users.daily_users)`, over a daily pre-aggregate the author wrote | the wrong answer, `4` |
| `active_users` | `COUNT(DISTINCT silver.sessions.user_id)` | the right one, `3` |
| `active_users_by_day` | `active_users` grouped by `session_day` | — |

## What was observed

`sqlmesh info` finds **2 models**, the plan applies them, and `sqlmesh audit` finds **0
audits**. `active_users_summed` returns `4` and `active_users` returns `3`, the corpus's two
numbers. Nothing in the load, the plan or the audit distinguishes them.

Grouped by day, the rewriter computes `COUNT(DISTINCT user_id)` over the sessions for each
day and returns `2` and `2`. The distinct count is computed from the rows at whatever grain
the request asks for. It is not rolled up from a finer result, because the metric names the
sessions model and no pre-aggregate is read in its place.

The probe is the last line. An `additive` key on the daily model, which would state that
its `daily_users` column may not be summed across days, is rejected by SQLMesh's own loader:

```text
Error: Failed to load model from file '<scratch>/probe/models/daily_users.sql':: Invalid
field name present in the MODEL block: 'additive'
```

## What that supports, and what it does not

For the **naive** reading it supports `NOT-REPRESENTED`. The daily column is correct for its
day and nothing states that it is a distinct count. `SUM` over it is a legal aggregate that
loads, plans and audits clean, and the probe shows the `MODEL` key set has no slot for the
fact.

For the **declared** reading it supports `NATIVE-PLAN`. `COUNT(DISTINCT ...)` is a bare
aggregate of a model column, and SQLMesh renders it from the rows at each grain it was asked
for.

It does **not** support any statement about SQLMesh beyond this configuration and this
version, and nothing here was run against Tobiko Cloud, another engine, or the linter.
