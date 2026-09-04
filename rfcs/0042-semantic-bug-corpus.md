# RFC 0042 — Production-style semantic bug corpus

- **Status:** 📝 Draft — proposed, **can start immediately** and in parallel with
  [RFC 0037](0037-semantic-grain-model.md). It is the only document in this sequence with
  no upstream dependency, and the one that gives the others their acceptance evidence.
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
| 7 | `OPEN` | **Which tier runs the corpus.** Execution (DuckDB) covers most cases; the SCD2 and timezone cases may need the Docker-gated engine tier, which is excluded from the default suite — and a corpus that does not run by default is a corpus that rots. Decide per case, and if any case cannot run in the default suite, say so where the case lives. |

## 11. Phasing

Cases 001–005 first: they are the ones RFCs 0037–0040 will be measured against, and 001
alone exercises all three of D4's expectations. The remaining five follow as the proof rules
that own them are designed.
