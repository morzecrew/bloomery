# SQLMesh × 005-semi-additive-balance

- **System:** SQLMesh `0.236.1`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-18.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, two `MODEL (...)`
  blocks with `grain` and `references`, and two `METRIC (...)` blocks. Commands run: `sqlmesh
  info`, `sqlmesh plan --auto-apply`, `sqlmesh audit`, `sqlmesh rewrite`.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/005-semi-additive-balance`](../../../tests/fixtures/semantic_corpus/005-semi-additive-balance) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`bronze.corpus__balances` is a daily snapshot: one row per account per day, carrying that
day's balance. A balance is additive across accounts and not across days. **Using SQLMesh's
documented feature set, is a metric that sums the column across both axes prevented before it
returns a number — and what does it take to get the right one?**

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `total_balance_naive` | `SUM(silver.balances.balance)` | the wrong answer, `320.0000` |
| `total_balance_declared` | `SUM(...)` over `silver.latest_balances`, a model that selects the last day | the right one, `170.0000` |

## What was observed

`sqlmesh info` finds **2 models**, the plan applies both, and `sqlmesh audit` finds **0
audits**: nothing in the project distinguishes the two metrics, and nothing is reported about
either. `sqlmesh rewrite` renders both, and the rendered SQL is a single `SUM` over one model
in each case. The numbers are the corpus's own: `320.0000` and `170.0000`.

The difference between the two cells is where the day was selected. `total_balance_declared`
reads `silver.latest_balances`, which is a model this project's author wrote:

```sql
SELECT account_id, as_of_day, balance
FROM silver.balances AS b
WHERE b.as_of_day = (SELECT MAX(as_of_day) FROM silver.balances)
```

The probe is the last line of `observed.txt`. Adding a `non_additive_dimension` key to the
`MODEL` block — the fact that would make the naive metric refusable, and the name MetricFlow
gives it — is rejected by SQLMesh's own loader:

```text
Error: Failed to load model from file '<scratch>/probe/models/balances.sql':: Invalid field
name present in the MODEL block: 'non_additive_dimension'
```

so the `MODEL` key set is closed too, and the absence is a property of the vocabulary rather
than of the search.

## What that supports, and what it does not

It supports two cells. The fact that a measure is **non-additive across one axis** has no
representation in this feature set: `MetricMeta` carries `name`, `dialect`, `expression`,
`description`, `owner`, and `ModelMeta`'s keys describe scheduling, storage, grain,
references, audits and columns — none of them says how a column may be aggregated. And the
right number was reached here **only through project-authored SQL**: a model whose `WHERE`
clause performs the reduction, which SQLMesh plans and materialises without knowing that the
reduction is what makes the metric correct.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. A different project could put the same reduction in a window function, in an
`INCREMENTAL_BY_TIME_RANGE` kind, or in the metric's own expression; all three are the same
kind of author-written SQL, and none of them was run here.
