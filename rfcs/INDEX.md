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

The next free number is **0023**. Before creating an RFC, read the number above — do not
compute it from `ls`, which no longer sees retired documents. **Numbers are never reused**:
0001–0019 are retired and permanently spent. Update this section in the same change that
mints a number.

Filename: `NNNN-kebab-title.md`. Keep the `# RFC NNNN — Title` H1 and the number in the
filename in sync.

## Index

| # | Title | Status | One-line routing description |
|---|---|---|---|
| [0020](0020-authoring-ergonomics.md) | Authoring ergonomics: schema export, CLI, fix suggestions | 📝 Draft | Making a spec writable outside an editor's guesswork: exported JSON Schema, a thin CLI over the public functions, and refusals that carry the fix they already computed. |
| [0021](0021-capability-boundaries.md) | Capability boundaries: identity resolution, dialects, closed questions | 📝 Draft | Where bloomery stops: identity resolution as a step rather than a spec kind, dialects gated on named demand, and the reusable test for whether anything deserves a spec kind. |
| [0022](0022-spec-evidence.md) | `SpecEvidence`: spec analysis as a first-class output | 📝 Draft | Everything knowable about a spec without touching data, returned as one value — including the partial result when the pipeline refuses partway through. |

## Status legend

- 📝 **Draft** — proposed, not started
- 🚧 **In progress** — partially shipped
- ✅ **Complete** — fully shipped
- ❌ **Rejected / withdrawn**

✅ and ❌ are transient: a row reaching either status is retired in the same change, so a
steady-state table holds only 📝 and 🚧 rows.
