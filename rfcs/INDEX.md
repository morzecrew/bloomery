# RFCs

Design proposals for **bloomery**, the entity-first spec compiler. This directory is
committed — the RFC corpus is a project deliverable. Three preserved input documents:
[`_original-smelter-spec.md`](_original-smelter-spec.md) (the original specification),
[`_bloomery-changes.md`](_bloomery-changes.md) (scope expansion: query planning, wide
marts, role-playing dimensions), and
[`_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md) (the planner backend
pivot: embedded MetricFlow replaces the hand-written planner lowering; milestones
renumbered to M1–M11 with an M4.5 verification gate). Where RFCs diverge from any input
document, the RFCs win.

## Allocating a number

The next free number is **0015**. Before creating an RFC, glance at the table
below (or `ls` this directory) and take the next unused integer — numbers
collide when minted in parallel. Update this table in the same change.

Filename: `NNNN-kebab-title.md`. Keep the `# RFC NNNN — Title` H1 and the
number in the filename in sync.

## Index

| # | Title | Status | One-line |
|---|---|---|---|
| [0001](0001-project-foundations.md) | Project foundations | 📝 Draft | Morze house scaffold scaled to one package: uv + hatchling + hatch-vcs, `just quality` as the single gate, seven SHA-pinned workflows, zensical docs, tag-driven release; deliberate divergences from forze: committed `rfcs/`, mermaid over d2, no CI sharding. |
| [0002](0002-spec-layer-and-errors.md) | Spec layer and error model | 📝 Draft | Four strict frozen Pydantic spec kinds + `Project`, pure text-in loaders, total `BloomeryError` hierarchy with source paths, batched parse errors; shape-only validation (references defer to resolve); adds PyYAML; `materialization` explicit-with-derived-default. |
| [0003](0003-ir-and-determinism.md) | IR and determinism contract | 📝 Draft | Frozen dataclass IR with all-tuple ordered collections, SQL stored as canonical dialect-neutral SQLGlot text, `blm1:`-prefixed sha256 fingerprint, floats banned, determinism enforced by cross-`PYTHONHASHSEED` subprocess tests; unreachable metrics are IR members. |
| [0004](0004-types-and-transforms.md) | Logical types and the transform registry | 📝 Draft | Closed 7-type LogicalType set; closed versioned transform whitelist (22 starters + `convert`) built as SQLGlot ASTs only; chain typechecking with tracked decimal precision (implicit widening, explicit narrowing); immutable default registry + explicit overlay, sorted iteration. |
| [0005](0005-resolution.md) | Resolution: dependency DAG, recipes, reachability | 📝 Draft | One DAG over source columns, fields, canonical recipes, metrics; the compiler validates recorded recipes but never chooses; metric reachability with specific missing leaves stored in IR; `CircularDerivation` names cycles; topo order with lexicographic tie-breaks; cross-spec reference checks live here, batched. |
| [0006](0006-guardrails.md) | Guardrails: refusing plausible-but-wrong arithmetic | 📝 Draft | Seven guardrails (unit, tax basis, currency, grain/fan-out, additivity, path conflict, range sanity) as batched compile errors — except path conflict, which emits both columns plus a reconciliation audit; unit/tax metadata propagates via `canonical:` links; `unknown` in arithmetic is an error. |
| [0007](0007-plan-and-change-classification.md) | Plan: spec diff and change classification | 📝 Draft | Pure structural diff of two IRs into ADDITIVE/WIDENING/RENAME/RESTATING/BREAKING; renames only via explicit `renamed_from`; expand/contract enforced (`ContractViolation` on dropping/narrowing metric-referenced fields); backfill scope + downstream impact from IR edges. |
| [0008](0008-ports-and-emitters.md) | Ports and emitters: targets, dialects, naming | 📝 Draft | Three independent Protocol ports (target/dialect/naming); file-shaped text artifacts as data (settles files-vs-Python-models); fail-loud `UnsupportedByTarget`; v0.1 ships SQLMesh+Cube+dbt over DuckDB+Postgres+Trino; date dimension and quarantine-as-IR deferred; fingerprint stamped in artifact headers. |
| [0009](0009-testing-strategy.md) | Testing strategy and fixture corpus | 📝 Draft | Seven layers fastest-first (unit → golden matrix → Hypothesis → DuckDB execution → engine containers → target e2e incl. SQLMesh no-op replan → native-vs-Cube equivalence); curated fixture corpus (`minimal`…`evolution_v1..v5` + planner fixtures) doubles as docs examples and future eval set; determinism + tenant-agnosticism guard tests; hydration bench; 100% branch coverage on guardrails. |
| [0010](0010-marts-and-role-playing.md) | Marts and role-playing dimensions | 📝 Draft | Gold = wide pre-joined marts as a fifth spec kind, flattened at build time (no query-time joins); measure grain must strictly equal mart grain; `DimensionRef(dimension, role)` modeled once, lowered per consumer; date roles expand to day/week/month/quarter/year; fan-out refused at compile time. |
| [0011](0011-native-planner.md) | Planner contract: MetricRequest → QueryPlan | 📝 Draft | The stable fourth-port contract: request/QueryPlan/Explanation types, refuse-don't-guess (`UnreachableAtGrain` on cross-grain), RowPolicy-in-every-scan, limit clamping, error taxonomy — binding regardless of backend; the native SQL assembly/additivity lowering it originally specified is superseded by RFC 0013 but retained as the behavior spec. |
| [0012](0012-compiled-semantic.md) | CompiledSemantic: serializable planner artifact | ❌ Superseded | Superseded by RFC 0014 (MetricFlow pivot): the bespoke canonical-JSON CompiledSemantic is replaced by MetricFlow's transformed manifest; the surviving principles (deterministic serialization, never-migrate, LRU-not-resident-memory) carry over. Kept as the record of the pre-pivot design. |
| [0013](0013-metricflow-backend.md) | MetricFlow backend: manifest emitter and planner adapter | 📝 Draft | Embedded render-only MetricFlow (`==0.211.*`, pinned internals + canary test) replaces hand-written planner lowering: `emit_manifest` maps IR marts → semantic models (one mart = one model, sorted, time spine from the catalog date dimension — reversing RFC 0008 D6), coverage precheck keeps refuse-don't-guess ahead of delegation, names.py bridges dunder names, Jinja filters are the fuzz-tested injection boundary, errors translate to bloomery taxonomy; M4.5 verification complete — all four tasks (V1–V4) pass (2026-08-07), cleared for implementation. |
| [0014](0014-hydration-and-caching.md) | Hydration and caching of the planner artifact | 📝 Draft | Two-level cache for the transformed manifest: L2 bytes keyed by `HydrationKey(spec_fingerprint, bloomery_version, metricflow_version)` stored by the caller, L1 in-process LRU of hydrated `SemanticManifestLookup` (~1.6 MB/entry, configurable size); budgets 50 ms cold / 10 ms warm CI-asserted; version mismatch is a cache miss by construction, never a migration. |

## Status legend

- 📝 **Draft** — proposed, not started
- 🚧 **In progress** — partially shipped
- ✅ **Complete** — fully shipped
- ❌ **Rejected / withdrawn**
