# RFC 0043 — Evidence-based semantic capability matrix

- **Status:** 📝 Draft — research and specification task, **not a code change**.
  [RFC 0042](0042-semantic-bug-corpus.md) is strongly recommended first: its cases are this
  document's rows.
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
| 6 | `OPEN` | **Where reproduction bundles live — in this repository under `comparisons/`, or beside it.** In-repo makes the citation strongest and puts third-party configuration under gates written for bloomery's own source; out-of-repo inverts both. Decide before the first bundle, since moving them later breaks every link the docs will have made. |
| 7 | `OPEN` | **The staleness policy.** Cells pin a date and nothing says when age alone should return a cell to `UNKNOWN`. Pick a rule — a release count, a month count, or a re-check on each corpus change — and write it into §4, because an unmarked stale cell is D2's failure arriving slowly. |

## 10. Phasing

One system at a time, one case at a time, starting with the corpus cases that already have
pinned bloomery behaviour. A partially filled matrix of researched cells is useful; a fully
filled one containing guesses is not.
