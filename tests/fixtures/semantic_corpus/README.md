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
  schema/         CREATE TABLE — the warehouse as it really arrives
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
| `accepted` | bloomery compiles it and the answer is right | the rule that permits it |
| `unguarded` | nothing refuses it and the answer is wrong | the rule that **will** convert it |

`unguarded` is the state a corpus written before its guard needs, and it is not
documentation. Every cited RFC must be either live in `rfcs/` or listed in `RETIRED.md` —
so a mistyped number is caught rather than read as retired — and then: an `unguarded`
expectation must cite a **live** one, and every other outcome must cite a **retired** one,
which in this repository means shipped. So when the owning RFC lands, the suite goes red
until somebody revisits the case and records what the new rule converted it to. That is the
corpus working as a design gate rather than as a transcript.

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
