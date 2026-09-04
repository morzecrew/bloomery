# RFC 0052 — dbt as a complete quality target

- **Status:** 📝 Draft — design locked, **not scheduled**
- **Scope:** The three artifact families the dbt emitter does not write, and the two
  refusals that stand in for them: the `<entity>__reject` model with its replay, and the
  `<check>__reconcile` model with its non-blocking audit. Shipping those leaves the
  data-quality mart with nothing left to refuse, so it lands as a consequence rather than
  as a fourth workstream. No IR change, no spec surface, no new dialect, no change to what
  SQLMesh emits — every SELECT involved is already built by the shared lowering and
  already rendered for one target. What changes is which projects compile for
  `--target dbt`, and the coverage sentence RFC 0008 §5.5 wrote when dbt emitted no audits
  at all. `python_model` steps stay refused, permanently and for an unrelated reason.
- **Related:** [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py),
  [`src/bloomery/emit/sqlmesh/__init__.py`](../src/bloomery/emit/sqlmesh/__init__.py),
  [`src/bloomery/emit/lower/silver.py`](../src/bloomery/emit/lower/silver.py),
  [`src/bloomery/emit/lower/reconcile.py`](../src/bloomery/emit/lower/reconcile.py),
  [`src/bloomery/emit/lower/quality_mart.py`](../src/bloomery/emit/lower/quality_mart.py),
  [`tests/e2e/test_dbt_parse.py`](../tests/e2e/test_dbt_parse.py),
  RFC 0008 (targets and the dbt positioning, retired at `7ba117b`), RFC 0016 (data
  quality: §5.3 reconcile, §5.6 reject and replay, §5.8 the quality mart), RFC 0026 (the
  dbt audit surface), RFC 0051 (the loose ends whose audit surfaced this).
- **Origin:** `logs/T-0014.md` D-073 — a `flag` rule on a step output was found to take a
  project off the dbt target, and the reason turned out to have nothing to do with steps.

---

## 1. Summary

dbt emits every silver model, every snapshot, every audit across five singular-test
families, every gold mart, the date dimension and Tier 2 step models. It does not emit
the reject table, the replay statements, the reconcile model, or the data-quality mart —
and each absence is a refusal a project meets at compile.

This RFC builds the three that are buildable. The reject table becomes an incremental
model that computes its own preserved columns against `{{ this }}` rather than asking dbt
to merge selectively — because the preservation is a `COALESCE`, which no column-exclusion
config can express, and because `merge` is not a strategy every dbt adapter has. Replay
becomes a `dbt run-operation` macro, which is not an ergonomic choice: the statements name
their relations through `ref()`, and `ref()` resolves nowhere else. The reconcile model is
an ordinary table model whose audit is the `severity`-carrying singular test RFC 0026
already emits five families of.

The quality mart then has no missing input left, and its refusal is deleted rather than
narrowed.

## 2. Motivation

**The refusals no longer describe a limitation; they describe a wave that ended.**
RFC 0008 §5.5 gave dbt one job — "proving the port abstraction; it ships minimal but
honest" — and wrote its refusals against an emitter that produced no audits whatsoever.
RFC 0026 then gave dbt the entire audit surface. Nobody restated the coverage claim, so
three refusals still stand on a sentence about a target that no longer exists.

**The gap is not where the messages say it is.** `_refuse_quarantine`'s own docstring
records that "flag-only quality surfaces still emit, because `_quality_flags` is the
*same* shared SELECT both targets render". So dbt already carries two thirds of RFC 0016:
the rules run, the flags project, the audits fire. What it cannot do is keep the row it
diverted, or replay it, or compare two aggregates, or count any of it.

**The asymmetry is now reachable from a second direction.** RFC 0051 lifted `on_fail:
flag` onto a Tier 2 step output, which puts a quality mart in the project, which dbt
refuses — so a step feature landed with one of its two targets untestable end to end
(`logs/T-0014.md` D-073). The step output is not special. A *mapped* entity with a single
`flag` rule has been unable to get its quality mart on dbt since RFC 0016 shipped, and
nobody noticed because nothing forced the two targets to be compared on that surface.

**Everything needed already exists and is rendered for one target.**
`reject_select`, `reject_when_matched`, `replay_statements`, `reconcile_select`,
`reconcile_audit_predicate`, `reconcile_audit_blocking` and `quality_mart_select` are all
in `emit/lower/`, all target-neutral, all covered. This is an envelope problem.

## 3. Current state

Verified against the tree, per artifact family.

| Family | SQLMesh | dbt |
|---|---|---|
| silver model, flags and routing | model | model |
| SCD type 2 | native `SCD_TYPE_2` kind | `snapshots/<entity>_snapshot.sql` |
| audits (5 families) | `AUDIT` blocks | `tests/<name>.sql`, `severity` per blocking-ness |
| gold marts | model | model |
| `gold.dim_date` | model | model |
| Tier 2 `sql_model` step | model | model |
| Tier 3 `python_model` step | generated wrapper | **refused** (RFC 0017 D52) |
| `<entity>__reject` | `INCREMENTAL_BY_UNIQUE_KEY` + `when_matched` | **refused** |
| `replay/<entity>.sql` | `ArtifactKind.REPLAY` | **refused with the above** |
| `<check>__reconcile` + audit | model + audit | **refused** |
| `gold.mart_data_quality` | model | **refused** |

The four refusals are three: `_refuse_quarantine` covers reject *and* replay,
`_refuse_reconcile` covers the comparison model, and the quality-mart branch in
`_mart_artifact` covers the mart.

**The quality mart's refusal is already false as written.** It says the mart "counts rule
evaluations over the reject tables and reconcile models", and both reads are conditional:
`_quality_rows_cte` unions the reject relation only when `entity.quarantine is not None`,
`_reconcile_branch` exists only when `ir.reconcile` is non-empty, and `_rows_deduped` is
the literal `0` without `dedupe:`. Since the other two refusals fire first and
unconditionally, every project that *reaches* the mart branch on dbt has a mart that reads
nothing dbt fails to build. That is the seam this RFC closes from the other end: after §5.1
and §5.3 the statement becomes true and vacuous at once.

**What the reject table needs from a merge.** `_PRESERVED_ON_MERGE` is
`{first_seen, last_evaluated_at}`, and the assignment for each is
`COALESCE(target.<col>, source.<col>)` — preserve, and heal a null left by a row inserted
before the clause existed. Every other reject column takes the arriving value.

**What dbt offers for that, measured against the installed packages.**
`merge_update_columns` / `merge_exclude_columns` (dbt-core
`macros/materializations/models/incremental/column_helpers.sql`) can only include or
exclude a column from the `UPDATE SET` list; neither can express a `COALESCE`, and the two
are mutually exclusive with each other. They also require the `merge` strategy, which is
not universal: dbt-duckdb's base strategies are `["append", "delete+insert"]` and it adds
`merge` only on DuckDB `>= 1.4.0-dev0`
(`dbt/adapters/duckdb/constants.py`); dbt-postgres has no merge strategy at all.

**Verification is available and real.** `tests/e2e/test_dbt_parse.py` runs `dbt parse`,
`dbt compile` **and** `dbt build` against dbt-duckdb over the fixture corpus, with a
control for the half a green build does not prove. The dependency is pinned
`dbt-core>=1.10.8,<2`, `dbt-duckdb>=1.9,<2`.

## 4. Goals / Non-goals

**Goals**

- A project declaring `quarantine:` compiles for dbt and builds, with a reject table whose
  columns mean what RFC 0016 §5.6 says they mean.
- Replay is runnable by a dbt operator without leaving dbt.
- A project declaring `reconcile:` compiles for dbt, and a disagreement reports rather
  than stops — `on_fail: flag`'s meaning, on a target that has non-blocking tests.
- `gold.mart_data_quality` is emitted for dbt, with dbt's own run context.
- The coverage claim is restated where a reader will find it, because RFC 0008 is retired
  and cannot be amended.

**Non-goals**

- **Tier 3 steps.** `python_model` stays refused (RFC 0017 D52) and this RFC does not
  touch it: dbt's Python models run on Snowflake, BigQuery and Databricks, none of which
  is one of bloomery's dialects. It is not a quality question.
- **Changing what SQLMesh emits.** Not one byte. Every golden in the corpus stays.
- **A second lowering.** If a SELECT has to be written for dbt that SQLMesh does not
  already have, the design is wrong — that is the drift `emit/lower/` exists to prevent.
- **Executing anything.** Emitting a `run-operation` macro is emitting text (§5.2).

## 5. Design

### 5.1 The reject table

```jinja
{{ config(materialized='incremental', unique_key='reject_id') }}
{% if is_incremental() %}
<the incremental SELECT>
{% else %}
<the first-run SELECT>
{% endif %}
```

Two **pre-rendered** SELECTs chosen by the envelope, never one SELECT with Jinja spliced
through it. That is RFC 0008 D4's doctrine applied unchanged: envelopes interpolate
rendered strings, and a conditional inside a rendered SQL string is a template the dialect
port never saw.

The first-run SELECT is `reject_select(entity, ctx)`, exactly as SQLMesh emits it. The
incremental SELECT is that same select, `LEFT JOIN`ed to `{{ this }}` on `reject_id`, with
each column of `_PRESERVED_ON_MERGE` projected as `COALESCE(<this>.<col>, <arriving>.<col>)`
— which is `reject_when_matched()`'s assignment, moved from the merge clause into the
projection. dbt's `unique_key` then replaces the whole row with values that are already
correct, so the preservation does not depend on how the adapter implements the write.

**Alternatives considered.** *`merge_exclude_columns=['first_seen', 'last_evaluated_at']`*
is the obvious mapping of `when_matched` and loses twice: it can only leave a column
untouched, so a null `first_seen` from an old row would stay null forever where SQLMesh
heals it — a silent divergence in a column the retention window reads — and it requires
the `merge` strategy, which dbt-postgres does not have and dbt-duckdb has only above a
DuckDB floor. *Emitting a per-adapter config* keeps the merge and buys a capability matrix
bloomery would have to track for adapters it does not ship. *Refusing `quarantine` on
adapters without merge* keeps a refusal this RFC exists to remove, and would make the same
spec compile or not depending on the reader's DuckDB build.

The `LEFT JOIN` form costs one scan of the reject table per run and works on every
adapter, including the two with no merge at all. It is the cheaper design *and* the more
portable one, which is unusual enough to be worth stating: the merge config looked like
the native answer and is the narrower one.

### 5.2 Replay as a run-operation macro

`macros/replay_<entity>.sql`, holding a macro that issues `replay_statements(entity, ctx)`
in order through `run_query`, invoked by the operator as
`dbt run-operation replay_<entity>`.

**This is not an ergonomic preference.** The statements name relations, and on dbt a
relation is named by `{{ ref(...) }}` — which is Jinja, resolved by dbt's own renderer
against the manifest. A bare `replay/<entity>.sql` carrying `{{ ref('order_item') }}` is
runnable by nothing: not by dbt, which does not execute loose files, and not by a SQL
client, which sees braces. The macro is the only form in which the references resolve.

bloomery still executes nothing. The artifact is text, the caller runs it, and the run
happens inside dbt's connection rather than the operator's — which is the same relationship
SQLMesh's replay file has to `sqlmesh`, spelled the way the other framework spells it.

The artifact keeps `ArtifactKind.REPLAY` even though its path is under `macros/`. The kind
means "a statement the caller runs, not a relation the framework maintains", and that is
exactly as true here; a caller routing the stream must still be able to tell "build this"
from "run this when you replay" without reading the path.

### 5.3 The reconcile model and its audit

The smallest of the three, and the one whose refusal already documents its own expiry:
`_refuse_reconcile`'s docstring records that half of RFC 0016 D58's argument is void — a
singular test carrying `severity='warn'` *is* a non-blocking check, and dbt emits several
— and that "the missing piece is the model, not the test".

So: `models/<ns>/<check>__reconcile.sql` from `reconcile_select(check, ir, ctx)`,
materialized `table` (the SQLMesh kind is `FULL`), plus `tests/<check>_reconcile.sql` from
`reconcile_audit_predicate()` with `severity` taken from `reconcile_audit_blocking(check)`
— the same function SQLMesh reads, so `on_fail: fail` blocks on both targets and
`on_fail: flag` reports on both.

### 5.4 The quality mart, and a refusal deleted rather than narrowed

With §5.1 and §5.3 landed, nothing the quality mart reads is missing on dbt, and the
branch in `_mart_artifact` is removed outright. Narrowing its predicate — refusing only
when a counted entity carries `quarantine:` or the project declares `reconcile:` — is the
change worth making *if this RFC does not ship*; it is dead code the moment it does.

dbt's run context is `RunContext(run_id="'{{ invocation_id }}'",
run_date="'{{ run_started_at.strftime(\"%Y-%m-%d\") }}'")`. The seam already exists and was
built for exactly this (`quality/mart.py`): each target says which engine-side expression
fills the two columns, and `exp.var` carries the text through rendering the way
`@execution_ds` already travels for SQLMesh.

Worth stating rather than discovering: dbt's run context is **more** complete than
SQLMesh's. The pinned sqlmesh exposes no run-identifier macro, so `run_id` is emitted
declared-but-NULL there; dbt has `invocation_id`. The compatibility target ends up with
the fuller column, which is a fact about the two frameworks and not about anyone's effort.

### 5.5 What stays refused

`python_model` steps, by `refuse_python_models`, unchanged and permanent while bloomery's
dialects are DuckDB, Postgres and Trino. This RFC deliberately leaves it alone so that
"dbt refuses this" keeps meaning something specific after the quality refusals go.

## 6. Tests

- **e2e (`dbt build`), the load-bearing tier.** A fixture with `quarantine:` and one with
  `reconcile:` are added to the build matrix. A build is what proves the incremental
  model's second run — the first run takes the `{% else %}` branch and would pass while
  the `is_incremental()` branch was nonsense, so the reject fixture must be **built twice**
  with a re-delivery seeded between, and `first_seen` read back unchanged. A single build
  proves the half that cannot fail.
- **Replay, executed.** `dbt run-operation replay_<entity>` over the built project, then
  the entity and reject table read back: the passer admitted, `resolved_at` stamped, the
  still-failing row's `failed_rules` re-derived. This is also where `ref()`'s availability
  inside a run-operation macro is *measured* rather than assumed (§9).
- **Equivalence, the strongest evidence available.** One spec set built on SQLMesh and on
  dbt over one DuckDB, and the two `<entity>__reject` tables compared row for row — the
  method `examples/targets/` already uses for marts, applied to the surface this RFC
  claims parity on. A golden cannot make this claim: the two targets emit different bytes
  on purpose.
- **Goldens** for each new artifact, as data files, and an assertion that the SQLMesh
  corpus is byte-identical to `main` — the non-goal stated as a test.
- **Refusal census:** three refusal messages leave the corpus and one (`python_model`)
  stays; the census is what stops a fourth quietly leaving with them.

## 7. Docs

- `pages/docs/reference/dialects.md` or its target-coverage sibling: the §3 matrix, with
  the two remaining `python_model` cells and nothing else refused.
- A how-to for replay on dbt — `dbt run-operation`, and the fact that retention deletes
  reject rows while resolved ones are kept as history.
- `pages/docs/concepts/data-quality.md`: wherever it says the quality mart is SQLMesh's.
- `CHANGELOG.md`: three refusals removed is a feature; nothing breaks, since every project
  affected currently fails to compile.

## 8. Out of scope

- **Tier 3 steps on dbt** (§5.5) — named as the one thing still refused, not built.
- **A capability matrix for dbt adapters.** §5.1 is designed to need none. If a future
  artifact genuinely requires `merge`, that RFC brings the matrix with it.
- **Cube.** It emits no silver surface at all, so none of this applies; its coverage claim
  is unchanged and correct.
- **Retiring RFC 0008's positioning sentence.** It cannot be amended — the document is
  retired at `7ba117b`. This RFC supersedes it for the RFC 0016 surface, and §7's doc page
  is where a reader meets the current claim.

## 9. Risks

- **`ref()` inside a `run-operation` macro.** The whole of §5.2 rests on it resolving
  there, and I have read that it does rather than run it. If it does not, the fallback is
  a macro that resolves relations through the naming policy instead — correct, and one
  degree less native. §6 measures this before the design is committed to, and it is the
  first thing the phasing builds.
- **The incremental branch is only exercised on a second run.** The classic dbt defect: a
  green build proves the `{% else %}` branch. Mitigated by building twice with a
  re-delivery, which is stated in §6 as a requirement rather than left to whoever writes
  the test.
- **`{{ this }}` in the first run.** dbt guards this with `is_incremental()`, which is
  false when the relation does not exist — but the guard is in the envelope bloomery
  writes, so a malformed envelope produces a first run that references a table that is not
  there. A parse will not catch it; the build will.
- **Two targets, one claim.** Parity asserted per artifact is parity per artifact. §6's
  equivalence leg is what turns it into a claim about the *rows*, and it is the leg most
  likely to be cut for time. It should not be.
- **Scope creep into "dbt is now equal".** It is not: Tier 3 stays refused, and the docs
  must say which cells are still unequal rather than declaring parity.

## 10. Unresolved questions

- Whether the reject model declares `incremental_strategy` explicitly or leaves the
  adapter's default. Explicit is this repo's habit for every other emitted config line —
  an artifact that states its own disposition cannot be misread — but naming
  `delete+insert` pins a strategy where the design no longer depends on one, and naming
  none lets a caller choose `merge` for free. Delegated to execution (D11).
- Whether the replay macro should refuse to run against a project whose fingerprint has
  moved since it was emitted. Every artifact carries the fingerprint in its header
  already; a macro could compare. Out of scope here, and named because a run-operation is
  the first emitted artifact that could act on it.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | The reject table preserves `first_seen` / `last_evaluated_at` **in its own SELECT**, by `LEFT JOIN` to `{{ this }}` and `COALESCE`, not by dbt's `merge_exclude_columns`. Column exclusion cannot express a `COALESCE`, so it would leave a null unhealed where SQLMesh heals it — a divergence in the column retention reads — and it requires a `merge` strategy dbt-postgres does not have and dbt-duckdb has only above a DuckDB floor. Locks the reject model to one scan of itself per run, in exchange for working on every adapter. |
| 2 | `LOCKED` | The incremental and first-run bodies are **two pre-rendered SELECTs** chosen by `{% if is_incremental() %}` in the envelope. Never one SELECT with Jinja spliced into it: RFC 0008 D4's rule is that envelopes interpolate rendered strings, and a conditional inside a rendered string is a template no dialect port ever saw. |
| 3 | `LOCKED` | Replay is `macros/replay_<entity>.sql`, run by `dbt run-operation`. Not ergonomics: the statements name relations through `ref()`, which resolves only inside dbt's Jinja, so a bare `.sql` file would be runnable by neither dbt nor a SQL client. |
| 4 | `ASSUMED` | The macro issues the statements in order through `run_query`. bloomery executes nothing — emitting a macro is emitting text, and the run happens in dbt's connection rather than the operator's, which is what SQLMesh's replay file already assumes about `sqlmesh`. |
| 5 | `LOCKED` | The dbt replay artifact keeps `ArtifactKind.REPLAY` despite living under `macros/`. The kind means "a statement the caller runs, not a relation the framework maintains", and a caller routing the artifact stream must be able to tell those apart without parsing a path. |
| 6 | `ASSUMED` | The reconcile model is `materialized='table'` (SQLMesh's `FULL`) and its audit a singular test whose severity comes from `reconcile_audit_blocking(check)` — the same function SQLMesh reads, so a check's `on_fail` means one thing across targets. |
| 7 | `LOCKED` | The quality mart's dbt refusal is **deleted**, not narrowed, once D1 and D6 land: no surface it reads is then missing. Narrowing its predicate is the right change only if this RFC does not ship — the two are alternatives, not a sequence, and pursuing both would leave dead code behind. |
| 8 | `ASSUMED` | dbt's `RunContext` is `invocation_id` and `run_started_at`, carried through `exp.var` exactly as `@execution_ds` already is. This gives dbt a `run_id` SQLMesh does not have; the asymmetry is reported, not hidden. |
| 9 | `LOCKED` | `python_model` steps stay refused (RFC 0017 D52), untouched by this RFC. Leaving one refusal standing is what keeps "dbt refuses this" a specific statement rather than a historical one. |
| 10 | `ASSUMED` | The coverage claim is restated in the docs, not in an amendment: RFC 0008 is retired at `7ba117b` and its "minimal but honest" sentence cannot be edited. This RFC supersedes it for the RFC 0016 surface only. |
| 11 | `OPEN` | Whether the reject model names `incremental_strategy` explicitly or takes the adapter's default. §10 states both sides; execution decides and logs it. |
| 12 | `ASSUMED` | Parity is proven by an equivalence leg — one spec set built on both targets over one DuckDB, reject tables compared row for row — not by per-artifact goldens alone. The two targets emit different bytes on purpose, so only the rows can carry the claim. |

## 12. Phasing

Four phases. P1 is first because it is the one that can invalidate a `LOCKED` row.

1. **P1 — measure `ref()` in a run-operation.** A spike, not a feature: emit one macro by
   hand over an existing fixture and run it. D3 stands or its fallback does (§9).
2. **P2 — the reconcile model.** The smallest, and independent of everything else: a model
   artifact and a singular test over two shared functions. It removes one refusal on its
   own.
3. **P3 — the reject table and replay.** D1, D2, D3 together; the e2e build-twice test and
   the equivalence leg land with it, not after.
4. **P4 — the quality mart.** Delete the refusal, add the `RunContext`, and the mart falls
   out. Gated on P2 and P3 by correctness, not by convenience: shipping it earlier would
   emit a mart that counts branches over relations that do not exist.
