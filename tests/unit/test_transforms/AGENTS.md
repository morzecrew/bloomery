<!-- torve:managed tests/unit/test_transforms — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/unit/test_transforms/`

### S-0020/D-2 — `ASSUMED` (Intermediate representation and determinism contract)

SQL is stored in the IR as canonical dialect-neutral SQLGlot text (`SqlExpr`), re-parsed at emit. Consequence: SQLGlot version changes can change fingerprints; the exact pin (D4 §5.5) makes that a deliberate event.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/emit/lower/marts.py` `src/bloomery/ir/nodes.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_dialects/test_postgres.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`

### S-0021/D-3 — `ASSUMED` (Logical types and the transform registry)

Starter set is exactly: `trim upper lower to_string to_int to_decimal to_bool parse_ts parse_date to_utc enum_map coalesce nullif split_part regex_extract strip_prefix strip_suffix multiply divide round abs concat json_path`, plus `convert` as the explicit currency-conversion marker required by the currency guardrail (S-0023).

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py` `tests/unit/test_transforms/test_registry.py`

### S-0025/D-3 — `ASSUMED` (Ports and emitters: targets, dialects, naming)

Capability mismatch behavior is fail-loud: `UnsupportedByTarget` naming entity + feature. Silent degradation is forbidden.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/trino.py` `src/bloomery/emit/cube/__init__.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/lower/silver.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/errors.py` `src/bloomery/spec/quality.py` `src/bloomery/transforms/_builtins.py` `tests/property/test_compile_properties.py` `tests/unit/test_emit/test_base.py` `tests/unit/test_emit/test_quality_artifacts.py` `tests/unit/test_emit/test_quality_mart.py` `tests/unit/test_quality/test_text_rules.py` `tests/unit/test_transforms/test_builtins.py`

### S-0044/D-6 — `ASSUMED` (ISO 8601 timestamps across dialects)

`parse_date: ISO8601` is in scope with `parse_ts`. It lowers the same way, to `CAST(… AS DATE)`, and a date has no `T` — but the two are one branch in one builder, and fixing one while leaving the other reads as an oversight rather than a boundary.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py`

### S-0045/D-5 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement.

- Paths: `src/bloomery/dialects/base.py` `src/bloomery/dialects/postgres.py` `tests/engines/test_postgres_spellings.py` `tests/engines/test_type_conformance.py` `tests/execution/test_type_conformance.py` `tests/support/type_conformance.py` `tests/unit/test_dialects/test_base.py` `tests/unit/test_transforms/test_type_conformance_corpus.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0046/D-1 — `ASSUMED` (Transform types the engine agrees with)

A builder is told its **input logical type**. `Builder` becomes `(input type, column AST, *args) -> AST` or gains it by keyword; the declaration and the construction then read the same fact. This is the enabling change for §2.1 and §2.2.

- Paths: `src/bloomery/resolve/build.py` `src/bloomery/transforms/registry.py` `tests/support/type_conformance.py` `tests/unit/test_transforms/test_registry.py`

### S-0046/D-2 — `ASSUMED` (Transform types the engine agrees with)

Arithmetic transforms **narrow their own result** to the type they declare, rather than leaving it to `build.py`'s terminal cast — which only fires when the chain's terminal type differs from the field's, and so never fires for a chain ending in `multiply`.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py`

### S-0046/D-5 — `OPEN` (Transform types the engine agrees with)

Whether `to_bool`/`to_int` across the boolean boundary get a PostgreSQL spelling (`x::int::boolean`) or a refusal. A spelling is cheap; a refusal is honest about `to_bool` over an arbitrary integer having no agreed meaning.

- Paths: `src/bloomery/transforms/_builtins.py` `tests/unit/test_transforms/test_builtins.py`

<!-- /torve:managed -->
