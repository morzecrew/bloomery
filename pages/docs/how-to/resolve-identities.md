# Resolve identities across systems

Two systems describe the same customers and share no key. The CRM issues `C-1001`, billing
issues `AC-77`, and only a fuzzy match can see they are one person.

bloomery has no `xref` spec kind, and will not get one. Identity resolution is a **Tier 3
step** — and that is a decision, not a gap. This page is the pattern end to end, on
mechanisms that already ship.

## Why a step and not a spec kind

Modelling identity resolution declaratively would mean modelling blocking keys, similarity
functions, thresholds and transitive closure. bloomery could typecheck none of them,
guardrail none of them, and diff none of them meaningfully — so a spec kind would give
**weaker** guarantees than a step, which at least carries a declared, runtime-enforced
output contract.

The version that inverts the intuition: a step is *safer* here.

| What you need | What supplies it |
|---|---|
| Fuzzy matching bloomery cannot express | A `python_model` step with a typed manifest contract |
| Two outputs from one computation | Multiple declared outputs, one generated wrapper each |
| Marts over the resolved entity | Step outputs are synthesized as entities |
| Metrics over resolved data | `canonical:` links declared per output on the wiring |
| Siblings agreeing *within* one run | The declared cross-output consistency audit |
| Reproducible backfills | `determinism: pure` plus `runtime_lock` in the step's identity |

That last row is the argument. `runtime_lock` means upgrading the matching library
classifies as a **restating** change and backfills the outputs. A declarative similarity
function would have no equivalent: the compiler could not see that the semantics moved.

**The reusable test.** Before adding a spec kind, ask whether it can be a referenced
implementation instead: *can bloomery typecheck it, guardrail it, and diff it
meaningfully?* If not, it is a step.

## The two sources

They stay separate entities. bloomery refuses two mappings into one entity — a
deterministic union merge is its own milestone — and separate relations are the truer
shape anyway: a step reads *inputs*, plural, and unioning them first would beg the
question the step exists to answer.

```yaml title="entity_model.yaml"
spec_version: 1
entities:
  customer_crm:
    grain: one row per customer in the CRM
    key: [source_system, source_id]
    fields:
      source_system: {type: string, required: true}
      source_id: {type: string, required: true}
      email: {type: string}
      name: {type: string}
  customer_billing:
    grain: one row per billing account
    key: [source_system, source_id]
    fields: # …the same four
```

Each has its own mapping, and normalization happens there — `[to_string, lower, trim]` on
the email — so the matcher sees clean values and the cleaning is visible in the compiled
SQL rather than buried in Python.

## The wiring

This is the whole of identity resolution as an authored spec. There is no field here that
could carry a matching rule, a threshold formula or a blocking key: the step declares
those, and the platform owns them.

```yaml title="steps.yaml"
steps_version: 1
steps:
  - use: resolve_customers@4
    inputs: {crm: silver.customer_crm, billing: silver.customer_billing}
    outputs:
      customer: silver.customer
      customer_xref: silver.customer_xref
    parameters: {threshold: 0.9}
    canonical:
      customer: {canonical_id: customer_ref}
    quality:
      - {name: confidence_is_high, rule: expression, expr: "confidence >= 0.8", on_fail: fail}
    applies_to: {confidence_is_high: customer}
```

Four things are doing work:

- **`parameters`** are bounded by the manifest. A second tenant wanting stricter matching
  changes `threshold`; it does not get a forked step.
- **`canonical:`** is what makes metrics over resolved data possible. Without it the
  produced columns are never *available* and every metric over the entity is unreachable;
  with it, nothing about metric resolution changes at all. It is never inferred from a
  matching column name.
- **`quality:`** applies declared rules at the escape hatch's boundary. `on_fail: fail`
  lowers to a blocking audit, so a low-confidence match stops the run rather than
  quietly entering the warehouse.
- **`applies_to`** names which output each rule is about — a step has several, so "on this
  step" would not be specific enough to lower.

## What comes out

```
audits/step_customer_confidence_is_high.sql
audits/step_customer_xref_canonical_id_references_customer.sql
models/silver/customer_crm.sql       ← the two mapped sources, ordinary silver models
models/silver/customer_billing.sql
models/silver/customer.py            ← generated wrapper, one per declared output
models/silver/customer_xref.py
models/gold/mart_customers.sql       ← an ordinary mart over the resolved entity
models/gold/dim_date.sql
```

The second audit is the one worth understanding. The manifest declares
`references: {canonical_id: customer}` between the two outputs, and each output is emitted
as its own model — so the step runs twice, and a step *misdeclared* as `pure` could produce
a `customer_xref` naming ids the `customer` execution never minted. No run-to-run gate can
see that, and neither can the contract assertion, since each output is individually valid.
That audit is the only thing standing between it and silently wrong numbers.

Both wrappers assert the contract on every run. The call is generated and non-optional:
there is no flag, no environment variable and no warn mode.

## Reading the result

`customer_xref` is a **total** map from source rows. A row the matcher could not resolve
appears with a NULL `canonical_id` and `method = 'none'` — "we could not resolve this" is a
fact the warehouse should carry, and dropping the row would make it look like the source
never had it.

So **the crosswalk's id must not be declared `required`**. The contract assertion checks
every `required` column null-free on every run, so a manifest asking for both a total
crosswalk and a required id aborts the step on the first row it could not match — and the
stricter the tenant's `threshold`, the sooner. The `references:` audit is already written
for the nullable reading: it skips a NULL child rather than failing it.

Then a metric over the resolved entity is an ordinary metric:

```yaml title="metrics.yaml"
metrics_version: 1
metrics:
  customer_count:
    template: customer_count
```

and a mart over it is an ordinary mart. Nothing downstream knows a step was involved,
which is exactly the promise.

## What bloomery does not do

**It never runs the step.** Compilation is a pure function of the specs — no I/O, no
imports of your code, no execution. bloomery emits a wrapper that imports your entrypoint
at run time, and the engine runs it. That is why a spec cannot become an
arbitrary-code-execution surface: the property comes from the *absence* of a surface, not
from validating one.

**The dbt target refuses this project.** dbt's Python models run on Snowflake, BigQuery
and Databricks, and none of bloomery's dialects is one of those. An identity resolver is
Tier 3 by construction, so this pattern is SQLMesh-only. Cube serves the marts over the
resolved entity like any other — it builds no relation and is asked nothing about steps.

**The matching is yours.** The step in bloomery's fixture corpus is a *demonstration*:
exact email, then a normalized-name comparison, no blocking, no tuning. Its value is the
wiring, not the matching. A production resolver swaps the body and changes nothing else.
