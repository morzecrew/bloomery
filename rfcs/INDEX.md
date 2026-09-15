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

**A retiring RFC takes no new rows.** Where the change that completes a document is also the
change that retires it, its execution's decisions go in the task log and nowhere else. The
retirement row names the branch point, so a row appended on the branch exists at no commit
the mainline can reach: not at the commit `RETIRED.md` names, which predates it, and not in
the tree, which no longer holds the file. This is the one place the usual habit — a phase's
decisions land in the change that executes it — does not apply, and it is not a licence to
skip recording them: the log is a committed file that survives the deletion, so an entry
there states its rationale in full rather than deferring to a row that will not exist.

Four consequences worth knowing:

- **Prose citations outlive the file.** Source, tests and docs cite decisions as
  `RFC 0016 D84` rather than as links, so a retired RFC's number keeps naming where a
  decision came from. Read those as historical: the code is the authority now. The five
  input documents the corpus grew from — `_original-smelter-spec.md` and the
  `_bloomery-*.md` set — were removed on the same reasoning, once every RFC deriving from
  them had shipped.
- **A log citation to a retired document still resolves, and a bare path check will say
  otherwise.** Task logs cite evidence as `rfcs/0064-….md:209-220`, and the file is gone.
  The line is not lost: the number is in [`RETIRED.md`](RETIRED.md), the commit there holds
  the document, and `git show <commit>:<path> | sed -n '209,220p'` prints it. Every such
  citation in `logs/` resolves this way today, measured. `log_check.py` reports them as
  missing because it tests the working tree and knows nothing of this table — a limitation
  of a vendored checker that gates neither CI nor `just quality`, not a decay in the record.
  Do not migrate the citations to work around it.
- **Retire whole, never in part.** A 🚧 In progress RFC stays, however much of it has
  shipped. Deleting the shipped half would leave the remainder arguing from a premise no
  longer in the tree.
- **A ✅ root of a live sequence stays too, for the same reason across documents rather
  than within one.** Where several unstarted RFCs are written *in* a landed document's
  vocabulary — not merely citing a decision it made, but arguing from terms it defines —
  retiring it leaves them unreadable in exactly the way the point above refuses. Its
  **status line** says so — the index one-liner records what an RFC *is*, never what has
  happened to it — and it is retired with the last of its dependants. 0037 is the first:
  0039, 0042 and 0053 still reason in its grain vocabulary. 0038 and 0040 were the other two
  and are gone, retired with 0058 — the last dependant of each, which is the rule working
  rather than an exception to it. 0062 and 0069 were held the same way and are gone too,
  retired together with 0064 once its last phase landed: nothing outside the three argued in
  their vocabulary, so all three left the directory in one change rather than one at a time.
  0044, 0065 and 0070 left in one change for the same reason, and that change is worth
  reading as the rule rather than as three retirements: 0070 was the import half taken out of
  0044 and the other half of 0065's consumer story, arguing from the first's D1–D4 and the
  second's `requires_evidence` — so it was the last dependant of both, and the three could
  only ever go together. 0037 is the one ✅ root left. A root is held by the dependants that
  exist, never by ones a reader expects: measured at that retirement, no live RFC argued in
  0065's vocabulary, and the one that still named it at all did so in a prose citation in its
  own decision table — which is the thing the sentence below says is not a reason to keep a
  document. This paragraph names it too, and that is the same kind of mention: a record of
  what happened, not a document arguing from it.
  This is not a licence to keep a document because something cites it — prose citations are
  precisely what `RETIRED.md` exists to keep followable.

## Allocating a number

The next free number is **0077**. Before creating an RFC, read the number above — do not
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
| [0033](0033-observability-logging-and-a-warnings-channel.md) | Observability: logging and a warnings channel | 🚧 In progress | Stage-level stdlib logging that stays silent by default and cannot touch artifact bytes, a typed compile-time advisory channel riding `SpecEvidence`, and `warnings` reserved for deprecation alone. |
| [0037](0037-semantic-grain-model.md) | Semantic grain model and functional dependencies | ✅ Complete | Grain as structural identity rather than a name, with functional dependencies carrying their basis, so rollup safety is proven instead of inferred from string equality. Root of the semantic sequence. |
| [0039](0039-semantic-proof-ir.md) | Semantic proof IR and closed-world checking | 🚧 In progress | Acceptance as a positive derivation rather than the absence of a violation, with provenance on every leaf: unknown is not safe, and capability grows by adding proof rules. |
| [0042](0042-semantic-bug-corpus.md) | Production-style semantic bug corpus | 🚧 In progress | Cases where the SQL is valid, every cast succeeds and the number is wrong anyway — the opposite question to the dirty corpus. Startable immediately; the acceptance evidence for the rest. |
| [0043](0043-semantic-capability-matrix.md) | Evidence-based semantic capability matrix | 🚧 In progress | Comparing represented semantic properties across engines, one tested configuration at a time, with bloomery scored by the same standard including where it loses. |
| [0046](0046-validating-a-dialect-port.md) | Validating a dialect port against an engine we cannot run | 📝 Draft | The tier ladder for a hosted engine with no container: what an emulator proves, why the engine's own compile-only check is the oracle, and the naming and credential rules that keep the two apart. |
| [0047](0047-snowflake-dialect.md) | Snowflake dialect port | 📝 Draft | Two credible local emulators and `EXPLAIN USING JSON` for authority; the risk is semantic, chiefly three timestamp types where bloomery has one zoneless UTC. |
| [0048](0048-bigquery-dialect.md) | BigQuery dialect port | 📝 Draft | A dry run is a full parse, bind and type check that scans nothing — the cheapest authoritative layer of the four. `DATETIME` versus `TIMESTAMP` carries most of the risk. |
| [0049](0049-redshift-dialect.md) | Redshift dialect port | 📝 Draft | The port whose local options are all PostgreSQL underneath, which bloomery already ships. It shares helpers with that port and inherits nothing; fixtures split by what a surrogate can speak to. |
| [0050](0050-databricks-dialect.md) | Databricks SQL dialect port | 📝 Draft | No local Databricks exists, so Spark is a labelled surrogate and `DESCRIBE QUERY` checks result types against the real analyzer. PySpark stays test-only; bloomery never executes Spark. |
| [0053](0053-retrieval-semantics.md) | Retrieval semantics | 📝 Draft | Semantic spaces, vector-field annotations and retrieval profiles as their own spec kind, so an embedding corpus is refused when its dimensions, space or grain disagree. |
| [0059](0059-multi-project-composition.md) | Multi-project composition | 🚧 In progress | One project reading another's published surface: what may cross the boundary, and what a fingerprint means once something does. |
| [0060](0060-replay-on-a-historical-entity.md) | Replay on a historical entity | 📝 Draft | Replay writes past the framework that owns a type 2 relation's versions, so a recovered row lands invisible; the pair is refused until a route through the framework exists. |
| [0071](0071-fuzzing-the-compile-boundary.md) | Fuzzing the compile boundary | 📝 Draft | Only `BloomeryError` may cross the compile boundary and exit 3 must never happen; mutated-byte targets that try to falsify both, with the seeds and triage policy that make them worth running. |
| [0072](0072-continuous-fuzzing-in-ci.md) | Continuous fuzzing in CI | 📝 Draft | Where the fuzz corpus lives between runs and on what schedule, plus the replay job checking byte-identical output across processes — the determinism claim no in-process assertion reaches. |
| [0073](0073-generating-from-the-spec-schema.md) | Generating from the spec schema | 📝 Draft | Mutated bytes rarely survive to the guardrails; documents generated from the exported JSON Schema always do. Why that generator belongs in the property tier, not the fuzz lane. |
| [0074](0074-declared-source-timezone.md) | Declared source timezone | 📝 Draft | `parse_ts` mints a UTC instant from a wall clock nobody named a zone for, so the assertion is made by an absence; where the zone is declared and what refuses its absence. |
| [0075](0075-a-ratio-over-one-row-set.md) | A ratio over one row set | 📝 Draft | A row with a zero denominator puts cost in the numerator and no units in the denominator; which rows a ratio is about, and why bloomery refuses rather than choosing between two honest readings. |
| [0076](0076-dimension-algebra.md) | Dimension algebra | 📝 Draft | Measures have an additivity algebra and dimensions have none; declaring that one dimension determines another, plays a role of another, or is another, and what each fact makes provable. |

## Status legend

- 📝 **Draft** — proposed, not started
- 🚧 **In progress** — the document is not finished *here* yet: either partially shipped,
  or fully shipped and waiting on a retirement commit the mainline can reach (above). The
  status tracks the document's life in this directory, and that ends at retirement rather
  than at the last decision implemented; the row says which case it is
- ✅ **Complete** — fully shipped
- ❌ **Rejected / withdrawn**

✅ and ❌ are transient: a row reaching either status is retired in the same change, so a
steady-state table holds only 📝 and 🚧 rows — **except a ✅ root of a live sequence**, which
stays until its last dependant is retired, for the reason the retirement section above
gives. Such a row says so in its own status line. 0037 is the only one today.
Do not relabel either 🚧: nothing about it is in progress, and the exception is about what
other documents still need, not about what it has left to do.
