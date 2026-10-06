# Plan a metric request

Turn a structured request ("revenue by month for these countries") into SQL that is
correct at the requested grain, or a typed refusal when it cannot be. The planner renders
through an embedded MetricFlow and executes nothing: you get SQL, its columns and its
provenance, and running it is yours. Requests are served from wide marts, so the project
needs a mart carrying each stored measure a request reads; a ratio or `derived:` metric is
answered from the marts carrying its inputs, aggregated on each and combined over the join
(see [marts](marts.md)).

## From the command line

```console
$ bloomery explain specs/ --metrics gross_revenue --by ordered_month --limit 5
$ bloomery explain specs/ --metrics gross_revenue --where '{"customer_id": {"$neq": "internal"}}'
$ bloomery explain specs/ --metrics gross_revenue --by ordered_day --grain month --policy 'country eq FR'
```

It prints the SQL, the provenance per metric, the **evidence** the plan rests on (each
fact `LOCKED`, written in a spec, or `ASSUMED`, derived by the compiler) and the derivation.
`--where` takes the JSON filter document below; `--policy` is `dimension op value`,
comma-separated values for `in`/`not_in`; `--dialect` picks the SQL dialect; `--format json`
emits what the Python call returns.

## Build the planner once

The planner works on the compiled IR and gets MetricFlow manifests through an in-process
LRU hydrator, rebuilt whenever the specs, bloomery or MetricFlow change:

```python
from bloomery import DefaultNaming, LruManifestHydrator, MetricFlowPlanner, build_project_ir

ir = build_project_ir(project, catalog=catalog)

naming = DefaultNaming()
planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
```

- `naming` must be the policy the artifacts were emitted with: it shapes the gold relation
  names in the SQL.
- Build once and reuse, across threads too; the cache makes repeat planning cheap. To
  persist manifests, pass `fetch_l2=` to the hydrator: it is called concurrently, must be
  thread-safe, and must return bytes stored under exactly the key it was handed.
- `MetricFlowPlanner(..., max_limit=50000, default_limit=None)`: a larger `limit` is
  clamped with a warning.
- When specs change, hand the new IR to the same planner; it is a new cache key.

## Make a request

A request is structured data, with no SQL string a caller could inject into:

```python
from bloomery import AnyOf, MetricRequest, Op, OrderSpec, Predicate, TimeGrain

request = MetricRequest(
    metrics=("revenue",),
    dimensions=("country", "ordered_day"),
    filters=(
        Predicate(dimension="country", op=Op.IN, values=("FR", "DE")),
        AnyOf((Predicate("region", Op.EQ, ("EU",)), Predicate("region", Op.EQ, ("UK",)))),
    ),
    time_grain=TimeGrain.MONTH,
    order_by=(OrderSpec(field="revenue", direction="desc"),),
    limit=100,
)
plan = planner.plan(ir, request, dialect="duckdb")
```

Construction raises `InvalidRequest` on: no metric, a duplicate, `order_by` over a member
not requested, `limit < 1`, or an operator whose values have the wrong arity.
`time_grain` re-buckets every date-role dimension: `ordered_day` at `MONTH` groups by
`ordered_month`. `TimeGrain.HOUR` is refused, since marts bucket day to year only.

**Filters are CNF.** Clauses AND together; each is one `Predicate` or one `AnyOf` group,
exactly one level of OR. Operators: `eq ne gt gte lt lte in not_in is_null like ilike`.

- `is_null` takes one bool: `(True,)` is `IS NULL`, `(False,)` is `IS NOT NULL`.
- `like`/`ilike` take SQL `LIKE` patterns, OR-ed; wildcards are yours (`%needle%`), with
  `\%`, `\_`, `\\` escaping. Nothing is auto-wrapped.
- A range is `gte` and `lte` as two clauses; there is no `between`.
- Float values become `Decimal(str(value))`; `NaN`/`Infinity` raise `InvalidLiteral`.

**The JSON front door** (`--where`, and `parse_filter_json` in `bloomery.planner`) takes a
Mongo-flavoured document: field maps, `$and $or $not`, `$eq $neq $gt $gte $lt $lte $in
$nin $null $like $ilike`. A scalar means `$eq`, an array `$in`, `null` `is_null: true`.
It normalizes (De Morgan, complement inversion, CNF distribution with a clause cap)
before refusing:

```json
{"carrier": {"$in": ["DHL", "UPS"]}, "$or": [{"region": "EU"}, {"region": "UK"}]}
```

What cannot cross raises `UnsupportedFilter` with a stable `.reason` from the closed list
`KNOWN_UNSUPPORTED` (`$regex` and other text operators, set relations, over-cap expansions).
Offsets and cursors are not filters: `parse_page_json`, the pagination parser, refuses them
from the same list as `unsupported_pagination`. A malformed document (wrong shape, unknown
`$op`) is `InvalidRequest` instead.

## Row policies

Row-level scoping is a typed filter, prepended to the user's filters and reaching every
scan of the mart. Deciding *whose* policy applies stays upstream of bloomery:

```python
from bloomery import MetricRequest, Op, RowPolicy

plan = planner.plan(
    ir,
    MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
    dialect="duckdb",
    policy=RowPolicy(dimension="country", op=Op.EQ, value="FR"),
)
```

The explanation then reads `policy:   applied`. An `AnyOf` is always parenthesized, so a
disjunction cannot leak past the policy.

## What comes back

| `QueryPlan` field | Carries |
|---|---|
| `sql` | SQL text, runnable as-is on the requested dialect |
| `columns` | one `ColumnDescriptor` per output column: `name` (bloomery's vocabulary), `sql_alias` (what the SQL projects), `type`, `role`, optional `label`; bind rows by `sql_alias`, render `name` |
| `mart`, `marts` | the serving mart; every mart read, one per branch across grains |
| `warnings` | a clamped `limit`, a `time_grain` with nothing to apply to |
| `explanation` | deterministic provenance; `explanation.render()` prints it |
| `fingerprint` | `sha256(sql)`: identical requests over identical specs give the same value, so it identifies the query; a result cache keys on it together with the data's freshness |
| `semantic` | the derivation: each step and the proof admitting it; `render()`, `proofs`, `serialize()` |

```text
revenue
  mart:     gold.mart_orders (grain: order)
  measure:  revenue = SUM(amount)
            [additive — SUM]
  filters:  country in ('FR', 'DE')
  policy:   not applied
```

Run `plan.sql` on your own connection, pair rows with `plan.columns`, and cache by
`plan.fingerprint`. A non-additive ratio is planned from its additive components, never
read from storage (see [metrics](metrics.md)).

## Across grains

Measures on different marts are not automatically refused. Where every requested
dimension is the same dimension on each mart, each measure aggregates on its own mart and
the results join; `marts` names each and the explanation prints a `branch:` line per mart.
Filters and the policy apply on **every** branch in its own spelling; one a branch cannot
evaluate refuses the whole request (`filter ... does not reach every branch`). A metric's
own `filter:` restricts only its measure. Ratios and `derived:` metrics compute once above
the join; a `derived:` whose inputs are restricted differently is `RatioOperandsDisagree`.

## Refusals

All subclass `PlannerError`; the first failure wins.

| Error | When |
|---|---|
| `UnknownMember` | a name that does not exist: `unknown metric 'revenu'; did you mean 'revenue'?` |
| `UnreachableAtGrain` | no mart carries the metric at that grain; define one that does |
| `AmbiguousDimension` | `'month' has roles ['ordered', 'shipped']`: ask `ordered_month` |
| `FilterTypeMismatch` | a filter value contradicting the column type, before SQL renders |
| `InvalidRequest`, `UnsupportedFilter` | structure, and the closed vocabulary above |

See [errors-and-refusals](errors-and-refusals.md) for reading any bloomery refusal.

Documentation: [plan a metric request](https://morzecrew.github.io/bloomery/latest/how-to/plan-a-metric-request/).
