# Assess a spec before it compiles

`evaluate()` answers the question a reviewer actually has about a draft spec: not "did it
compile" but **"what would this give me."**

```python
from bloomery import Stage, evaluate, load_catalog, load_project

evidence = evaluate(load_project(sources), catalog=load_catalog(catalog_text))

if evidence.stage_reached is not Stage.COMPLETE:
    for refusal in evidence.refusals:
        print(f"{refusal.source_path}: {refusal}")

print(f"{len(evidence.reachable)} metrics reachable")
for metric in evidence.unreachable:
    print(f"  {metric.name} blocked on {', '.join(metric.missing)}")
```

It never raises for a refusal. It runs no SQL, opens no connection, and reads no data.

## Read `stage_reached` first

Every tuple on `SpecEvidence` is empty in two situations that mean opposite things.

| `stage_reached` | `unreachable == ()` means |
|---|---|
| `COMPLETE` | nothing is unreachable |
| anything else | reachability was never computed |

There is no way to tell those apart from the tuple. That is why the field exists, why it
is the first thing the CLI prints, and why every example here branches on it before
touching anything else.

Compare against `COMPLETE` and treat everything else as "analysis stopped early". `Stage`
is an **open** enum: a stage may be added or split as the pipeline grows, and code
written that way keeps working.

## The stages

```text
resolve ──▶ typecheck ──▶ lower ──▶ guardrails ──▶ COMPLETE
   │            │            │           │
   └────────────┴────────────┴───────────┴──▶ SpecEvidence(stage_reached=…)
```

| Stage | Refuses when |
|---|---|
| `RESOLVE` | a reference dangles, a recipe is invalid, the graph has a cycle |
| `TYPECHECK` | a transform chain's terminal type is not assignable to the declared one |
| `LOWER` | a step a mapping wires is not in the registry |
| `GUARDRAILS` | the arithmetic parses and typechecks and would still be wrong |

Analysis stops at the first stage that refuses. Stages are never reordered or skipped to
salvage more: a guardrail refusal means the model is wrong, and summarizing marts past it
would report a shape derived from a spec bloomery has already called invalid.

## The partial answer is the point

A spec refused by the guardrail stage still reports its reachability, because that was
computed two stages earlier:

```python
evidence = evaluate(draft, catalog=catalog)

evidence.stage_reached      # Stage.GUARDRAILS
evidence.reachable          # ('landed_revenue', 'shipping_cost') — still known
evidence.refusals           # the batch, each with its own source_path
evidence.fingerprint        # None — a draft is not a project
```

`compile_project()` gives you none of this: it emits artifacts or it raises, and the
prefix goes with the exception. "Seven metrics reachable, two blocked on `cogs`, one
refusal at `mappings/crm.yaml`" is the most useful sentence bloomery can produce about a
spec it will not compile.

## Refusals are values, one per failure

Each refusal is the individual failure, not the batch aggregate — so `source_path` points
at a spec node rather than at a paragraph you have to parse:

```python
for refusal in evidence.refusals:
    refusal.source_path     # 'marts: marts.order_items.measures.shipping_cost'
    type(refusal).__name__  # 'GrainViolation'
    str(refusal)            # the claim, why it is wrong, and the fix
```

Structured fix suggestions ride along on the errors that carry them —
`UnknownMember.did_you_mean`, `GrainViolation.offending_measures`, and the rest. See
[Errors](../reference/errors.md).

## Why a metric is blocked, and through what

`missing` names the specific **leaves** — the canonical fields nothing maps — because the
fix is always a mapping, never a metric. When a metric is blocked *through* another one,
`via` names the chain:

```python
UnreachableMetric(name='margin_rate', missing=('cogs',), via=('margin',))
```

Read that as: map `cogs`, and both `margin` and `margin_rate` unblock. Only blocked
requirements appear in `via` — a required metric that is perfectly reachable is not on the
path to anything missing.

`unreachable` says what is blocked; `unresolved` says what edit would unblock it, and
which recipes the catalog offers for the job. See
[Close an open decision](close-an-open-decision.md).

## What it does not do

**No data-dependent evidence, ever.** Coercion failure rates, null deltas, sample rows and
row counts all require running the emitted SQL. That is outside the library by design: a
platform composes `evaluate()` with its own dry-run into one review payload.

```text
bloomery.evaluate()   →  static evidence      (specs only, no data)
your dry-run          →  data evidence        (sample rows through the emitted SQL)
             ↘
        one review payload
```

**No judgement.** `SpecEvidence` carries facts — no score, no confidence, no
approve/reject. The reviewer decides; bloomery reports.

**No target-specific refusals.** `evaluate()` stops before emission, so a target that
refuses a `coverage:` check is invisible to it. Evidence is target-independent;
compilation is not.

## From the command line

`bloomery resolve` prints exactly this:

```console
$ bloomery resolve specs/
Stage: guardrails
  analysis stopped here — every count below is a prefix, not a total

Reachable (2)
  landed_revenue
  shipping_cost

Unreachable (0)

Refusals (1)
  marts: marts.order_items.measures.shipping_cost
    GrainViolation: measure 'shipping_cost' has grain 'order' (one row per
      order), not the mart's grain 'order_item' …
```

Exit code `1`, because the spec is still refused. `--format json` emits the whole
`SpecEvidence` including every refusal's full message. See
[Use the CLI](use-the-cli.md).
