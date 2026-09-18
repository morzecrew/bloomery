<!-- torve:managed pages/docs/how-to — rendered from the corpus; do not edit by hand -->

## Decisions governing `pages/docs/how-to/`

### S-0024/D-5 — `ASSUMED` (Plan: spec diff and change classification)

Expand/contract is enforced in this stage: dropping/narrowing a field referenced by a metric reachable in `new`, or by an old-reachable metric that vanished in the same plan, raises `ContractViolation` (`PlanError`). Deprecation must land in a prior version. This is the stage's only refusal — BREAKING changes are classified and returned, not raised.

- Paths: `pages/docs/how-to/evolve-a-spec.md` `src/bloomery/errors.py` `src/bloomery/plan/diff.py`

### S-0033/D-56 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12 fix)* **The dialects a `pattern` is checked against are the shipped ports, never the registry.** `registered_dialects()` is process-global and mutable, so an extension dialect registered by an unrelated import could decide whether an existing project compiles — the ambient dependency S-0020 exists to forbid, and one no golden would catch. The checked set is the constant `PATTERN_TARGET_DIALECTS = (duckdb, postgres, trino)`, overridable by an explicit argument the caller supplies. Recorded consequence: an extension dialect is no longer checked at compile time. Checking it would mean plumbing a dialect set into `build_project_ir`, which is dialect-free by construction and right to be — a project is portable or it is not, and the guardrail stage has no target. Named as the escape hatch, not built.

- Paths: `pages/docs/how-to/add-quality-rules.md` `src/bloomery/compile.py` `src/bloomery/dialects/__init__.py` `src/bloomery/quality/pattern.py` `tests/unit/test_compile.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_guardrails/test_quality.py` `tests/unit/test_quality/test_edges.py`

### S-0062/D-10 — `LOCKED` (Ownership, classification and grants)

`secret` on a column a **published relation** carries is a refusal — a mart or a rollup, unconditionally. A published relation is the thing `secret` says this column is not part of, so the two statements cannot both hold. Independent of redaction, and of whether anything is granted.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0062/D-11 — `LOCKED` (Ownership, classification and grants)

A `pii`/`secret` column reaching a relation that **admits a role its source entity does not** is a refusal — a set difference, not a superset test, so disjoint grant sets are refused too: a role that can read the mart and not the entity is the leak whether or not the mart also admits the entity's roles; an **undeclared** audience on either side is an advisory, not a refusal. Refusing the unknown case would refuse every project managing gold grants outside bloomery, and the compiler can only call a contradiction where it holds both statements.

- Paths: `pages/docs/how-to/annotate-a-spec.md` `src/bloomery/errors.py` `src/bloomery/evidence.py` `src/bloomery/guardrails/classification.py` `src/bloomery/guardrails/stage.py` `tests/unit/test_classification_guard.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0063/D-2 — `LOCKED` (Exposures and downstream consumers)

An exposure naming an undeclared metric or mart is refused. An exposure pointing at nothing reports clean, which is the failure mode the feature exists to remove.

- Paths: `pages/docs/how-to/declare-an-exposure.md` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/errors.py` `src/bloomery/guardrails/exposures.py` `src/bloomery/guardrails/stage.py` `src/bloomery/resolve/graph.py` `tests/unit/test_guardrails/test_exposures.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
