# Bloomery

The worst failure in a config-driven data platform is not a crash. It is a number that
looks right and is wrong — an order-level shipping cost joined to line items and summed
three times over, a net price subtracted from a gross cost, an average stored and then
re-averaged. Every one of those passes syntax checks, type checks and code review,
because nothing in the stack knows what the columns *mean*.

Bloomery is an entity-first spec compiler that does know, and refuses. Declarative specs
carry grains, units, tax bases and additivity classes; anything that would produce a
plausible-but-wrong number is a compile error with a source path, not a warning. It is a
pure function library — specs in, byte-reproducible SQL artifacts and query plans out,
with no clock, no randomness, and no filesystem anywhere in the compile path.

It does four things:

- **Compiles specs into artifacts** — Catalog, EntityModel, Mapping, MetricSet, Marts
  and StepSet documents become SQLMesh, dbt, and Cube models, audits, and MetricFlow
  semantic manifests, with [declarative data quality](concepts/data-quality.md) —
  cleansing, dedupe, quarantine and replay — lowered into the same pipeline.
- **Plans metric queries** — a `MetricRequest` becomes SQL over a wide, pre-joined
  mart, with no query-time joins and no execution. Behind the stable request/plan
  contract sits an embedded, render-only MetricFlow — pinned, driven entirely
  in-process, never connected to a database.
- **Diffs spec versions** — two compiled versions produce a plan in which every change
  is classified (additive, widening, rename, restating, breaking), with backfill scope
  and downstream impact computed from the dependency graph.
- **Assesses a spec** — `evaluate()` returns everything knowable without touching data:
  what is reachable, what is not and which leaf is missing, and every refusal with its
  source path. Refusals come back as a *value*, so a draft mid-edit still reports what
  it would give you.

All four are reachable from a shell as well as from Python — see
[Use the CLI](how-to/use-the-cli.md).

## Where to start

New here? Read the [Introduction](get-started/introduction.md) for the problem bloomery
removes, how the spec kinds fit together, and — just as important — what it deliberately
does not do. Then work through the [Quickstart](get-started/quickstart.md), which takes
one small project from YAML to compiled artifacts to a planned query.

If you would rather see it run than read about it, the four
[examples](get-started/examples.md) are self-contained and execute everything they claim
— including one that builds the same mart with SQLMesh and with dbt and compares the two
row for row.

For the model underneath, the [Concepts](concepts/specs-and-catalog.md) pages cover the
domain model, the [compile pipeline](concepts/compile-pipeline.md), the
[wide-mart gold layer](concepts/wide-marts.md), and the
[guardrails](concepts/guardrails.md) that make fail-closed concrete.
