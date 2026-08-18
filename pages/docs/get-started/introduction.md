# Introduction

This page is for a data platform engineer deciding whether bloomery fits their stack.
It explains the problem the library exists to remove, the spec kinds it compiles,
the invariants it holds itself to, and — just as important — what it deliberately does
not do.

## The problem

In a config-driven data platform, the worst failure mode is not a crash. It is a number
that looks right and is wrong: an order-level shipping cost joined to line items and
summed three times over, a net price subtracted from a gross cost, an average stored as
a column and then re-averaged. These bugs pass syntax checks, pass type checks, survive
code review, and surface months later as a finance discrepancy. The formula was right,
the data was right, and the answer was 3× wrong.

The failure mode gets sharper when spec changes arrive from many hands — humans and
LLM-assisted proposal systems — across many tenants. A typo'd key that is silently
ignored, a join that silently fans out, a recipe that is silently re-chosen: each is a
plausible number with no audit trail.

Bloomery's answer is a compiler that refuses. Every spec is validated against a domain
model that carries units, tax bases, grains, and additivity; anything that would produce
a plausible-but-wrong number is a compile error with a source path, not a warning. The
system may not know an answer, but it may not return a wrong one without warning.

The `refusals/` [example](examples.md) is six of those specs, each one a project that a
hand-written model would run without complaint, printed next to the message bloomery
gives instead — worth ten minutes if this section is the reason you are here.

## What bloomery is

A pure function library. Specs go in as data structures; artifacts and plans come out as
data structures. Compilation produces SQLMesh, dbt, and Cube artifacts plus a MetricFlow
semantic manifest; the planner turns a `MetricRequest` into SQL over a wide mart at
request time, using an embedded, render-only MetricFlow behind a stable bloomery-owned
contract; `plan()` diffs two spec versions and classifies every change. Nothing is
executed, read, or written by the library itself.

## The spec kinds

Six document kinds describe a deployment end to end. Each is strict YAML — unknown keys
are rejected loudly — and each self-identifies by its version key, so bloomery never has
to guess what it is reading.

The four below the Catalog are the tenant's project; the **Catalog** sits outside it,
loaded separately and shared across tenants. The sixth kind, **StepSet**
(`steps_version`), is optional: it wires platform-owned code into the pipeline where a
declaration cannot reach — see [Steps](../concepts/step-registry.md).

### Catalog

Domain knowledge, one per vertical, written by the platform operator — never by tenants.
It holds canonical fields with units and tax bases, derivation recipes ordered by
reliability, canonical relationships, and metric templates: the domain graph,
independent of any tenant's data.

```yaml
canonical_fields:
  unit_price:
    entity: order_item
    type: decimal(12,4)
    unit: currency
    tax_basis: net
    recipes:
      - {id: direct,     requires: [unit_price]}
      - {id: from_total, requires: [line_total, quantity], expr: "line_total / quantity"}
```

### EntityModel

What one tenant's data means: entities with grains, keys, and typed fields. A field with
a `canonical:` link is the tenant's realization of a Catalog field; a field without one
is tenant-native — legal, but it participates in no catalog-derived metric.

```yaml
entities:
  order_item:
    grain: one row per line on an order
    key: [order_id, line_no]
    fields:
      unit_price: {type: decimal(12,4), canonical: unit_price}
      quantity:   {type: int, canonical: quantity}
```

### Mapping

How one source becomes one entity: field extractions, whitelisted transform chains, and
— crucially — the *recorded* recipe choice for each derived field. Resolution happened
upstream; the compiler validates the recorded decision and never re-makes it.

```yaml
source: shopify__order_lines
target: order_item
fields:
  unit_price:
    recipe: from_total
    from: {line_total: "$.total", quantity: "$.qty"}
  order_date:
    from: "$.created_at"
    transform: [{parse_ts: "ISO8601"}, {to_utc: "Europe/Paris"}]
```

### MetricSet

The tenant's measures, each carrying grain and an additivity class — `additive`,
`semi_additive`, or `non_additive` — which decides how the metric may ever be aggregated
or stored.

```yaml
metrics:
  gross_revenue:
    requires: [unit_price, quantity]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "unit_price * quantity"
```

### Marts

The gold layer: one wide, pre-joined mart per (grain × subject area), with dimensions
flattened in at build time so the common query path has no joins at all.

```yaml
marts:
  orders:
    grain: order
    base: order
    flatten:
      - {via: order_of_customer, prefix: customer_}
      - {date: order_date, role: ordered}
    measures: [order_count, shipping_cost]
```

## The hard invariants

These are the reason bloomery exists as a separate package; violating any of them makes
it untestable.

1. **No I/O.** No filesystem, network, database, clock, environment, or randomness.
   Loaders take strings, not paths.
2. **Deterministic.** `compile(x) == compile(x)` byte-for-byte, across processes,
   machines, and `PYTHONHASHSEED` values — enforced by test, not by intent.
3. **Tenant-agnostic.** The compiler does not know what a tenant is; tenant scoping is
   ordinary spec values supplied by the caller.
4. **No framework dependency.** No orchestrator, no cloud SDK.
5. **Total errors.** Every failure is a typed `BloomeryError` with a source path into
   the offending spec node — never a bare `KeyError`.

## What bloomery is not

- **It does not execute SQL.** It emits text and plans; something else runs them.
- **It does not read catalogs or profile data.** Those are inputs, computed elsewhere.
- **It does no orchestration** — no scheduling, no backfill execution.
- **It contains no LLM.** Proposals may be produced upstream with LLM assistance, but
  they arrive as validated specs, and everything the library outputs — including
  human-readable query explanations — is generated deterministically.

If that boundary fits your platform, continue to [Installation](installation.md) and
the [Quickstart](quickstart.md), run one of the [examples](examples.md), or read
[Specs and the catalog](../concepts/specs-and-catalog.md) for the full domain model.
