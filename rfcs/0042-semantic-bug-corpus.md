# RFC 0042 — Production-style semantic bug corpus

- **Status:** 🚧 In progress — every name in §3's set now exists under
  [`tests/fixtures/semantic_corpus/`](../tests/fixtures/semantic_corpus/), with the loader,
  its guard, and the execution tier that runs them. **The numbers drifted from §3's list and
  the names did not**: 006 went to a case §3 never names, so `distinct-users-fanout` landed
  as 007 and the last four as 008–011 (logs/T-0028.md, logs/T-0029.md). D7 is answered for
  every case; all of them run in the default suite.
  **It stays 🚧 rather than completing**, and not for want of cases: two of them are
  `unguarded` and cite D5 as the decision a future rule converting them answers to, and
  `test_a_retired_rfc_owns_no_unguarded_case` refuses a retired RFC in that position — so
  the document is held open by the gate it wrote for itself (logs/T-0029.md).
  Execution's findings and the rows it proposes are in
  [`logs/T-0018.md`](../logs/T-0018.md); nothing below has been amended to agree with what
  was built. It had no upstream dependency, and it is what gives the rest of the
  semantic-correctness sequence its acceptance evidence.
- **Scope:** A permanent corpus of cases where SQL and schema validation succeed while the
  analytical answer is semantically wrong. Regression suite, design input, benchmark,
  documentation source, and product evidence.
- **Related:** [`tests/fixtures/dirty/`](../tests/fixtures/dirty/) — the existing
  dirty-data corpus, which this deliberately does **not** extend (§2);
  [`tests/fixtures/fanout_trap/`](../tests/fixtures/fanout_trap/);
  RFC 0009 (testing strategy and fixture corpus, retired), RFC 0016 (data quality,
  retired).

---

## 1. Inclusion rule

A case belongs in the semantic bug corpus when:

> Ordinary syntax, type, and basic schema validation can pass while a plausible query still
> returns the wrong business answer because declared semantics were not preserved.

The corpus is not a replacement for parser tests, null tests, uniqueness tests, or ordinary
warehouse data-quality fixtures.

## 2. Why this is not the dirty corpus

`tests/fixtures/dirty/` already exists and answers a different question. Its specimens are
*values that will not survive a cast* — `01/02/2025`, `0000-00-00`, a leap second — and
each one is either quarantined or passes. Every case there is about a value bloomery can
see is wrong.

This corpus is the opposite: every value is valid, every cast succeeds, the query runs, and
the number is wrong anyway. Sharing a directory with the dirty corpus would blur the one
distinction both exist to make, and a reader looking for "why was this row rejected" would
find cases where nothing was.

`fanout_trap` is the nearest existing fixture and is a single case; case 001 below is its
generalization.

## 3. Initial case set

```text
001-order-shipping-fanout/     006-distinct-users-fanout/
002-average-of-averages/       007-ratio-rollup/
003-scd2-unqualified-join/     008-null-denominator/
004-currency-mix/              009-many-to-many-bridge/
005-semi-additive-balance/     010-timezone-boundary/
```

Additional cases require a short justification against §1.

## 4. Case layout

```text
problem.md   schema/   data/   naive.sql   correct.sql   expected/   bloomery/
```

`problem.md` states: the business question; declared semantic facts; the tempting naive
query; why that SQL is valid; the wrong result; the correct result; the semantic failure
mode; expected bloomery behaviour — refuse, or prove and plan; and **which proof rule or
guardrail owns the case**.

### Minimal reproducibility

Fixtures must be tiny enough that a reviewer can calculate the correct result by hand.
Prefer 3–20 rows; scale benchmarks are separate. The failure must be deterministic and
independent of database query ordering.

### Canonical example

```text
orders:       order 1 shipping=10
order_items:  order 1 item A / item B / item C
```

Naive joined sum: `30`. Correct shipping: `10`.

Expected bloomery behaviour is pinned separately for the unsafe wide-mart representation
(refuse), the safe order-level rollup query (prove), and the item-level shipping request
(refuse). **This case therefore survives the evolution from validator to planner**, which
is the property that makes it worth building before the planner exists.

## 5. Expected artifacts

```text
expected/
  result.json
  semantic_outcome.json
  proof.json            # when accepted
  refusal.json          # when refused
```

Only the relevant proof or refusal file is required. Stable semantic rule IDs are asserted;
unstable prose is golden-tested only where diagnostics are part of the public contract.

## 6. Engine execution

Where practical, execute both `naive.sql` and `correct.sql` against the project's existing
execution-tier fixture, demonstrating that the naive query is executable, that it returns a
plausible but wrong answer, and that the corrected semantic plan returns the expected one.
A case depending on a target-specific feature says so explicitly.

## 7. Sourcing and regression policy

Real incidents may be translated into synthetic fixtures, but the corpus must not contain
customer data or proprietary schemas. Each case may record an `origin` of `synthetic`,
`industry-pattern`, or `production-derived-anonymized`. No unverifiable marketing claim is
inferred from that label.

Every semantic correctness bug found after release should add a minimal corpus case before
or with the fix. A fix is incomplete if it only adds a unit test at the implementation
layer when the bug can be expressed end to end.

## 8. Corpus as design gate

A new proof rule identifies which corpus cases it converts from refusal to acceptance. A
rule that causes a previously refused unsafe case to become accepted must supply a new
correct result and proof, or the change fails review.

## 9. Unresolved questions

- **Which test tier runs it.** Execution (DuckDB) covers most; cases 003 and 010 may need
  the engine tier, which is Docker-gated and excluded from the default suite.
- **Whether `bloomery/` holds specs or a recorded outcome**, which decides whether a case
  breaks when unrelated spec syntax changes.

## 10. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The inclusion rule is "valid SQL, wrong answer" — not "bad data".** It is what separates this corpus from `tests/fixtures/dirty/`, and the separation is the point of both: one holds values bloomery can see are wrong, the other holds values that are all fine while the number is not. A case admitted for the wrong reason dilutes the only thing this corpus proves. |
| 2 | `LOCKED` | **Every case is hand-checkable — 3–20 rows, deterministic, order-independent.** A corpus case a reviewer cannot verify by eye is a test asserting whatever the implementation did on the day it was written, which is the failure mode this corpus is meant to catch in *other* people's pipelines. |
| 3 | `LOCKED` | **Each case pins a machine-readable outcome against a stable rule ID, not prose.** Prose is golden-tested only where diagnostics are already a public contract. This is what lets RFC 0039's rules cite cases and RFC 0043's matrix cite both without either restating the other. |
| 4 | `ASSUMED` | **A case pins behaviour for *each* of representation, safe rollup and unsafe refinement where all three apply.** Case 001 is refused as a mart, proven as an order-level rollup, and refused at item level — one fixture, three expectations, which is what carries it across the validator-to-planner evolution instead of being rewritten at each step. |
| 5 | `ASSUMED` | **A new proof rule names the cases it converts from refusal to acceptance.** The corpus is the design gate: a rule that converts nothing has no demonstrated purpose, and a rule that converts a case without supplying a correct result and proof fails review. Not `LOCKED` because a soundness fix may legitimately convert *nothing* while still being necessary. |
| 6 | `ASSUMED` | **The corpus is a sibling directory to the dirty corpus, not an extension of it.** Sharing a home blurs D1's distinction at exactly the moment a reader is trying to use it. Departing means finding a shared harness worth more than the separation, and logging why. |
| 7 | `OPEN` | *Superseded by D10.* **Which tier runs the corpus.** Execution (DuckDB) covers most cases; the SCD2 and timezone cases may need the Docker-gated engine tier, which is excluded from the default suite — and a corpus that does not run by default is a corpus that rots. Decide per case, and if any case cannot run in the default suite, say so where the case lives. |

| 8 | `LOCKED` | **A third outcome, `unguarded` — it compiles, and the planner returns the naive number — and §8's gate read in both directions.** Two of the phase-one cases were neither refused nor correct: an average and a snapshot balance both declared `additivity: additive` compile clean, because nothing verifies that an `additive` claim is true. With only "refuse" and "prove" available such a case can be written as a fiction or left out, and leaving it out drops exactly the cases RFC 0038 exists to convert. So a new rule names the cases it converts from refusal to acceptance *and* the ones it converts from unguarded to refused. Locked because the word is the corpus's whole claim to being a design gate rather than a transcript, and every case's vocabulary rests on it — see `logs/T-0018.md` (D-096). |
| 9 | `ASSUMED` | **`bloomery/` holds specs, one subdirectory per expectation.** §9's second question closes. A recorded outcome there would be the fact `expected/` already carries, stated twice and testing nothing; D4's three-expectations-one-fixture needs three specs, because one spec cannot be refused and accepted at once. The cost §9 named — a case breaking when unrelated spec syntax changes — is the exposure every fixture in the tree already carries, and it is the exposure that makes them tests — see `logs/T-0018.md` (D-097). |
| 10 | `ASSUMED` | **The whole corpus runs in the default suite, on the execution tier, and each case records its tier where it lives.** Answers D7 and supersedes it. §9 guessed that the SCD2 and timezone cases would need the Docker-gated engine tier; an as-of join over a validity interval is ordinary SQL, and DuckDB has both a named-zone conversion and a truncation, so neither case sits outside `just test`. D7's own reasoning decided it — a corpus that does not run by default is a corpus that rots — and what the engine tier is still owed is the *dialect* question, which is RFC 0043's matrix rather than this corpus's job — see `logs/T-0018.md` (D-098) and `logs/T-0029.md` (D7, 21:08Z). |
| 11 | `ASSUMED` | **`expected/` holds `result.json` and `semantic_outcome.json`, and nothing else.** §5's four files assume one outcome per case where D4 requires several: one `refusal.json` cannot hold three outcomes, and splitting it per expectation duplicates what the outcome map already keys by the same names, so that map carries the error class and the rule id. `proof.json` arrives when there is a proof value worth serializing. What §5 asked for and is kept is D3's requirement — a machine-readable outcome against a stable rule ID, never prose — see `logs/T-0018.md` (D-099). |
| 12 | `LOCKED` | **An expectation's outcome is defined by the number the planner returns, asserted by running the SQL bloomery rendered.** The first execution ran the two hand-written queries as standalone SQL and planned nothing, so `accepted` and `unguarded` asserted identically and the difference rested on whether the cited RFC was still in `rfcs/` — a fact about the repository, not about the case. That proxy would have passed a mis-modelled case, and did: case 002's naive metric over line-grain rows returns the *right* answer, because an average over lines is right, and the average-of-averages bug needs an average already taken. Locked because it is the difference between the corpus asserting behaviour and asserting its own bookkeeping — see `logs/T-0018.md` (D-101), where it is logged as this task's one `drift`. |
| 13 | `ASSUMED` | **A case is identified by its name; its number is whatever was free when it landed.** §3 pairs each name with a number and the tree drifted from it twice — RFC 0041 P1 took 006 for a case §3 never names, so `distinct-users-fanout` landed as 007 and §3's last four as 008–011. Reading the roadmap's numbers rather than its names would have silently dropped `ratio-rollup`, which is the case the derived-ratio rule exists to convert. The rule is stated here instead of the numbers being corrected, because §3's list is a record of what was planned — see `logs/T-0028.md` (unlisted, 19:02Z) and `logs/T-0029.md` (unlisted, 21:05Z). |

## 11. Phasing

Cases 001–005 first: they are the ones RFCs 0037–0040 will be measured against, and 001
alone exercises all three of D4's expectations. The remaining five follow as the proof rules
that own them are designed.
