# The three-way equivalence tier

Three independent answers to the same request, compared over one Postgres:

| Leg | What it is | Maturity |
|---|---|---|
| **Planner** | The MetricFlow-backed `QueryPlan` | Mature — every planner test exercises it |
| **Cube** | SQL from the emitted Cube schema, loaded in a real container | **Thin** — the emitter is ~281 LOC against SQLMesh's ~798 |
| **Reference SQL** | Hand-written, per request, in `reference_sql/` | One-off per case |

When two legs disagree, all three are suspects and only one investigation order is
efficient:

> **Triage order: suspect the Cube emitter first, the reference SQL second, the planner
> third.**

This orders *investigation*, not conclusions. Every divergence still gets root-caused, and
the answer is sometimes the planner. But thirty seconds of stated prior beats thirty
minutes of symmetric searching, and the prior is honest: the thinnest leg with the least
independent coverage is the likeliest place for a gap.

The Cube emitter's size is proportionate rather than a deficiency. Cube is the escape
hatch and the equivalence oracle, not a deployment target — it emits one view per mart,
builds no relation, and is asked nothing about steps. It legitimately does less.

## `known_divergences.yaml`

It ships as `divergences: []` and should stay that way.

An entry is **a finding to fix, not a tolerance to accumulate**. Adding one is a design
change and gets argued as one; a file that grows entries quietly is a file that has stopped
being a gate. If a divergence is genuinely correct behaviour on both sides, that is a
statement about the semantics worth writing down where the semantics live, not a row here.
