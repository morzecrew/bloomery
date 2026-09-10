# Declare what reads your project

Everything that consumes a bloomery project lives outside it. An `exposures:` document
tells the compiler what those consumers are, so `bloomery lineage --direction downstream`
does not stop at gold and `plan()` can put names to the people a breaking change reaches.

```yaml
exposures_version: 1
exposures:
  weekly_revenue_review:
    kind: dashboard
    owner: analytics@example.com
    url: https://bi.example.com/dash/17
    depends_on:
      metrics: [gross_revenue, order_count]
      marts: [order_items]
```

One such document per project, beside the others. `kind` is one of `dashboard`,
`notebook`, `analysis`, `ml`, `application` — dbt's vocabulary, adopted rather than
invented, so the emitted exposure needs no translation.

## Ask what a dashboard reads

```console
$ bloomery lineage specs/ --node exposure.weekly_revenue_review --direction upstream
exposure.weekly_revenue_review  (upstream)
  canonical.quantity                   --requires-->           metric.gross_revenue
  canonical.unit_price                 --requires-->           metric.gross_revenue
  metric.gross_revenue                 --depends_on-->         exposure.weekly_revenue_review
  metric.order_count                   --depends_on-->         exposure.weekly_revenue_review
  order_item.quantity                  --canonical-->          canonical.quantity
  order_item.unit_price                --canonical-->          canonical.unit_price
  source.shopify__order_lines.$.qty    --direct-->             order_item.quantity
  source.shopify__order_lines.$.qty    --recipe:from_total-->  order_item.unit_price
  source.shopify__order_lines.$.total  --recipe:from_total-->  order_item.unit_price
```

Downstream from a metric now reaches the other way, which is the question anyone asking
about lineage was actually asking:

```console
$ bloomery lineage specs/ --node metric.gross_revenue --direction downstream
metric.gross_revenue  (downstream)
  metric.gross_revenue  --depends_on-->        exposure.weekly_revenue_review
  metric.gross_revenue  --requires_metrics-->  metric.average_order_value
```

Nothing is downstream of an exposure. It is the graph's only sink.

A **mart** dependency draws an edge too, so an exposure that names only marts still has
an upstream — and the walk carries on past the mart into the metrics it measures and the
columns behind those. What it does not carry is the mart's own dimension columns; see
[Trace where a metric comes from](trace-lineage.md#naming-a-node) for why.

## Ask who a change reaches

`Plan.affected_exposures` names the consumers a diff touches, and `bloomery plan` prints
them last — everything above the section says what changed, and this says who to tell.

```console
$ bloomery plan deployed/ proposed/ --catalog catalog.yaml
Changes (1, 1 breaking)
  breaking  mart:order_items  materialization changed

Backfill scope
  (none)

Affected exposures
  finance_extract
  weekly_revenue_review
```

A consumer is reached by a changed **mart** as well as by a changed metric. That matters
for `finance_extract` above, which names no metric at all: an exposure may depend on a
mart directly, and a report built from the metric walk alone would omit exactly that one.

Additive changes reach nobody. A mart added, or one whose partitioning moved, tells no
dashboard anything, and a report that names everyone names no one.

## What gets emitted

dbt gets `models/exposures.yml`, so `dbt ls --select +exposure:*` walks upstream from
each consumer into the models behind it. A metric dependency is written as a `ref()` on
the marts that serve it — dbt resolves `metric()` against its own semantic models, which
bloomery does not emit — and the metric names you declared are kept under `meta:`.

Cube and SQLMesh get nothing, and nothing is refused. Neither framework has the concept:
Cube's consumers are its API's callers, and a SQLMesh tag is a label rather than an edge.
Declaring a dashboard never restricts what you can compile.

## The one refusal

An exposure naming a metric or a mart the project does not declare is refused as the spec
is read:

```
exposure 'weekly_revenue_review' depends on metric 'revenue_gross', which this project
does not declare. An exposure pointing at nothing reports clean — it names no consumer of
a change that should reach one (RFC 0056 D2). Fix: correct the name, or declare the
metric. Declared metrics: 'average_order_value', 'gross_revenue', 'margin', 'order_count'
```

That is the whole point of the check. A dangling dependency does not fail: it matches no
change, so the impact report comes back naming nobody — which is worse than having no
exposure at all, because a reader trusts it.

## What it does not do

- **Nothing is discovered.** An exposure is declared, always. Reading a BI tool would need
  a network and credentials, and compilation does no I/O.
- **The `url:` is text.** Never fetched, never validated. Its correctness is yours.
- **A metric with no exposure is not reported.** Plenty of metrics exist for ad-hoc use,
  and a warning nobody can act on is one everybody learns to skip.
- **A declaration can rot.** A dashboard deleted in the BI tool leaves a declaration
  nothing refutes, and one that starts reading a second metric leaves a report that is
  confidently incomplete. `depends_on` is hand-maintained; keep it that way deliberately.
