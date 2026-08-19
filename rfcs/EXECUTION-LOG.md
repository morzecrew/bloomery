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
