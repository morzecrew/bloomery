# Plan a metric request

You have compiled specs and a built mart, and you want SQL that answers "revenue by
month for these countries" — correct at the requested grain, refused when it cannot be.
The planner turns a structured `MetricRequest` into a `QueryPlan`: SQL text plus
metadata, rendered by an embedded MetricFlow that never executes anything. For a
runnable end-to-end script see
[`examples/quickstart/run.py`](https://github.com/morzecrew/bloomery/tree/main/examples/quickstart);
the [wide-marts](../concepts/wide-marts.md) page explains why requests are served from
one mart with no query-time joins.

## Build the IR and the planner

The planner works on the compiled IR, not on specs, and gets its manifests through a
hydrator — an in-process LRU that rebuilds (or loads caller-supplied bytes) whenever
the specs, the bloomery version, or the MetricFlow version change:

```python
from bloomery import LruManifestHydrator, MetricFlowPlanner, build_project_ir
from bloomery.naming import DefaultNaming

ir = build_project_ir(project, catalog=catalog)

naming = DefaultNaming()
planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
```

Two wiring rules:

- `naming` must be the policy the artifacts were emitted with — it shapes the gold
  relation names in the SQL, the refusals, and the explanations.
- Build the planner once and reuse it: the hydrator's cache is what makes repeated
  planning cheap. If you persist manifests yourself, pass `fetch_l2=` to the hydrator;
  a `None` return falls back to rebuilding from the IR.

## Make a request

A request is structured data — metrics, dimensions, typed filters, a time grain,
ordering, a limit. There is no SQL string anywhere a caller could inject into:

```python
from bloomery import MetricRequest, Op, OrderSpec, Predicate, TimeGrain

request = MetricRequest(
    metrics=("revenue",),
    dimensions=("country", "ordered_day"),
    filters=(Predicate(dimension="country", op=Op.IN, values=("FR", "DE")),),
    time_grain=TimeGrain.MONTH,
    order_by=(OrderSpec(field="revenue", direction="desc"),),
    limit=100,
)
plan = planner.plan(ir, request, dialect="duckdb")
```

Structural rules, enforced at construction with `InvalidRequest`: at least one metric,
no duplicates, `order_by` only over requested members, `limit >= 1`, and filter
operator/value arity coherence. Float filter values are accepted and normalized to
`Decimal(str(value))` at the boundary — no float ever reaches the rendered SQL, and
non-finite values (`NaN`/`Infinity`, float or string form) are refused with
`InvalidLiteral`. `time_grain` re-buckets every date-role dimension in the request —
here `ordered_day` with `TimeGrain.MONTH` groups by the `ordered_month` bucket column.

### Filters are CNF clauses

`filters` is an implicit AND across clauses; each clause is a single `Predicate` or one
`AnyOf` disjunction group — exactly one level of OR, which covers every filter a BI UI
builds ("carrier in [DHL, UPS] **and** (region = EU **or** region = UK)"):

```python
from bloomery import AnyOf, Op, Predicate

filters = (
    Predicate("carrier", Op.IN, ("DHL", "UPS")),
    AnyOf((Predicate("region", Op.EQ, ("EU",)), Predicate("region", Op.EQ, ("UK",)))),
)
```

The operators are `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `is_null`,
`like`, and `ilike`. Three worth knowing:

- `is_null` takes exactly one bool — `(True,)` renders `IS NULL`, `(False,)` renders
  `IS NOT NULL`.
- `like`/`ilike` (case-sensitive / case-insensitive) take one or more SQL `LIKE`
  *patterns* with OR semantics. Wildcards are yours: write `%needle%` for a substring
  match, and escape literal `%`/`_`/`\` as `\%`/`\_`/`\\` (a pattern ending in an
  unpaired `\` is refused). There is no auto-wrapping.
- Ranges compose from `gte` + `lte` as two clauses — there is no `between` operator.

Each clause renders as its own `WHERE` constraint; an `AnyOf` group is always
parenthesized, so a disjunction can never leak past a row policy.

### The JSON front door

If your filters arrive as a Mongo-flavoured JSON document (`$and`/`$or`/`$not`,
field maps, `$eq $neq $gt $gte $lt $lte $in $nin $null $like $ilike`),
`bloomery.planner.parse_filter_json` turns it into clauses, *normalizing before
refusing* — De Morgan push-down, complement inversion (`$not $eq` → `ne`), then CNF
distribution with a clause cap:

```python
from bloomery.planner import parse_filter_json

clauses = parse_filter_json(
    {"carrier": {"$in": ["DHL", "UPS"]}, "$or": [{"region": "EU"}, {"region": "UK"}]}
)
request = MetricRequest(metrics=("revenue",), filters=clauses)
```

Scalars are the `$eq` shortcut, arrays the `$in` shortcut, and `null` means
`is_null: true`. What cannot cross is refused with a typed `UnsupportedFilter` carrying
a stable `.reason` code from the closed list `bloomery.planner.KNOWN_UNSUPPORTED` —
a reviewed gap, never drift. `parse_sort_json` and `parse_page_json` ship alongside
(sort is direction-only; pagination is limit-only — non-default nulls placement,
offsets, and cursors are refused, never silently dropped).

## What comes back

`QueryPlan` is the planner's whole product:

| Field | What it carries |
|---|---|
| `sql` | The rendered SQL text — runnable as-is on the requested dialect |
| `columns` | Self-describing output envelope: one `ColumnDescriptor(name, type, role)` per output column, in bloomery names (`ordered_month`, never MetricFlow's internal names) |
| `mart` | The serving mart's logical name |
| `warnings` | Non-fatal notices: a clamped `limit`, a `time_grain` with nothing to apply to |
| `explanation` | Deterministic provenance — `explanation.render()` gives the human-readable block |
| `fingerprint` | `sha256(sql)` — your result-cache key |

The explanation is generated from the plan, never from a model — every number ships
with how it was computed:

```text
revenue
  mart:     gold.mart_orders (grain: order)
  measure:  revenue = SUM(amount)
            [additive — SUM]
  filters:  country in ('FR', 'DE')
  policy:   not applied
```

## Refusals

The planner answers correctly or refuses with a typed error — never guesses. All
planner errors subclass `PlannerError`; the first failure wins (they are not batched).
The three you will design UX around:

`UnknownMember` — a name that does not exist, with a closest match:

```text
unknown metric 'revenu'; did you mean 'revenue'?
```

`UnreachableAtGrain` — no single mart can serve the request. Summing across grains
would double-count, so the planner refuses rather than join at plan time:

```text
metric 'order_count' (grain: order) is served by no mart — no mart lists it as a measure.
  Define a mart at grain 'order' carrying it.
```

`AmbiguousDimension` — an unqualified bucket where the mart has several date roles:

```text
'month' has roles ['ordered', 'shipped']. Use 'ordered_month' or 'shipped_month'.
```

The remaining refusals: `InvalidRequest` (structural problems, raised at request
construction or planning), `FilterTypeMismatch` (a filter value whose type contradicts
the dimension's column type — refused before any SQL renders), and the
`UnsupportedFilter` family — the closed query-vocabulary list (set relations,
hierarchy operators, `$regex`, over-cap CNF expansions, non-invertible negations,
non-finite literals, non-default sort-nulls, offset/cursor paging), each with a
stable `.reason` in `bloomery.planner.KNOWN_UNSUPPORTED`. See
[Errors](../reference/errors.md).

## Scope rows with a policy

Row-level scoping is a typed filter, not a predicate string. Deciding *whose* policy
applies is your upstream concern; the planner takes the value and renders it through
the same escaping pipeline as every other filter, prepended to the user's filters:

```python
from bloomery import Op, RowPolicy

plan = planner.plan(
    ir,
    MetricRequest(metrics=("revenue",), dimensions=("ordered_month",)),
    dialect="duckdb",
    policy=RowPolicy(dimension="country", op=Op.EQ, value="FR"),
)
```

The rendered predicate reaches every scan of the mart relation, and
`explanation.render()` reports `policy:   applied` — the plan itself records that
scoping happened.

## Execute the SQL yourself

The planner never sees a connection — execution is your side of the line. `plan.sql`
runs directly on the dialect you asked for; on DuckDB, with the mart table built (by
the emitted SQLMesh models in real life, by hand here):

```python
import duckdb

con = duckdb.connect()
con.execute("CREATE SCHEMA gold")
con.execute("""
    CREATE TABLE gold.mart_orders AS
    SELECT * FROM (VALUES
        ('FR', DECIMAL '10.00', DATE '2024-01-05'),
        ('DE', DECIMAL '20.00', DATE '2024-01-20'),
        ('FR', DECIMAL '5.00',  DATE '2024-02-01')
    ) AS t(country, amount, ordered_day)
""")
rows = con.execute(plan.sql).fetchall()
```

Pair the rows with `plan.columns` for names and types, and cache results under
`plan.fingerprint` — identical requests over identical specs produce identical SQL,
so the fingerprint is a sound cache key.

## Notes

- `limit` is clamped to the planner's `max_limit` (default 50 000) with a warning on
  the plan, and `default_limit` applies when a request carries none.
- `TimeGrain.HOUR` is accepted by the contract but refused at coverage — marts expand
  date roles to day–year buckets only.
- A non-additive ratio metric is planned from its additive components on the mart that
  carries both; it is never read from storage. See
  [guardrails](../concepts/guardrails.md#additivity) for why.
- When specs change shape, re-run `build_project_ir` and hand the new IR to the same
  planner — the hydrator treats it as a new cache key automatically.
