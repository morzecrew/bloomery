# MetricFlow × 007-distinct-users-fanout

- **System:** MetricFlow `0.213.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-29.
- **Feature set:** semantic models with `measures` including `agg: count_distinct`, and
  `simple` metrics requested with and without a `metric_time` group-by
  (`metricflow_semantic_interfaces/parsing/schemas.py`). The per-day counts are
  project-authored SQL in `config/setup.sql` — see below.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/007-distinct-users-fanout`](../../../tests/fixtures/semantic_corpus/007-distinct-users-fanout) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`active_users` is a distinct count, and two days' distinct users do not add up to the
period's. **Using MetricFlow's documented feature set, is a total that adds per-day distinct
counts prevented before it returns a number, and does the distinct count plan correctly at
each grain?**

| Request | How it is modelled | What it should return |
|---|---|---|
| `active_users` | `agg: count_distinct` over `user_id` | `declared`: `3` |
| `active_users/metric_time__day` | the same, by day | `2` and `2` |
| `active_users/metric_time__month` | the same, by month | `3` |
| `active_users_summed_daily` | `agg: sum` over `daily_users` on `daily_active_users`, a view of per-day counts | `naive`: the wrong answer, `4` |

The corpus's `naive` spec is an *additivity claim* over a distinct count. A measure has no
key that claims additivity (`sources.md`), so there is no way to make that claim about the
`count_distinct` measure; the reachable form of the same arithmetic is a relation of
per-day counts summed as an ordinary column, which `config/setup.sql` builds from the case's
sessions.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings**. Full
transcript in `observed.txt`.

- `active_users` returns `3`; by day `2` and `2`; by month `3`. The month is not the sum
  of the days: the distinct count is recomputed from the sessions at each grain requested.
- `active_users_summed_daily` returns `4` — the corpus's `naive` number.

## What that supports, and what it does not

**The distinct count is native and right at every grain asked.** A `count_distinct`
measure is aggregated from the rows of its own model at the requested grain, so the month
never re-adds the days.

**Summing stored per-day counts is accepted.** Once the counts are a column of another
relation, they are numbers to MetricFlow, and `agg: sum` over them validates clean. No key
records that a column is already a distinct count over some identity, so nothing can notice
that summing it is meaningless. Reaching the wrong answer needs project SQL here; nothing in
the manifest refuses it once written.

Neither half is a statement about MetricFlow beyond `0.213.0` and this configuration. It
says nothing about whether a dbt test or a review convention would catch the summed view —
only that the semantic layer itself did not, here.
