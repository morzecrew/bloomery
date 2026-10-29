<!-- torve:managed pages/docs/reference — rendered from the corpus; do not edit by hand -->

## Decisions governing `pages/docs/reference/`

### S-0004/D-10 — `ASSUMED` (Observability: logging and a warnings channel)

The advisory vocabulary is a closed enum with no free-text constructor, and every member has a row in the reference's advisory table while every documented code is constructible — checked in both directions

- Paths: `src/bloomery/evidence.py` `pages/docs/reference/errors.md` `tests/unit/test_docs_floor.py`
- Consequence: Adding an advisory is a reviewed change that lands its documentation row with it; a documented code no path can construct fails the census, which is what blocks the deprecated-spelling advisory until a spelling is actually deprecated
- Check: `uv run pytest tests/unit/test_docs_floor.py -q` (shadow; runs as `decision:S-0004/D-10`, no log entry owed)

### S-0011/D-14 — `ASSUMED` (Retrieval semantics)

The retrieval kind carries the same spec-YAML promise as every kind from its first release, with no pre-adoption carve-out: `retrieval_version` is `1`, changes within it are additive, as phase 4's `fusion.k`, `fusion.depth` and `analyser` were, and a breaking change mints `retrieval_version: 2`, per S-0042/D-23.

- Paths: `src/bloomery/spec/retrieval.py` `pages/docs/reference/stability.md`
- Consequence: a retrieval spec written against 0.3.0 keeps compiling under the same promise as every other kind, the two refusals the stability page names included

### S-0022/D-11 — `ASSUMED` (Resolution: dependency DAG, recipes, reachability)

A metric's `filter[].dimension`, its `filter[].column` and its `semi_additive.over` are bound through the grain entity's canonical links, as its `expr` is under D-10. A filter's name that a mart listing the metric carries as written reads that column; it is bound once the marts are lowered, because a joined entity's column reaches a mart flattened under a prefix. An `over` names a column of the metric's own entity, so it is bound at the IR build and a grain column of its name keeps it. Otherwise the one grain column that links the name as its canonical is read, and a name no grain column links, or two do, is kept as written. `unbound` respells each as the canonical of the column it reads, where binding would read that column, so `plan()` and `timeline` compare them in canonical spelling

- Paths: `src/bloomery/ir/lower.py` `src/bloomery/resolve/build.py` `tests/unit/test_resolve/test_canonical_filter_binding.py` `pages/docs/reference/spec-schemas.md`
- Consequence: A catalog template that filters, or reads a snapshot along an axis, in canonical names compiles for every project that links each of those canonicals from exactly one grain column, whatever it calls the column. Every spec that compiled before reads the same columns: its names were each a column of every mart listing the metric, or of the grain for an `over`, and those keep their literal reading. A field renamed under such a metric respells it and does not restate it

### S-0023/D-13 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

The `over` of a semi-additive metric names the source column of a date role — the column a `{date: …, role: …}` flatten step is declared over — never a bucket that role produces (`<role>_day` and the rest), and every mart listing the metric among its measures must declare a date role over that column. A mart that does not is refused at the guardrail stage as `MartMissingTimeDimension`, and the MetricFlow emitter re-refuses it

- Paths: `src/bloomery/guardrails/metrics.py` `src/bloomery/emit/metricflow/__init__.py` `src/bloomery/planner/explain.py` `tests/unit/test_guardrails/test_metrics.py` `tests/fixtures/semi_additive_over_refusal/metrics.yaml` `tests/golden/refusals/semi_additive_over_refusal.txt` `pages/docs/reference/spec-schemas.md`
- Consequence: `over: snapshot_day` beside `{date: stock_date, role: snapshot}` is refused at `bloomery check`, naming `stock_date`, rather than compiling clean and failing only when the MetricFlow manifest is built; a mart added to a metric's listing without the role is refused even when another mart owns the metric

### S-0023/D-14 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

A canonical field may declare `unit: ratio`: a dimensionless number such as a percentage, a rate, a sign or a 0/1 flag. Like `count`, it is a declared unit that is not money, so the tax-basis rule does not read it as the `unknown` that poisons, and the unit rule compares it as a unit of its own: a ratio beside currency or count at `+`/`-` is a `UnitMismatch`, and two ratios meet. A ratio declares no `currency` and no `tax_basis`; the catalog refuses either at load, because the currency rule reads a declared code at every operator

- Paths: `src/bloomery/spec/catalog.py` `src/bloomery/ir/nodes.py` `tests/unit/test_guardrails/test_dimensionless_unit.py` `tests/golden/schema/catalog.json` `pages/docs/reference/spec-schemas.md`
- Consequence: `price * (100 - discount) / 100 - cost` compiles once `discount` is declared a ratio, and `price + discount` is still refused. An undeclared factor keeps poisoning, so nothing that compiled or was refused before changes. A factor no longer has to be declared a count, a unit that is wrong for a percentage

### S-0023/D-15 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

A canonical field may declare `per_unit: true`: its value is a rate that holds per unit of each row reading it, such as a unit cost or a price, rather than an amount of its own entity. The grain guard admits such an operand, in a metric or a derivation, where the grain reaches the operand's entity through one declared many-to-one relationship, either way round. Every other foreign-grain operand is refused under D-5 as before, a per-unit one read from the parent side included, and the refusal names the declaration where it would apply

- Paths: `src/bloomery/spec/catalog.py` `src/bloomery/guardrails/grain.py` `src/bloomery/guardrails/operands.py` `tests/unit/test_guardrails/test_per_unit_parent.py` `tests/golden/refusals/fanout_trap.txt` `pages/docs/reference/spec-schemas.md`
- Consequence: Cost of goods at order-line grain, `product_cost * line_quantity` with the cost on `product`, compiles once the catalog declares the cost per unit. Order shipping read per line, the `fanout_trap`, is refused as before, in the same expression shape. The declaration is not verified, so a per-unit amount summed per line overstates exactly as the fan-out D-5 refuses, and the declaration is where a reviewer looks for it. A chain of two many-to-one hops is still refused

### S-0033/D-30 — `ASSUMED` (Data quality: declarative cleansing, dispositions, quarantine)

*(2026-08-08, M12; closed by D84)* **Postgres cannot host quality-carrying entities.** `coercible` needs a real NULL-on-failure cast (`DialectFeature.TRY_CAST`); sqlglot renders `TRY_CAST` on Postgres as a plain `CAST`, which aborts the run instead of marking the row, so the dialect declares the feature gap and compiling a quality-carrying entity for it raises `UnsupportedByTarget` — loud, never a silent degradation into an aborted run. Consequence for §6's dialect matrix: there is no Postgres dirty-corpus tier to add until either sqlglot renders a real `TRY_CAST` or the lowering grows a per-type `CASE`-based fallback whose semantics are proven equal to `TRY_CAST`'s on the corpus. Named as the escape hatch, not built.

- Paths: `pages/docs/reference/errors.md` `src/bloomery/emit/lower/silver.py`

### S-0035/D-11 — `ASSUMED` (Public surface and stability policy)

`spec_version: 1` promises a document keeps its meaning, not that it keeps loading. A newly reserved generated-column name, or authored text that is not one SQL expression, may refuse a document that loaded before without a version bump, provided the refusal is binary, reaches only an already-broken document, names the authored address and fix, and appears in `CHANGELOG.md`

- Paths: `pages/docs/reference/stability.md` `src/bloomery/spec/common.py` `tests/unit/test_steps/test_lowering.py`
- Consequence: Adding a name to `RESERVED_MEMBER_REASONS` ships in a minor with a Changed entry and a reason the refusal quotes, while any change that alters what a loading document means still mints a version

### S-0041/D-7 — `ASSUMED` (Deterministic union merge)

A `_source` system column carries provenance. It is load-bearing rather than diagnostic: the collision audit reports which sources collided, and without it the report is unactionable on a multi-source entity.

- Paths: `pages/docs/reference/stability.md` `src/bloomery/emit/lower/silver.py` `src/bloomery/ir/nodes.py` `src/bloomery/spec/common.py` `tests/unit/test_emit/test_sqlmesh.py` `tests/unit/test_steps/test_lowering.py`

### S-0042/D-1 — `LOCKED` (v0.1.0 release readiness)

The three S-0018/out-of-scope ratchets land before the `v0.1.0` tag, not after. Their stated trigger was the release; deferring them past it converts a deliberate deferral into an oversight, and a promise nothing enforces is what the release exists to stop.

- Paths: `pages/docs/reference/stability.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0042/D-4 — `LOCKED` (v0.1.0 release readiness)

The perf gate is an **absolute ceiling with headroom** against S-0031's budgets, never a drift comparison against a stored baseline. Runner variance makes percentage drift on millisecond measurements flaky, and a flaky gate is one people learn to re-run.

- Paths: `pages/docs/reference/stability.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0042/D-6 — `LOCKED` (v0.1.0 release readiness)

`RETIRED.md` (the retired register, since deleted) is three columns — number, title, retiring SHA — and **never a summary**. A fourth column would reintroduce the drifting second account the retirement policy exists to prevent; three columns describe no behaviour and so cannot drift.

- Paths: `pages/docs/reference/stability.md`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0048/D-10 — `ASSUMED` (Lineage)

`resolve()` takes the step registry as `steps`, defaulting to the empty one, and the compile pipeline passes it the registry it was handed. Where the registry holds a wired step's manifest, the step draws a `step_output` edge to each column its bound output produces, beside the relation node; a step input bound to that output reads it whole, from each of those columns; and an expression metric whose grain is that output draws `expr` edges from the produced columns its `expr` names. A step the registry does not hold keeps the wiring-only edges. No label or triple is added

- Paths: `src/bloomery/resolve/graph.py` `src/bloomery/resolve/resolution.py` `src/bloomery/resolve/build.py` `tests/unit/test_steps/test_step_lineage.py` `pages/docs/reference/api.md`
- Consequence: A walk runs through a `sql_model` step: downstream from an input column to the columns the step produces and to the metrics and marts over them, and upstream back again. `bloomery lineage` takes no registry, so it still shows the wiring alone, and so does a caller of `resolve()` that passes none. Lowering, the IR and every fingerprint are unchanged, since nothing past resolve reads the graph

### S-0091/D-4 — `ASSUMED` (A recipe's operands carry types)

Every catalog in the repository that computes a recipe over a non-canonical operand declares `types:`; the reference pages and the skill's catalog reference document the key, and the changelog marks the refusal as breaking with an upgrade note.

- Paths: `tests/fixtures/` `examples/` `pages/docs/reference/` `skills/bloomery-skills/references/` `CHANGELOG.md`
- Consequence: the repository's own catalogs compile under D-3, and a user upgrading reads what to add

<!-- /torve:managed -->
