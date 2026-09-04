# RFC 0054 — The SQLMesh project file

- **Status:** 📝 Draft (execution-ready — one PR) — **§3's measurements are done**, and
  M4 is why this document exists in the shape it does rather than as a one-line chore.
- **Scope:** One emitted artifact, `config.yaml`, so that `bloomery compile --target
  sqlmesh --out out/` produces a directory SQLMesh recognises as a project. It carries
  `model_defaults` and nothing else: no gateway, no credentials, no environment — the same
  line bloomery already draws for dbt, where `dbt_project.yml` is emitted and
  `profiles.yml` deliberately is not. No IR change, no spec surface, no change to any
  model, audit or replay artifact. Every SQLMesh golden gains one path.
- **Related:** [`src/bloomery/emit/sqlmesh/__init__.py`](../src/bloomery/emit/sqlmesh/__init__.py),
  [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py) (the
  `dbt_project.yml` precedent), [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py)
  (`DateDimensionIR.start_year`), [`examples/targets/run.py`](../examples/targets/run.py)
  (which writes the missing file by hand today), RFC 0008 (targets and the
  emitted-artifact contract; retired at `7ba117b`), RFC 0003 (no environment; retired at
  `33bc4f9`).
- **Origin:** A ceiling review observing that "SQLMesh output is not a runnable project".
  §3 measures the claim, finds it true and total, and finds a second thing nobody had
  looked for.

---

## 1. Summary

bloomery's primary target emits `models/`, `audits/` and `replay/` — and no project file,
so SQLMesh does not recognise the output directory as a project at all. Its compatibility
target emits `dbt_project.yml`, `macros/`, `sources.yml` and `schema.yml`, and a dbt user
can run the output as it stands. The asymmetry runs the wrong way.

This closes it with one artifact carrying two values: the `dialect` the compile was asked
for, and a `start` **derived from the catalog's date dimension**. The second is the
substance of this RFC. Without it SQLMesh silently backfills every
`INCREMENTAL_BY_TIME_RANGE` model over one day and reports success — a project that runs
clean and answers wrongly, which is exactly the failure bloomery exists to refuse, and it
would be produced by an artifact bloomery wrote.

## 2. Motivation

The proof that the gap is real is in the repository's own example: `examples/targets/run.py`
writes `config.yaml` itself before it can run `sqlmesh plan`. A demonstration that has to
supply what the compiler did not is the clearest possible statement that something is
missing — and its sibling comment, four lines below, explains why `profiles.yml` is
*deliberately* absent for dbt. One of those two omissions is a principle; the other was
never decided.

## 3. Current state — measured

All five findings are from running SQLMesh 0.236.1 against a real emitted tree (the
`ecom_basic` fixture, four models, two of them `INCREMENTAL_BY_TIME_RANGE`).

**M1 — the directory is not a project.** With no `config.yaml`:

```text
Error: SQLMesh project config could not be found. Point the cli to the project path
with `sqlmesh -p`. If you haven't set up the SQLMesh project, run `sqlmesh init`.
```

Not "less convenient" — SQLMesh declines to look at the models at all.

**M2 — a gateway-less config is a valid project.** With `config.yaml` containing only
`model_defaults: {dialect: duckdb}` and a gateway supplied through
`SQLMESH__GATEWAYS__…` in the environment:

```text
Models: 4
Macros: 0
Data warehouse connection succeeded
```

So the project half and the connection half separate cleanly, exactly as they do for dbt.
Without the environment gateway the same file yields `Error: No connection configured.` —
the file is accepted, the connection is missing, and the caller supplies it.

**M3 — comments survive.** A `config.yaml` opening with `#` lines loads unchanged, so this
artifact can carry the `fingerprint:` header every other emitted file carries.

**M4 — omitting `start` produces a wrong answer, quietly.** This is the finding that
shaped the design, and nothing in the ceiling review anticipated it. With `dialect` and no
`start`, `sqlmesh plan` reports:

```text
**Models needing backfill:**
* `gold.dim_date`: [full refresh]
* `gold.mart_order_items`: [2026-09-03 - 2026-09-03]
* `silver.order`: [full refresh]
* `silver.order_item`: [2026-09-03 - 2026-09-03]
```

One day. The `FULL` models are complete and the two time-range models hold a single
partition, with no warning and no error. bloomery emits `INCREMENTAL_BY_TIME_RANGE` for
every `incremental_by_partition` entity and for a partitioned mart, so this is not an edge
case — it is the corpus's own headline fixture.

An artifact that makes `sqlmesh plan` succeed and load 0.1% of the data is worse than no
artifact, and it is worse in this project's specific sense: the SQL is right, the run is
green, the number is wrong.

**M5 — `start` need not be invented.** The catalog already declares
`date_dimension.start_year`, whose own docstring says the bounds are "calendar years — the
emitted table is a pure function of the spec, never of a clock". Setting
`start: 2024-01-01` on the same project gives:

```text
* `gold.mart_order_items`: [2024-01-01 - 2026-09-03]
* `silver.order_item`: [2024-01-01 - 2026-09-03]
```

The value is derived, deterministic, needs no new spec surface, and is coherent by
construction: a project's partitioned models backfill from the year its own date dimension
begins, and those two disagreeing was never a sensible state.

## 4. Goals / Non-goals

**Goals**

- `bloomery compile --target sqlmesh --out out/` produces a directory `sqlmesh` recognises.
- The emitted config states every value it contains and contains no value bloomery cannot
  state.
- The backfill window is the project's own, not SQLMesh's default.

**Non-goals**

- **A gateway, a connection, or credentials.** The reason `profiles.yml` is not emitted for
  dbt is the reason `gateways:` is not emitted here: a connection carries hosts and
  secrets, and the compiler reads no environment (RFC 0003). M2 shows the split works.
- **`sqlmesh init` parity.** No `audits/` scaffolding, no `tests/`, no `macros/`, no
  seeds — bloomery emits what it knows, and it knows nothing about those.
- **Making every project runnable.** It makes every project *loadable*. A caller still
  supplies a connection, and §5.3's `OPEN` case still supplies a `start`.

## 5. Design

### 5.1 The artifact

`config.yaml` at the artifact root, `ArtifactKind.CONFIG` — the kind's own definition is
"framework scaffolding (`dbt_project.yml`, `sources.yml`, `schema.yml`)", and this is the
SQLMesh member of exactly that set.

```yaml
# Generated by bloomery — do not edit.
# fingerprint: blm1:…
#
# The gateway is yours. A connection carries hosts and credentials, which this
# compiler never reads — add a `gateways:` block here, or set SQLMESH__GATEWAYS__…
# in the environment.
model_defaults:
  dialect: duckdb
  start: '2020-01-01'
```

Two keys, both known:

- **`dialect`** is the compile's own `--dialect` argument, so it cannot disagree with the
  SQL in the models beside it.
- **`start`** is `f"{date_dimension.start_year}-01-01"` (M5).

Nothing else. `disable_anonymized_analytics` is deliberately absent — it is a choice about
the caller's telemetry, not a fact about their project, and an emitted artifact that
switched it either way would be bloomery having an opinion about something it cannot see.

### 5.2 Why `start` is derived rather than declared

A new spec key for the backfill start would be the obvious move and is the wrong one:
it is a second place to say something the catalog already says, and two declarations of one
fact are two declarations that will disagree. The date dimension's span *is* the project's
temporal extent — `gold.dim_date` is built from it, MetricFlow's time spine points at it,
and a partitioned model backfilling from outside it would be joining against dates the
dimension does not have.

The value is a date literal built from an int, so no clock is read and the artifact stays a
pure function of the spec.

### 5.3 The project with no date dimension

`start` is derivable only when the catalog declares a date dimension. A project with a
partitioned entity, no marts and no date dimension has no honest value to put there — and
this is the one case where M4's silent one-day backfill would still reach a caller.

The narrow shape matters: a measure-carrying mart with no date role is already refused
(`MartMissingTimeDimension`), and MetricFlow already refuses marts without a catalog date
dimension. So the gap is a partitioned **silver entity** in a project with no marts.

The choice is `OPEN` (D5), with the alternatives stated rather than ranked:

- **Emit the config, comment the missing key, name the consequence.** Non-regressing and
  actionable; still silent if the comment goes unread.
- **Emit no config for such a project.** Exactly today's behaviour, so nothing regresses
  and nothing is learned — the caller writes the file as they do now.
- **Refuse the compile.** Proportionate to the harm and disproportionate to the case; it
  would refuse a project that compiles today over a file that did not exist yesterday.

## 6. Tests

- **The measured claims, as tests, at the e2e tier.** M1, M2 and M4 are the design; a
  golden proves none of them. `dbt parse`'s sibling for SQLMesh: emit a fixture, add a
  gateway from the environment, and assert `sqlmesh info` loads every model — the check
  that would catch a config bloomery emits and SQLMesh rejects.
- **M4 as a regression, explicitly.** Plan the `ecom_basic` project and assert the backfill
  window opens at the catalog's `start_year`, not at yesterday. This is the one test that
  fails if someone later "simplifies" the config down to `dialect`, and it is the whole
  reason this RFC is longer than its diff.
- **Goldens:** every SQLMesh fixture gains `config.yaml`, so every `EXPECTED_PATHS` entry
  moves — a large, mechanical, reviewable diff, and the corpus is where a stray artifact
  would show up.
- **Determinism:** the artifact through the existing cross-process guard, since it is the
  first emitted file whose content derives from the catalog rather than from the entities.

## 7. Docs

The CLI page's compile section, which today lists what lands under `--out` and would
otherwise still say it produces models and audits; and one sentence naming the gateway as
the caller's, beside the one that already says it about `profiles.yml`.

`CHANGELOG.md` under *Added*. Not breaking: a new path in the artifact stream, and a caller
who already writes their own `config.yaml` into the output directory would now find one
there — which is worth a sentence, since "an artifact appeared where I was writing my own"
is a real, if minor, surprise.

## 8. Out of scope

- **`profiles.yml`-equivalent gateway emission.** §4.
- **The dbt/SQLMesh capability asymmetry in the other direction** — dbt refusing
  quarantine, reconcile and the quality mart. That is RFC 0052, and the two are
  independent: this one makes the primary target's output runnable, that one makes the
  compatibility target's output complete.
- **`sqlmesh init` parity**, seeds, tests, macros.

## 9. Risks

- **A caller who already writes `config.yaml` into `--out`.** They now find one there.
  Mitigated by the `do not edit` header every emitted file carries and by the CHANGELOG
  note; not mitigated by anything cleverer, because an artifact that stepped aside when a
  file already existed would make the output a function of the destination directory.
- **`start` is a policy the catalog was not written to express.** It is being read as
  "when this project's history begins", which is what a date dimension's first year means
  in practice and not quite what it says. If a project's date dimension starts in 2020 for
  reporting convenience while its fact data begins in 2023, the emitted `start` backfills
  three empty years — wasteful, not wrong. Named because the reverse case (a dimension
  starting *after* the data) would be wrong, and it is already incoherent for other
  reasons.
- **One more file in every SQLMesh golden.** A large mechanical diff is where a real change
  hides. The goldens are regenerated in their own commit, separate from the emitter change.

## 10. Unresolved questions

- §5.3's three-way choice for a project with no date dimension (D5).
- Whether `config.yaml` should carry `model_defaults.cron`. SQLMesh defaults to daily and
  bloomery knows nothing about a schedule, so silence looks right — but silence is what M4
  punished, and the question is whether an unstated cron has a wrong-answer mode of its
  own. It probably does not: a wrong cadence is late, not incorrect. Recorded because that
  reasoning is exactly the reasoning M4 falsified once already.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | bloomery emits `config.yaml` with `model_defaults` and **never** a `gateways:` block. The dbt precedent is not an analogy but the same rule: `dbt_project.yml` is emitted, `profiles.yml` is not, because a connection carries hosts and credentials and the compiler reads no environment. M2 measures that SQLMesh accepts the split. |
| 2 | `LOCKED` | `model_defaults.start` is emitted, derived from `date_dimension.start_year`. Omitting it makes `sqlmesh plan` backfill every time-range model over a single day and report success (M4) — an artifact bloomery wrote, producing a plausible-but-wrong result. This row is the RFC. |
| 3 | `LOCKED` | `start` is **derived**, never a new spec key. The catalog's date dimension already states the project's temporal extent; a second declaration of one fact is two declarations that will disagree. |
| 4 | `ASSUMED` | `disable_anonymized_analytics` is not emitted, either way. It is a choice about the caller's telemetry rather than a fact about their project, and an artifact that set it would be the compiler holding an opinion about something outside the spec. |
| 5 | `OPEN` | What to emit for a project with a partitioned entity and no catalog date dimension: config with the key commented and the consequence named, no config at all, or a refusal. §5.3 states all three and ranks none. The case is narrow — a partitioned silver entity in a project with no marts — which is why it is delegated rather than settled here. |
| 6 | `ASSUMED` | `ArtifactKind.CONFIG`, path `config.yaml` at the artifact root. The kind's definition already names the dbt files this is the sibling of. |
| 7 | `ASSUMED` | The goldens are regenerated in a commit of their own, separate from the emitter change. Every SQLMesh fixture gains a path, and a mechanical diff of that size is where a real change hides. |

## 12. Phasing

One PR, three commits:

1. The emitter and the artifact (D1–D4, D6), with unit tests.
2. The golden regeneration, alone (D7).
3. The e2e tier: `sqlmesh info` over an emitted project with an environment gateway, and
   the M4 regression asserting the backfill window opens at the catalog's year.
