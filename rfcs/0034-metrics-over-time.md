# RFC 0034 — Metrics over time: derived metrics, offsets, cumulative windows, metric filters

- **Status:** 🚧 In progress — argued and executed on one branch. Retired one change later,
  once a mainline-reachable commit exists to cite ([`RETIRED.md`](RETIRED.md) argues why).
- **Scope:** Four constructs the metric surface has never had, all of them time-shaped or
  filter-shaped and all of them today pinned to `None` in the MetricFlow manifest emitter:
  (1) **derived metrics** — a metric computed by an expression over other metrics; (2)
  **offsets** on a derived metric's inputs, which is what makes period-over-period
  expressible; (3) **cumulative windows** — `cumulative:`, reserved spec surface since
  RFC 0002 D10 and refused ever since; (4) **metric-level filters** — a metric that is its
  sibling restricted to a subset of rows. Adds spec surface, IR nodes, guardrails, the
  MetricFlow lowering, a Cube position per construct, and the planner's coverage rule for a
  metric with no measure of its own.
- **Non-goals:** post-aggregate (`HAVING`) filters, computed dimensions, cursor pagination,
  cross-mart metrics. §9 says why each stays out; the last is a standing refusal rather than
  a gap.
- **Related:** RFC 0002 D10 (reserved `cumulative:`), RFC 0006 §5.4 (the additivity guard a
  metric without a measure has to satisfy), RFC 0010 D8 (measure ownership — the rule three
  surfaces share), RFC 0011 D5 (a non-additive metric is recomputed from additive parts,
  never stored), RFC 0013 (the manifest emitter and the planner adapter), RFC 0015 (the
  request-time filter vocabulary this deliberately does not reuse — D12), RFC 0023 (the
  previous ceiling lift, and the source of the one-fact-two-modules lesson §10 applies).
- **Origin:** A feature-ceiling report against `main` at `c5acc25`: *"No period-over-period,
  offsets, windows, or metric-level filters. Every relevant MetricFlow field is pinned None
  (`emit/metricflow/__init__.py:448–476`). 'Revenue vs. same month last year' — arguably the
  most common BI question — is unexpressible."*

---

## 1. Summary

A bloomery metric today is a single aggregate over a single mart: `SUM(unit_price *
quantity)`, grouped by whatever the request asks for. Every question that needs *two*
aggregates related to each other — this month against last, the running total to date, the
paid subset against the whole — is unexpressible, and the emitter says so structurally:
`_type_params` pins `expr`, `window`, `grain_to_date`, `metrics` and
`cumulative_type_params` to `None`, and every `PydanticMetric` is constructed with
`filter=None`.

This RFC lifts that ceiling with four additions that share one shape — **a metric may be
defined in terms of other metrics, in terms of time, or over a subset**:

- **`derived:`** — an expression over named inputs, each input a metric (D1). The inputs are
  aliased, because the interesting case names the same metric twice.
- **`offset:`** on an input — `{window: "1 year"}` or `{to_grain: month}` (D2). This is the
  whole of period-over-period: `revenue_yoy` is `current - prior` where `prior` is `revenue`
  offset by a year.
- **`cumulative:`** — the reserved surface, lowered at last (D5). `{window: "7 days"}` for a
  trailing window, `{grain_to_date: month}` for month-to-date.
- **`filter:`** — a typed predicate list on the metric, restricting the rows it aggregates
  (D8). Typed and closed, never a SQL string.

None of it is new *semantics*: MetricFlow already models all four, and the probe in §11
confirms the shipped version renders each one. What is new is bloomery's own surface for
them, the refusals that keep an unlowerable combination from compiling to a wrong number,
and a Cube position stated per construct rather than left to be discovered.

## 2. Motivation

**The ceiling is the most common question in BI.** "Revenue vs. same month last year" is the
first chart on most dashboards. A compiler whose entire purpose is to be the place metrics
are defined, which cannot define that one, sends its users to define it somewhere else —
and once one metric lives outside the spec, the spec has stopped being the single account.

**`cumulative:` has been a promise for the whole life of the project.** It parses, it
validates, it has a `CumulativeSpec` model and its own error class — and it refuses. That is
the right refusal while nothing lowers it (a cumulative metric compiled as a simple one
aggregates per period instead of cumulatively, which is the silent wrong number this project
exists to refuse). It is still a stub, and every reader who finds it discovers the ceiling by
hitting it.

**Filtered metrics are how a metric set stays honest.** `gross_revenue` and
`gross_revenue_paid` are two metrics, not one metric and a convention about which filters
callers must remember to add. Without metric-level filters the second is expressible only as
a request the caller must get right every time — which is the definition of a metric that
isn't in the metric layer.

**The emitter's `None`s are load-bearing, and that is the problem.** Each pinned field has a
comment explaining that it is deliberately unused. That was true and is no longer: the fields
are unused because nothing upstream can produce them, and this RFC produces them.

## 3. The shape of the addition

Of the constructs this RFC adds, exactly one — `derived:` — describes a metric that
**has no measure of its own**, and it is not the first of its kind:

| Construct | Has its own measure? | MetricFlow type |
| --- | --- | --- |
| simple (today) | yes | `SIMPLE` |
| ratio (today) | no — two components | `RATIO` |
| **derived** | no — N inputs | `DERIVED` |
| **cumulative** | yes, plus a window | `CUMULATIVE` |
| **filtered** | yes, restricted | `SIMPLE` + `filter` |

The ratio row is the precedent the derived row follows, and it already answers most of the
structural questions: a metric with no measure is declared `non_additive`, is never
materialized (RFC 0011 D5), is emitted only where every component is emitted, and is refused
by the planner's coverage precheck by name when it cannot be served. Derived metrics inherit
all four behaviours, which is why this addition is smaller than it looks: **the ratio is a
derived metric with a fixed expression, and the code paths it already exercises are the ones
being generalized.**

The cumulative row is different in kind: a cumulative metric *is* a measure, plus a statement
about how it accumulates over time. So `cumulative:` sits beside `agg:`/`expr:` rather than
replacing them, and a cumulative metric is `additive` — the additivity describes the measure,
the window describes the accumulation (D6).

## 4. Design: derived metrics and offsets

### 4.1 Surface

```yaml
metrics_version: 1
metrics:
  gross_revenue:
    template: gross_revenue

  revenue_yoy:
    description: Revenue against the same period one year earlier
    additivity: non_additive
    derived:
      expr: "current - prior"
      inputs:
        current: {metric: gross_revenue}
        prior:   {metric: gross_revenue, offset: {window: "1 year"}}
```

`inputs` is a **mapping keyed by alias**, not a list. The alias is what `expr` references, so
it is the identity of the input; a list would carry the same name in a field and let two
entries collide. A dict makes the collision unrepresentable and gives the IR a deterministic
sort key for free (RFC 0003 — tuples, sorted, never sets).

`offset` takes exactly one of:

- **`window: "<count> <grain>"`** — "1 year", "7 days", "3 months". The grain vocabulary is
  `day | week | month | quarter | year`, matching the mart's date buckets (RFC 0010 D4);
  a plural `s` is accepted and normalized away.
- **`to_grain: <grain>`** — the value at the start of the containing period. `to_grain:
  month` against a daily grouping compares each day to the first day of its month.

### 4.2 Why aliases are mandatory

The headline case names one metric twice with different offsets. Without an alias there is no
way to write the expression, and no way for MetricFlow to name the two columns apart. Making
the alias the dict key rather than an optional field means the mandatory thing is
syntactically mandatory.

### 4.3 Dependency edges come from the inputs, not from the author

A derived metric's inputs are metrics, which makes them exactly what `requires_metrics:`
already declares. Rather than asking the author to write each input twice — once in
`inputs:`, once in `requires_metrics:` — the template merge **unions the derived inputs into
`requires_metrics`** (D3). Reachability, the resolution DAG, cycle detection and
`MetricIR.depends_on` then work with no further change, and a derived metric naming an
unreachable input reports the same missing-leaf message every other metric does.

The reference check (`resolve/refs.py`) reads the spec model directly, before the merge, so
it validates `derived.inputs[].metric` as well. Both readers call one helper on the spec
model rather than each spelling out "the metrics a derived metric depends on" — the
one-fact-two-modules failure §10 records.

## 5. Design: cumulative windows

```yaml
  revenue_mtd:
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity"
    cumulative: {grain_to_date: month}
```

`CumulativeSpec` is unchanged — it has parsed and validated `{window | grain_to_date}` since
RFC 0002 D10, and `window` now takes the same `"<count> <grain>"` grammar an offset does.
What changes is that the guardrail stops refusing it and the emitter lowers it to
`MetricType.CUMULATIVE` with `cumulative_type_params`.

A cumulative metric keeps its own measure, so it is named in a mart's `measures:` like any
other. It needs a time spine, which every measure-carrying mart already requires
(RFC 0013 R1 rule 4 — a mart with measures and no date role is `MartMissingTimeDimension`).

## 6. Design: metric filters

```yaml
  paid_revenue:
    template: gross_revenue
    filter:
      - {dimension: order_status, op: eq, values: [paid]}
      - {dimension: line_no, op: gte, values: [1]}
```

Clauses are ANDed. The operator vocabulary is closed and **deliberately smaller than the
request-time one** (D12): `eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `is_null`.
`like`/`ilike` are absent, and their absence is what keeps this cheap — a pattern operand
needs the `\` escape language, an `ESCAPE` clause and per-dialect case-folding argument
(RFC 0015 decision 13), all of it for a construct rare in a metric *definition*, where the
author knows the values.

The dimension is resolved and type-checked at the guardrail stage against every mart that
lists the metric, so a filter naming a column no mart flattens is a compile error rather than
an invalid manifest (D9).

## 7. Design: the two semantic targets

**MetricFlow gets all four.** It models each one natively; §11's probe renders each against
the shipped version.

**Cube gets metric filters and refuses the other three**, per construct, with
`UnsupportedByTarget` naming what it cannot express (D11):

- A **derived** metric with an offset has no Cube shape. Cube does period-over-period at
  *query* time (`compareDateRange` on a time dimension), not as a stored measure definition,
  so there is nothing to emit; a Cube consumer is not blocked, they ask the question a
  different way.
- A derived metric **without** an offset could in principle emit as a calculated `number`
  measure over `{member}` templating — the shape the ratio already uses. It is refused
  anyway, because emitting it means translating an arbitrary expression's alias references
  into Cube templating, and a half-supported construct whose support depends on whether an
  input happens to carry an offset is worse to explain than a clean refusal. The ratio form
  remains available for the division case, which is the one this would have covered.
- **Cumulative** windows map onto Cube's `rolling_window`, but only the trailing form;
  `grain_to_date` has no equivalent. Refusing both is one rule instead of one rule and an
  exception.

This asymmetry is the existing pattern, not a new one: `SemiAdditiveRule.AVG` is refused on
MetricFlow and emitted on Cube today. What a target cannot express is refused per construct,
checked by tests, and cannot drift from the emitter it lives in (RFC 0008 D3).

**SQLMesh and dbt are unaffected.** They build mart tables; metrics are query-time
constructs and appear in neither.

## 8. Design: the planner

`coverage._required_measures` answers "what measures must one mart carry to serve this
metric". Two new answers:

- a **derived** metric requires the union of its inputs' required measures, computed
  recursively — a derived metric over a ratio over two simple metrics requires both simple
  measures. The recursion is bounded by the resolution DAG's acyclicity (D3), and carries an
  explicit visited set so a hypothetical cycle is a refusal rather than a hang;
- a **cumulative** metric requires itself, like any simple metric.

Nothing else in the planner changes. `_measure_type` already answers `decimal(38,9)` for a
non-additive metric, which is what a derived metric is; a cumulative metric keeps its
measure's type. The offset itself is entirely MetricFlow's to render, and the time spine it
needs is already emitted.

## 9. What is deliberately absent

- **Post-aggregate (`HAVING`) filters.** A filter on an aggregate is a different construct
  from a filter on rows, needs its own request-side vocabulary, and interacts with `limit`
  and ordering in ways worth their own argument.
- **Computed dimensions.** A dimension defined by an expression over mart columns. Real, and
  orthogonal to everything here — it belongs with the mart flattener, not the metric set.
- **Cursor pagination.** A query-vocabulary concern (RFC 0015), unrelated to metric
  definition.
- **Cross-mart metrics.** Not a gap: summing across grains double-counts, and the coverage
  precheck refuses it by name with the per-metric grain table. It stays refused.
- **Per-input filters on a derived metric.** MetricFlow allows a filter on each
  `PydanticMetricInput`; the metric-level filter (D8) covers the cases the ceiling named, and
  the input-level one can be added later without moving anything.
- **`fill_nulls_with` / `join_to_timespine`.** A gap in a cumulative or offset series is a
  real question and a data-shaped one; defaulting it silently is the wrong answer, and
  answering it properly is its own decision.

## 10. Risks

**The three-way emitter equivalence gets a fourth shape to keep honest.** Mitigated by
refusing rather than approximating on Cube: the constructs Cube refuses have no Cube
behaviour to diverge.

**A constant two modules must agree on.** The last ceiling lift produced this defect three
times (`logs/T-0010.md`) — a marker predicate, a currency-code rule, an arity, each spelled
in two places and defined at neither. This change has three candidates: the time-grain
vocabulary shared by offsets and cumulative windows, the set of metrics a derived metric
depends on (read by both `refs.py` and the template merge), and the filter operator
vocabulary. Each gets exactly one definition, and §12's checklist says where.

**Fingerprints all move.** `MetricIR` gains fields, the canonical encoder writes each
dataclass's field names and count, so every project with a metric re-fingerprints —
`bloomery_ir_version` 8 → 9 (D14). The lesson from the previous bump is to check what does
*not* move: a project with no metrics at all.

## 11. Verification sketch

Grounding first, because the design assumes MetricFlow renders these. A probe against the
shipped `metricflow==0.212.0`, built from the `ecom_basic` fixture's real manifest with three
metrics appended by hand:

- `DERIVED` with `offset_window=(1, year)` — renders, joining the measure to itself over the
  time spine and projecting `current` and `prior`;
- `CUMULATIVE` with `grain_to_date=month` — renders as `Join Self Over Time Range` against
  `gold.dim_date`;
- `SIMPLE` with a `filter` — renders, and names its available dimensions when the filter
  references one the mart does not flatten (which is the failure the guardrail in D9 moves to
  compile time).

The tiers this lands in: unit tests per stage; golden artifacts for a new fixture carrying
all four constructs; an **execution** test that runs the planned SQL against DuckDB and
asserts the numbers — three months of revenue, the year-over-year delta against a hand-computed
value, and a month-to-date series — because a period-over-period metric that compiles is not
the claim, one that is *arithmetically right* is.

## 12. Implementation checklist

1. `spec/common.py` — the time-grain vocabulary and the filter-operator vocabulary, one
   definition each.
2. `spec/metrics.py` — `DerivedSpec`, `MetricInputSpec`, `MetricOffset`, `MetricFilter`;
   `Metric.derived`/`Metric.filter`; the `input_metrics` helper both readers call.
3. `spec/catalog.py` — the same fields on `MetricTemplate`, so a template can carry them.
4. `resolve/refs.py`, `resolve/metrics.py` — reference-check and merge the derived inputs.
5. `ir/nodes.py` — `TimeWindow`, `MetricInputIR`, `DerivedIR`, `CumulativeIR`,
   `MetricFilterIR`; the `MetricIR` fields; `bloomery_ir_version` 9.
6. `resolve/build.py` — lower the four constructs into `MetricIR`.
7. `guardrails/` — the refusals: cumulative-with-derived, derived-not-non-additive, unknown
   alias in a derived expression, filter dimension unknown or ill-typed. `UnsupportedCumulative`
   is retired as a blanket refusal and its class deleted.
8. `emit/lower/predicates.py` — the shared filter renderer, parameterized by the target's
   spelling of a column reference.
9. `emit/metricflow/` — `DERIVED`, `CUMULATIVE`, and `filter=` on every metric.
10. `emit/cube/` — the three refusals and the filter emission.
11. `planner/coverage.py` — `_required_measures` for derived and cumulative.
12. Fixture, goldens, docs, CHANGELOG.

## 13. Decision table

| # | Grade | Decision |
|---|---|---|
| 1 | `LOCKED` | **A derived metric is `expr` over aliased inputs, each input a metric.** `inputs` is a mapping keyed by alias, not a list: the alias is the input's identity because `expr` references it, and a dict makes a duplicate alias unrepresentable rather than a validation. Consequence: `MetricIR` gains a `derived` field and the additivity guard must accept it as a decomposition. |
| 2 | `LOCKED` | **An offset is `{window: "<count> <grain>"}` or `{to_grain: <grain>}`, exactly one.** The grain vocabulary is `day`, `week`, `month`, `quarter`, `year` — the mart's own date buckets (RFC 0010 D4). `hour` is refused despite MetricFlow accepting it: the emitted time spine is day-grain, so an hourly offset would resolve against a spine that cannot express it. |
| 3 | `LOCKED` | **Derived inputs are unioned into `requires_metrics` by the template merge, never written twice by the author.** The DAG, reachability, cycle detection and `depends_on` then need no change at all. The reference checker reads the spec model before the merge and validates the inputs there; both callers use one helper on the spec model, so the set of metrics a derived metric depends on has exactly one definition. |
| 4 | `ASSUMED` | **A derived metric need not be named in any mart's `measures:`.** It has no measure to place. It is emitted where every input's measure is emitted — the rule the ratio already uses — and the planner's coverage precheck resolves it to the mart carrying those measures. Naming it in `measures:` stays legal and inert, as it is for a ratio. |
| 5 | `LOCKED` | **`cumulative:` is lowered, and the blanket `UnsupportedCumulative` refusal is deleted rather than narrowed.** The class goes with it: a reserved-surface error whose surface is no longer reserved is a class that can only mislead. Combinations that still cannot be lowered are refused by their own named guardrails (D7). |
| 6 | `LOCKED` | **A cumulative metric is `additive` and keeps its own measure.** The additivity describes the measure, the window describes the accumulation over time. Declaring it `non_additive` would trip `NonAdditiveWithoutComponents` with nothing to decompose into, which is the guard doing its job on a metric that has misdescribed itself. |
| 7 | `LOCKED` | **`derived:` and `cumulative:` on one metric is refused.** A derived metric has no measure and a cumulative window accumulates one; the combination names two mutually exclusive shapes, and MetricFlow has no type for it. Refused by name at the guardrail stage rather than left to produce an invalid manifest. |
| 8 | `LOCKED` | **A metric filter is a typed predicate list — `{dimension, op, values}` — and never a SQL string.** A string would be dialect-bound, unvalidatable against the column's declared type, and an injection surface in a compiler whose input may be untrusted. The list is ANDed; a disjunction is expressed as `in`. |
| 9 | `LOCKED` | **A filter's dimension is checked against every mart listing the metric, at the guardrail stage.** Not at emit: a filter naming a column no mart flattens is a *model* error, decidable from the spec, and it should fail with the batched aggregate every other model error joins. Checking every listing mart rather than the owning one avoids reaching for the ownership rule from a layer below the module that defines it, and is a superset of what correctness needs. |
| 10 | `ASSUMED` | **The filter operator set is `eq, ne, in, not_in, gt, gte, lt, lte, is_null` — no `like`/`ilike`.** Patterns need the `\` escape language, an `ESCAPE` clause and a case-folding portability argument, all for a construct rare in a metric definition. Adding them later is additive. |
| 11 | `LOCKED` | **Cube refuses derived and cumulative metrics per construct with `UnsupportedByTarget`, and emits metric filters.** Period-over-period is a query-time concern in Cube, and `grain_to_date` has no `rolling_window` equivalent. Refusing the offset-free derived case too — which `{member}` templating could express — keeps one rule where support-that-depends-on-an-offset would need two, and the ratio form still covers division. |
| 12 | `LOCKED` | **The metric-filter operator vocabulary is defined in the spec layer and is *not* shared with `planner.request.Op`.** They are different facts: one is what a request may ask, the other what a definition may pin, and the request set carries `like`/`ilike` this one refuses. Stated as a decision rather than left as an accident, because a future reader will see two enums and reach for the merge. |
| 13 | `LOCKED` | **String values in a metric filter refuse `{` and `}`, at parse.** Both semantic targets template with braces — Jinja on MetricFlow, `{member}` on Cube — and a value carrying one would need per-target neutralization. One refusal beats two escaping rules that can disagree; a curly brace in a filtered dimension value has no BI use worth the divergence. At parse rather than at the guardrail because it is a property of the document alone, which is where RFC 0002 D4 draws that line — unlike D9's dimension check, which needs the marts. NUL and floats are refused in the same validator, for the reasons they are refused everywhere else. |
| 14 | `ASSUMED` | **`bloomery_ir_version` 8 → 9.** `MetricIR` gains fields; the canonical encoder writes each dataclass's field names and count, so every project carrying a metric re-fingerprints whether or not it uses any of this. `plan()` refuses to diff a v8 IR against a v9 one. |
| 15 | `LOCKED` | **The filter renderer lives once, in `emit/lower/predicates.py`, parameterized by the target's column spelling.** Each target supplies how it names a column — `{{ Dimension('e__c') }}` for MetricFlow, `{CUBE}.c` for Cube — and the comparison syntax, list rendering and literal escaping are shared. Two renderers would be the same injection-safety rules spelled twice, which is the defect class this project keeps finding in itself. |
