# RFC 0026 — The dbt singular-test surface

- **Status:** 📝 Draft — design proposed, not scheduled. The trigger is a dbt
  consumer; see §12.
- **Scope:** Giving the dbt emitter the one artifact it has never had — a
  **singular test**, a `.sql` file under `tests/` whose query returns the rows
  that fail. Five separate refusals in that emitter give the same reason in
  different words: dbt's schema tests are per-column or per-model *predicates*,
  and a check that groups, joins or aggregates is none of those. A singular test
  is exactly that missing shape, and bloomery's audit bodies are already written
  in it. Touches `emit/dbt/__init__.py`, `emit/steps.py` (four refusal helpers),
  and the emitted `dbt_project.yml`. Adds no IR node, no new `ArtifactKind`, and
  no spec surface. Deliberately does **not** give dbt the reject/replay tables,
  Tier 3 Python models, or composite-key SCD2 snapshots: those need artifacts
  that are *models*, not tests, and each is refused for a reason this RFC does
  not touch.
- **Related:**
  [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py)
  (the emitter and five of the refusals),
  [`src/bloomery/emit/steps.py`](../src/bloomery/emit/steps.py)
  (`refuse_step_audits`, `refuse_coverage`, `refuse_mart_asserts`),
  [`src/bloomery/emit/lower/silver.py`](../src/bloomery/emit/lower/silver.py)
  (`collision_audit_select`),
  [`src/bloomery/emit/sqlmesh/__init__.py`](../src/bloomery/emit/sqlmesh/__init__.py)
  (the audit envelopes this mirrors), RFC 0008 (`DialectPort`, `Feature`,
  `UnsupportedByTarget`, and D3 — fail loud, never degrade silently), RFC 0016
  (dispositions, blocking audits, §5.4's target-coverage sentence), RFC 0024 D5
  and **D30** (the collision audit, and the refusal this lifts).
- **Origin:** RFC 0024 D30, which refused merged entities on dbt and said the
  fix "is its own change and not P2's". Writing that row down surfaced that the
  missing surface was never about the union merge.

---

## 1. Summary

The dbt emitter refuses six constructs. **Five of them are one missing
capability**, and none of the five is about the construct it names: a mart
assertion, a coverage check, a step audit, an exotic entity audit kind, and the
union merge's collision audit are all refused because each lowers to a query
that *groups or joins*, and the only test artifact this emitter has ever emitted
is a `schema.yml` entry — a per-column or per-model row predicate.

dbt has the missing shape and has had it since long before bloomery: a
**singular test** is a `.sql` file whose query returns failing rows, with no
constraint whatsoever on its shape. Every audit body bloomery already generates
is written in exactly that form. SQLMesh's envelope is
`SELECT * FROM @this_model WHERE <violation>`; the collision audit's is a
`GROUP BY … HAVING …`. Both *return the rows that fail*, which is the whole of
the singular-test contract.

So this is not a translation problem. It is a directory bloomery never wrote to.

## 2. Motivation

**The five refusals read as five limitations and are one.** Each was written
separately, each is individually correct, and reading them together is what
shows the shape:

| Refusal | Where | Its stated reason |
| --- | --- | --- |
| Mart assertions | [`emit/steps.py:171`](../src/bloomery/emit/steps.py) | "lowers to an audit over a grouped aggregate, and dbt's schema tests are per-column or per-model *predicates* — there is no grouped form to approximate it with" |
| Coverage checks | [`emit/steps.py:148`](../src/bloomery/emit/steps.py) | "the body joins two relations and groups" — "same argument … one relation further out" |
| Step audits | [`emit/steps.py:101`](../src/bloomery/emit/steps.py) | "whole-query checks — a join between sibling outputs, or an `on_fail: fail` rule's blocking body; neither shape survives the translation" |
| An unmapped audit kind | [`emit/dbt/__init__.py:448`](../src/bloomery/emit/dbt/__init__.py) | "has no honest dbt schema-test mapping" |
| A merged entity | [`emit/dbt/__init__.py:227`](../src/bloomery/emit/dbt/__init__.py) | "its whole test surface is `schema.yml` entries … and a generated `GROUP BY <key> HAVING COUNT(DISTINCT _source) > 1` is none of those" |

Four of the five say "schema tests are predicates" in their own words. The fifth
enumerates the same three test kinds and observes that the audit is not among
them. **The premise they share is true and incomplete**: it describes the tests
bloomery emits, not the tests dbt has.

**What this costs a dbt user is not exotic.** Declaring one `assert:` on a mart
is enough to refuse the whole target. So is one `coverage:` entry. Neither is an
advanced feature; both are ordinary quality declarations documented without a
target caveat, and the refusal arrives at emit — after the spec typechecks, after
the guardrails pass.

**And it is asymmetric in the way that matters most.** RFC 0008 D3's rule is
fail loud, never degrade silently, and every one of these refusals honours it.
But the reason they exist is a gap in *this emitter*, not in dbt — which makes
them a limitation bloomery invented and then documented, which is precisely what
RFC 0024 D20 warned against before D30 had to depart from it.

## 3. Current state

Verified against `main` @ `2489584`.

**The emitted dbt project has three directories and declares them.**
`dbt_project.yml` sets `model-paths`, `snapshot-paths` and `macro-paths`
([`emit/dbt/__init__.py:662-667`](../src/bloomery/emit/dbt/__init__.py)) —
`macro-paths` is declared "though it matches dbt's default … the emitted project
states its own layout". **`test-paths` is absent**, and so is any artifact that
would live under it.

**The whole test vocabulary is three entries wide.** `_entity_tests`
([`emit/dbt/__init__.py:432`](../src/bloomery/emit/dbt/__init__.py)) walks
`EntityIR.audits` and maps:

- `not_null` → dbt's builtin,
- `enum` → `accepted_values`,
- `_EXPRESSION_KINDS = {"min", "max", "regex", "reconcile"}` → the
  `bloomery_expression_is_true` generic test, whose body is the shared audit
  predicate rendered through the dialect port,
- anything else → `UnsupportedByTarget`.

**The generic test is bloomery's own, and that precedent is load-bearing here.**
`macros/bloomery_expression_is_true.sql` is emitted rather than referencing
`dbt_utils` (RFC 0008 D18) because "a package reference leaves the emitted
project *incomplete*, declaring a test no `dbt compile` can build until someone
runs `dbt deps` against the network". A singular test needs no macro and no
package at all — it is a file of SQL — so it is *further* inside that boundary,
not a new exception to it.

**The audit bodies are already singular tests in every respect but their path.**
The SQLMesh envelope is verbatim:

```sql
SELECT * FROM @this_model WHERE {{ predicate }}
```

and the collision audit's is a `GROUP BY <key…> HAVING COUNT(DISTINCT _source) > 1`
([`emit/lower/silver.py:1037`](../src/bloomery/emit/lower/silver.py)). Both
return the offending rows. A dbt singular test is a query that returns the
offending rows. The only substitution is `@this_model` → a model reference, and
**`_reference_map` already builds those strings**
([`emit/dbt/__init__.py:524-562`](../src/bloomery/emit/dbt/__init__.py)),
producing `{{ ref('<model>') }}` for exactly this purpose.

**`ArtifactKind.AUDIT` already exists** and is documented as "custom audit
bodies" ([`emit/base.py:67`](../src/bloomery/emit/base.py)). No new kind is
needed; today no dbt artifact carries it.

**One verified fact that narrows a sixth refusal rather than lifting it.**
`_refuse_reconcile` ([`emit/dbt/__init__.py:266`](../src/bloomery/emit/dbt/__init__.py))
argues in part that "dbt's test surface has no non-blocking equivalent that would
not silently turn 'report the disagreement' into 'fail the build'". dbt tests do
carry `severity: warn`, so that half of the argument does not survive. The other
half does: a reconcile check is "a model **and** a non-blocking audit", and this
RFC gives dbt no models. See §5.5 and D8.

## 4. Goals / Non-goals

**Goals**

- Emit singular tests, so that a check which groups or joins has an honest dbt
  home.
- Lift the five refusals that exist only because that home was missing —
  including RFC 0024 D30, which is the one a user meets soonest.
- Keep the emitted project self-contained: no package dependency, no
  `dbt deps`, no network (RFC 0008 D18).
- Keep every refusal that has a reason of its own, and say which is which.

**Non-goals**

- **Reject and replay tables** — RFC 0016 §5.4. Those are models and a
  statement-to-run, not tests; a test surface does not touch them.
- **Tier 3 Python models** — refused because no adapter bloomery ships can run
  one ([`emit/steps.py:74`](../src/bloomery/emit/steps.py)), which is a fact
  about adapters, not about tests.
- **Composite-key SCD2 snapshots** — dbt's snapshot `unique_key` is one
  expression; unrelated.
- **Making dbt reach parity with SQLMesh.** This closes one gap. Target
  coverage stays partial and stays stated.
- **Changing any audit body.** The bodies are already correct; they are
  currently written to one target.

## 5. Design

### 5.1 What a singular test is

A `.sql` file under `test-paths`. dbt runs the query; **any row it returns is a
failure**. There is no shape constraint — no per-column binding, no requirement
that it be a row predicate. The file's name is the test's name.

That is the entire contract, and it is the contract every bloomery audit body
already satisfies. Nothing needs translating; the bodies need a destination.

### 5.2 What is emitted

`tests/<audit-name>.sql`, one file per audit that has no schema-test mapping,
carried as `ArtifactKind.AUDIT`:

```sql
-- Generated by bloomery — do not edit.
-- fingerprint: <fingerprint>
{{ config(severity='error') }}

SELECT <key…>, COUNT(DISTINCT _source) AS sources
FROM {{ ref('order_line') }}
GROUP BY <key…>
HAVING COUNT(DISTINCT _source) > 1
```

`dbt_project.yml` gains `test-paths: ["tests"]`, declared for the same reason
`macro-paths` is: the emitted project states its own layout rather than relying
on a default.

**The `@this_model` substitution is the only difference from the SQLMesh
artifact**, and it goes through `_reference_map` rather than string formatting,
so a singular test participates in dbt's DAG exactly as a model does — which is
what makes it run against the right relation in the right order.

### 5.3 Which refusals lift, and which do not

| Construct | After this RFC |
| --- | --- |
| Merged entity (collision audit) | **Emitted** — lifts RFC 0024 D30 |
| Mart assertions | **Emitted** |
| Coverage checks | **Emitted** |
| Step audits | **Emitted** |
| Unmapped entity audit kinds | **Emitted** — the `else` branch becomes a singular test rather than a raise |
| `reconcile:` | Still refused — needs a *model* (§5.5) |
| `quarantine:` (reject/replay) | Still refused — models and a replay statement |
| Tier 3 Python models | Still refused — no adapter |
| Composite-key SCD2 | Still refused — snapshot `unique_key` |

**`_entity_tests`'s `else` branch stops being a refusal and becomes a route.**
That is the shape of the whole change: the schema test remains the *preferred*
lowering where dbt has a native equivalent, because a native `not_null` reads
better in `dbt docs` and in test output than a hand-rolled query, and the
singular test is the fallback rather than the replacement.

### 5.4 Blocking, and the one honest weakening

**This is the decision the RFC turns on.** A SQLMesh audit blocks because the
framework evaluates it as part of the model's own materialization. A dbt test
blocks under `dbt build`, which interleaves tests with models and skips
downstream models when one fails — and does **not** run at all under `dbt run`.

RFC 0024 D5 makes the collision audit blocking and not configurable. Does a test
that a particular invocation can skip satisfy that?

**Yes, and the argument is consistency rather than indulgence.** Every schema
test bloomery emits today has exactly this property: a `not_null` on a required
column does not block `dbt run` either. If a `dbt build`-conditional check is
too weak to carry the collision audit, then it is too weak to carry the
`not_null` audits this emitter has shipped since RFC 0008 — and no one has
argued that. Refusing the merge for a property shared by every check already
emitted to this target would be a standard applied once.

What that buys has to be *stated*, not assumed, and it belongs in the operator
contract the emitted project already carries: **on dbt, bloomery's blocking
audits are blocking under `dbt build`.** That sentence is the cost of this RFC,
and writing it down is what keeps this from being a silent degradation under
RFC 0008 D3.

### 5.5 Severity, and why `reconcile:` stays refused

`on_fail` maps to dbt's `severity`: `fail` → `error` (the default, written
explicitly), `flag` → `warn`. This is a real equivalence, not an approximation,
and it corrects half of `_refuse_reconcile`'s argument (§3).

`reconcile:` stays refused anyway, on the half that survives: a reconcile check
lowers to a **comparison model** plus a non-blocking audit over it. This RFC
emits no models. Lifting it means deciding what a reconcile model is on dbt,
which is a separate question with a separate answer, and folding it in here
would let one decision ride on another's argument — which is how D58 came to
carry a claim about severity it did not need.

### Alternatives considered

**Widen `bloomery_expression_is_true` to take a whole query.** The macro exists,
so this looks cheaper. Rejected: a generic test is bound to a model and a
column-or-model scope by dbt's own semantics, and a "generic test" whose
argument is an arbitrary SELECT is a singular test wearing a macro's clothes —
with worse error messages, since a failure reports the macro rather than the
check.

**Emit the checks as models with a `WHERE` that yields zero rows in the good
case.** Works, and it is how some projects fake assertions. Rejected: it puts
check output into the warehouse as tables, makes `dbt run` build them, and gives
an operator no way to tell a check from a dataset. dbt already distinguishes the
two; using the wrong one to avoid writing to a new directory is not a saving.

**Reference `dbt_utils`' `expression_is_true` and its grouped variants.**
Rejected on RFC 0008 D18's existing ground: it makes the emitted project
incomplete until someone runs `dbt deps` against the network. This RFC does not
reopen that.

**Refuse everything that groups, permanently, and document dbt as the
row-predicate target.** The honest status quo, and the one this RFC argues
against: the limitation is bloomery's, not dbt's, and a compiler that refuses a
construct its target supports is describing itself rather than the target.

## 6. Tests

- **A fixture per lifted refusal**, each asserting the emitted `tests/*.sql` and
  each *without* the construct compiling clean — so the test discriminates the
  construct rather than the fixture.
- **`multi_source` gains dbt to its target set.** It is the fixture RFC 0024 P1
  built and could only emit to SQLMesh; the collision audit landing on both
  targets is the assertion that D30 is actually lifted rather than routed around.
- **The two targets' audit bodies are compared, not merely both asserted.** The
  SQLMesh audit and the dbt singular test are the same SELECT modulo the model
  reference and the envelope; a test that pins each independently would pass
  through a divergence. This is the `reading-isnt-proof` shape: one contract,
  two implementations, one battery.
- **Severity round-trip**: `on_fail: flag` emits `severity='warn'`,
  `on_fail: fail` emits `severity='error'` — asserted separately, since a single
  test of one proves nothing about the other.
- **The refusals that stay** get tests proving they still fire, and naming their
  own reason rather than the lifted one. `reconcile:` is the sharp case: its
  message must stop citing the missing test surface (§3) and cite the missing
  model.
- Sabotage: removing `test-paths` from `dbt_project.yml` must fail a test — a
  singular test in an undeclared directory is a file dbt never runs, which is
  the silent-no-op version of this whole feature.

## 7. Docs

- The target-coverage table, wherever it states what dbt cannot do — five rows
  come out, and the `dbt build` sentence from §5.4 goes in.
- `pages/docs/how-to/merge-sources.md` loses its SQLMesh-only note.
- The operator contract gains the `dbt build` requirement, stated as a
  requirement rather than a recommendation.
- **No page may describe dbt as reaching parity.** Reject tables, replay,
  reconcile and Tier 3 remain refused, and a docs page that implies otherwise is
  the defect RFC 0023 §7 names in another form.

## 8. Out of scope

- **Reject/replay on dbt** — RFC 0016 §5.4 and D10. Models and a statement to
  run; unrelated to tests. Would change if someone designs the dbt reject
  lowering.
- **`reconcile:` on dbt** — §5.5. Needs the comparison model. Would change with
  a decision about what that model is.
- **Tier 3 Python models** — no adapter in reach runs one.
- **Test selection, tags, or `store_failures`.** dbt offers all three; none is
  needed to make a check exist, and each is a choice about *operating* the
  emitted project rather than compiling it.
- **Making the dbt target's audits blocking under `dbt run`.** Not possible, and
  §5.4 accepts it rather than working around it.

## 9. Risks

- **`dbt build` vs `dbt run` is missed by a reader**, and a project runs with its
  audits silently unevaluated. This is the RFC's real risk and §5.4 is the
  mitigation — but a sentence in a contract is weaker than a mechanism, and there
  is no mechanism available. Stated rather than solved.
- **The lifted refusals were load-bearing for something else.** Each of the five
  was written independently; this RFC claims they share one cause. If one of them
  turns out to have a second reason, lifting it ships a check that compiles and
  does not mean what it says. §6's per-refusal fixtures exist for this.
- **Test-name collisions.** A singular test's name is its filename, and it shares
  a namespace with generic tests. Audit names are already unique per project and
  constrained to `[a-z0-9_]+`, so this is a risk of the naming *scheme* rather
  than of the data — but it needs a prefix decision (D6).
- **Read as "dbt is now supported".** The most likely misreading, and it would
  undo RFC 0016 §5.4's honesty about partial coverage. Mitigated by §7's last
  bullet and by the refusals that stay.

## 10. Unresolved questions

- **Does the singular test carry the fingerprint header?** Every other artifact
  does, and it is what `plan()` diffs. A `.sql` file whose first line is a
  comment is fine for dbt; the question is whether a test's fingerprint means
  anything to a reader, or is noise on an artifact nobody diffs.
- **Do `not_null` and `enum` stay schema tests?** §5.3 says yes, on readability
  grounds. Emitting *everything* as a singular test would make one mechanism
  where there are two, at the cost of losing dbt's native test output. Whoever
  builds this should confirm the readability claim against real `dbt test`
  output rather than take it from here.
- **Where does the operator-contract sentence live?** It is a property of the
  emitted project, so arguably it belongs *in* the emitted project — a comment
  in `dbt_project.yml` — rather than only in bloomery's docs.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The dbt emitter gains singular tests** — `.sql` files under a declared `test-paths`, one per audit with no schema-test mapping. This is the artifact five refusals were each missing, and it is dbt's own mechanism rather than an approximation of one. Consequence: `_entity_tests`'s `else` branch stops being a raise and becomes a route, so "no honest mapping" ceases to be a reachable state for an audit kind. |
| 2 | `LOCKED` | **A `dbt build`-conditional block satisfies RFC 0024 D5.** A dbt test does not run under `dbt run`, so the collision audit is blocking only under `dbt build`. Accepted because **every schema test this emitter already ships has the same property** — a `not_null` audit does not block `dbt run` either — and refusing the merge for a property shared by every existing dbt check would apply a standard exactly once. Consequence: the emitted project's operator contract states that bloomery's blocking audits on dbt are blocking under `dbt build`; that sentence is this RFC's cost and it is not optional. |
| 3 | `ASSUMED` | **`on_fail` maps to `severity`**: `fail` → `error` written explicitly, `flag` → `warn`. A real equivalence rather than an approximation, and it corrects half of `_refuse_reconcile`'s stated argument (§3) — which is recorded here so that the correction is not mistaken for a licence to lift D58. |
| 4 | `ASSUMED` | **Native schema tests stay preferred where dbt has an equivalent.** `not_null` and `enum` keep their builtin lowering; the singular test is the fallback, not the replacement. Rationale is reader-facing: a native test names its column in `dbt test` output and appears in `dbt docs`, and a hand-rolled query does neither. Graded `ASSUMED` because it is a readability claim, and D10 asks whoever builds this to check it against real output. |
| 5 | `LOCKED` | **The model reference goes through `_reference_map`, never string formatting.** It is what makes a singular test a DAG participant rather than a query that happens to name a table, and it is already built for exactly this shape. Consequence: a singular test is ordered against its model by dbt, which is what makes "blocking" mean anything at all under D2. |
| 6 | `OPEN` | **The test-file naming scheme.** A singular test's name is its filename in a namespace shared with generic tests. Audit names are unique per project and `[a-z0-9_]+`-constrained, so the raw name may suffice; a `bloomery_` prefix would match the macro's convention at the cost of length. Whoever builds this decides and logs it. |
| 7 | `OPEN` | **Whether the fingerprint header goes on a test artifact.** Every other emitted file carries one. Whoever builds this decides, and the decision is either "yes, uniformly" or an explicit statement of which artifact classes carry it and why. |
| 8 | `ASSUMED` | **`reconcile:` stays refused, and its message changes.** The surviving half of D58's argument is the comparison *model*, which this RFC does not provide. Its refusal message currently cites the missing test surface; once that surface exists the message would be false, so lifting-adjacent work has to correct it even though the refusal stands. |
| 9 | `ASSUMED` | **RFC 0024 D30 is lifted, not superseded.** D30's argument was correct when written — the emitter genuinely had no artifact for the audit. What changes is the emitter, not the reasoning, and D30's row stays as the record of why merged entities were SQLMesh-only for one release. |

## 12. Phasing

**One phase.** The five refusals share a cause, and lifting them separately would
mean five changes each re-arguing the same premise. The fixtures in §6 are the
bulk of the work; the emitter change is a template, a path, and turning four
raises into routes.

**Gated on a dbt consumer**, and the gate is worth naming precisely because it is
weaker than RFC 0023 P2's or RFC 0024 P2's. Those wait for someone to need a
feature. This waits only for someone to use **dbt at all** with an ordinary
quality declaration — one `assert:`, one `coverage:`, one merged entity. So the
question is not "does anyone want singular tests" but "does anyone target dbt",
and if the answer is yes this is already costing them.

**Not sequenced against RFC 0024 P2.** They touch different things — P2 is the
quality system on a merged entity in the shared lowering, this is one emitter's
artifact set — and the only contact is D30, which this lifts and P2 does not
read.
