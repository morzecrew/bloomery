# RFC 0061 — Declared input currency for conversion

- **Status:** 🚧 In progress — P1 has landed: `currency_in:`, R009, the chain walk and §5.3's two-hop fix. P2 (per-row denomination lowered) is unscheduled. D9 records the two §6 tests execution struck and why; §6 keeps its text. The refusal it adds is small; the spec surface it
  adds is one optional key, and the migration is one line per converting field.
- **Scope:** Give a currency conversion's *input* a declared fact to be checked against.
  `{convert: [<from>, <to>, <anchor>]}` asserts what currency the column holds, and nothing
  verifies it — so a wrong `from` applies the wrong rate and returns a plausible wrong
  number. This RFC adds `currency_in:` to a mapping's field, derives a conversion's input
  from the chain where a previous step already fixed it, refuses a conversion whose input is
  unknown, and mints the proof rule that says on what basis a converted column is in the
  currency it claims. Touches `spec/mapping.py`, `resolve/build.py`'s conversion lowering,
  `semantic/proof.py`'s registry, and the arithmetic guardrail's currency rule. No emitter
  changes; no change to how a rate is looked up.
- **Related:** [`src/bloomery/transforms/_builtins.py`](../src/bloomery/transforms/_builtins.py)
  — the `convert` marker; [`src/bloomery/resolve/build.py`](../src/bloomery/resolve/build.py)
  — the conversion lowering and its `to`-side refusal;
  [`src/bloomery/guardrails/arithmetic.py`](../src/bloomery/guardrails/arithmetic.py) — the
  currency rule; [`src/bloomery/spec/catalog.py`](../src/bloomery/spec/catalog.py) — where
  `currency:` may be declared today; [RFC 0038](0038-measure-semantic-types-and-additivity.md)
  D3, whose second clause this document is the missing half of;
  [RFC 0039](0039-semantic-proof-ir.md) — the proof registry this mints into;
  [RFC 0042](0042-semantic-bug-corpus.md) — case 004.
- **Origin:** Executing RFC 0038 D3 halted on a readiness gate; the probes that produced §3
  are in [`logs/T-0024.md`](../logs/T-0024.md) (D-155).

---

## 1. Summary

A conversion says three things and bloomery checks two of them. `{convert: [EUR, USD,
paid_at]}` names the currency the column is in, the currency it should end up in, and the
date that picks the rate. The second is checked against the catalog and the third is
resolved against a real field. The first is an assertion about the column's own values, and
there is no fact in the system to check it against, because `currency:` may be declared only
on a canonical field and a mapping's `from:` is a JSON path into bronze that declares
nothing.

So this compiles clean, reads the yen rate, and applies it to euros:

```yaml
amount_usd: {from: "$.amount_eur", transform: [{to_decimal: [12, 4]}, {convert: [JPY, USD, paid_at]}]}
```

This RFC gives the input a declaration — `currency_in:` on the mapping's field — derives it
for any conversion a previous step in the same chain already fixed, and refuses a conversion
whose input is neither. Acceptance then cites a rule instead of resting on silence.

## 2. Motivation

**The failure is the one this project exists to refuse.** Nothing errors, every cast
succeeds, the SQL is valid, and the number is wrong by whatever the two rates differ by.
It is RFC 0042's inclusion rule stated exactly, and it is reachable from four authored
characters.

**The check that exists is on the wrong side of the operation.** `resolve.build` refuses a
conversion whose `to` disagrees with the column's declared currency, and the message
explains why: the guardrail "would then reason about this column in a currency it is not in,
which is how a wrong number passes every check". That reasoning applies with equal force to
`from`, and `from` is unguarded.

**RFC 0038 D3 asks for a proof and there is nothing to prove.** D3 (`LOCKED`) says currency
behaviour "becomes a proof-producing rule rather than a waiver that suppresses the
mismatch". Executing it found no waiver to replace — RFC 0023 D5 had already deleted the
marker that waived the arithmetic — and no obligation left to discharge, because the
checkable half is checked and the other half has no fact to close it against. A rule whose
only leaf is the assertion under test restates the assertion. **The missing piece is not a
rule, it is the fact a rule would read**, which is what this document adds.

## 3. Current state

Verified against `03d3ade` by compiling deliberately wrong specs; the probes are in
[`logs/T-0024.md`](../logs/T-0024.md).

- **`currency:` is declarable on a canonical field and nowhere else** —
  `spec/catalog.py:65`. Neither `SimpleFieldMapping` nor an entity `Field` carries one, so
  the input side of a conversion has no declaration anywhere in the spec language.
- **A wrong `from` compiles clean.** `{convert: [JPY, USD, paid_at]}` on a column whose
  values are euros produces artifacts with no diagnostic.
- **A wrong `to` is refused, at resolution** — `resolve/build.py:2320`, before any guardrail
  runs, with a message naming both the declared currency and the produced one.
- **The `to` check runs per marker, so a legitimate two-hop conversion is refused.**
  `[{convert: [EUR, CHF, paid_at]}, {convert: [CHF, USD, paid_at]}]` fails on the first
  step with *"convert produces 'CHF' but column 'amount_usd' is declared 'USD'"* — a message
  written for a single conversion, describing a chain that ends in USD correctly. Bridging
  through a major currency is how minor pairs are converted in practice, so the restriction
  is real and its diagnostic misleads.
- **`convert` is currency-only**, by signature and by its `fx_rates:` backing
  (`transforms/_builtins.py:799`). `Unit` has two members, `currency` and `count`; there is
  no unit conversion for D3's `Distance<km> + Distance<m>` case.
- **The proof registry holds R001–R008** (`semantic/proof.py:194`), append-only, and
  RFC 0039 §3 already lists "explicit unit conversion" among the rules it anticipates.
- **Corpus case 004 pins its converted arm against `"rule": "RFC 0023 D11"`** — a document
  citation where RFC 0042 D3 asks for a stable rule id, because no rule id exists to name.

## 4. Goals / Non-goals

**Goals**

- A conversion's input currency is a **declared or derived fact**, never an unchecked
  assertion.
- A conversion whose input is unknown is **refused**, naming the declaration that would
  settle it.
- A chain of conversions is checked for **internal coherence**, and the column's currency is
  the one the *last* conversion produces.
- Acceptance of a converted operand cites a **rule id**, so RFC 0042's "which rule admitted
  this?" has an answer for currency.

**Non-goals**

- **Inferring a currency from data, a column name, or a source path.** RFC 0021 closed
  inference for exactly this class; a guessed denomination is `INFERRED_HEURISTIC`, which
  RFC 0039 D1 refuses as a way to close an obligation.
- **Unit conversion.** D3's unit clause has only its refusal half and no declared conversion
  to name; designing a dimension system with declared factors is its own document (§8).
- **Verifying that the rate relation's contents are correct.** bloomery reads rates and
  never invents them (RFC 0023); this document is about which rate is asked for, not
  whether the operator's feed is right.

## 5. Design

### 5.1 The input currency is one of three things

A conversion step's input currency is **known** if and only if one of these holds, checked
in this order:

1. **Derived from the chain.** A previous `convert` in the same transform chain produced a
   currency; that is this step's input. Free, no declaration, and it is what makes a
   multi-hop conversion expressible.
2. **Declared on the mapping's field.** `currency_in:` sits beside `from:` and `transform:`,
   which is the one place in the spec language where a source path and a transform chain
   meet — so it is the only place that can say *this JSON path holds euros*.
3. **Named as a column, for per-row denomination.** `currency_in: {column: currency_code}`
   for the shape a payment processor actually exports: an amount and the code it was taken
   in, one row at a time.

Otherwise the conversion is **refused**.

```yaml
# 1 — derived: only the first step declares
amount_usd:
  from: "$.amount"
  currency_in: EUR
  transform: [{to_decimal: [12, 4]}, {convert: [EUR, CHF, paid_at]}, {convert: [CHF, USD, paid_at]}]

# 3 — per-row: the code lives in a sibling column
amount_usd:
  from: "$.amount"
  currency_in: {column: currency_code}
  transform: [{to_decimal: [12, 4]}, {convert: [USD, paid_at]}]   # P2 — see D10
```

Three shapes rather than two because the vocabulary has to admit per-row denomination from
the first commit even if nothing lowers it yet. Adding it later means a *second* mechanism
for "what currency is this in", which is the argument that withdrew RFC 0040's P3: a
capability the design already expresses once, expressed a second way, is worse than the
capability being absent.

### 5.2 `from` stays, and is checked

`from` becomes derivable everywhere once §5.1 holds, and it is kept anyway. A conversion
that reads `{convert: [USD, paid_at]}` cannot be understood without looking somewhere else
to learn what it converts *from*, and that cost is paid by every future reader, while the
redundancy costs one comparison at compile time. A `from` that disagrees with the known
input is refused, naming both.

This is a *checked* redundancy, which is why it does not repeat RFC 0038 D5's second-spelling
mistake: there, `additivity:` and `ratio:` said one fact twice with nothing comparing them.

### 5.3 The column's currency is the chain's last conversion

The `to`-side check moves off the individual marker and onto the chain: intermediate steps
are checked against the *next* step's input, and only the final conversion's `to` is compared
with the canonical field's declared `currency:`. This fixes §3's refused two-hop chain
without weakening anything — the guarantee the existing check buys, that the guardrail never
reasons about a column in a currency it is not in, is a property of where the chain *ends*.

### 5.4 R009, and what it may cite

```text
R009  a converted column is in the currency its last conversion produced,
      from an input that was declared or produced by a prior conversion
```

Its facts are the `currency_in:` declaration (`DECLARED`), or the premise proof of the
preceding conversion — so a multi-hop chain is a proof with a premise, which is the shape
RFC 0039 §3 already gives `Proof`. A per-row input is `DECLARED` too: what is declared is
*which column carries the code*, not what the code is.

The rule converts nothing in the corpus and refuses a new class, which RFC 0042 D5 permits
by name — "a soundness fix may legitimately convert *nothing* while still being necessary".
Case 004's converted arm re-pins from `RFC 0023 D11` to `R009`.

### Alternatives considered

- **Drop `from` from `convert`.** Once the input is known, `from` is wholly redundant, and
  the three-argument spelling already replaced a one-argument one. Rejected for §5.2's
  readability reason and because it is a breaking spelling change to every converting spec
  for no checking gain — the check is what removes the risk, not the shorter call.
- **Accept a missing `currency_in:` when `from` is present, treating `from` as the
  declaration.** This is the smallest migration and it is a waiver wearing a proof's
  clothes: the assertion under test would be its own evidence, which is the exact failure
  RFC 0038 D3 was written against.
- **Declare the input currency on the entity field or the canonical field.** Both are
  further from the source path than the mapping is, and a canonical field is shared across
  mappings — one field mapped from a euro feed and a dollar feed would need two different
  input currencies for one declaration.
- **Infer from the column name** (`amount_eur` → EUR). Cheap, wrong under any renaming, and
  closed by RFC 0021.

## 6. Tests

> **Two items below were struck by D9 and are not P1's** — the per-row `column:` name check
> in the refusal battery, and the whole adversarial bullet. The text stands as written so a
> reader can see what was asked for and what execution answered; D9 says which and why.
> Everything else here is built.

- **Refusal battery**: unknown input; `from` disagreeing with a declared `currency_in:`;
  `from` disagreeing with a prior step's output; a per-row `column:` naming a field the
  mapping does not produce.
- **Acceptance battery**: single conversion with a declaration; a two-hop chain where only
  the first step declares — the case §3 shows is refused today; a conversion whose column
  declares no `currency:` at all.
- **The proof**: R009's tree for a two-hop chain has the premise structure §5.4 describes,
  and every leaf's provenance `closes`.
- **Corpus**: case 004's converted arm pins `R009`, and a new arm pins the wrong-`from`
  refusal against the same fixture, since the data is already there.
- **Adversarial, per RFC 0039 §5**: a project accepted before this change and unchanged by
  it stays accepted — the monotonicity property, asserted over the fixture corpus rather
  than argued.

## 7. Docs

`pages/docs/concepts/data-quality.md` and the currency section of
`pages/docs/concepts/specs-and-catalog.md` gain `currency_in:`, and
`pages/docs/reference/errors.md` gains the refusal. The migration note must say plainly that
**a converting spec that compiled yesterday is refused until it declares its input** — one
line per converting field — and must not describe the change as a tightening of something
that was previously checked, because nothing was.

## 8. Out of scope

- **Unit conversion.** D3's `Distance<km> + Distance<m>` needs declared conversion factors
  and a dimension algebra. Named as the next thing this area owes, not built.
- **Lowering a per-row conversion.** §5.1 admits the vocabulary; the emitted lookup joins
  the rate relation on a literal today and would join on a column instead. P2 (§12).
- **`tax_basis` and `unit` on the input side.** The same declaration hole exists — both are
  canonical-only — but no transform asserts them, so nothing is currently unchecked. When
  one does, it reads this design.
- **Rate-relation coverage.** Whether the operator's `fx_rates:` actually holds a row for
  the pair and date is a runtime fact; a missing rate already turns the amount NULL and that
  is RFC 0023's ground.

## 9. Risks

- **The migration is breaking and silent to a reader of the diff.** A converting spec that
  compiles today stops compiling. Mitigated by the refusal naming the exact line to add, and
  by there being few such specs — but the honest statement is that this newly refuses
  accepted projects, and §7 requires the note to say so.
- **`currency_in:` reads as documentation and gets copied wrong.** It is load-bearing, and a
  wrong one is exactly the bug this document is about — moved from `convert`'s first argument
  to a new key. What changes is that it now has *one* home and a rule that reads it, rather
  than being asserted per step; what does not change is that a human must get it right.
- **Per-row denomination admitted but not lowered** can read as a promise. The refusal for a
  `column:` input in P1 must say it is unbuilt rather than invalid.
- **R009 could become a rule nobody reads.** Its consumer is the corpus's outcome pin and the
  explain surface; if neither lands, the rule is bookkeeping. §12 gates it behind the corpus
  re-pin for that reason.

## 10. Unresolved questions

- **What a per-row conversion does with a code the rate relation has no row for.** Per-row
  makes this a data question rather than a spec one, and the answer is probably the existing
  NULL behaviour plus a quality rule — but it is not settled, and P2 is where it must be.
- **Whether `currency_in:` belongs on `RecipeFieldMapping` and `MacroFieldMapping` too.** A
  recipe's chain can contain a conversion; a macro's body is opaque SQL and probably cannot
  be reasoned about at all. Decide when P1 meets them.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **A conversion's input currency must be a declared or derived fact; an unknown input is refused.** This is the whole document: an assertion that nothing can check is indistinguishable from a fact, and the difference is a wrong number that passes every existing guard. Locked because relaxing it — accepting `from` as its own evidence — restores exactly the situation RFC 0038 D3 was written against, and because the refusal is what makes R009 mean anything. |
| 2 | `LOCKED` | **A currency is never inferred — not from a column name, a source path, or the data.** RFC 0021 closed inference for this class and RFC 0039 D1 refuses `INFERRED_HEURISTIC` as a way to close an obligation. Locked because a guess here is indistinguishable at the call site from a declaration, which is the property that makes the guess dangerous rather than merely imprecise. |
| 3 | `LOCKED` | **The column's currency is what the chain's *last* conversion produces.** The existing per-marker check refuses a correct two-hop chain (§3), and bridging through a major currency is how minor pairs convert in practice. Locked because the guarantee the check buys is a property of where the chain ends, and any rule reading an intermediate step is reading a currency the column is never in. |
| 4 | `ASSUMED` | **`from` is kept and checked rather than dropped.** It is derivable everywhere once D1 holds, and it stays because a conversion whose source currency is not at the call site costs every future reader a lookup. Not `LOCKED` because the redundancy is a judgement about readability against ceremony, and execution may find the double declaration is a nuisance in practice — if so, depart with the migration note, since removing it is a spelling change rather than a semantic one. |
| 5 | `ASSUMED` | **Per-row denomination is admitted by the vocabulary from the first commit, and refused as unbuilt until P2.** Adding it later means a second mechanism for "what currency is this in", which is the argument that withdrew RFC 0040's P3. Not `LOCKED` because if P1 shows the `column:` form distorts the declaration's shape, a separate spelling is a defensible retreat — but it must then be designed, not improvised. |
| 6 | `ASSUMED` | **The declaration lives on the mapping's field, not on the entity or canonical field.** The mapping is where a source path and a transform chain meet, and a canonical field is shared across mappings — one field fed by a euro feed and a dollar feed would need two input currencies for one declaration. Not `LOCKED` because a project that never maps the same canonical field twice would not notice the difference. |
| 7 | `OPEN` | **Whether `currency_in:` extends to `RecipeFieldMapping` and `MacroFieldMapping`.** This row assumed a recipe's chain can hold a conversion, and it cannot: a `Recipe` is `{id, requires, expr}` — a SQL expression over aliases, with no transform chain — and a macro's body is opaque SQL. Neither can carry a `convert` step, so neither can hold a conversion whose input would need declaring, and neither reaches the code that would ask. Answered "no" for both, and "yes" for `KeyField`, which this row did not think to ask about (see [`logs/T-0025.md`](../logs/T-0025.md), D-158). |
| 8 | `OPEN` | **Whether R009's proof is retained anywhere or produced on demand.** `prove_rollup` is called by the planner when someone asks; a conversion happens once at compile time and nobody asks later. Deciding it decides whether the guardrail stage grows a proof channel — which is a bigger change than this document, and probably the wrong place for it. Prefer on demand, and log the reason. |
| 9 | `ASSUMED` | **Two of §6's tests are struck rather than written.** The per-row item — a `column:` naming a field the mapping does not produce — cannot be written as §6 states it, because D5 refuses per-row as *unbuilt* before anything reads the name; the check belongs with the P2 lowering that would use it. The monotonicity item is a property this phase declares itself an exception to: converting specs that compiled yesterday are refused, which §9 names as breaking, so asserting `SafeQueries(N) ⊆ SafeQueries(N+1)` over a corpus containing the exception either fails or is written to exclude what it exists to check. The residue — that nothing which does not convert is affected — is what the whole-corpus suite already asserts. Not `LOCKED` because a later phase that makes per-row real should re-read §6 rather than this row. Added by execution 2026-09-07 — see [`logs/T-0025.md`](../logs/T-0025.md) (D-161, attempt 4). |
| 10 | `OPEN` | **How a per-row conversion spells its source currency.** §5.1's example wrote `{convert: [*, USD, paid_at]}`, and `*` is not an ISO-4217 code — resolution refuses it on the code format before the per-row refusal is reached, so the example was uncopyable and the question it stood in for was never asked. With the input declared on the field, `from` is derivable and the two-argument spelling is the obvious candidate; keeping a three-argument form would need something to write in the first slot that is not a currency. Decide with P2's lowering, which is the first code that reads it. Added by execution 2026-09-07 — see [`logs/T-0025.md`](../logs/T-0025.md) (D-162). |

## 12. Phasing

- **P1 — the fact and the refusal.** `currency_in:` as a literal code, chain derivation,
  the coherence check, D3's two-hop fix, and the refusal for an unknown input. R009 minted
  and cited by corpus case 004. A `column:` input parses and is refused as unbuilt.
- **P2 — per-row denomination lowered.** The rate lookup joins on a column rather than a
  literal, and §10's missing-rate question is answered where it can be tested.

Unit conversion is not phased here; it is §8's, and it needs its own document.
