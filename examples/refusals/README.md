# refusals/

Five specs that look right and cannot be right, and what bloomery says about
each. No containers, no warehouse, no setup — every case here is decided at
compile time, which is the whole point.

```bash
cd examples/refusals
just show
```

`just spec <case>` prints one case's YAML; `just list` names them all.

## Why this example exists

Every other example shows bloomery building something. This one shows it
*refusing* to, which is the claim the project is actually built on: a spec that
would produce a plausible wrong number is a compile error, not a query someone
discovers is wrong three months later.

Four of these five would run fine in a hand-written dbt or SQL project. They
would return rows. The rows would be wrong, and nothing would say so.

| Case | Refusal | What it would have done |
|---|---|---|
| `scd2-flatten/` | `HistoricalFanout` | Joined every order to every *version* of its customer, multiplying revenue by each customer's revision count |
| `wrong-grain/` | `GrainViolation` | Duplicated an order-level shipping cost once per line, so `SUM` overstates by the line count |
| `fanout/` | `FanoutRisk` | Multiplied the mart's rows once per match across a `one_to_many` relationship |
| `mixed-currency/` | `CurrencyMismatch` | Added EUR to USD and returned a number that is the sum of two different things |
| `unimplemented-convert/` | `UnsupportedByTarget` | Asked to convert a currency with no `fx_rates:` declared to convert against |

The last one is a different kind of refusal and the distinction is worth
keeping: that spec is not *wrong*, it is *incomplete*. `convert` typechecks and
passes every guardrail, and is refused only because the catalog declares no
`fx_rates:` relation to read a rate from — add one and the same spec compiles to
an as-of rate lookup. A gap that names what would close it is not a defect.

## What to read

Each case is a complete project of two to five YAML files. They are small
enough to read top to bottom, and the line that makes each one wrong is
commented in place — `scd: type2` on an entity that gets flattened,
`cardinality: one_to_many` on a relationship that gets walked, a `currency:`
code that differs from its neighbour's.

Delete that line and the project compiles. That is the test the cases are built
around: the refusal must be about the construct, not about the fixture.

## Reading the messages

Every message names three things: what is wrong, why it cannot be right, and
what to do instead. That is a deliberate contract rather than a courtesy — a
compiler that refuses without routing is one people learn to work around.

```
measure 'shipping' has grain 'order' (one row per order), not the mart's grain
'order_item' (one row per line on an order) — measure grain must strictly equal
mart grain (RFC 0010 D2). Flattened into the mart it is duplicated once per
'order_item' row and any SUM over it overstates. Fix: remove it from this mart's
measures, or serve it from a mart at grain 'order'
```

The `RFC NNNN Dn` citations point at the design decision behind the rule. Those
documents are retired once shipped — `rfcs/RETIRED.md` says where to read each
one — because the code, the tests and these messages are the account of what
bloomery does.

## The full catalogue

These five are a sample chosen to tell a story. The complete list of error
classes, what raises each and at which stage, is in the
[errors reference](https://morzecrew.github.io/bloomery/reference/errors/).
Every class documented there is produced by the test suite — a documented
refusal nothing raises fails the build.
