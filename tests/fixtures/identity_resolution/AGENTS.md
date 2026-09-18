<!-- torve:managed tests/fixtures/identity_resolution — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/identity_resolution/`

### S-0026/D-4 — `ASSUMED` (Testing strategy and fixture corpus)

The fixture corpus is exactly spec §7.7 (`minimal`, `ecom_basic`, `fanout_trap`, `semi_additive`, `messy_types`, `multi_source`, `evolution_v1..v5`), stored as YAML under `tests/fixtures/<name>/`, loaded only via public `load_project`/`load_catalog`. Consequence: the corpus is also the doc example set and future LLM-eval set — fixture edits carry corpus-level review weight. `multi_source` covers deterministic two-source union merge only; identity xref is out of scope for v0.1.

- Paths: `tests/fixtures/identity_resolution/entity_model.yaml` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0034/D-36 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13; narrowed by D41)* **Step outputs are entities, as §5.8 always said — now actually.** Outputs previously lived only inside `StepIR`, so §5.8's "downstream mappings, marts, and metrics reference them like any silver entity" and §5.4's "downstream models are typechecked against `produces`" were both untrue: a mart over a step output was refused with *"mart base names entity 'customer', which no mapping lowers"*. `build_project_ir` now synthesizes one `EntityIR` per output. Three fields have no natural value and are **chosen**, recorded rather than left to be discovered: `source` names the relation the step itself writes (an entity's `source` is mandatory and a step has no bronze one — this is the honest reading, since that is where the rows come from as far as anything downstream can tell); `materialization`/`scd` are `FULL`/`TYPE1`, matching what the wrapper already declares, because an IR disagreeing with its own artifact is worse than an arbitrary-but-consistent choice; and each column's `expr` is the column referring to itself, which is what a downstream model selecting from the relation would emit anyway.

- Paths: `src/bloomery/emit/dbt/__init__.py` `tests/fixtures/identity_resolution/marts.yaml`

### S-0034/D-37 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-08, M13)* **`EntityIR.produced_by` marks a step-written entity, and the emitter skips it.** The entity exists so the rest of the compiler can reference it; the relation is written by the step's generated wrapper. Without the marker the emitter's entity loop would emit a *second* model at the same path — precisely the two-writers-one-relation collision D28 refuses everywhere else, arrived at from the inside.

- Paths: `tests/fixtures/identity_resolution/marts.yaml`

### S-0034/D-49 — `ASSUMED` (The step registry: referenced implementations)

*(2026-08-09)* **D41 is built: metrics and `reconcile` reach step outputs, through a declared canonical link.** What was missing was a *surface*, not a mechanism. A metric is reachable iff every leaf of its `requires` closure is **available**, and a canonical field is available iff something draws a `canonical` edge to it — which only mapped entity fields could. So a step's columns were never available and any metric over one was unreachable, for a reason narrower than D41's own wording ("metric resolution keys on mappings") suggested. `StepWiring` gains `canonical: {<output>: {<column>: <canonical_field>}}`. On the **wiring**, not in the manifest: canonical names are the authored spec's vocabulary, and a manifest naming them could not be reused by a second project spelling them differently — the fork §5.7 exists to refuse. Never inferred from a matching column name, which is D43's argument about references applied to the same temptation. Nothing about metric resolution changed: the link draws the ordinary `canonical` edge and reachability follows. `reconcile` needed a second, unrelated repair — it resolved sides against *declared and mapped* entities, and a step output is neither, so a check naming one was refused as "declared but no mapping targets it", which is true and useless since the step writes the relation. Both kinds now answer through one `_SideEntity` view (field names and key), so the check asks what it needs rather than branching on provenance; declared-but-unmapped stays refused, which was always the real point. The refusal's wording now names both ways a relation can exist.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/resolve/graph.py` `src/bloomery/resolve/refs.py` `src/bloomery/spec/steps.py` `tests/fixtures/identity_resolution/catalog.yaml` `tests/fixtures/identity_resolution/steps.yaml` `tests/unit/test_quality/test_reconcile.py` `tests/unit/test_steps/test_step_canonicals.py` `tests/unit/test_unresolved.py`

<!-- /torve:managed -->
