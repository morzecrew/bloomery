# RFC 0032 — Mapping identity

- **Status:** 🚧 In progress — **fully shipped, waiting on a retirement commit the mainline
  can reach.** `Mapping.document`, `FieldProvenance.mapping`, §6's battery and §7's docs all
  landed; D8–D11 were added by execution (`logs/T-0008.md`). The document stays here because
  a retirement row must name a commit that holds it *and* that a fresh clone can reach, and
  this RFC was authored and executed in one branch — so no such commit exists until this
  lands on `main`. `INDEX.md` names exactly this case for 🚧: the status tracks the
  document's life in this directory, which ends at retirement rather than at the last
  decision implemented. It is retired in the change immediately after the merge.
- **Scope:** The identity of a mapping document, settled once for the two readers that
  need it. `Mapping` carries no name today, so a report that must say *which document to
  edit* either picks one arbitrarily (`FieldProvenance`, "last in document order") or
  withholds the entry (`OpenDecision`, RFC 0030 D9). Both are waiting on the same missing
  noun, and both are waiting on it behind RFC 0024 P2's demand gate, which is gated on an
  unrelated need. This adds the name the loader already computes and already discards,
  and spends it on those two readers. Touches `spec/project.py`, `spec/mapping.py`,
  `resolve/resolution.py`, `evidence.py`. **Two public shape changes**, both additive:
  a field on `Mapping` (exported from `bloomery.spec`, not from the top level) and a field
  on `FieldProvenance` (top level). No IR change, no emitted artifact changes, no golden
  moves.
- **Related:** [`src/bloomery/spec/project.py`](../src/bloomery/spec/project.py)
  (`load_project` — where the name is computed and dropped),
  [`src/bloomery/spec/mapping.py`](../src/bloomery/spec/mapping.py) (`Mapping`),
  [`src/bloomery/resolve/resolution.py`](../src/bloomery/resolve/resolution.py)
  (`FieldProvenance`, `_field_provenance`),
  [`src/bloomery/evidence.py`](../src/bloomery/evidence.py) (`OpenDecision`,
  `_unresolved`), RFC 0024 (the merged entity, D19/D26/D31), RFC 0002 §5.3 (source paths
  — where document names are already the user-facing coordinate).
- **Origin:** Refuted out of scope on PR #55 and recorded on `FieldProvenance`'s docstring,
  where it has sat as prose ever since: *"an entry would have to name its mapping, which is
  the same identity RFC 0030 D9 withholds an open decision for want of."*

---

## 1. Summary

A mapping document has no name in the object model. `load_project` reads
`sources: dict[str, str]`, iterates `sorted(sources)`, and appends each `Mapping` to a
tuple — keeping the name for entity models (`entity_models.append((name, model))`) and
dropping it for mappings (`mappings.append(model)`).

Two reports need that name, and neither can be correct without it:

- **`FieldProvenance`** keys on `(entity, field)`. Where two mappings build one entity and
  implement one field differently, it reports the last in document order and no others.
- **`OpenDecision`** promises "here is the edit that would close it", so RFC 0030 D9 omits
  the entry entirely when the entity has more than one mapping.

This adds `Mapping.document` — the name the loader already has — and gives
`FieldProvenance` a `mapping` field, one entry per `(entity, field, mapping)`. It does
**not** lift RFC 0030 D9's omission, which is a separate question about what a worklist
entry means; it removes the reason D9 gave for being unable to.

## 2. Motivation

**The arbitrary answer is invisible at the call site.** `FieldProvenance` is documented as
"the loop's memory of what it has already decided" — a chooser reads it to know which
fields already carry a recorded recipe. On a merged entity it answers for one mapping and
says nothing about the others, and the entry looks identical to a single-mapping one. A
chooser cannot tell the difference between "this field has no recipe" and "this field has
no recipe *in the document I happened to be shown*".

**Measured, not assumed.** Across the fixture corpus exactly one project has a merged
entity — `multi_source`, entity `order_line` — and **4 provenance facts are not
representable** there. That is the whole current cost, and it is deliberately reported as
small: the argument for this change is not volume but that the report is silently wrong on
a shape the compiler supports, and the wrongness scales with the first real merged project.

**The tie-break is opposed to the artifact.** `multi_source`'s own fixture comment records
that document order and branch order are deliberately opposed there — `mapping_legacy`
parses first while its branch (`woo__order_lines`) is unioned second. So "last in document
order" is not merely arbitrary; it is a coordinate with no stable relationship to anything
the reader can see in the emitted SQL.

**Both readers are blocked behind a gate that is about something else.** RFC 0030 D9
(`LOCKED`) says the omission "lifts when the report can carry a mapping identity, which is
RFC 0024 P2's question rather than this one's". RFC 0024 D31 (`LOCKED`) demand-gates P2:
*"implementation begins when a project needs quality rules on a merged entity, and not
before."* An identity two reports need is therefore waiting on a project needing the
**quality system** on a merged entity — two unrelated needs joined by nothing but the word
"merged". Neither document can dissolve that on its own without reopening the other's
locked row, which is what this RFC is for.

## 3. Current state

Verified against `main` @ `13d2049`.

**The name exists and is discarded.** `load_project` (`spec/project.py`):

```python
for name in sorted(sources):
    ...
    entity_models.append((name, model))   # kept
    ...
    mappings.append(model)                # dropped
```

`Project.mappings` is documented as "ordered by document name", so the name is already
load-bearing for determinism — it just never survives into the model.

**`(source, target)` is not an identity.** RFC 0024 D19 uses `f"{source.relation}->{entity.name}"`
as the quality mart's accounting key, which reads like a candidate. It is not unique:
two documents with identical `source:` and `target:` load without complaint.

```python
sources["mapping_dup"] = sources["mapping_order_items"]      # same source, same target
load_project(sources)                                        # loads
# [('shopify__order_lines', 'order_item'), ('shopify__order_lines', 'order_item'), ...]
```

Nothing in the loader, the resolver or the guardrails refuses it. A report keyed on the
pair would collapse two documents into one entry — the same defect one level up.

**`FieldProvenance` today** carries `(entity, field, provenance, recipe_id)` and is built
by `_field_provenance(project, graph)`, which iterates `project.mappings` in document order
writing into `recipe_of[mapping.target, field_name]` — last write wins, by construction.

**`_unresolved` today** counts `mappings_per_entity = Counter(mapping.target for ...)` and
`continue`s past any canonical whose entity has more than one mapping. The branch is
covered by `test_a_merged_entity_reports_no_open_decision`, which constructs the shape
rather than reading it from a fixture — no corpus fixture reaches it, because
`multi_source` has neither catalog nor metrics.

**`resolution.provenance` is read by `evidence.py` alone.** It reaches no IR node and no
emitted artifact, which is what keeps this change's blast radius to two modules and no
goldens.

## 4. Goals / Non-goals

**Goals**

- One noun for "which mapping document", available wherever a `Mapping` is.
- `FieldProvenance` representing a merged entity's field honestly: one entry per mapping
  that builds it, none silently dropped.
- The identity chosen so that it is what a **reader edits**, not what a compiler indexes.

**Non-goals**

- **Lifting RFC 0030 D9's omission.** D9 withheld the entry for two reasons — no identity,
  and no answer to what a worklist entry *means* when N documents could each close a gap.
  This RFC removes the first. The second is a question about the report's promise, not
  about identity, and answering it here would decide RFC 0030's contract inside a document
  about nouns. §8 names what would settle it.
- **Anything in RFC 0024 P2.** The quality system on a merged entity is untouched; D31's
  demand gate is unaffected, and this RFC deliberately does not consume it.
- **A stable identity across renames.** The document name is the identity; renaming the
  file changes it. See D5.

## 5. Design

### 5.1 `Mapping.document`

The loader passes the name it already has:

```python
class Mapping(SpecModel):
    """One (source, target entity) mapping document (``mapping_version``)."""

    #: The document this mapping was parsed from — the same name that prefixes
    #: its refusals (RFC 0002 §5.3) and orders `Project.mappings`.
    document: str
    mapping_version: Literal[1]
    source: str
    target: str
```

**It is set by the loader, never authored.** The field is not in the YAML vocabulary — a
document that declares `document:` is refused as an unknown key, by the same
`extra="forbid"` shape checking that refuses every other unknown key. The name is a fact
about *where the document was read from*, and a document asserting its own filename is a
second source of truth that can disagree with the first.

`load_project` sets it at construction, which keeps `Mapping` a value that is complete when
it exists rather than one filled in afterwards.

### 5.2 `FieldProvenance.mapping`

```python
@dataclass(frozen=True, slots=True)
class FieldProvenance:
    entity: str
    field: str
    mapping: str
    provenance: Provenance
    recipe_id: str | None = None
```

One entry per `(entity, field, mapping)`, sorted by that triple. A single-mapping entity's
report grows one field and no rows; a merged entity's grows a row per mapping that builds
the field.

`mapping` is placed **third, before `provenance`** rather than appended last. Every field
before `recipe_id` is required, so there is no positional-rebinding hazard of the kind
`SpecEvidence` records in its own field order — a caller constructing this positionally
gets a `TypeError` on arity, not a silently wrong value. Reading order beats wire order
where the wire is safe.

### 5.3 What the readers do with it

**`_field_provenance`** keys `recipe_of` on the triple instead of the pair, which deletes
the last-write-wins line rather than replacing it. The "document order, overwriting"
comment goes with it: there is nothing left to overwrite.

**`_unresolved` does not change in this RFC.** Its `continue` stays, and its comment is
amended to say what is now true: the identity exists, and what remains is the contract
question (§8).

### 5.4 Sorting

`FieldProvenance` sorts by `(entity, field, mapping)`. Mapping is the last term so that a
merged entity's rows for one field stay adjacent — the reader's question is "how is this
field built", and the answers to it should not be interleaved with another field's.

### Alternatives considered

**`(source, target)`, the quality mart's key (RFC 0024 D19).** Rejected on a demonstrated
collision: two documents may share both. Its trade-off was attractive — it is derived from
declared content rather than from a filename, so it survives a rename — and that is exactly
what makes it wrong here: content is not identity, and two documents describing the same
`(source, target)` are a legal spec.

**An integer index into `Project.mappings`.** Unique and cheap. Rejected because it is a
coordinate in a tuple, not in the user's project: an entry saying `mapping=1` sends a
reader to count documents in sorted order. RFC 0030 D9's whole promise is that an entry
names an edit.

**A synthesised digest of the document's content.** Stable across renames, and unique.
Rejected for the same reason as the index, more so: it names nothing a human can open.

## 6. Tests

- **`Mapping.document` is the loader's name, not the author's.** A document declaring
  `document:` is refused as an unknown key; a document that does not gets the name it was
  loaded under. Both asserted, because the second alone would pass if the field were
  silently authorable.
- **Corpus sweep.** Every mapping in every spec fixture has a `document` that is a key of
  the fixture's own `read_spec_directory` result — the identity is total and correct, not
  merely present.
- **The merged case, on the fixture rather than a construction.** `multi_source`'s
  `order_line.quantity` is built by both mappings; the report carries two entries naming
  `mapping_legacy` and `mapping_platform`. This replaces
  `test_a_merged_entitys_field_reports_one_provenance`, which pinned the defect.
- **The single-mapping case does not grow rows.** `ecom_basic`'s provenance keeps its
  length and gains a `mapping` on each entry — the change is additive for the shape almost
  every project has.
- **Uniqueness of the triple**, swept over the corpus: no `(entity, field, mapping)`
  appears twice. This is the invariant that replaces "last write wins", and it is the one
  a future merge-shape change would break first.

Not tested: that `document` reaches no emitted artifact. That is asserted structurally
instead — provenance is read by `evidence.py` alone — and the golden suite is the check.

## 7. Docs

`SpecEvidence.provenance` is documented in the how-to that RFC 0030 shipped
(*Close an open decision*). Its one sentence about a merged entity's field appearing once
becomes a sentence about it appearing per mapping. The CHANGELOG entry names both public
shape changes, since both bind under SemVer.

## 8. Out of scope

- **Lifting RFC 0030 D9.** With an identity available, the remaining question is what an
  `OpenDecision` *means* when N documents could each close the gap: one entry per mapping
  (N worklist items for one gap, each individually actionable), or one entry naming all N
  (one item, not individually actionable). That is a decision about the report's promise
  and belongs in whatever RFC reopens D9 — with the observation, recorded here so it is
  not rediscovered, that a merged entity's gap may be closable in *any* one document, which
  makes N entries an over-count rather than a list.
- **A mapping identity in the IR or the artifacts.** `mapping_version` is already a
  provenance stamp in `plan/diff.py`, and the quality mart accounts per entity (RFC 0024
  D19). Nothing here proposes a second coordinate down there.
- **RFC 0024 P2.** Untouched, and deliberately not consumed: this RFC exists so that P2's
  demand gate stops standing between two reports and a noun.

## 9. Risks

- **The identity is a filename, so a rename is a change of identity.** Accepted, and it is
  the honest reading: renaming a mapping document *is* a change to where an edit goes. The
  mitigation is that nothing durable is keyed on it — it appears in an assessment value,
  never in the IR, the fingerprint or an artifact, so a rename moves a report and nothing
  else. Were it ever to reach the fingerprint, this decision would need reopening; D4
  records that.
- **Two public shape changes at once.** Both are additive and pre-1.0, and both are in the
  CHANGELOG. The risk is a caller constructing `FieldProvenance` positionally; §5.2 argues
  why that fails loudly rather than silently.
- **This looks like it lifts D9 and does not.** Mitigated by saying so in three places —
  the scope line, the non-goals, and the `_unresolved` comment that the change amends
  rather than removes. A reader who assumes otherwise finds the `continue` still there.

## 10. Unresolved questions

None blocking. The one deliberate deferral — what an `OpenDecision` means across N
mappings — is §8's first bullet, and it is not a precondition for anything here: the
`continue` stays exactly as it is, so nothing in this RFC depends on the answer.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The identity is the document name.** It is unique by construction (a key of the `sources` mapping), already computed, already the ordering key for `Project.mappings`, and already the user-facing coordinate for refusals (RFC 0002 §5.3). Consequence: identity is a filename, so a rename changes it — accepted under D4's boundary. |
| 2 | `LOCKED` | **`(source, target)` is refused as the identity**, against RFC 0024 D19's key shape looking like a candidate. Demonstrated non-unique: two documents may declare the same pair and the loader accepts them. Consequence: D19's quality-mart key is left alone — it is an accounting key for a per-entity mart, not an identity, and this decision does not reopen it. |
| 3 | `LOCKED` | **`document` is set by the loader and is not part of the YAML vocabulary.** A document declaring its own name is a second source of truth that can disagree with the first. Consequence: `Mapping` cannot be constructed from YAML alone in a test without the loader — which is already how every test builds one. |
| 4 | `ASSUMED` | **The identity stays out of the IR, the fingerprint and every artifact.** It is a coordinate for an assessment, and RFC 0003's determinism argument is about what reaches output. Consequence: a rename moves a report and nothing else; if a future change wants mapping identity in the IR, D1's rename cost has to be re-argued there, because a filename in a fingerprint makes a rename a rebuild. |
| 5 | `ASSUMED` | **`FieldProvenance.mapping` goes third, not last.** Every field before `recipe_id` is required, so a positional caller gets a `TypeError` rather than the silent rebinding `SpecEvidence`'s field order exists to avoid. Consequence: reading order and wire order agree here, and the precedent does not generalise to a type whose fields all have defaults. |
| 6 | `LOCKED` | **RFC 0030 D9's omission is not lifted here.** D9 gave two reasons and this RFC removes one; the other — what a worklist entry means when N documents could each close a gap — is a decision about the report's promise. Consequence: `_unresolved` keeps its `continue`, and the change is a comment saying what is now true. Answering both at once would decide RFC 0030's contract inside a document about nouns. |
| 7 | `OPEN` | **Whether `FieldProvenance` sorts by `(entity, field, mapping)` or `(entity, mapping, field)`.** §5.4 argues the first — a field's answers stay adjacent — but the second groups a reader's attention by document, which is what they will edit. Execution decides against the corpus, and logs it: whichever reads better on `multi_source`'s four collapsed facts is the answer, and that is a thing to look at rather than reason about. |
| 8 | `ASSUMED` | **The identity is bound in `validate_document`, which already receives the document name as the prefix for this document's refusals (RFC 0002 §5.3)** — not in `load_project`, as §5.1's prose said. A required field only one caller could supply leaves every other caller with a model it cannot construct; binding it at the one gate every parsed document passes also means the coordinate a report sends a reader to and the coordinate a refusal names are the same value by construction. Consequence: a caller reaching the shape check directly gets an identity too. *Added by execution 2026-08-30 — see logs/T-0008.md (D-035, attempt 1).* |
| 9 | `LOCKED` | **`document` is `SkipJsonSchema` — absent from the schema `bloomery schema` exports.** That schema's audience is a spec author and D3 says this field is not theirs to write; a required `document` there would have an editor demand the one key the loader refuses, the exported contract contradicting the compiler on the surface whose whole job is to agree with it. Consequence: the model and the exported schema deliberately disagree about one field, recorded by `test_document_is_in_the_model_and_not_the_schema` where the other measured divergences live. *Added by execution 2026-08-30 — see logs/T-0008.md (D-036, attempt 1).* |
| 10 | `ASSUMED` | **The refusal of an authored `document:` is returned, not raised, so it joins the document's other shape failures** (RFC 0002 D6). Raising at the check pre-empted every other error in the same document — the one-at-a-time fixing batching exists to prevent, reintroduced by a check that runs before pydantic sees the data. Consequence: `_with_document_identity` returns a `(data, refusal)` pair rather than raising, and `validate_document` merges the refusal into the collected set. *Added by execution 2026-08-30 — see logs/T-0008.md (A-1).* |
| 11 | `LOCKED` | **`FieldProvenance.mapping` is keyword-only, and D5's rationale for placing it third was wrong.** D5 argued that a positional caller would fail on arity; `recipe_id` carries a default, so the old four-argument call `FieldProvenance(entity, field, provenance, recipe_id)` still satisfies arity and binds `provenance` into `mapping` — the silent rebinding the placement was chosen to prevent, reproduced rather than reasoned about. `kw_only=True` restores the loud failure and keeps the reading order D5 wanted. Consequence: the field's *position* is now a reading convenience only, and nothing rests on it. *Added by execution 2026-08-31 — see logs/T-0008.md (R-1).* |

## 12. Phasing

One phase, one PR. The two shape changes and both readers land together: a `Mapping` that
carries a name nothing consumes is a field waiting to drift, and a `FieldProvenance` that
names a mapping the loader cannot supply does not compile.
