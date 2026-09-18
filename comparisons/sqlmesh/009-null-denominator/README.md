# SQLMesh × 009-null-denominator

- **System:** SQLMesh `0.236.1`, against DuckDB `1.5.5` through its `duckdb` gateway.
- **Checked:** 2026-09-18.
- **Feature set:** a SQLMesh project — `config.yaml` with one gateway, one `MODEL (...)` block
  with `grain`, `references` and a built-in `accepted_range` audit, and six `METRIC (...)`
  blocks, two of them derived. Commands run: `sqlmesh info`, `sqlmesh plan --auto-apply`,
  `sqlmesh audit`, `sqlmesh rewrite`.
- **Hosted features:** none, and none involved. Open-source SQLMesh with a local DuckDB
  gateway; no Tobiko Cloud and no scheduler.
- **Case:** [`tests/fixtures/semantic_corpus/009-null-denominator`](../../../tests/fixtures/semantic_corpus/009-null-denominator) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

Three shipments; one was cancelled after the carrier had charged for it, so its `parcels` is
a known zero. A cost per parcel over all three charges the cancelled shipment's cost to the
parcels the other two moved. **Using SQLMesh's documented feature set, can a metric say which
rows its ratio is over — and if not, what does it take to get either answer?**

The case pins three expectations, so this bundle declares three metrics:

| Metric | How it is modelled | The corpus's number |
|---|---|---|
| `cost_per_parcel_inclusive` | a derived metric over `SUM(carrier_cost)` and `SUM(parcels)` | `4.00`, the right answer to the inclusive question |
| `cost_per_parcel_restricted` | the same shape, over operands whose `CASE WHEN parcels > 0` the author wrote | `3.00` |
| `cost_per_parcel_compound` | the restricted ratio as one expression rather than a derived metric | — |

## What was observed

`sqlmesh info` finds **1 model** and the plan applies it. Both ratios load, render and
answer: `4.0` and `3.0`, the corpus's own numbers. Nothing in the project says which of them
the question wanted, and nothing was reported about either.

**The third metric is a limit of this version rather than of the vocabulary.** A metric whose
expression is a compound of aggregates renders a subquery that projects the quotient with no
alias, and the outer select then names it:

```text
refused: BinderException: Binder Error: Column "cost_per_parcel_compound" referenced that
exists in the SELECT clause - but this column cannot be referenced before it is defined
```

So a ratio is written as a derived metric over two aggregate metrics — which is the documented
form and the one both working metrics use — and the alternative is recorded here rather than
left as a guess.

**The audit is the part of this bundle that exists to be measured.** `silver.shipments`
declares a built-in `accepted_range(column := parcels, min_v := 1)`, non-blocking, and it
fires: the plan reports `audits failed 1` and `sqlmesh audit` reports `accepted_range on model
silver.shipments ❌ FAIL [1]`. SQLMesh **can** detect the row at run time, with no SQL written
by this project.

What it detects is the row, not the metric. `s3` is valid data — a real shipment, really
charged for, that really moved nothing — so an audit that fails on it is a constraint saying
the row should not exist, and making it pass means deleting a legitimate shipment. It fires
identically whether the project asks for the inclusive ratio, the restricted one, both, or
neither, and it says nothing about which of them a request meant. The cell is therefore
`NOT-REPRESENTED` rather than `RUNTIME-DETECT`: the run is in `observed.txt` and a reader who
weighs it differently has the evidence in hand.

The probe is the last line. Adding `denominator_rows 'parcels > 0'` to the inclusive metric —
the fact that would let the two readings be told apart — is rejected by SQLMesh's own loader:

```text
Error: 1 validation error for MetricMeta: denominator_rows Extra inputs are not permitted
```

## What that supports, and what it does not

It supports three cells. The fact that a ratio is **over a particular set of rows** has no
representation in this feature set: `MetricMeta`'s five keys carry no such slot, and the probe
shows a sixth is refused. The inclusive reading is reached **natively**, by SQLMesh's derived
metric. The restricted one is reached **only through project-authored SQL** — the `CASE WHEN`
in each operand — which SQLMesh carries through without knowing it is the ratio's row set.

It does **not** support any statement about SQLMesh beyond this configuration and this
version. A project could express the restriction in a model instead, or add a blocking audit
that refuses the load; neither changes which fact the metric vocabulary can state, and neither
was run here.
