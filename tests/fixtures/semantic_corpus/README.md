# The semantic bug corpus

Cases where **ordinary SQL, schema and type validation all pass while the answer is still
wrong**. Every value here is valid, every cast succeeds, every join is the one the ERD
draws, and the number is not what anyone asked for.

That inclusion rule is the whole point, and it is what separates this directory from
[`../dirty/`](../dirty/). The dirty corpus holds values bloomery can *see* are wrong —
`01/02/2025`, `0000-00-00`, a leap second — and each is quarantined or passes. Here nothing
is wrong with any value. A case admitted for the wrong reason dilutes the only thing this
corpus proves, so a new one carries a short justification against the rule above.

## A case

```text
NNN-short-name/
  problem.md      the business question, the naive query, why it is valid, both results,
                  the failure mode, and which guardrail or rule owns the case
  schema/         CREATE TABLE — the bronze relations bloomery reads, so the queries
                  below run against the same rows it does. A table created in `silver`
                  is one the operator supplies (type-2 versions, a rate relation) and
                  bloomery's model for it is not run
  data/           INSERT — 3 to 20 rows, hand-checkable by design
  naive.sql       the tempting query. It runs, and it is wrong
  correct.sql     the same question, answered
  expected/
    result.json           both numbers, as strings — never floats
    semantic_outcome.json one entry per expectation
  bloomery/
    <expectation>/        one spec directory per entry above
```

**Three to twenty rows, deterministic, order-independent.** A case a reviewer cannot check
by eye is a test asserting whatever the implementation did on the day it was written.

## Outcomes

An expectation is one of three, keyed by name in `semantic_outcome.json`:

| Outcome | Means | Pins |
| --- | --- | --- |
| `refused` | bloomery refuses the spec | the error class, and the rule that owns it |
| `accepted` | it compiles, and **the planner returns the `correct` number** | the rule that permits it |
| `unguarded` | it compiles, and **the planner returns the `naive` number** | the rule that **will** convert it |

Every outcome that is not `refused` is asserted by compiling the spec, materializing it
against the case's own warehouse, planning the case's metric, and running the SQL bloomery
rendered. So `accepted` and `unguarded` differ by which of the two hand-checked numbers
comes back — not by a label, and not by anything about the state of the repository.

The metric asked for is the single column both results name. A case whose expected numbers
are keyed by anything else would be asserting a number against a name nothing connects to
it, so the loader refuses that too.

There is a second, weaker check beside it: every cited RFC must be either live in `rfcs/`
or listed in `RETIRED.md` — so a mistyped number is caught rather than read as retired —
and an `unguarded` expectation must cite a **live** one while every other outcome cites a
**retired** one, which here means shipped.

That is kept because it can disagree with the number. When the owning RFC lands and is
retired, a case it did not actually fix still plans to the naive number, so the primary
assertion stays green and says nothing — while this one goes red and reports that the rule
you named shipped without converting this case. That is the corpus working as a design gate
rather than as a transcript, and it is not something the number can tell you.

## Several expectations, one fixture

A case pins behaviour for each of representation, safe rollup and unsafe refinement where
all three apply. Case 001 is refused as a wide mart, accepted as an order-level rollup, and
refused at line level — one warehouse, three specs, three outcomes. That is what carries a
case across the evolution from validator to planner instead of it being rewritten at each
step.

## Adding one

Add a directory. `tests/support/semantic_corpus.py` discovers it, and refuses it if any
part above is missing or if `bloomery/` and `semantic_outcome.json` disagree about which
expectations exist. Nothing needs editing to register a case, and a half-written one fails
at collection rather than quietly contributing a shorter test run.

Every semantic-correctness bug found after release should add a case here before or with
its fix. A fix is incomplete if it only adds a unit test at the implementation layer when
the bug can be shown end to end.
