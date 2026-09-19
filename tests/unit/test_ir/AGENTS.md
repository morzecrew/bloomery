<!-- torve:managed tests/unit/test_ir — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_ir/`

### S-0020/D-3 — `ASSUMED` (Intermediate representation and determinism contract)

`project_fingerprint` = `"blm1:" + sha256(canonical bytes)`; includes `bloomery_ir_version`; stable within a bloomery version, explicitly not across versions.

- Paths: `src/bloomery/ir/fingerprint.py` `tests/unit/test_ir/test_fingerprint.py` `tests/unit/test_ir/test_nodes.py`

### S-0023/D-7 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Path conflict does not raise (`PathConflict` is not an error class): the compiler emits the derived column, a `<name>__direct` shadow, and a `RECONCILE` `AuditIR`. The forbidden thing is the silent choice; both paths are valid, so the refusal targets the silence, not the spec.

- Paths: `src/bloomery/emit/lower/predicates.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/guardrails/conflict.py` `src/bloomery/guardrails/quality.py` `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `src/bloomery/spec/mapping.py` `tests/fixtures/path_conflict/entity_model.yaml` `tests/fixtures/path_conflict/mapping.yaml` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_guardrails/test_conflict.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_ir/test_lower.py` `tests/unit/test_spec/test_mapping.py`

### S-0033/D-2 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

`OnFail = flag | quarantine | fail` (v1 — `repair` deferred, decision 17; landed in D87), explicit per rule, never a global default. Deliberately no `drop`: quarantine is drop plus recoverability; deletion happens via retention policy, with a paper trail.

- Paths: `src/bloomery/ir/nodes.py` `src/bloomery/plan/diff.py` `src/bloomery/spec/quality.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_plan/test_quality_changes.py` `tests/unit/test_spec/test_quality.py`

### S-0033/D-19 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

Three-valued logic: each rule defines a violation predicate and fires only when it is definitively TRUE — NULL-involved comparisons evaluating to SQL `UNKNOWN` do **not** fire (`not_null`/`coercible` own nulls; declare them if nulls are invalid). Applies to `range`/`length`/`pattern`/`in_enum`/`in_set`/`expression`/`referential` — a NULL fk is not an orphan. Corrects Document 5's referential lowering: the bare `COALESCE(fk, '__unknown__')` sketch was wrong (it maps a NULL fk to the unknown member); the lowering is `CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE fk END`.

- Paths: `src/bloomery/emit/dbt/__init__.py` `src/bloomery/ir/nodes.py` `src/bloomery/quality/predicates.py` `tests/fixtures/quality_precedence/mapping_dups.yaml` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_quality/test_predicates.py`

### S-0035/D-1 — `ASSUMED` (Public surface and stability policy)

**Signature closure** is the root-namespace rule: any type appearing in a public signature, return, generic argument, or returned-dataclass field is itself exported from `bloomery`. **Fourteen** types are added under it (§5.1), the walk stopping at handle types (decision 9). Enforced by a unit test walking `get_type_hints`, not by review — a walk that decision 10 has to make runnable first.

- Paths: `src/bloomery/__init__.py` `src/bloomery/evidence.py` `src/bloomery/ir/nodes.py` `tests/unit/test_advisories.py` `tests/unit/test_ir/test_nodes.py` `tests/unit/test_package.py` `tests/unit/test_signature_closure.py`

### S-0079/D-2 — `LOCKED` (Determinations reach the IR and the rollup lowering)

`bloomery_ir_version` moves 19 → 20 with the field, and `ProjectIR`'s docstring gains the sentence saying why. The default of `()` is not a reason to skip it: the canonical encoder writes each dataclass's field count and names per instance, so every project with an entity column re-fingerprints whether or not it declares anything

- Paths: `src/bloomery/ir/nodes.py` `tests/unit/test_ir/**`
- Consequence: Every project's fingerprint moves and `plan()` refuses to diff a version 19 IR against a version 20 one, which is the refusal that makes the change loud. The version is declared once, on the dataclass — `test_the_compiler_emits_the_declared_ir_version` is what stops it being bumped in one of two places
- Check: `uv run pytest tests/unit/test_ir/test_nodes.py tests/unit/test_determinism_guard.py -q` (shadow; runs as `decision:S-0079/D-2`, no log entry owed)

<!-- /torve:managed -->
