# Bloomery

Bloomery is an entity-first spec compiler and metric planner, built as a pure function
library: declarative specs go in, byte-reproducible SQL artifacts and query plans come
out. It is deterministic, fail-closed, and tenant-agnostic — the same specs compile to
the same bytes forever, anything plausible-but-wrong is refused with a named error, and
the compiler never knows what a tenant is.

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

New here? Start with the [Introduction](get-started/introduction.md) to see the problem
bloomery solves and how the spec kinds fit together, then read the
[Concepts](concepts/specs-and-catalog.md) pages for the domain model, the
[compile pipeline](concepts/compile-pipeline.md), the
[wide-mart gold layer](concepts/wide-marts.md), and the
[guardrails](concepts/guardrails.md) that make fail-closed concrete.
