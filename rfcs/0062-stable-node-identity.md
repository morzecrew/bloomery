# RFC 0062 — Stable node identity across renames

- **Status:** ✅ Complete — all three phases have landed, and **retained rather than
  retired**: RFC 0064 and RFC 0069 argue from this document's vocabulary rather than merely
  citing a decision it made, and deleting it would leave both arguing from a premise no
  longer in the tree. This line names the live dependants, so it is what says when 0062 may
  go.

  P1 shipped the optional `id:`, node-id construction reading it, the duplicate refusal and
  the byte-exact opt-out ([`logs/T-0032.md`](../logs/T-0032.md)); D6 and D4 are settled
  there — a write-once `id:`, and partial adoption allowed with only a collision refused.
  P2 and P3 shipped `plan()`'s second `RENAME` producer with its citation list, and
  `lineage` printing the name while `--format json` carries both
  ([`logs/T-0044.md`](../logs/T-0044.md)). Rows 8–16 are execution's, accepted; **the
  `explain` half of §5.4 is struck** by row 10 and P2 reaches **metric and step renames
  only** by row 11. Nothing above the decision table has been amended to agree with what was
  built — §9's "until `check` lands" reads as written, and T-0032 records that `check`
  turned out not to be a place checks live.
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
| 8 | `ASSUMED` | **`plan()` takes a node-id-to-name map per side rather than reading an `id:` from the IR.** §5.3 assumes the ids are reachable and they are not: neither `MetricIR` nor `StepIR` carries one, because P1 substitutes the id into node ids and lowers nothing — and putting it in the IR is what D3 forbids, since the canonical encoder writes each dataclass's field count and every field name, so a defaulted `id=None` moves the bytes of every project with a metric. `node_labels(project, catalog)` produces the map and both parameters default to empty, so every existing caller keeps today's report. Not `LOCKED`: handing `plan` the two `Project`s reads more naturally and re-admits the spec layer into a diff whose whole design is that it consumes IR, and a later document may prefer that trade. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 9 | `ASSUMED` | **The citation list is `Change.citations`, populated only for a node rename.** §5.3 and §12 name it and no section designs one; nothing under `plan/` carried citations. It names what the compiler can see — the metrics whose definition reads the old name, the marts carrying it as a measure, the exposures declaring it — in `Change`'s own `<kind>:<name>` grammar. A dashboard or a decision row cites a node too and is outside the project, which is why the list is what it is rather than everything §2 imagines. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 10 | `ASSUMED` | **P3 is `lineage` alone; the `explain` half of §5.4 is struck.** `Explanation` carries `mart`, `grain`, `measures`, `filters`, `policy_applied` and `branches` — no node id in any of them — and is built from the IR, which carries none either. There is nothing there to print as a name or to carry as an id. If `explain` is to carry node identity, what it would carry has to be designed first: its subject is a metric *request*, not a graph node. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 11 | `ASSUMED` | **P2 reports metric and step renames only.** `node_keys` mints ids for three kinds and `plan()` diffs two of them: there is no canonical-field pass and there cannot be one, because `ProjectIR` holds no canonical record at all — the field survives lowering only as `ColumnIR.canonical`, a string reference. A renamed canonical field is unreachable here whatever else changes, and making it reportable means changing what the IR *is* rather than what `plan()` reads. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 12 | `ASSUMED` | **A label is the node spelled with its name, not the bare name — supersedes nothing, narrows §5.4.** `metric.mtr_7f3a9c` maps to `metric.gross_revenue`. A bare name leaves an adopted node as the only one in a lineage walk without a kind prefix, so the edge list reads `canonical.quantity --requires--> gross_revenue`: two spellings in one column, harder to read than either. The label is what the id would have been had the project adopted nothing, which is also what makes it substitutable wherever an id appears. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 13 | `ASSUMED` | **The walk is rendered in names and a suggestion is answered in ids.** §5.4 settles the first; the second is what a reader *types*, so `_find_node`'s did-you-mean and its collision refusal keep node ids. Offering a name `--node` does not accept would be worse than the mistype it answers. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 14 | `ASSUMED` | **A rename that lands on a name the old version already used is refused.** Relabelling `a` to `b` in the version that deletes `b` leaves two nodes called `b`, and every pass below keys by name — so one silently wins and which one is an artefact of tuple order. §4 already refuses the shape in prose ("two metrics becoming one is a different change with a different report"); this is the refusal in code, checked *after* the substitution so a legitimate chain — `a` to `b` while `b` becomes `c` — still lands in one version. Reporting a merge properly means keying the whole diff by identity rather than by name, which is a change to what `plan()` is. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 15 | `ASSUMED` | **Each side of a rename diff carries its own catalog.** A metric defined by a `template:` lives in the catalog, so a rename moves text there too and one catalog read for both versions describes neither. A *version* is its documents and its catalog — which the CLI already had right, each spec directory carrying its own — and the how-to did not. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |
| 16 | `ASSUMED` | **The identity material sits with the lineage how-to rather than in `pages/docs/concepts/`.** §7 asks for siting "with the lineage material rather than with the spec reference", and the lineage material is `how-to/trace-lineage.md`, where P1 already put the `id:` section; the rename half lands in `evolve-a-spec.md` beside `renamed_from`'s. §7's reason is honoured and its directory is not: a concepts page is worth minting when there is a concept to explain rather than a surface to use. Added by execution 2026-09-11 — see [`logs/T-0044.md`](../logs/T-0044.md). |

## 12. Phasing

**P1** — the field, node-id construction, the duplicate-id refusal, and the byte-exact
opt-out test. Nothing observable changes for an unadopted project.

**P2** — `ChangeClass.RENAME`'s second producer in `plan()` and its citation list.

**P3** — `lineage` and `explain` output carrying both id and name.

P1 alone is worth landing: it is what RFC 0063 needs, and it costs an unadopted project
nothing.
