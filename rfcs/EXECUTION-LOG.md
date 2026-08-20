# Execution log

Departures taken while executing an RFC, appended and never edited in place.

**This is not an RFC.** It carries no number, has no status, and never appears in
[`INDEX.md`](INDEX.md)'s table — that document links to it in prose instead. It lives here,
beside the designs it records departures from, because an RFC's own prose may never be
edited to match what was built: doing that launders the flip and destroys the record that a
decision changed at all.

One file for the whole corpus, not one per RFC. Departures cross documents — the unit that
executes one design is the unit that finds an earlier one was built wrong — and a per-RFC
log has nowhere to put that.

`D-NNN` numbers run continuously across the file and are never reused; RFC decision rows
cite them.

## Classes

One question decides the class: **could this have been known before code existed?**

| Class | Test | Meaning |
| --- | --- | --- |
| `discovery` | No — only building it revealed this | Healthy. The RFC was right to be silent. |
| `spec-gap` | Yes — the RFC was silent, or pitched at the wrong altitude | The design process missed something. |
| `drift` | Yes — the RFC covered it and it was built otherwise anyway, **or** the RFC asserted something about reality that execution disproved | **A defect.** |
| `irreducible` | Neither — no amount of design settles it | Stop and spike; ship the information, not the code. |

**`drift` should be zero.** A non-zero count is a finding against the executor, not against
the document — including the second half of that row, because an RFC's evidence is written
by the same hand that executes it. The two halves are not the same failure, so an entry
says which: an implementation that departed, or a claim that was not true when it was
made.

---

# Unit 1 · Retire RFC 0028

Branch `design/rfc-0029-transform-types`. RFC 0028 retirement only; RFC 0029 execution is
gated (see below).

**Drift count: 0.**

No departures. RFC 0028's five decisions were implemented and verified in #41; this unit
only performs the retirement its own status line committed to, now that `558b31c` on
`main` holds the document and a retirement row can name a commit the mainline can reach.

## Carried into the next unit

- **RFC 0029 did not clear the readiness gate.** Three load-bearing decisions the document
  does not settle were found while planning against the code, before any of it was
  written — recorded as [G-1](#g-1)–[G-3](#g-3) below rather than answered in code.
  Execution is blocked on those three being settled in the RFC.

## Gaps found while planning, not yet decisions

These are not departures — nothing was built. They are the readiness-gate findings, kept
here so the planning evidence outlives the conversation that produced it.

### G-1

**A builder gaining its input type changes a documented public type.** RFC 0029 D1 offers
"`Builder` becomes `(input type, column AST, *args) -> AST` **or** gains it by keyword" and
does not choose. `Builder` is exported from `bloomery.__all__` and listed in
`pages/docs/reference/api.md` as an extension point, and `stability.md` binds it: nothing in
an `__all__` moves without a version bump and a changelog entry naming the migration. The
positional form breaks every registered extension builder; the keyword form with a default
does not. The choice decides whether this is a breaking release.

### G-2

**Narrowing a result to its declared type turns a silent widening into a runtime error, and
RFC 0029 does not say where that error should live.** The arithmetic algebra is safe —
`decimal(p1,s1) × decimal(p2,s2)` needs at most `p1+p2` digits, which is exactly what
`_arith_output` declares, so narrowing `multiply` and `round` is lossless. `coalesce` is
not: its declared type is the *input* type, and its fallback literal is not range-checked,
so `{coalesce: 99999999999999}` over a `decimal(12,4)` column typechecks today, widens on
the engine, and would raise on cast once narrowed. Measured on DuckDB:
`CAST(d * 10000 AS DECIMAL(13,4))` raises `ConversionException` where the unnarrowed
expression returns a `DECIMAL(18,4)`. Compile-time refusal of the out-of-range literal and
a runtime cast failure are different products; §5 puts the precision algebra out of scope
without settling this.

### G-3

**RFC 0029 §4 and the project's own non-negotiable disagree about `divide` on DuckDB.** §4
says the DuckDB `DOUBLE` row needs "a documented port note plus a narrowing cast" because
the engine has no exact decimal division. A narrowing cast does not remove the float — the
division still happens in binary floating point and the result is rounded into a decimal —
and `CLAUDE.md` states, as non-negotiable, that no float may appear on an emission path
(RFC 0003 D5). Either §4 is wrong, or the invariant needs an explicit carve-out for an
operation the engine cannot express exactly. Refusing `divide` on DuckDB and emulating it
with scaled integer arithmetic are both live alternatives and neither is argued in the
document.

---

# Unit 2 · RFC 0029 · transform types the engine agrees with

Branch `design/rfc-0029-transform-types`. RFC 0029 §2.1–§2.4, decisions D1–D6 —
**complete and retired** in this unit; readable at `558b31c`.

**Drift count: 1** — D-004, against RFC 0029's evidence, found while executing it.
Self-audit added four findings (A-1–A-4) and four unlogged departures (D-006–D-009);
none was a `drift`.

Executed after the readiness gate was overridden by the author, who elected to proceed
with G-1–G-3 decided by the executor rather than amended into the RFC first. D-001–D-003
are those three decisions, taken under that delegation and recorded before any code was
written. Each proposes a row back to RFC 0029.

## D-001 — `Builder` gains its input type by a declared flag, not a changed signature

- **Touches:** RFC 0029 D1 (`ASSUMED`), gap [G-1](#g-1)
- **RFC said:** "`Builder` becomes `(input type, column AST, *args) -> AST` **or** gains it
  by keyword" — two forms, no choice
- **Built:** a transform declares `types: True` on its `TransformSpec`, and only those
  builders are called with `input_type=`. Existing builders and every registered extension
  keep their current signature.
- **Because:** `Builder` is exported from `bloomery.__all__` and named in `api.md`'s
  extension-point table, and `stability.md` binds it — nothing in an `__all__` moves
  without a version bump and a changelog entry naming the migration. The positional form
  breaks every third-party builder to serve six built-in ones. A declared flag is also how
  this codebase already carries per-transform facts (`variadic`, `nullifies`), so the
  registry gains no new *kind* of thing.
- **Class:** `spec-gap`
- **Consequence:** a builder that needs its input type must say so; forgetting the flag is
  a silent miss rather than a `TypeError`. The conformance battery is what catches it —
  the declared type stays wrong and the row stays in `KNOWN`.
- **Proposed row (RFC 0029):** D1 is settled as the keyword form, gated by a `types` flag
  on `TransformSpec`; the public `Builder` type is unchanged and this is not a breaking
  release.

## D-002 — an out-of-range `coalesce`/`nullif` literal is refused at compile time

- **Touches:** RFC 0029 D2 (`ASSUMED`), §5 ("the precision algebra is not in question"),
  gap [G-2](#g-2)
- **RFC said:** nothing — D2 narrows arithmetic results and is silent on what narrowing
  does to a literal that does not fit
- **Built:** `typecheck_chain` refuses a `coalesce`/`nullif` literal outside its declared
  type, so the narrowing cast D2 adds can never be the thing that fails
- **Because:** `coalesce`'s declared output is its *input* type, and its literal is not
  range-checked, so `{coalesce: 99999999999999}` over a `decimal(12,4)` column typechecks
  today and the engine quietly widens to fit it. Narrowing without the check converts that
  into a runtime `ConversionException` on the first NULL — measured on DuckDB:
  `CAST(d * 10000 AS DECIMAL(13,4))` raises where the unnarrowed expression returns
  `DECIMAL(18,4)`. A compile-time refusal is the same information one stage earlier, and
  RFC 0008 D3 already says fail loud rather than approximate.
- **Class:** `spec-gap`
- **Consequence:** a spec that compiles today stops compiling. It was already outside its
  declared type; nothing that was correct becomes an error.
- **Proposed row (RFC 0029):** a literal argument whose value does not fit the transform's
  declared output type is a `TypeCheckError`, not a runtime cast failure.

## D-003 — DuckDB's `divide` keeps a float behind a narrowing cast, and the invariant says so

- **Touches:** RFC 0029 §4 and D3 (`ASSUMED`), `CLAUDE.md`'s "no floats in IR or emission
  paths" (RFC 0003 D5), gap [G-3](#g-3)
- **RFC said:** §4 — a documented port note plus a narrowing cast
- **Built:** §4 as written, and the carve-out stated in the dialect reference rather than
  left as a contradiction
- **Because:** DuckDB's `/` is float division and `//` is integer division; the engine has
  no exact decimal division to reach for. The alternatives were both worse: refusing
  `divide` on DuckDB removes a working transform from the default dialect and breaks the
  flagship example's `unit_price`, and emulating exact division with scaled integer
  arithmetic is unproven lowering work this RFC does not schedule. The narrowing cast does
  not remove the float; what it does is bound it to one operation on one port, with the
  emitted type finally equal to the declared one.
- **Class:** `spec-gap`
- **Consequence:** the non-negotiable in `CLAUDE.md` is now inexact as stated. It is left
  unedited on purpose — that file is the author's — and this entry is the flag.
- **Proposed row (RFC 0029):** where an engine has no exact operator for a transform, the
  port emits the engine's operation and narrows the result to the declared type; the
  divergence is documented per port rather than registered as a permanent row.
- **Deliberately not applied:** refusal on DuckDB via the D4 capability mechanism. It is
  the consistent reading of the invariant and was rejected on blast radius, not on
  principle — if the author prefers it, D-003 is the entry to reverse.

## D-004 — the shipped float is a catalog recipe, not `divide`

- **Touches:** RFC 0029 §2.2 (evidence, not a decision row)
- **RFC said:** `divide` "is shipping", evidenced by three `ecom_basic` goldens
  computing `unit_price` as `CAST(CAST(total AS DOUBLE PRECISION) / qty AS DECIMAL(12, 4))`
- **Built:** the marker, which fixes `divide` — and moved **no golden**, because that SQL
  is not `divide`. `unit_price` comes from the `from_total` catalog recipe,
  `expr: line_total / quantity`, whose SQL is parsed rather than built and therefore
  carries no marker. No fixture uses the `divide` transform at all.
- **Because:** the two were conflated while writing §2.2 — a float division was found in a
  golden and attributed to the transform being measured, without checking which surface
  emitted it. The register's `divide` row was measured directly and is unaffected; the
  golden was corroborating evidence and was wrong.
- **Class:** `drift` — against RFC 0029's own evidence section, written by the same author
  in the previous unit. It could have been known before code existed: `grep divide
  tests/fixtures/` returns nothing, which is the whole finding.
- **Consequence:** a float still ships on a money column in three goldens, from a source
  RFC 0029 does not cover. It is documented in `_builtins.divide` and corrected in §2.2
  rather than left implying the fix reached it.
- **Proposed row (RFC 0029):** whether a catalog recipe's `/` should be marked exact the
  way the transform's is. **Not obviously yes:** a recipe body is arbitrary SQL, and
  `typed=True` over two integer operands is truncating integer division rather than the
  float division it does today — so the same change that fixes a money column would
  silently change an integer ratio. It needs operand types (D1) and probably a narrower
  trigger than "every `Div` in a recipe".

**Drift count for this unit is now 1** — D-004, against RFC 0029, found while executing it.

## D-005 — the whole starter set had no golden coverage, which is why none of this was caught

- **Touches:** RFC 0029 §2 as a whole; no decision row
- **RFC said:** nothing about coverage — it presented the divergences as facts about
  engines
- **Built:** the fixes, and then this observation: **not one register row moved a golden.**
  No fixture uses `json_path`, `divide`, `multiply`, `round`, `abs`, `coalesce` or
  `nullif`, and none writes `parse_ts` with an explicit format. Nine of the twenty-four
  whitelisted transforms compile in no fixture at all.
- **Because:** the fixture corpus grew to cover *features* — quality, merges, marts, SCD2 —
  and the transform whitelist was assumed covered because it is small and each entry is
  a few lines. Every defect in this unit lived in a transform nothing compiled.
- **Class:** `discovery`. Knowable in principle, but only by asking a question nobody had:
  the golden tier answers "does this fixture still emit what it emitted", never "is any
  transform unexercised".
- **Consequence:** the conformance battery now covers all 24 by construction, and its
  completeness guard fails when a transform or an input type arrives without a case. That
  is a stronger floor than fixtures, and it is *type*-shaped: it would not have caught
  `regex_extract` dropping its capture group, which is a value defect, nor the
  `json_path` shallow-path failure, which needed a second case for the same
  (transform, input type) pair.
- **Proposed row (RFC 0029):** none. This belongs in the test strategy, not the design.

## Rules distilled

- **A conformance battery keyed by (interface, input type) still has a hole per
  *branch*.** `json_path` takes two path depths on one input type; the completeness guard
  demanded one case and got the deep one, so the shallow-path failure on PostgreSQL
  shipped and was found only by adding the case by hand (D-005, and the `json_path`
  commit). Enumerate the builder's branches, not just its signature.
- **A type check and a value check fail apart.** `regexp_substr` had the right type and
  the wrong group; `AT TIME ZONE 'UTC'` had the right type and the wrong clock; a
  narrowing cast gives a wrong value the right type. Every port substitution in this unit
  is asserted against DuckDB value-for-value for that reason.
- **The fix that resembles the neighbouring fix is the one to measure twice.**
  `AT TIME ZONE 'UTC'` closed RFC 0028 and *reopens* the same defect in `parse_ts`, where
  the zone was attached by `to_timestamp` rather than carried by the value.
- **Evidence found near a defect is not evidence of that defect.** D-004: a float division
  in a golden was attributed to `divide` without checking which surface emitted it, and
  `grep divide tests/fixtures/` would have said so before any code was written.

## Carried into the next unit

- **The recipe float is open.** `expr: line_total / quantity` in a catalog recipe still
  emits `CAST(x AS DOUBLE PRECISION) /` on PostgreSQL and Trino (D-004). Marking it needs
  operand types and a narrower trigger than "every `Div` in a recipe", since `typed=True`
  over two integers is truncating division.
- **`divide` on DuckDB stays inexact** (D-003), documented in the dialect reference rather
  than registered. `CLAUDE.md`'s float invariant is inexact as stated and was deliberately
  left for the author; `pages/docs/reference/dialects.md` now carries the exception.
- ~~RFC 0029's readiness gate~~ — overridden by the author; G-1–G-3 decided as D-001–D-003.
- **D4 shipped unused.** "Where an engine cannot express a transform, the port declares
  the capability absent and emit refuses by name" was written for the four PostgreSQL
  cases, and all four turned out to be expressible — so no capability was retired and no
  refusal added. The decision stands as policy with no instance, which is worth knowing
  before someone reaches for it: the premise to test first is *inexpressible*, not
  *unimplemented*.

## Self-audit — 2026-08-19, unit 2

Adversarial pass over the finished branch (10 commits, +1049/-569). Scope: whole branch —
source, tests, docs, corpus. Findings are departures the executor did not notice, which is
why they are filed here beside the ones they did.

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| A-1 | Three of four new PostgreSQL rewrites had no coverage outside the Docker tier; a sabotage sweep left every non-Docker tier green | High | Fixed |
| A-2 | `_narrowed` — the branch's largest behaviour change — survived sabotage entirely | High | Fixed |
| A-3 | No `CHANGELOG.md` entry for a branch that moves stored values on all three engines | High | Fixed |
| A-4 | Four departures beyond RFC 0029's decision table went unlogged | Medium | Fixed (D-006–D-009) |

**A-1.** Neutering `_zoneless_parse`, `_variant_is_jsonb` or `_jsonb_extraction` left
`tests/unit`, `tests/golden` and `tests/execution` fully green — only `tests/engines`
(Docker, opt-in) failed. `just test` is what most contributors run and what CI's fast
matrix runs, so a regression in any of them would reach review unremarked. Rendering
assertions added to `tests/unit/test_dialects/test_postgres.py`; the sweep now kills all
four. The engine tier keeps the semantic claims — a wrong-but-zoneless spelling passes the
rendering test and fails the session-zone one.

**A-2.** The same shape, one layer up and worse: removing the narrowing cast from every
arithmetic transform failed **nothing** in the unit tier. No fixture uses `multiply`,
`divide`, `round` or `abs` (D-005), so there was no golden either, and the conformance
battery is engine-tier. Rendering and `TRY_CAST`-shape assertions added to
`test_builtins.py`; re-sabotage now fails seven tests. This is the surviving-mutant case
the audit exists for: the sweep was clean until it wasn't, and coverage — 86% patch, every
uncovered line in `postgres.py` — is what pointed at it.

**A-3.** `stability.md` binds `__all__` to SemVer and says a change may never be *quiet*.
This branch changes emitted SQL on all three engines, and nothing in `CHANGELOG.md` said
so. RFC 0028's timestamp fix (#41) was missing too — a pre-existing omission, filled here
rather than left, because both are restating changes and a reader planning an upgrade needs
them together.

**A-4.** Recorded below as D-006–D-009.

## D-006 — a neutral `variant` cast is `JSONB` on PostgreSQL

- **Touches:** RFC 0029 §2.4 (adjacent to it, not covered by it)
- **RFC said:** nothing — it listed `json_path`'s output type, not the neutral cast
- **Built:** `_variant_is_jsonb`, rewriting any neutral `CAST(x AS JSON)` to `JSONB` on
  this port
- **Because:** `variant`'s neutral type is `JSON` and its PostgreSQL physical type is
  `JSONB`, so *every* neutral variant cast disagreed with the column it cast — latent until
  `COALESCE(jsonb, json)` refused to coerce (`42846`). It is the same declared-vs-produced
  defect the RFC is about, reached from the type map rather than from a transform.
- **Class:** `discovery` — only building D6's literal cast surfaced it.
- **Consequence:** applied *before* the `JSONExtractScalar` lowering, which adds a
  `CAST(... AS JSON)` of its own and means it; ordering is load-bearing and commented.

## D-007 — `neutral_type` moved from `ir` down to `transforms`

- **Touches:** RFC 0029 D1; no row covers where the mapping lives
- **Built:** the logical→neutral-SQL map now lives in `transforms.registry`;
  `ir.generic_type` delegates. `neutral_type` is a new name in
  `bloomery.transforms.__all__`.
- **Because:** a builder declaring `types` needs it, and `transforms` sits below `ir` in
  the layer contract, so the alternative was a second seven-row map that could disagree
  with the first about one row.
- **Class:** `spec-gap`
- **Consequence:** an additive public-surface change, now in the changelog (A-3).

## D-008 — `capture_group` became public and moved earlier in the PostgreSQL pipeline

- **Touches:** RFC 0028 D5's fix, not RFC 0029
- **Built:** `_capture_group` renamed to `capture_group`, exported from
  `dialects.base.__all__`, and applied at the *top* of `PostgresDialect.render`
- **Because:** the base render applies it last, after a port's own rewrites — too late for
  a port that must read the capture group to spell the call at all, which
  `regexp_substr` does. The second application is a no-op on a tree that already names a
  group, and that idempotence is now stated in the docstring and pinned by a test.
- **Class:** `discovery`
- **Consequence:** one more name on a public surface; no behaviour change for other ports.

## D-009 — `coalesce` does not cast a string literal over a `string` column

- **Touches:** RFC 0029 D6, decided in D-001's spirit but narrower than "cast the literal"
- **Built:** the cast is skipped when the input type is `string` *and* the literal is a
  string; `{coalesce: 0}` over a string column still casts
- **Because:** all three engines already read a string literal as text there, so the cast
  buys nothing and the emitted SQL is a reviewed artifact — `{coalesce: unknown}` should
  read as `COALESCE(segment, 'unknown')`. The condition is on the literal as well as the
  type because `COALESCE(text, 0)` does not plan on Trino.
- **Class:** `spec-gap`
- **Consequence:** a legibility exception inside a correctness rule, which is the kind that
  rots. Both branches are pinned by test.

## D-010 — `{json_path: "$"}` rendered a call PostgreSQL does not define

- **Touches:** nothing in RFC 0029 — found by the self-audit's boundary pass, pre-existing
- **RFC said:** nothing; the register listed the two path depths that had cases, and a
  root-only path had neither
- **Built:** a root-only path renders as the operand cast to `JSONB` — the identity, which
  is what the path means
- **Because:** PostgreSQL's extraction functions are variadic but not *nullary*, so both
  `json_extract_path(json)` and `jsonb_extract_path(jsonb)` are undefined. Verified against
  postgres 16 that **both** the old and new spellings fail identically, so this is not a
  regression from this branch — but it is one line inside a function this branch rewrote
  twice, and leaving a knowingly invalid render there would have been a choice.
  DuckDB (`x -> '$'`) and Trino (`JSON_EXTRACT(x, '$')`) both accept their own spelling, so
  PostgreSQL was the only port that could not express a path the spec allows.
- **Class:** `discovery` — the boundary pass asks what the empty case does, and the empty
  case here is a path with no keys.
- **Consequence:** the conformance battery still does not probe it. Its completeness guard
  is keyed by (transform, input type), and this is a third *branch* of the same pair — the
  same hole that hid the single-key failure. Covered by a rendering case instead.

## D-011 — `json_path` subscripts were dropped, and the function form is why

- **Touches:** RFC 0029 §2.4; supersedes the lowering D-006/D-010 described
- **RFC said:** that `json_path` returns `json` where `variant` is `JSONB` — nothing about
  path shapes
- **Built, then rebuilt:** the first fix reached for `jsonb_extract_path`, the `jsonb` twin
  of the function SQLGlot already emitted. That function takes **text** path elements, so
  it had to pull the keys out of the parsed path — and a subscript is not a key. `$[0]`
  rendered as the bare operand (the whole document) and `$.a.b[0]` silently lost its
  `[0]`. Measured against `main`, which rendered `JSON_EXTRACT_PATH(x, 'a', 'b', '0')` and
  indexed correctly, so this was a **regression introduced by the fix**, caught in review
  rather than by the audit.
- **Because:** chaining `->` needs no path-element extraction at all, so nothing can be
  dropped: `-> 'a' -> 'b'` for keys, `-> 0` for a subscript, and the bare cast for a
  root-only path, which is the identity D-010 added a branch for. One branch replaces
  three. Verified against postgres 16 that every shape returns `jsonb` and the right
  value, arrays included.
- **Class:** `discovery` for the shape, but the regression itself was avoidable — the
  self-audit's boundary pass asked what the *empty* path does and got D-010, and never
  asked what a non-key part does. Enumerating the parts a path can contain is the check
  that was missing, not a boundary on the count.
- **Consequence:** `_jsonb_extraction` no longer names path elements, so there is nothing
  for a future path grammar to fall out of.

**Rule distilled:** a lowering that has to *name* the parts of a structure can only carry
the parts it knows the names of — prefer the form that passes the structure through.

---

# Unit 3 · RFC 0026 · the dbt singular-test surface

Branch `design/rfc-0026-dbt-singular-tests`. RFC 0026, whole — it is a one-phase
document — plus the retirement its completion earns.

**Drift count: 0.** Three departures, none of them an implementation that went its own
way: D-012 is a mechanism the RFC could not have known it needed, D-013 is a refusal the
RFC counted that does not exist, and D-014 is a reachability limit on work the author
added past the RFC.

One decision was taken **before** execution and is recorded here because it changes what
shipped: the author extended the lift past the RFC's five refusals to the two checks dbt
was *silently* missing — an entity's `on_fail: fail` audits and its ingestion-metadata
audit. Both were absent under RFC 0016 §5.4's target-coverage sentence, which was written
when this emitter had no artifact for them. The plan flagged it as the one load-bearing
gap; the author agreed to extend. See D-014 for what that actually bought.

## D-012 — an audit body crosses targets as a tree, not as rendered SQL

- **Touches:** RFC 0026 D10 (`LOCKED`) — its mechanism, not its decision
- **RFC said:** "A producer instead returns a *named body* — **rendered SELECT**, name,
  disposition — and each target wraps it."
- **Built:** `AuditBody.select` is an unrendered `exp.Select | exp.Union`.
- **Because:** the dbt emitter rewrites every relation in a body to a `ref()` before
  rendering it (D5), and it can only do that to a tree. A pre-rendered SELECT arrives as
  text, and the only thing text supports is the string substitution D10 refuses in its
  own next sentence. The two halves of D10 are inconsistent as written; the half that
  carries the argument is the one about substitution.
- **Class:** `discovery` — visible only once the body had to reach `_render`.
- **Consequence:** `emit/base.py` gains a public dataclass whose annotation is a sqlglot
  type. Rendering moves to the two call sites that wrap the body, which is where the
  envelope already was.

## D-013 — the fifth refusal does not lift, because there is nothing to route

- **Touches:** RFC 0026 §2's table, §5.4's table, and D1's consequence
- **RFC said:** "An unmapped audit kind" is one of the five refusals a singular test
  lifts, and D1's consequence is that "'no honest mapping' ceases to be a reachable state
  for an audit kind".
- **Built:** the branch stays a refusal, with a corrected message.
- **Because:** a singular test needs a **body**, and an unmapped audit kind has none. The
  `assert:` vocabulary is closed at six kinds — `guardrails/asserts.py` and
  `guardrails/conflict.py` are the only constructors of an `AuditIR` — and
  `audit_predicate` handles exactly the four custom ones. All six already map to a schema
  test, so the branch is unreachable from any spec; it is reachable only by
  hand-building the IR, which is what its test does. Worse, the refusal was **misnamed**:
  the SQLMesh emitter reaches the same branch and dies on a `KeyError`, so this was never
  a dbt limitation but the only guard either target had.
- **Class:** `spec-gap` — knowable before code. The RFC read the five refusal *messages*
  and did not read the predicate behind the fifth, which is why four of them share a
  cause and the fifth only shares a sentence.
- **Consequence:** the lift is four refusals, not five, and the message now says the kind
  is outside the closed vocabulary rather than that dbt cannot map it. §5.4's row is
  wrong as written; the corrected claim lives in the test's docstring and here.

## D-014 — half the extension is unreachable on dbt, and stays anyway

- **Touches:** nothing in RFC 0026 — the author's extension past it
- **Built:** both `fail_audits` and the ingestion-metadata audit lower to singular tests.
  Only the second can be reached by a spec.
- **Because:** an `on_fail: fail` rule needs a `quality:` surface; declaring one opts the
  entity into coercion routing; the implicit `coercible` rules default to `quarantine`;
  and a **key** column's cannot be overridden, because a key mapping takes no `quality:`
  block at all. So every entity that could carry a fail audit also carries a quarantine
  disposition, and `_refuse_quarantine` raises first — measured across four spec shapes,
  including entity-level `quality:` and an untransformed string key. The metadata audit
  has no such problem: `dedupe:` alone does not opt an entity in, and that shape compiles
  on both dialects and both targets.
- **Class:** `discovery` — the coupling runs through three documents (RFC 0016 §5.2's
  coercible default, the key mapping's schema, `_refuse_quarantine`) and no reading of
  RFC 0026 would surface it.
- **Consequence:** the lowering stays, because it is correct and goes live the day dbt
  grows the reject model RFC 0016 §5.4 leaves out of scope. It is covered by a test that
  builds the IR directly, and both the docstring and the changelog say the leg is empty
  rather than letting a reader infer coverage. **The changelog claims the metadata audit
  and does not claim entity fail audits** — that asymmetry is deliberate.
- **Deliberately not applied:** deleting the `fail_audits` leg. Unreachable code is
  untested code, so it got a test rather than a deletion; removing and re-adding it when
  the reject lowering lands is churn that loses the measurement above.

## Rules distilled

- **A refusal message is evidence about a message, not about a capability.** Four of
  RFC 0026's five refusals shared a cause and the fifth shared only a sentence; reading
  `audit_predicate` rather than the five messages would have separated them before the
  RFC was written (D-013).
- **"Silently absent" and "refused" are the same gap seen from two sides, and only one of
  them is in the refusal list.** The dbt target's missing checks were found by asking
  what SQLMesh emits that dbt does not, which is a different question from what dbt
  refuses — and it is the question that found the inconsistency the lift would otherwise
  have created between a step's `on_fail: fail` audit and an entity's.
- **A lift is worth measuring for reachability, not just for correctness.** Half of one
  landed as code no spec can run, and the coupling that makes it so lives in three
  documents (D-014). Ask "what spec reaches this?" before claiming a gap closed.
- **Two targets, one body, one comparison.** Asserting each target's audit body
  separately would pass straight through a divergence; the battery that compares them is
  what makes D10's envelope split provable rather than merely intended.

## Carried into the next unit

- **Entity `on_fail: fail` audits on dbt are lowered and unreachable** (D-014). They go
  live with a dbt reject lowering, which is RFC 0016 §5.4's out-of-scope item and has no
  RFC of its own.
- **RFC 0026 §5.4's row for "unmapped entity audit kinds" is wrong** (D-013). The
  document is retired in this unit, so the correction lives here and in the guard's own
  test; anyone citing that row should read this entry.
- ~~The dbt consumer's gate~~ — fired, and the work it gated has landed.
- **`quarantine:` and `reconcile:` on dbt stay refused**, each on its own argument, and
  both now need *models* rather than tests. `reconcile:`'s message was corrected here to
  stop citing the test surface (RFC 0026 D8).
- **The recipe float** (D-004) and **`divide` on DuckDB** (D-003) are still open; nothing
  in this unit touched them.

## Self-audit — 2026-08-20, unit 3

Scope: 8 commits / 25 files / +1146−306 against `main` @ `d51daf8`, plus this log.
Patch coverage **100.00%** (69/69 added lines) on the full local profile
(unit + golden + property + execution + e2e, 3137 passed / 5 skipped, 99.12% total).
`just test` with `--refusal-census` passes, which is the check that deleting three
refusal functions left no error class unproduced. Sabotage sweep below.

*Written down twice.* The first version of this line claimed 100% before the number was
measured — a prediction from having just closed the one gap the previous run named. It
was right about the percentage and wrong about the count, which is the point: a figure
in a durable document has to be an observation. Recorded rather than quietly overwritten,
because pass 9's rule is exactly the one it broke.

| # | Finding | Status |
| --- | --- | --- |
| A-1 | **A `LOCKED` row's conflict was resolved in code instead of halted.** RFC 0026 D1's consequence — "`_entity_tests`'s `else` branch stops being a raise and becomes a route" — turned out unbuildable (D-013), and the executor kept the raise and logged it. `flag-dont-flip` says a `LOCKED` conflict halts and waits, precisely because an obviously-correct resolution is the one whose confidence is under test. The code outcome is almost certainly right; the procedure was not. | **Open — the author's call** |
| A-2 | **Both `OPEN` rows were decided and neither decision reached this log.** D6 (test-file naming) and D7 (fingerprint header) were settled in `_singular_test`'s docstring only. Choosing an option an RFC delegated is not a departure, so conformance looked perfect while the choice and its rationale lived nowhere a reader of the corpus would find them. | Fixed — D-015, D-016 |
| A-3 | **D4's stated obligation was not discharged.** The row is `ASSUMED` and §10 asks whoever builds this to "confirm the readability claim against real `dbt test` output rather than take it from here". Nothing had. | Fixed — an e2e test reads the built node names and shows a native test carries its column (`not_null_customer_email`) where a singular test carries only the check's own name |
| A-4 | **The plan promised the operator contract in the emitted project and the diff dropped it.** §5.5 calls that sentence the RFC's cost and "not optional"; §10 argues it belongs *in* `dbt_project.yml`. The docs page had it; the emitted bytes did not — and the reader who runs `dbt run` on a generated project is exactly the one who never saw the page. | Fixed — a comment header on `dbt_project.yml`, pinned by a test rather than by the goldens alone |
| A-5 | **A latent `KeyError` behind a refusal's ordering.** `_step_test_artifacts` skipped on `is SQL_MACRO`, copied from the SQLMesh producer, while its dbt sibling `_step_artifacts` skips on `is not SQL_MODEL`. A Tier 3 step reaching the relation resolver has no `ref()` in the map, so it would raise `KeyError` rather than the refusal — unreachable only because `refuse_python_models` runs first, which is exactly the dependency a condition should not have. | Fixed |
| A-6 | **The one body D10 could not unify was the one body nothing watched.** The ingestion-metadata audit keeps two spellings on purpose — SQLMesh's Jinja envelope, and the tree `metadata_audit_select` builds — because §4 rules out changing a correct audit body and a pretty-printed AST is not byte-identical to a template line. Every *shared* body is pinned by the cross-target comparison; this one was pinned by nothing, which is D10's parallel-maintenance failure surviving in the single place D10 does not reach. | Fixed — the two spellings are parsed and compared on all three dialects, verified red |
| A-7 | One added line uncovered: the Tier 1 skip in `_step_test_artifacts`, whose condition A-5 had just changed. | Fixed — a macro-step case |

**Sabotage sweep**, five mutations, four killed:

- `severity` always `error` → killed by the mart-assert and coverage tests.
- the self-relation reverts to a literal `silver.<entity>` → killed by three unit tests and the `multi_source` golden.
- the shared collision predicate `>` → `>=` → killed by four goldens across both targets. **The cross-target comparison survived this one, correctly**: it is a relational check, so a change to the *shared* body moves both sides together. That is the division of labour — the comparison catches divergence, the goldens catch wrongness — and it is why the comparison ships with a control proving it can fail.
- one target's body diverges (`.limit(100)` on the dbt side only) → killed by the comparison on all three dialects, and by nothing else.
- singular tests emitted to `checks/` while `test-paths` still says `tests/` → killed by the e2e build tests, which is the evidence that dbt runs the files rather than merely accepting them.

**And the RFC's own §6 warning, confirmed rather than assumed.** §6 says removing the
`test-paths` declaration would *not* break discovery, because dbt's default is already
`["tests"]`, and that an earlier draft claiming otherwise was wrong. Measured: with the
declaration deleted and the files left in place, the seeded collision still fails
`dbt build`. So the unit test asserts the right thing — that the layout is *stated* — and
the e2e test is what carries the discovery claim.

**Narrowing recorded, not a finding.** §6 asks for "a fixture per lifted refusal". Two
lifted refusals (mart assertions, step audits) are exercised by projects built inline in
their own test modules rather than by corpus fixtures. §6's stated purpose — a test that
discriminates the construct rather than the fixture — is met either way, and
`quality_precedence` could not serve for mart assertions because it also carries a
`reconcile:` block that dbt still refuses.

## D-017 — the path-uniqueness guard is shared, because it stopped being SQLMesh's

- **Touches:** nothing in RFC 0026 — found in review of #43, by both bots
- **RFC said:** nothing. §9 named "test-name collisions" as a risk of the naming
  *scheme* and D6 answered it by showing dbt's generic-test names cannot collide with
  `<entity>_<rule>`. Both were about one family at a time.
- **Built:** `_assert_unique_paths` moves from the SQLMesh emitter to `emit/base.py` as
  `assert_unique_paths`, and both SQL targets call it.
- **Because:** the risk §9 named is real and it is *between* families, not inside one.
  Reproduced before fixing: a mart `a` asserting `b_c` and a mart `a_b` asserting `c`
  both lower to the audit name `a_b_c`, and neither declaration is wrong on its own.
  SQLMesh refuses that project with an `EmitError` naming the path; dbt emitted **two
  artifacts at `tests/a_b_c.sql`** — 8 artifacts, 7 unique paths — so the caller's
  path-to-content map kept whichever was written last and a declared quality gate
  silently did not exist. That is exactly the degradation RFC 0008 D3 refuses, and this
  branch is what created the exposure: before it, dbt wrote no audit artifacts to
  collide.
- **Class:** `spec-gap`. Knowable before code — §9 wrote the risk down, and answering it
  per-family is what let the cross-family case through. The general guard already existed
  and was in the wrong module.
- **Consequence:** a project in that shape now refuses on dbt where it used to emit,
  which is a changelog entry rather than a silent fix. Cube is deliberately not a caller:
  its paths are `model/cubes/<mart>.yml` and `model/views/<mart>_view.yml` over mart
  names already unique by construction, so the map is injective and the guard would have
  no instance.
- **Also closes an untested raise.** The SQLMesh guard had shipped since RFC 0017 with
  **no test that it fires** — line-covered because it runs on every emit, and its refusal
  branch never exercised. The battery added here drives both targets, so the older half
  of the contract is proved for the first time too.

## D-015 — a singular test's filename is the audit's own name, unprefixed

- **Touches:** RFC 0026 D6 (`OPEN`)
- **RFC said:** the executor decides between the raw audit name and a `bloomery_` prefix
  matching the macro's convention, and logs it.
- **Built:** `tests/<audit name>.sql`, no prefix.
- **Because:** audit names are already unique per project and constrained to
  `[a-z0-9_]+`, and dbt's generic tests are named mechanically from their model, column
  and arguments (`accepted_values_order_segment__business__consumer`), so nothing dbt
  generates can collide with `<entity>_<rule>`. A prefix would buy nothing and cost every
  failure report its readable name. §9's "test-name collisions" risk is answered by the
  namespace being provably disjoint rather than by decoration.
- **Class:** `spec-gap` by the log's own definition — the RFC delegated it, so nothing was
  missed, but the entry exists because an `OPEN` row answered only in code is
  indistinguishable from a row nobody read.
- **Consequence:** an audit has one name on both targets, which is what lets the
  cross-target comparison pair the bodies at all.

## D-016 — every artifact carries the fingerprint header, tests included

- **Touches:** RFC 0026 D7 (`OPEN`)
- **RFC said:** decide, and the decision is either "yes, uniformly" or an explicit
  statement of which artifact classes carry one and why.
- **Built:** yes, uniformly.
- **Because:** the alternative is not "leave it off a test" but "write down a rule about
  artifact classes", and no such rule exists today — every emitted file carries the
  header. Uniformity is the cheaper claim to keep true, and §10's doubt (whether a
  fingerprint means anything on an artifact nobody diffs) argues against the header's
  *usefulness* on a test rather than against its cost.
- **Class:** `spec-gap`, on the same reading as D-015.
- **Consequence:** `plan()` sees a test's fingerprint move with the project's, like every
  other artifact.
