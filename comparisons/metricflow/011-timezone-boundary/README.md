# MetricFlow × 011-timezone-boundary

- **System:** MetricFlow `0.212.0`, driven from Python against DuckDB `1.5.5`.
- **Checked:** 2026-09-18.
- **Feature set:** semantic models with `measures`, time dimensions with `expr`, and a
  `filter` on a `simple` metric's input measure
  (`metricflow_semantic_interfaces/parsing/schemas.py`). The zone conversion is
  project-authored DuckDB SQL inside a dimension's `expr`, because nothing else was found to
  carry it — see `sources.md`.
- **Hosted features:** none. Everything here runs from the installed package against a local
  DuckDB; no dbt Cloud or dbt Semantic Layer service is involved.
- **Case:** [`tests/fixtures/semantic_corpus/011-timezone-boundary`](../../../tests/fixtures/semantic_corpus/011-timezone-boundary) —
  its schema and rows are read directly, so the two cannot drift.

## The exact question

`placed_at` is a local wall clock published as a string with no zone on it; the store runs
on `America/New_York`, which is a fact about the source system and appears nowhere in its
data. **Using MetricFlow's documented feature set, is a February total that reads the wall
clock as if it were UTC prevented before it returns a number — and if it is not, what does
reaching the right number cost?**

| Metric | How it is modelled | What it should return |
|---|---|---|
| `february_revenue_zoneless` | `agg: sum` over `revenue`, filtered on a time dimension whose `expr` is `CAST(placed_at AS TIMESTAMP)` | the wrong answer, `40.00` |
| `february_revenue_anchored` | the same sum and the same filter, over a time dimension whose `expr` appends `AT TIME ZONE 'America/New_York' AT TIME ZONE 'UTC'` | the right one, `140.00` |

Both measures sit in the **same semantic model** over the same column and differ only by that
suffix, which is what makes the comparison about the zone rather than about the aggregation.
The second conversion is what makes the bundle reproducible: it hands back a UTC wall clock,
so the February bounds compare the same way whatever the session's time zone is.

## What was observed

MetricFlow's own `SemanticManifestValidator` reports **0 errors, 0 warnings** for the
manifest containing both. `february_revenue_zoneless` returns `Decimal('40.00')`;
`february_revenue_anchored` returns `Decimal('140.00')`. Full transcript in `observed.txt`.
Both match the corpus's `expected/result.json`.

## What that supports, and what it does not

**The right number is reachable, and only as SQL.** What makes
`february_revenue_anchored` correct is a dialect-specific expression the author wrote:
`AT TIME ZONE 'America/New_York' AT TIME ZONE 'UTC'`, passed through as an opaque `expr`.
MetricFlow does not supply it, does not know it is a zone conversion, and would render the
same plan around any other string. Nothing in the manifest vocabulary names a zone —
`time_zone` and `timezone` do not appear anywhere in `metricflow_semantic_interfaces`, and a
time dimension's `type_params` is a closed object whose only keys are `time_granularity` and
`validity_params` (`sources.md`). That is why the `anchored` row is `CUSTOM` rather than
`NATIVE-PLAN`: the semantics live in project-authored SQL, not in a declaration.

**Nothing marks the zoneless one as an assertion.** The two time dimensions are equally
valid to `0.212.0`'s validator, and the one that silently reads a New York wall clock as UTC
is the shorter of the two to write. `o1` lands in January, February reports `40.00`, and
there is no declaration that was omitted — the claim "this wall clock is UTC" is made by the
absence of a conversion, which is the one place a claim cannot be checked.

That is what `NOT-REPRESENTED` names for the `zoneless` row: the fact whose absence would
make the bare cast refusable — *this column is a wall clock, written in this zone* — has no
place in the manifest to be stated.

Neither half is a statement about MetricFlow beyond `0.212.0` and this configuration, and
the `CUSTOM` half is a DuckDB claim: which dialects agree on a named-zone conversion is a
separate question this bundle did not ask. It says nothing about whether a dbt test or a
review convention would catch the zoneless dimension — only that the semantic layer itself
does not.
