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
| `drift` | Yes — the RFC covered it and it was built otherwise anyway | **A defect.** |
| `irreducible` | Neither — no amount of design settles it | Stop and spike; ship the information, not the code. |

**`drift` should be zero.** A non-zero count is a finding against the executor, not against
the document.

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
