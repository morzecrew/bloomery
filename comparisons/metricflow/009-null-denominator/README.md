# MetricFlow × 009-null-denominator

- **System:** MetricFlow `0.212.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** semantic models with `measures`, a `simple` metric, a `ratio` metric, and
  a `filter` on a ratio's input measures
  (`metricflow_semantic_interfaces/parsing/schemas.py`). No project-authored SQL.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/009-null-denominator`](../../../tests/fixtures/semantic_corpus/009-null-denominator) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`carrier_cost` and `parcels` are both additive facts about a shipment, and `s3` was
cancelled after the carrier charged for it: 40.00 of cost against 0 parcels. Sum over sum is
the right *shape* for a ratio and the wrong *set of rows*. **Using MetricFlow's documented
feature set, can each of the two readings be stated, and is the one that answers "what did
it cost to ship a parcel" reachable without the author already knowing the trap is there?**

| Metric | How it is modelled | What it should return |
|---|---|---|
| `cost_per_parcel_inclusive` | `type: ratio`, numerator `carrier_cost`, denominator `parcels` | the overheads-included reading, `4.00` |
| `cost_per_parcel_restricted` | the same ratio, both inputs carrying `filter: "{{ Dimension('shipment__moved_parcels') }}"` | the per-parcel reading, `3.00` |
| `cost_per_parcel_filled` | the same ratio with `fill_nulls_with: 0` on the denominator | — it is here to be measured, not to be right |

The third metric is the reason this bundle exists rather than an inspection of the schema.
`fill_nulls_with` is the key in the manifest whose name reads as if it were about this case;
declaring it is the only way to record what it actually does here.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing all three. `cost_per_parcel_inclusive` returns `4.0`;
`cost_per_parcel_restricted` returns `3.0`; `cost_per_parcel_filled` returns `4.0`. Full
transcript in `observed.txt`.

The first two are the corpus's own numbers: `expected/result.json` pins `4.00` for the naive
reading and `3.00` for the correct one, so both readings are reproduced exactly.

## `fill_nulls_with` does nothing here, and that is a measurement

`fill_nulls_with: 0` on the denominator changes the answer by nothing: `4.0` with it and
`4.0` without. It is not a near miss. The key fills the gaps a time-spine join opens —
periods with no rows — with a value (`metricflow_semantic_interfaces/protocols/metric.py`,
`fill_nulls_with`, beside `join_to_timespine`); this case has no null and no missing period.
`parcels` is `0` because the count is known and it is none, and `SUM` over three present
rows is 40 either way. A key that is about absent rows has nothing to say about a present
row that does not belong.

## What that supports, and what it does not

**Both readings are representable, and one of them is reachable by accident.** A `ratio`
metric returns the overheads-included number with nothing declared; the same metric with a
`filter` on each input measure returns the per-parcel number. `filter` is a documented key
on a metric's input measure, so the restriction is native — it does not need
project-authored SQL, only a dimension over the case's own column.

**Nothing marks the unfiltered one as the other question.** The two metrics sit in one
manifest over one pair of measures and differ only by the two filters; to `0.212.0`'s
validator they are equally valid, and neither is annotated as being about a different row
set. An author who has not already seen `s3` writes the first one, gets `4.00`, and is told
nothing.

That is what `NOT-REPRESENTED` names for the `declared` row: not that the restriction cannot
be expressed — it plainly can — but that the fact which would make the unrestricted ratio
refusable, *this ratio is over rows whose denominator is zero*, has no place in the manifest
to be stated, so nothing can be wrong about it and nothing can refuse it.

It does **not** support any statement about MetricFlow beyond this configuration and this
version, and nothing at all about whether a dbt test, a `saved_query` or a reviewer would
catch the unfiltered ratio — only that the semantic layer itself does not.
