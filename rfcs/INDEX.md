# RFCs

Design proposals for **bloomery**, the entity-first spec compiler. This directory is
committed — the RFC corpus is a project deliverable. Five preserved input documents:
[`_original-smelter-spec.md`](_original-smelter-spec.md) (the original specification),
[`_bloomery-changes.md`](_bloomery-changes.md) (scope expansion: query planning, wide
marts, role-playing dimensions),
[`_bloomery-metricflow-pivot.md`](_bloomery-metricflow-pivot.md) (the planner backend
pivot: embedded MetricFlow replaces the hand-written planner lowering; milestones
renumbered to M1–M11 with an M4.5 verification gate),
[`_bloomery-query-vocabulary.md`](_bloomery-query-vocabulary.md) (Document 4: the
filter/sort/pagination DSL and closed refusal list → RFC 0015), and
[`_bloomery-quality-and-steps.md`](_bloomery-quality-and-steps.md) (Document 5:
declarative data quality and the step registry → RFCs 0016–0017). Where RFCs diverge
from any input document, the RFCs win.

## Allocating a number

The next free number is **0018**. Before creating an RFC, glance at the table
below (or `ls` this directory) and take the next unused integer — numbers
collide when minted in parallel. Update this table in the same change.

Filename: `NNNN-kebab-title.md`. Keep the `# RFC NNNN — Title` H1 and the
number in the filename in sync.

## Index

| # | Title | Status | One-line |
|---|---|---|---|
| [0001](0001-project-foundations.md) | Project foundations | ✅ Complete | Morze house scaffold scaled to one package: uv + hatchling + hatch-vcs, `just quality` as the single gate, seven SHA-pinned workflows, zensical docs, tag-driven release; deliberate divergences from forze: committed `rfcs/`, mermaid over d2, no CI sharding. Shipped 2026-08-07; docs floors/ratchets deliberately deferred to v0.1.0 (§8). |
| [0002](0002-spec-layer-and-errors.md) | Spec layer and error model | ✅ Complete | Four strict frozen Pydantic spec kinds + `Project`, pure text-in loaders, total `BloomeryError` hierarchy with source paths, batched parse errors; shape-only validation (references defer to resolve); adds PyYAML; `materialization` explicit-with-derived-default. |
| [0003](0003-ir-and-determinism.md) | IR and determinism contract | ✅ Complete | Frozen dataclass IR with all-tuple ordered collections, SQL stored as canonical dialect-neutral SQLGlot text, `blm1:`-prefixed sha256 fingerprint, floats banned, determinism enforced by cross-`PYTHONHASHSEED` subprocess tests; unreachable metrics are IR members. |
| [0004](0004-types-and-transforms.md) | Logical types and the transform registry | ✅ Complete | Closed 7-type LogicalType set; closed versioned transform whitelist (22 starters + `convert`) built as SQLGlot ASTs only; chain typechecking with tracked decimal precision (implicit widening, explicit narrowing); immutable default registry + explicit overlay, sorted iteration. |
| [0005](0005-resolution.md) | Resolution: dependency DAG, recipes, reachability | ✅ Complete | One DAG over source columns, fields, canonical recipes, metrics; the compiler validates recorded recipes but never chooses; metric reachability with specific missing leaves stored in IR; `CircularDerivation` names cycles; topo order with lexicographic tie-breaks; cross-spec reference checks live here, batched. |
| [0006](0006-guardrails.md) | Guardrails: refusing plausible-but-wrong arithmetic | ✅ Complete | Seven guardrails (unit, tax basis, currency, grain/fan-out, additivity, path conflict, range sanity) as batched compile errors — except path conflict, which emits both columns plus a reconciliation audit; unit/tax metadata propagates via `canonical:` links; `unknown` in arithmetic is an error. |
| [0007](0007-plan-and-change-classification.md) | Plan: spec diff and change classification | ✅ Complete | Pure structural diff of two IRs into ADDITIVE/WIDENING/RENAME/RESTATING/BREAKING; renames only via explicit `renamed_from`; expand/contract enforced (`ContractViolation` on dropping/narrowing metric-referenced fields); backfill scope + downstream impact from IR edges. Shipped 2026-08-07 (M9); amended: identity beats staleness — an already-applied `renamed_from` is inert, `plan(ir, ir)` empty for every IR (D8). |
| [0008](0008-ports-and-emitters.md) | Ports and emitters: targets, dialects, naming | 🚧 In progress | Three independent Protocol ports (target/dialect/naming); file-shaped text artifacts as data (settles files-vs-Python-models); fail-loud `UnsupportedByTarget`; fingerprint stamped in artifact headers. Shipped 2026-08-07 (M2–M10): SQLMesh+Cube+dbt emitters over DuckDB+Postgres+Trino, D6 reversed (`gold.dim_date` emitted per RFC 0013); remaining: engine matrix beyond Postgres, containerized target e2e tiers. |
| [0009](0009-testing-strategy.md) | Testing strategy and fixture corpus | 🚧 In progress | Seven layers fastest-first (unit → golden matrix → Hypothesis → DuckDB execution → engine containers → target e2e incl. SQLMesh no-op replan → three-way equivalence); curated fixture corpus (`minimal`…`evolution_v1..v5` + planner fixtures) doubles as docs examples and future eval set; determinism + tenant-agnosticism guard tests; hydration bench. Shipped 2026-08-07: tiers 1–4, Postgres engine tier, bench lane, and the local SQLMesh replan no-op e2e; remaining: Trino/Spark engines, Cube container, dbt parse, three-way equivalence (nightly). |
| [0010](0010-marts-and-role-playing.md) | Marts and role-playing dimensions | ✅ Complete | Gold = wide pre-joined marts as a fifth spec kind, flattened at build time (no query-time joins); measure grain must strictly equal mart grain; `DimensionRef(dimension, role)` modeled once, lowered per consumer; date roles expand to day/week/month/quarter/year; fan-out refused at compile time. |
| [0011](0011-native-planner.md) | Planner contract: MetricRequest → QueryPlan | ✅ Complete | The stable fourth-port contract: request/QueryPlan/Explanation types, refuse-don't-guess (`UnreachableAtGrain` on cross-grain), RowPolicy-in-every-scan, limit clamping, error taxonomy — binding regardless of backend; the native SQL assembly/additivity lowering it originally specified is superseded by RFC 0013 but retained as the behavior spec. Shipped 2026-08-07 (M7) as the contract behind `MetricFlowPlanner`. |
| [0012](0012-compiled-semantic.md) | CompiledSemantic: serializable planner artifact | ❌ Superseded | Superseded by RFC 0014 (MetricFlow pivot): the bespoke canonical-JSON CompiledSemantic is replaced by MetricFlow's transformed manifest; the surviving principles (deterministic serialization, never-migrate, LRU-not-resident-memory) carry over. Kept as the record of the pre-pivot design. |
| [0013](0013-metricflow-backend.md) | MetricFlow backend: manifest emitter and planner adapter | ✅ Complete | Embedded render-only MetricFlow (`==0.211.*`, pinned internals + canary test) replaces hand-written planner lowering: `emit_manifest` maps IR marts → semantic models (one mart = one model, sorted, time spine from the catalog date dimension — reversing RFC 0008 D6), coverage precheck keeps refuse-don't-guess ahead of delegation, names.py bridges dunder names, Jinja filters are the fuzz-tested injection boundary, errors translate to bloomery taxonomy. Shipped 2026-08-07 (M6–M7, R1–R9); amended: upstream `transform()` orders ratio `input_measures` via a builtin set — re-sorted post-transform (D15); the R10 equivalence oracle is RFC 0009's nightly tier. |
| [0014](0014-hydration-and-caching.md) | Hydration and caching of the planner artifact | ✅ Complete | Two-level cache for the transformed manifest: L2 bytes keyed by `HydrationKey(spec_fingerprint, bloomery_version, metricflow_version)` stored by the caller, L1 in-process LRU of hydrated `SemanticManifestLookup` (~1.6 MB/entry, configurable size); budgets 50 ms cold / 10 ms warm CI-asserted; version mismatch is a cache miss by construction, never a migration. Shipped 2026-08-07 (M8); measured 10.5 ms median cold / ~1.54 MB per lookup. |
| [0015](0015-query-vocabulary.md) | Query vocabulary: filters, sort, pagination | ✅ Complete | CNF filter model (`Clause = Predicate \| AnyOf`, one disjunction level) replacing the flat FilterExpr: drop `between`, split `contains` into `like`/`ilike`, string-carrier scalars with the non-finite fail-open guard, no sort-nulls control, limit-only paging; new public `planner/parse.py` normalizes Mongo-flavored JSON (De Morgan → complement → CNF → clause cap) before refusing; the closed `KNOWN_UNSUPPORTED` refusal list with drift-guard test is the deliverable. Amends shipped RFC 0003/0011/0013 surface (pre-0.1 migration). Shipped 2026-08-07 (M14); the Forze app adapter is a deliberate non-goal, not a remainder. |
| [0016](0016-data-quality.md) | Data quality: declarative cleansing, dispositions, quarantine | 📝 Draft | Run-time row dispositions (repair/flag/quarantine/fail — deliberately no drop) on a closed rule catalogue + mandatory-tie-break dedupe + referential `unknown_member` + reconcile; coercion failure becomes the implicit `coercible` rule (retires `on_unmapped_enum`, supersedes RFC 0008 D7); one replayable `__reject` table per entity with required retention/redaction; `_quality_flags` on silver, `has_quality_flags` on marts, quality mart without a tenant column (invariant #3); plan() gains `replay_scope`; conservation-law property doubles as a runtime audit. Wave M12. |
| [0017](0017-step-registry.md) | The step registry: referenced implementations | 📝 Draft | Specs reference implementations, never contain them: four-tier ladder (transform → sql_macro → sql_model → python_model), `StepRegistry` as a pure compile input (no dynamic loading), manifests with typed contracts trusted at compile and enforced by a generated non-optional runtime assertion, determinism tiers with nondeterministic = compile error, `runtime_lock` in step identity so dependency bumps classify RESTATING; parameterize-never-fork. Wave M13, after RFC 0016. |

## Status legend

- 📝 **Draft** — proposed, not started
- 🚧 **In progress** — partially shipped
- ✅ **Complete** — fully shipped
- ❌ **Rejected / withdrawn**
