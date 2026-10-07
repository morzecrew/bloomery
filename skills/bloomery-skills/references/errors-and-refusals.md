# Errors and refusals

When bloomery says no, it says where and why. This reference covers reading a refusal: its
class, its `source_path`, the fix it names; diagnosing how far a spec got before it was
refused; and telling a refusal from a usage error, an internal error and an advisory.
Every refusal the library raises derives from `BloomeryError`, so one `except BloomeryError`
catches them all. A CLI usage error (code `2`) is not one: it belongs to the command line
and is about the invocation, not the spec.

## First: which exit code

| Code | Meaning | Whose mistake |
|---|---|---|
| `0` | success | |
| `1` | a **refusal**: bloomery read the spec and said no, with a reason and a path | the spec's |
| `2` | a **usage error**: a missing path, an unknown flag, a mistyped `--target` or `--dialect`, bad `--where` JSON | the invocation's |
| `3` | an **internal error**: an unexpected exception, printed with its traceback | bloomery's: report it |

Never treat `1` as "fine with warnings". A pipeline branching on the code stops on it.
`InvariantViolated` derives from `BloomeryError`, so the CLI exits `1` for it as for a
refusal; its class name says it is bloomery's fault, not the spec's.

## Diagnose how far a spec got

`bloomery resolve` never raises for a refusal. It reports the stage analysis reached,
what was reachable by then, and every refusal with its path:

```console
$ bloomery resolve specs/
$ bloomery resolve specs/ --format json
$ bloomery check specs/
```

```text
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

**Read the stage before the counts.** At any stage but `complete` the counts are a
prefix: `Unreachable (0)` means "never computed", not "nothing unreachable". `check` runs
the same analysis as a CI gate; only a refusal fails it, not an unreachable metric.

The same from Python, as a value:

```python
from bloomery import Stage, evaluate, load_catalog, load_project

evidence = evaluate(load_project(sources), catalog=load_catalog(catalog_text))
print(evidence.stage_reached)
if evidence.stage_reached is not Stage.COMPLETE:
    for refusal in evidence.refusals:
        print(f"{refusal.source_path}: {type(refusal).__name__}: {refusal}")
for metric in evidence.unreachable:
    print(f"{metric.name} blocked on {', '.join(metric.missing)} via {metric.via}")
for advisory in evidence.advisories:
    print(advisory.code, advisory.source_path)
```

## The stages

Analysis stops at the first stage that refuses, and never skips one to salvage more.

| Stage | Refuses when | Typical classes |
|---|---|---|
| parse | YAML, duplicate or unknown keys, shape, an unparseable `expr:` | `SpecParseError` |
| `RESOLVE` | a reference dangles, a recipe is invalid, the graph has a cycle | `MissingReference`, `CircularDerivation` |
| `TYPECHECK` | a chain's terminal type is not assignable to the declared type | `TypeCheckError`, `UnknownTransformError` |
| `LOWER` | a wired step is not in the registry | `StepError` family |
| `GUARDRAILS` | it parses and typechecks and would still be wrong | `GuardrailError` family |
| emit | the target cannot express something | `UnsupportedByTarget` |

A parse failure has no stage: nothing loaded. `evaluate` stops before emission, so a
target refusal appears only from `compile`.

## Reading one refusal

Each refusal states the claim, why it is wrong, and the fix. Its `source_path` addresses
the authored node, prefixed with the document name you loaded it under:

```text
mappings/shopify.yaml: fields.unit_price.from
marts: marts.order_items.measures.shipping_cost
```

The parse stage always sets it; later stages best-effort. Go to that node first.

**Batching.** Parse, resolve and guardrail stages collect every failure in the stage and
raise one aggregate whose message lists every path; `error.collected` holds them
individually. A single failure is raised directly. Fix the whole batch in one round. The
planner is the exception: a request fails on its first problem.

**Fix suggestions** ride on five classes as values: `UnknownMember.did_you_mean`,
`UnreachableAtGrain.covering_marts`, `GrainViolation.offending_measures`,
`UnknownStep.available_versions`, `UnsupportedFilter.nearest_supported`.

## Common refusals and their fix

| Class | Usually means | Fix |
|---|---|---|
| `SpecParseError` | a typo'd key, a wrong shape, a missing version key | match the kind's schema: `bloomery schema --kind <kind>` |
| `MissingReference` | a name points at nothing | spell the entity, field, canonical or relationship as declared |
| `CircularDerivation` | a dependency cycle; the message names the path | break one edge of the printed cycle |
| `UntypedRecipeOperand` | a recipe's `+`/`-`/`*`/`/` operand typed neither by `types:` nor by a canonical field of the same name, or not in `requires` at all | add the operand to the recipe's `types:`, or add it to `requires:` and bind it in the mapping's `from:` (with a `types:` entry unless canonical) |
| `UnknownTransformError` | a transform not in the whitelist | use the suggested name, or register one |
| `TypeCheckError` | the chain's result does not fit the declared type | add a cast, or widen the declared type |
| `GrainViolation` | a measure coarser than the mart's grain | move it to a mart at its grain, or a rollup |
| `UnitMismatch`, `CurrencyMismatch` | adding unlike quantities | convert first, or split the metric |
| `NonAdditiveWithoutComponents` | a ratio with no additive parts | declare numerator and denominator |
| `InsufficientEvidence` | a strict consumer rests on an `ASSUMED` fact | author the fact, or accept `assumed` |
| `UnsupportedByTarget` | the target cannot express a construct | choose another target, or drop the construct |

For the guardrail family in depth, and closing an open decision, see
[guardrails-and-evidence](guardrails-and-evidence.md). For mapping and transform fixes,
see [mappings-and-transforms](mappings-and-transforms.md).

## Blocked, not refused

An unreachable metric is not a refusal. `missing` names the **leaves**, the canonical
fields nothing maps, because the fix is always a mapping; `via` names the blocked metrics
between:

```text
UnreachableMetric(name='margin_rate', missing=('cogs',), via=('margin',))
```

Map `cogs` and both `margin` and `margin_rate` unblock. `evidence.unresolved` names the edit
that would, and the recipes the catalog offers for it.

## Other families

- **`PlanError`**: `ContractViolation` (expand/contract) and `RenameTargetMissing`
  (stale `renamed_from`), raised by `plan()`; see [plan-a-change](plan-a-change.md).
- **`PlannerError`**: request-time refusals (`UnknownMember`, `UnreachableAtGrain`,
  `AmbiguousDimension`, `UnsupportedFilter` with a stable `.reason`); see
  [plan-a-metric-request](plan-a-metric-request.md).
- **`StepContractViolation`** is raised at **run time** by the wrapper bloomery emits
  into your warehouse, when a step's output contradicts its manifest.
- **`InvariantViolated`** is never your spec's fault. Report it, with the spec.

## Advisories

Some findings are legal, compile correctly, and are still worth knowing. They are
**advisories** on `SpecEvidence.advisories`, never raised and never logged. Branch on
`code`, a closed list, not on the message:

| Code | Means |
|---|---|
| `undeclared_audience` | a mart publishes a `pii` or `secret` column with no `grants:` saying who reads it |

Anything bloomery can show makes a number wrong is a refusal, never an advisory.

Documentation: [errors](https://morzecrew.github.io/bloomery/latest/reference/errors/),
[assess a spec](https://morzecrew.github.io/bloomery/latest/how-to/evaluate-a-spec/).
