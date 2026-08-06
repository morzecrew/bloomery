# Bloomery

Bloomery is an entity-first spec compiler and metric planner, built as a pure function
library: declarative specs go in, byte-reproducible SQL artifacts and query plans come
out. It is deterministic, fail-closed, and tenant-agnostic — the same specs compile to
the same bytes forever, anything plausible-but-wrong is refused with a named error, and
the compiler never knows what a tenant is.

It does three things:

- **Compiles specs into artifacts** — Catalog, EntityModel, Mapping, MetricSet, and
  Marts specs become SQLMesh, dbt, and Cube models, audits, and MetricFlow semantic
  manifests.
- **Plans metric queries** — a `MetricRequest` becomes SQL over a wide, pre-joined
  mart, with no query-time joins and no execution. Behind the stable request/plan
  contract sits an embedded, render-only MetricFlow — pinned, driven entirely
  in-process, never connected to a database.
- **Diffs spec versions** — two compiled versions produce a plan in which every change
  is classified (additive, widening, rename, restating, breaking), with backfill scope
  and downstream impact computed from the dependency graph.

New here? Start with the [Introduction](get-started/introduction.md) to see the problem
bloomery solves and how the spec kinds fit together, then read the
[Concepts](concepts/specs-and-catalog.md) pages for the domain model, the
[compile pipeline](concepts/compile-pipeline.md), the
[wide-mart gold layer](concepts/wide-marts.md), and the
[guardrails](concepts/guardrails.md) that make fail-closed concrete.
