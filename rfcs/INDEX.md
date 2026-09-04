# RFCs

Design proposals for **bloomery**, the entity-first spec compiler. This directory is
committed — the RFC corpus is a project deliverable.

## Retiring a landed RFC

**An RFC is retired — deleted from this directory — once it lands or is rejected.** A
✅ Complete RFC has finished its job: the design it argued for is now the code, the tests
and the user-facing docs, and those are the authority for what bloomery does. Keeping the
document alongside them creates a second, drifting account of the same behaviour, which is
worse than none, because a reader cannot tell which one is current. A ❌ Rejected RFC goes
the same way; what stops the design being re-proposed is the rejection recorded wherever
the alternative was chosen, not an unread file sitting in this directory.

Retire in the same change that flips the status. `git rm` the file, drop its row from the
table below, and add one to [`RETIRED.md`](RETIRED.md) — number, title, **a commit the
document is readable at**, and nothing else. In practice that is the branch point: whatever
`main` was when you started. It is deliberately *not* the commit that deletes the document,
which does not exist until after the change lands and whose branch SHA the squash-merge
discards — the rule used to ask for that one, and the single row ever written to it in
flight named a commit no clone of `main` can resolve. That table is how a citation stays
followable once the document is gone; `just quality` refuses a number that is neither live
nor retired, a commit that does not hold the document, and one the mainline cannot reach.
`git show <commit>:rfcs/<file>` prints a retired document back in full.

Two consequences worth knowing:

- **Prose citations outlive the file.** Source, tests and docs cite decisions as
  `RFC 0016 D84` rather than as links, so a retired RFC's number keeps naming where a
  decision came from. Read those as historical: the code is the authority now. The five
  input documents the corpus grew from — `_original-smelter-spec.md` and the
  `_bloomery-*.md` set — were removed on the same reasoning, once every RFC deriving from
  them had shipped.
- **Retire whole, never in part.** A 🚧 In progress RFC stays, however much of it has
  shipped. Deleting the shipped half would leave the remainder arguing from a premise no
  longer in the tree.

## Allocating a number

The next free number is **0053**. Before creating an RFC, read the number above — do not
compute it from `ls`, which no longer sees retired documents. **Numbers are never reused**:
0001–0022 are retired and permanently spent. Update this section in the same change that
mints a number.

Filename: `NNNN-kebab-title.md`. Keep the `# RFC NNNN — Title` H1 and the number in the
filename in sync.

## Index

Every RFC 0001–0022 landed or was rejected and was retired in the change that finished it,
as did 0025 and 0027. A live row is usually a design argued and not yet settled — not work
in flight.

One other row can be live: a document whose decisions are all settled and implemented,
but which **cannot yet be retired** because a retirement row must name a commit the
mainline can reach ([`RETIRED.md`](RETIRED.md) argues why). An RFC born and finished on one
branch has no such commit until that branch lands, so it stays live for exactly one more
change. Such a row says so in its description. 0028 was the first, and retired one change
later exactly as this says; 0029 needed no such wait, because it reached `main` before the
branch that executed it.

Departures taken while executing these documents are recorded in
[`logs/`](../logs/) — one file per task, outside this directory. They are not RFCs: no
number, no status, no row in the table below. A reader deciding which RFC to trust should
know it has a companion recording where it turned out to be wrong.

| # | Title | Status | One-line routing description |
|---|---|---|---|
| [0024](0024-deterministic-union-merge.md) | Deterministic union merge | 🚧 In progress | Letting several mappings build one entity when they share a key space but no overlapping keys, so the entity model integrates sources instead of renaming one. Overlap stays a step. |
| [0033](0033-observability-logging-and-a-warnings-channel.md) | Observability: logging and a warnings channel | 📝 Draft | Stage-level stdlib logging that stays silent by default and cannot touch artifact bytes, a typed compile-time advisory channel riding `SpecEvidence`, and `warnings` reserved for deprecation alone. |
| [0037](0037-semantic-grain-model.md) | Semantic grain model and functional dependencies | 📝 Draft | Grain as structural identity rather than a name, with functional dependencies carrying their basis, so rollup safety is proven instead of inferred from string equality. Root of the semantic sequence. |
| [0038](0038-measure-semantic-types-and-additivity.md) | Measure semantic types and additivity algebra | 📝 Draft | A measure typed over value, origin grain, aggregation class, and unit — consolidating additivity, units and currency, which today live on three different nodes. |
| [0039](0039-semantic-proof-ir.md) | Semantic proof IR and closed-world checking | 📝 Draft | Acceptance as a positive derivation rather than the absence of a violation, with provenance on every leaf: unknown is not safe, and capability grows by adding proof rules. |
| [0040](0040-safe-rollup-planner.md) | Safe rollup planner and SemanticPlan IR | 📝 Draft | A proof-producing planner for single-measure requests, separating what a mart may represent from what a query may answer. The mart's grain rule does not move. |
| [0041](0041-multi-grain-query-planning.md) | Multi-grain aggregate-then-join planning | 📝 Draft | Measures from different origin grains answered by aggregating each branch to the common grain first and joining only after — never join-then-hope. Not scheduled. |
| [0042](0042-semantic-bug-corpus.md) | Production-style semantic bug corpus | 📝 Draft | Cases where the SQL is valid, every cast succeeds and the number is wrong anyway — the opposite question to the dirty corpus. Startable immediately; the acceptance evidence for the rest. |
| [0043](0043-semantic-capability-matrix.md) | Evidence-based semantic capability matrix | 📝 Draft | Comparing represented semantic properties across engines, one tested configuration at a time, with bloomery scored by the same standard including where it loses. |
| [0044](0044-check-command-and-imported-provenance.md) | `bloomery check` and imported semantic provenance | 📝 Draft | A CI command that resolves, type-checks and proves without emitting or executing, and the provenance rules deciding which imported facts may close a proof obligation. |
| [0045](0045-soundness-positioning.md) | Soundness positioning and the claims the docs may make | 📝 Draft | What bloomery may claim to prove — preservation of declared semantics, never truth — and the rule that the planner claim is not published before the capability exists. |
| [0046](0046-validating-a-dialect-port.md) | Validating a dialect port against an engine we cannot run | 📝 Draft | The tier ladder for a hosted engine with no container: what an emulator proves, why the engine's own compile-only check is the oracle, and the naming and credential rules that keep the two apart. |
| [0047](0047-snowflake-dialect.md) | Snowflake dialect port | 📝 Draft | Two credible local emulators and `EXPLAIN USING JSON` for authority; the risk is semantic, chiefly three timestamp types where bloomery has one zoneless UTC. |
| [0048](0048-bigquery-dialect.md) | BigQuery dialect port | 📝 Draft | A dry run is a full parse, bind and type check that scans nothing — the cheapest authoritative layer of the four. `DATETIME` versus `TIMESTAMP` carries most of the risk. |
| [0049](0049-redshift-dialect.md) | Redshift dialect port | 📝 Draft | The port whose local options are all PostgreSQL underneath, which bloomery already ships. It shares helpers with that port and inherits nothing; fixtures split by what a surrogate can speak to. |
| [0050](0050-databricks-dialect.md) | Databricks SQL dialect port | 📝 Draft | No local Databricks exists, so Spark is a labelled surrogate and `DESCRIBE QUERY` checks result types against the real analyzer. PySpark stays test-only; bloomery never executes Spark. |
| [0051](0051-loose-ends-inside-shipped-subsystems.md) | Loose ends inside shipped subsystems | 🚧 In progress | MetricFlow becomes a compile target, a lineage node-id collision becomes a refusal, and `on_fail: flag` lowers on a Tier 2 step output. |
| [0052](0052-dbt-as-a-complete-quality-target.md) | dbt as a complete quality target | 📝 Draft | The reject table, its replay and the reconcile model are the three artifacts dbt refuses instead of emitting; building them leaves the quality mart nothing to refuse. |

## Status legend

- 📝 **Draft** — proposed, not started
- 🚧 **In progress** — the document is not finished *here* yet: either partially shipped,
  or fully shipped and waiting on a retirement commit the mainline can reach (above). The
  status tracks the document's life in this directory, and that ends at retirement rather
  than at the last decision implemented; the row says which case it is
- ✅ **Complete** — fully shipped
- ❌ **Rejected / withdrawn**

✅ and ❌ are transient: a row reaching either status is retired in the same change, so a
steady-state table holds only 📝 and 🚧 rows.
