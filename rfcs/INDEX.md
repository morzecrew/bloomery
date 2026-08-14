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
table below, and note nothing else here — the deletion commit is the record.
`git log --diff-filter=D -- rfcs/` lists the commits that retired documents, and
`git show <commit>^:rfcs/<file>` prints one back in full.

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

The next free number is **0026**. Before creating an RFC, read the number above — do not
compute it from `ls`, which no longer sees retired documents. **Numbers are never reused**:
0001–0022 are retired and permanently spent. Update this section in the same change that
mints a number.

Filename: `NNNN-kebab-title.md`. Keep the `# RFC NNNN — Title` H1 and the number in the
filename in sync.

## Index

Every RFC 0001–0022 landed or was rejected and was retired in the change that finished it;
the three below are the first live rows since. A live row means a design argued and not yet
settled — not work in flight.

| # | Title | Status | One-line routing description |
|---|---|---|---|
| [0023](0023-temporal-joins-scd2-flattening-and-currency-conversion.md) | Temporal joins: SCD2 flattening and currency conversion | 📝 Draft | Two constructs that compile clean and cannot be correct — flattening a historical dimension, and `convert` — both needing a join against a validity interval. Refuse now, design the as-of join later. |
| [0024](0024-deterministic-union-merge.md) | Deterministic union merge | 📝 Draft | Letting several mappings build one entity when they share a key space but no overlapping keys, so the entity model integrates sources instead of renaming one. Overlap stays a step. |
| [0025](0025-v0-1-0-release-readiness.md) | v0.1.0 release readiness | 📝 Draft | What must hold before the stability promises stop describing an intention and start binding: the ratchets RFC 0001 deferred to this moment, a navigable retired corpus, and the release act. |

## Status legend

- 📝 **Draft** — proposed, not started
- 🚧 **In progress** — partially shipped
- ✅ **Complete** — fully shipped
- ❌ **Rejected / withdrawn**

✅ and ❌ are transient: a row reaching either status is retired in the same change, so a
steady-state table holds only 📝 and 🚧 rows.
