<!-- torve:managed tests/fixtures/multi_source — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/multi_source/`

### S-0026/D-4 — `ASSUMED` (Testing strategy and fixture corpus)

The fixture corpus is exactly spec §7.7 (`minimal`, `ecom_basic`, `fanout_trap`, `semi_additive`, `messy_types`, `multi_source`, `evolution_v1..v5`), stored as YAML under `tests/fixtures/<name>/`, loaded only via public `load_project`/`load_catalog`. Consequence: the corpus is also the doc example set and future LLM-eval set — fixture edits carry corpus-level review weight. `multi_source` covers deterministic two-source union merge only; identity xref is out of scope for v0.1.

- Paths: `tests/fixtures/identity_resolution/entity_model.yaml` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_fixtures.py`

### S-0041/D-2 — `LOCKED` (Deterministic union merge)

**No new syntax.** Multi-source is expressed by two mappings naming one `target:`. A `sources:` list or a `union:` kind would duplicate what `target:` already says, with the failure mode that the two can disagree.

- Paths: `tests/fixtures/multi_source/mapping_platform.yaml`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-14 — `LOCKED` (Deterministic union merge)

**P1 refuses `dedupe:` and `quarantine:` on a merged entity** (§5.6). The boundary is drawn at those two block-level declarations because it is exact, not approximate: every use of the per-source row identity in the silver lowering sits behind one of them — the reject projection, the conservation audit, the dedupe sort key, the replay merge — and the `on_fail: fail` audit path references it zero times. A merged entity may still carry field and row rules (`flag`/`fail`), `assert:`, `references:` and `coverage:`. Consequence: P1 ships the union to entities with no dedupe and no quarantine, which is the shape the `multi_source` fixture needs, and the two blocks return in P2.

- Paths: `src/bloomery/guardrails/quality.py` `src/bloomery/plan/diff.py` `tests/fixtures/multi_source/entity_model.yaml` `tests/unit/test_plan/test_diff.py` `tests/unit/test_quality/test_reconcile.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0041/D-22 — `ASSUMED` (Deterministic union merge)

**Answers D8 (`OPEN`) — no acknowledgement, and §9's premise for wanting one is false.** A mapping naming a field the entity model does not declare is *already* refused: `MissingReference: mapping maps unknown field 'loyalty_teir' of entity 'order'`, measured on this tree against the existing single-mapping path. So a misspelling is a compile error rather than a silent NULL, and the only thing an acknowledgement could mark is a correctly-spelled field a source deliberately lacks — the legitimate case. Adding a key for that would also strain D2's "no new syntax", to flag the one shape the RFC agrees is fine. §9's risk row is corrected in place.

- Paths: `tests/fixtures/multi_source/mapping_legacy.yaml`

<!-- /torve:managed -->
