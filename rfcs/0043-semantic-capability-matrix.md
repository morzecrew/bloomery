# RFC 0043 — Evidence-based semantic capability matrix

- **Status:** 🚧 In progress — research and specification task, **not a code change**.
  [RFC 0042](0042-semantic-bug-corpus.md) is strongly recommended first: its cases are this
  document's rows. **A second column is measured** (2026-09-15,
  [`logs/T-0058.md`](../logs/T-0058.md)): `comparisons/` exists with MetricFlow `0.212.0`
  against three cases, and D6 and D7 are settled by rows 9 and 10. `comparisons/MATRIX.md`
  carries 25 rows, which is one row per **expectation** — RFC 0042's twelve cases pin
  between one and three apiece, and a case is refused in one shape while being planned
  correctly in another. bloomery's column is filled for all 25, MetricFlow's for the 6 its
  three bundles cover, and dbt Core, SQLMesh and Cube are `UNKNOWN` throughout, which is D2
  working rather than work missing. §§3, 4 and 8 read as they were written and describe the
  state before that research; rows 11–13 record what it settled that they do not mention.
- **Scope:** A reproducible comparison of bloomery, dbt, SQLMesh, MetricFlow, Cube and
  other explicitly selected systems against concrete semantic failure cases.
- **Non-goal:** Competitive marketing copy. §6 exists to keep it that way.

---

## 1. Principle

The matrix compares **specific represented semantic properties**, not products as wholes.

Bad:

```text
dbt does not prevent fanout
```

Better:

```text
For corpus case 001, using documented native feature set X and configuration Y, the
system does/does not encode the measure-origin grain needed to reject the naive query
before execution.
```

## 2. Evidence standard

Every cell is one of:

- `NATIVE-PREVENT` — documented native semantics prevent the failure before producing the
  wrong answer;
- `NATIVE-PLAN` — native semantics construct a correct plan;
- `RUNTIME-DETECT` — a native runtime test or audit can detect the bad result or data
  condition;
- `CUSTOM` — achievable only with project-authored custom test, model or SQL;
- `NOT-REPRESENTED` — the required semantic fact has no documented native representation
  found;
- `UNKNOWN` — research incomplete.

**No cell may be filled from reputation or memory alone.**

## 3. Reproduction bundle

```text
comparisons/<system>/<case>/
  README.md   config/   commands.txt   observed.txt   sources.md
```

`README.md` records version, date, and the exact question being tested.

## 4. Versioning

The matrix is time-sensitive. Every result pins the product or library version; the date
checked; relevant feature flags; and whether hosted-only features were required. Cells do
not claim permanence.

## 5. Dimensions

Rows come from RFC 0042 — fact fanout, SCD2/as-of correctness, currency and unit mismatch,
ratio rollup, semi-additive time behaviour, distinct-count fanout, many-to-many bridges.

Columns may include bloomery, dbt Core, SQLMesh, MetricFlow, Cube, and further systems only
when someone is willing to maintain the reproduction.

## 6. bloomery receives no special scoring

If bloomery requires a custom step, a runtime audit, or cannot represent a case, the matrix
says so. The purpose is to discover boundaries, not to manufacture wins.

Documentation may summarize only findings backed by a checked-in reproduction. Preferred
wording:

```text
bloomery refuses corpus case 001 at compile time because measure origin grain is part of
its semantic IR. In the tested dbt Core configuration, equivalent pre-execution grain
semantics were not represented; a custom test or model can still detect or avoid the
problem.
```

Avoid universal claims such as "dbt cannot do X".

## 7. Automation

Where licensing and tooling permit, comparison reproductions should be executable in CI or
a scheduled compatibility workflow. Where not possible, the cell is marked manual and
records exact reproduction steps.

## 8. Unresolved questions

- **Where the bundles live.** A `comparisons/` tree pulls third-party configs into a
  repository whose gates run over everything; a sibling repository keeps them out and makes
  the citation weaker.
- **What a stale cell does.** Cells pin a date; nothing yet says at what age a cell becomes
  `UNKNOWN` again.

## 9. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **A cell claims a property of a tested configuration, never a property of a product.** Every claim names the version, the date, the feature set and the configuration. Locked because the failure mode is not a wrong cell — it is a true cell quoted later as a general statement, and only the phrasing discipline prevents that. |
| 2 | `LOCKED` | **No cell is filled from reputation or memory; `UNKNOWN` is an honest value.** A guessed cell is indistinguishable from a researched one once written down, which makes one guess enough to void the table. |
| 3 | `LOCKED` | **bloomery is evaluated by the same standard as every other column, including where it loses.** A matrix that scores its author's tool favourably is worth nothing as evidence and is worse than none, because it will be cited. If bloomery needs a custom step or cannot represent a case, the cell says so. |
| 4 | `ASSUMED` | **Rows are RFC 0042's cases, not a separately invented taxonomy.** One set of cases keeps the matrix and the regression suite from drifting into two accounts of the same question. Departing means the matrix needs a row no corpus case covers — in which case the case is what is missing, and it belongs in 0042 first. |
| 5 | `ASSUMED` | **Documentation may state only what a checked-in reproduction supports.** The `sources.md` and `observed.txt` in each bundle are what a README sentence points at. Not `LOCKED` because it is a docs discipline rather than a compiler rule; RFC 0045 carries the same constraint for the claims themselves. |
| 6 | `OPEN` | **Superseded by row 9.** **Where reproduction bundles live — in this repository under `comparisons/`, or beside it.** In-repo makes the citation strongest and puts third-party configuration under gates written for bloomery's own source; out-of-repo inverts both. Decide before the first bundle, since moving them later breaks every link the docs will have made. |
| 7 | `OPEN` | **Superseded by row 10.** **The staleness policy.** Cells pin a date and nothing says when age alone should return a cell to `UNKNOWN`. Pick a rule — a release count, a month count, or a re-check on each corpus change — and write it into §4, because an unmarked stale cell is D2's failure arriving slowly. |
| 8 | `ASSUMED` | **Cube's pre-aggregation matching is a row of this matrix.** RFC 0058 §9 named the risk and §12 assigned the measurement here rather than to the emitter: bloomery proves a rollup's measures re-aggregable over the dimensions it drops, and Cube decides at query time, by its own rules, whether a pre-aggregation may serve a request. A rollup bloomery proves safe and Cube declines to use is wasted; one Cube uses that bloomery did not prove is a wrong number by Cube's reasoning rather than bloomery's, and only a tested configuration can tell which happens. 0058 retired with the emitter built and the comparison unmade — it is readable at `efba2b6`. `ASSUMED` rather than `LOCKED` because it is a row this table owes, not a rule anything enforces; it sits under D4 as a case RFC 0042 does not yet carry, which by that row is where the gap belongs first. Transferred at RFC 0058's retirement — see [`logs/T-0035.md`](../logs/T-0035.md). |

| 9 | `LOCKED` | **Reproduction bundles live in this repository, under `comparisons/<system>/<case>/`.** D6's objection — third-party configuration falling under gates written for bloomery's own source — turned out not to arise: `just quality` runs ruff and mypy over `src` alone and the pre-commit hooks are scoped `^src/.*\.py$`, so the tree needed no exclusion from any of them and `tools/spikes`'s deptry exclusion was not even needed as precedent. The one gate that does read `comparisons/` is written for it rather than inherited from `src` — row 10's, which reads a bundle's pinned version and date and never lints its configuration. In-repo is what makes D5 enforceable: a docs sentence points at an `observed.txt` the reader has already cloned, and a gate can read the version a cell pins. `LOCKED` because a docs page now links into the tree and every later link compounds the cost of moving it. Proposed by execution — see [`logs/T-0058.md`](../logs/T-0058.md) (D-6, attempt 1). |
| 10 | `ASSUMED` | **A cell returns to `UNKNOWN` when the version it pins stops matching what the reproduction resolves, or when its check date passes twelve months — and the rule is a gate, not a sentence in §4.** Of D7's three candidates only this one is computable here: a release count needs an index query, and a corpus change does not move a third-party system. `tests/unit/test_comparisons_floor.py` reads each bundle's pinned version and date, compares the version against the installed distribution for a system this repository resolves, and refuses a date past the ceiling. Written as a program because an unmarked stale cell is D2's failure arriving slowly, and a rule in prose is a hope that the next reader re-reads §4 before quoting a cell. `ASSUMED` because twelve months is a judgement a reviewer may set differently; the mechanism is what matters. Proposed by execution — see [`logs/T-0058.md`](../logs/T-0058.md) (D-7, attempt 1). |
| 11 | `ASSUMED` | **The matrix itself is `comparisons/MATRIX.md`, beside the bundles it cites — not a page under `pages/docs/`.** §3 says where a bundle lives and nothing said where the table lives, and the two candidates are not equivalent: a docs page is bound by D5 to what a reproduction supports, which a table whose honest state is mostly `UNKNOWN` cannot satisfy on the day it is created. The matrix is evidence; §6's "documentation may summarize only findings backed by a checked-in reproduction" describes a docs page reading *from* this table, which means the table cannot be that page. Proposed by execution — see [`logs/T-0058.md`](../logs/T-0058.md) (unlisted, attempt 1). |
| 12 | `ASSUMED` | **bloomery's column cites the semantic corpus rather than duplicating it as a bundle.** Every corpus case pins a machine-readable outcome against a stable rule ID and `tests/execution/test_semantic_corpus.py` runs all twelve in the default suite, where a bundle is run by hand — so the citation is the heavier standard, not the lighter one, and D3 asks for the same standard rather than the same file layout. A second bloomery account is exactly the split D4 exists to prevent, arriving from the other side. What D3 actually demands is that the losses are published, and they are: `009-null-denominator` and `011-timezone-boundary` appear as `NOT-REPRESENTED`, and a test refuses a matrix cell edited away from the outcome the corpus pins. Proposed by execution — see [`logs/T-0058.md`](../logs/T-0058.md) (unlisted, attempt 1). |
| 13 | `LOCKED` | **A cell compares which semantic facts a system's vocabulary requires an author to state — never how carefully a system checks facts both systems hold.** Measured on the first column: bloomery refuses 002, 005 and 008's naive models because its spec requires an additivity declaration, so there is a claim on the page to be wrong; MetricFlow's measure schema is closed (`additionalProperties: False`) and none of its keys states that a column is already an aggregate, so the naive model is not a claim its validator declines to check — it is not a claim at all. `NATIVE-PREVENT` printed beside `NOT-REPRESENTED` without that sentence reads as a scoreboard, which is the non-goal in this document's header. Locked for D1 and D3's reason: the failure is not a wrong cell but a true one quoted as a verdict, and only the framing prevents it. Proposed by execution — see [`logs/T-0058.md`](../logs/T-0058.md) (unlisted, attempt 1). |

## 10. Phasing

One system at a time, one case at a time, starting with the corpus cases that already have
pinned bloomery behaviour. A partially filled matrix of researched cells is useful; a fully
filled one containing guesses is not.
