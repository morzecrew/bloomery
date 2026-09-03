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

The next free number is **0037**. Before creating an RFC, read the number above — do not
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
| [0036](0036-the-offset-bearing-timestamp.md) | The offset-bearing timestamp | 🚧 In progress | An ISO 8601 timestamp carrying a UTC offset is out of `parse_ts`'s local-clock contract and every engine truncates it silently, so one shared guard makes it NULL instead. Shipped; live until a mainline commit exists to retire it at. |

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
