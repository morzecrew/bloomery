# RFC 0062 — Stable node identity across renames

- **Status:** 🚧 In progress — §12's P1 has landed: the optional `id:` on every spec kind
  that mints a node, node-id construction reading it, the duplicate refusal, and the
  byte-exact opt-out ([`logs/T-0032.md`](../logs/T-0032.md)). D6 is settled there — a
  write-once `id:`, because RFC 0063 reads history backwards and an annotation only exists
  in the current spec — and D4 too: partial adoption is allowed and only a collision is
  refused. **P2 (`plan()`'s second `RENAME` producer) and P3 (`lineage` and `explain`
  carrying both id and name) are unscheduled** and are what hold this document open.
  Execution's findings and the rows it proposes are in the same log; nothing below has been
  amended to agree with what was built — §9's "until `check` lands" reads as written, and
  the log records that `check` turned out not to be a place checks live.
- **Scope:** A stable identifier on every node kind in `NODE_ID_PREFIXES`, minted once and
  never derived from the name, with the name demoted to a display label. One optional spec
  field, one change to node-id construction, one widened classification in `plan()`. No
  SELECT changes, no artifact-byte changes for a project that does not adopt it.
- **Related:** [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py)
  (`NODE_ID_PREFIXES`), [`src/bloomery/guardrails/lineage.py`](../src/bloomery/guardrails/lineage.py),
  [`src/bloomery/plan/model.py`](../src/bloomery/plan/model.py) (`ChangeClass`),
  [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) (`lineage`, `plan`,
  `fingerprint`), RFC 0056 (exposures — a consumer references a metric by node id),
  RFC 0044 (`check`), RFC 0007 D3 (`renamed_from` — the same problem solved one level down).
- **Origin:** A ceiling review of what `plan()` can and cannot classify. Every other
  classification it makes is about a thing changing; a rename of a *node* is the one case
  where it reports two things instead.

---

## 1. Summary

`NODE_ID_PREFIXES` is `("canonical", "metric", "source", "step")` and a node id is a prefix
joined to the spec's name with a dot — `metric.gross_revenue`, `canonical.unit_price`,
`step.resolve_customers`. The name is therefore the identity. (`source` is the exception
already: a bronze extraction is `source.<relation>.<path>`, three segments rather than two.)

Rename a metric and nothing in the compiler can tell that a rename happened. The old node
has no successor and the new node has no history: `plan()` reports a deletion and an
addition, `lineage` cannot trace across the boundary, and every downstream citation of
`metric.gross_revenue` — an exposure under RFC 0056, a decision row, a dashboard — points
at a node that no longer exists.

This RFC gives a node an identity that a rename does not touch. The name becomes what it
should have been all along: a label people read.

## 2. Motivation

**A rename is an ordinary edit and today it is a destructive one.** Renaming
`gross_revenue` to `revenue_gross` is a naming-convention change with no semantic content.
The compiler treats it as removing one metric and introducing another, which is the same
report it would give for a genuinely deleted metric — so the one classification that should
be free is indistinguishable from the one that should stop a merge.

**The blast radius is the wrong shape.** `plan()`'s breaking-change report exists so that a
reader knows what a change reaches. A rename reaches everything that names the metric and
nothing that uses it, and the current report says the opposite: maximal breakage, no
continuity.

**The problem is already solved one level down, and only there.** RFC 0007 D3 gives an
entity *field* a `renamed_from:` annotation, and `plan()` classifies the result `RENAME`
rather than as a drop plus an add. Nodes have no equivalent. So the compiler already agrees
that rename identity must be declared rather than guessed — the question this document
answers is which declaration shape to use at node level, and D6 records that it is not
settled.

**It silently caps the two documents that follow.** Definition history (RFC 0063) and
change attribution (RFC 0064) both need to say "this thing, over time". Neither can be built
on an identifier that a routine edit destroys, and building them first would mean writing
history keyed to a name and discovering the defect at the first rename.

**Citations already outlive files here.** `INDEX.md` argues that a retired RFC's number
keeps naming where a decision came from, precisely because a stable citation is worth more
than a live link. Node ids are cited the same way — in exposures, in logs, in prose — and
they do not have that property.

## 3. Current state

Verified against the tree.

| | How the id is formed | What a rename does |
|---|---|---|
| `canonical.` | prefix + spec name | old id vanishes, new id appears |
| `metric.` | prefix + spec name | same |
| `source.` | prefix + relation + path | same |
| `step.` | prefix + ref | same |

`ChangeClass` already carries `RENAME`, and `plan/diff.py` reads `column.renamed_from` to
mint it. That path is column-only: `renamed_from` is a field on the entity model's `Field`
and reaches nothing at node level.

`fingerprint` changes on a rename, which is correct — the artifacts do change, because names
reach the emitted text. What is not correct is that the *graph* changes shape rather than
relabelling a vertex.

There is no field on any spec kind that survives a node rename. A project's only record that
two names denote the same thing is its git history, which the compiler does not read.

## 4. Goals / Non-goals

**Goals**

- A node keeps its identity across a rename, and `plan()` classifies the change as a
  rename rather than as a delete plus an add.
- `lineage` traverses across a rename in both directions.
- Adoption is optional and incremental: a project with no stable ids compiles exactly as it
  does today, byte for byte.
- The identifier is stable across machines and processes, like everything else the compiler
  produces.

**Non-goals**

- **Renaming emitted relations.** What a target calls a table stays derived from the spec
  name; this is about the compiler's own graph, not about the warehouse.
- **Merging or splitting nodes.** Two metrics becoming one is a different change with a
  different report, and conflating it with a rename is how a real semantic change gets
  classified as cosmetic.
- **Inferring renames.** Similarity heuristics over names or SQL are exactly the guess this
  document exists to replace.
- **Re-spelling existing node ids.** `bloomery lineage --node metric.gross_revenue` is a
  documented invocation and the ecosystem stores those strings; the separator and the
  prefixes do not move.
- **A migration tool.** Adding an id to an existing spec is a one-line edit; a project that
  wants history from before that edit does not get it, and should not be told otherwise.

## 5. Design

### 5.1 The field

Every spec kind that produces a node gains an optional `id:`.

```yaml
metrics:
  - id: mtr_7f3a9c            # minted once, never edited
    name: gross_revenue       # a label
```

The value is opaque to the compiler: it is compared, never parsed. A generated form
(`bloomery mint`) is convenient and not required — a hand-written `id: revenue_v1` is
equally valid, because the only property that matters is that it does not change.

### 5.2 Node id construction

Wherever a node id is minted from a spec name today, the id substitutes for the name and
nothing else moves: `metric.<id or name>`, `canonical.<id or name>`, `step.<id or name>`,
and `source.<relation>.<path>` unchanged, since a bronze extraction is named by its
relation rather than by an authored spec name and has nothing to substitute.

A project with no `id:` anywhere gets today's ids and today's bytes. A project that adopts
`id:` gets ids that survive renames. There is no third state and no flag.

### 5.3 What `plan()` gains

`ChangeClass.RENAME` exists and is minted today only from a *field*'s `renamed_from`. It
gains a second producer: a node whose id is present on both sides with a differing name.
The class is not new; the subject is. A rename is not a breaking change to the graph; it
*is* a breaking change to any consumer that cites the old name, and the report says so with
the citation list rather than with a severity.

### 5.4 Display

`lineage` and `explain` print `name` and carry `id` in machine-readable output. A reader
sees `gross_revenue`; a script keys on `mtr_7f3a9c`. Printing the id in human output would
trade the readability the name exists for against a property only tooling needs.

## 6. Tests

- **A rename is a rename.** Two projects differing only in a metric's `name`, same `id`:
  `plan()` reports one `RENAME` and no deletions.
- **A delete is still a delete.** Remove the metric entirely: `plan()` reports a deletion,
  not a rename. The pair with the test above is the whole point.
- **Traversal crosses the rename.** `lineage --node metric.mtr_7f3a9c` returns the same
  edges before and after.
- **Opt-out is byte-exact.** A fixture project with no `id:` field emits artifacts
  identical to the pre-change tree. This is the test that makes adoption safe.
- **Ids are compared, not parsed.** A spec with `id: ../../etc/passwd` produces a node id
  and no filesystem access — the value reaches nothing that resolves paths.
- **A node id never collides with an entity field.** The lineage-namespace guard
  (RFC 0051 D6–D8) refuses an entity named after a prefix; an authored `id:` must not open
  a second route to the collision that guard closes.

## 7. Docs

`pages/docs/concepts/` gains a short section on identity versus naming, sited with the
lineage material rather than with the spec reference: the field is trivial and the reason
for it is not.

## 8. Out of scope

- RFC 0063's definition history and RFC 0064's change attribution, both of which consume
  this and neither of which this document assumes.
- Stable identity for anything not in `NODE_ID_PREFIXES`. Columns and dimensions are named
  within their owner, and RFC 0007 D3's `renamed_from` already answers rename there.
- Cross-project identity under RFC 0059. Two projects minting the same string is a
  collision that composition has to answer, and it answers it in its own vocabulary.

## 9. Risks

- **A copied id is worse than no id.** Duplicating a spec file to start a new metric and
  forgetting to change `id:` produces two nodes claiming one identity. The duplicate must be
  refused and the refusal must name both files. RFC 0044's `check` is the best home for it;
  until that lands the guardrail stage is where it goes, so this risk does not make the
  document wait.
- **An edited id is a silent delete-and-add.** Nothing can distinguish "renamed the id"
  from "removed one metric and added another", because that distinction is precisely what
  the id was carrying. The docs say the field is write-once; the compiler cannot enforce it.
  `renamed_from` does not have this weakness — it is one-shot and a stale annotation is
  refused — which is the strongest argument on that side of D6.
- **Optionality is a two-state world that has to stay two-state.** The moment a project can
  have some ids and some not, `plan()`'s report mixes classifications derived from different
  identity models. Refusing partial adoption at project level is the cheaper rule and this
  document does not choose it — see D4.

## 10. Unresolved questions

- Whether partial adoption is allowed within a project, or `check` refuses a project where
  some nodes of a kind carry `id:` and others do not.
- Whether `fingerprint` should have an id-only variant that a rename does not move, for the
  callers that want to know whether the *semantics* changed rather than the bytes.
- Whether a write-once `id:` or a one-shot `renamed_from:` is the right shape at node level
  (D6). The second is what this codebase already does for fields, and it is enforceable;
  the first is what RFC 0063 and RFC 0064 want, because an id is a key to hang history on
  and an annotation is not.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Identity is declared, never inferred. No similarity heuristic over names, SQL or column sets decides that two nodes are the same node; a wrong guess here rewrites history rather than raising an error. |
| 2 | `LOCKED` | The id is opaque. Compared for equality, never parsed, never used to derive a path, a relation name or an ordering. |
| 3 | `LOCKED` | Absence of `id:` reproduces today's behaviour byte for byte. A feature that changes artifacts for projects that did not ask for it is not optional. |
| 4 | `OPEN` | Whether partial adoption within a project is refused by `check` (§10). |
| 5 | `ASSUMED` | Emitted relation names stay derived from `name`. Decoupling them is a warehouse-migration feature wearing this document's clothes. |
| 6 | `OPEN` | Whether node identity is a write-once `id:` or a one-shot `renamed_from:` in RFC 0007 D3's shape (§10). Recorded rather than assumed: the codebase already chose the second answer for fields, and a document that does not say why nodes differ is one that looks like it did not know. |
| 7 | `ASSUMED` | Existing node-id spellings do not move — the dot separator, the four prefixes, and `source.<relation>.<path>`'s three segments. `lineage --node metric.gross_revenue` is documented surface and the ecosystem stores those strings. |

## 12. Phasing

**P1** — the field, node-id construction, the duplicate-id refusal, and the byte-exact
opt-out test. Nothing observable changes for an unadopted project.

**P2** — `ChangeClass.RENAME`'s second producer in `plan()` and its citation list.

**P3** — `lineage` and `explain` output carrying both id and name.

P1 alone is worth landing: it is what RFC 0063 needs, and it costs an unadopted project
nothing.
