# RFC 0070 — Mechanical imports and per-relationship provenance

- **Status:** 📝 Draft
- **Scope:** The import half of [RFC 0044](0044-check-command-and-imported-provenance.md),
  taken out of that document and given its own. Two things that have to arrive together: a
  command that reads an external semantic artifact and produces bloomery relationships, and
  a provenance model that can tell an imported relationship from an authored one. Today it
  cannot — `BASIS_PROVENANCE` is keyed by *basis kind*, so every `many_to_one` in a project
  shares one provenance and `IMPORTED_VERIFIED` has no producer. Touches `spec/entity.py`,
  a new `bloomery.imports` package, `guardrails/evidence.py`, `semantic/proof.py` and the
  CLI. No IR change and no fingerprint movement, deliberately (D3).
- **Related:** [`src/bloomery/semantic/proof.py`](../src/bloomery/semantic/proof.py) —
  `Provenance`, `EvidenceGrade` and `BASIS_PROVENANCE`;
  [`src/bloomery/guardrails/evidence.py`](../src/bloomery/guardrails/evidence.py) —
  `weak_bases`, the only consumer of a fact's grade;
  [`src/bloomery/spec/entity.py`](../src/bloomery/spec/entity.py) — `Relationship`;
  [`src/bloomery/emit/metricflow/__init__.py`](../src/bloomery/emit/metricflow/__init__.py)
  — the emitter for the format this reads;
  [RFC 0039](0039-semantic-proof-ir.md) — the provenance vocabulary;
  [RFC 0065](0065-consumer-evidence-strictness.md) — the consumer that reads the grade,
  and whose row 16 names this document's absence as the reason its refusal is untrippable;
  [RFC 0044](0044-check-command-and-imported-provenance.md) — where P2 used to live.
- **Origin:** Executing RFC 0044 P2 halted at the plan gate with five load-bearing questions
  the document does not settle; the entries and their evidence are in
  [`logs/T-0053.md`](../logs/T-0053.md).

---

## 1. Summary

`IMPORTED_VERIFIED` is a provenance nothing produces. RFC 0039 minted it, RFC 0065 graded
it `ASSUMED`, and RFC 0065's own row 16 records the consequence: the refusal that phase
shipped cannot be tripped by any project, because every fact the compile path mints grades
`LOCKED`.

This document gives it a producer.

```bash
bloomery import metricflow semantic_manifest.json --into specs/
```

reads an external MetricFlow semantic manifest, emits the relationships its
`primary`/`foreign` entity pairs state exactly, and marks them imported. A mart declaring
`requires_evidence: locked` over a measure carried by one of those relationships is then
refused, naming the relationship and the artifact it came from.

The provenance has to become **per relationship** for any of that to be observable, and
that is the larger half of the change.

## 2. Motivation

**A grade nothing can lower is a grade nobody can test.** RFC 0065 shipped
`requires_evidence: locked` and its own log says the requirement is one no current project
can fail — the test restores a pre-row-14 mapping by hand to reach the refusal at all
(`logs/T-0040.md`). A guard whose only exercise is a monkeypatched constant is a guard
whose wiring to real facts is unproven, and the wiring is the part that matters.

**The adoption story RFC 0044 §5 describes needs it.** "Import names, relations and types
mechanically; author a small bloomery semantic overlay for grain, additivity and units" is
the path onto this compiler for a project that already has a semantic layer. Without
provenance the imported half is indistinguishable from authored, and `requires_evidence`
— the one knob a cautious consumer has — silently accepts a relationship no human here
ever read.

**The gap is narrow and load-bearing.** One dict, keyed the wrong way:

```python
BASIS_PROVENANCE: Final[dict[str, Provenance]] = {
    "entity_key": Provenance.DECLARED,
    "many_to_one": Provenance.DECLARED,
    ...
```

## 3. Current state

Verified against `e81fe936`.

- **No importer, and no `import` command.** The CLI has `compile`, `plan`, `resolve`,
  `check`, `lineage`, `timeline`, `explain`, `schema` and `fingerprint`
  (`cli/__init__.py:757`'s `build_parser`). Every one of them reads specs and prints; none
  writes a file.
- **`IMPORTED_VERIFIED` has no producer.** `grep -rn IMPORTED_VERIFIED src/` returns the
  enum member, two docstrings, its `_CLOSING` membership and its `_GRADES` row — nothing
  constructs a `SemanticFact` with it.
- **Provenance is keyed by basis kind** — `semantic/proof.py:710`. Four rows, all
  `DECLARED` since RFC 0065 row 14 moved `entity_key`. There is no per-edge dimension.
- **`weak_bases` is the only consumer of a grade** — `guardrails/evidence.py:87`, reading
  `BASIS_PROVENANCE[basis].grade`. It takes routes as sets of basis *strings*, so a
  per-relationship map cannot reach it without a signature change.
- **`FunctionalDependency.via` already names the relationship** each step traversed
  (`semantic/nodes.py:147`), and is `None` only for `ENTITY_KEY`. The key a per-edge map
  needs therefore already exists on every step; nothing new has to be threaded through the
  closure.
- **A bloomery `Relationship` is `{name, from, to, via, cardinality}`**
  (`spec/entity.py:121`), where `cardinality` is `many_to_one`, `one_to_one` or
  `one_to_many`.
- **bloomery's own MetricFlow output cannot be round-tripped.** Emission is per *mart*:
  compiling `ecom_basic` produces one `semantic_manifest.json` whose single semantic model
  `order_items` carries `[('order', 'foreign', 'order_id')]` and no model declares `order`
  as `primary`. The pairs an importer reads come from a real Semantic Layer project, which
  declares one semantic model per source table. §6 is written against a hand-authored
  manifest for that reason, not a round trip.

## 4. Goals / Non-goals

**Goals**

- `IMPORTED_VERIFIED` has a producer, and RFC 0065's refusal is reachable by a project a
  person could write.
- An imported relationship is distinguishable from an authored one *at the point a
  consumer asks about it*, not only at the point it was read.
- The mapping from artifact field to bloomery fact is exact, documented field by field, and
  refuses rather than guessing.
- No IR change, and no fingerprint movement for a project that imports nothing.

**Non-goals**

- **A dbt `manifest.json` importer.** Named as the obvious first choice and rejected in
  §5.1; a `relationships` test does not state cardinality, and reading one as
  `many_to_one` is the guessed default RFC 0044 D3 forbids.
- **Importing anything but relationships.** Grain, additivity, units and currency are the
  overlay an author writes — that is RFC 0044 §5's adoption path, and widening the first
  importer to touch them makes every one of them a provenance question at once.
- **A conflict-resolution mechanism.** D4 of RFC 0044 says a conflict refuses; §5.4 defines
  when two relationships are the same relationship, and refusing is all it does.
- **Round-tripping bloomery's own MetricFlow output.** §3 records why it would not work,
  and RFC 0013 owns what that emitter writes.

## 5. Design

### 5.1 Why MetricFlow and not dbt

A dbt `manifest.json` states referential integrity and never cardinality. Its
`relationships` test asserts that every value of a column appears in a target column; the
target being *unique* is a separate `unique` or `primary_key` test the project may not have
written. Reading the first as `many_to_one` invents the cardinality that makes the edge
determine anything, which is the failure RFC 0044 D3 names by example.

A MetricFlow semantic manifest states cardinality directly. Each semantic model declares
entity elements with a `type`:

```yaml
semantic_models:
  - name: orders
    entities:
      - {name: order, type: primary, expr: order_id}
      - {name: customer, type: foreign, expr: customer_id}
  - name: customers
    entities:
      - {name: customer, type: primary, expr: customer_id}
```

**Two things are called entities here and they are not the same thing.** A *semantic model*
is the relation, and it is what a bloomery entity corresponds to. An *entity element* —
the rows under `entities:` — is a join identity that several models share, and it
corresponds to nothing in bloomery's vocabulary. `orders` above is a bloomery entity;
`order` and `customer` are not. Reading the element names as endpoints is the mistake this
paragraph exists to prevent, and §5.2's table says `semantic_models[].name` for that reason.

A `foreign` *element* named `E` in one model, and a `primary` (or `unique`) element named
`E` in another, is a `many_to_one` **from the first model to the second**, joined on the
two elements' `expr` columns. So the example yields one relationship, `orders -> customers`
on `customer_id`. Nothing is inferred: both halves are authored in the artifact, and the
pair is what carries the cardinality.

The dbt importer is not refused forever — it becomes exact the moment it requires *both*
tests, which §8 records as the escape hatch rather than building it.

### 5.2 The mapping, field by field

RFC 0044 §5 asks for five columns; these are they.

| Source field | bloomery fact | Transformation | Provenance | Refuses when |
| --- | --- | --- | --- | --- |
| a `foreign` **element** named `E` in model `M` | the from-side | `from` is `M`'s name, never `E` | `IMPORTED_VERIFIED` | no model declares `E` as `primary` or `unique` |
| the model `N` declaring `E` as `primary`/`unique` | the to-side | `to` is `N`'s name, never `E` | `IMPORTED_VERIFIED` | two models declare `E` `primary` — the target is ambiguous |
| both elements' `expr` | `via: {from_expr: to_expr}` | verbatim, one pair | `IMPORTED_VERIFIED` | either `expr` is absent, or is not a bare column name |
| the `foreign`/`primary` pairing | `cardinality: many_to_one` | fixed by the pair | `IMPORTED_VERIFIED` | — |
| `semantic_models[].name` | the **entity** name, on both sides above | verbatim | `IMPORTED_VERIFIED` | it is not a `MemberName`, or names no entity the project declares |
| — | the relationship's own `name` | generated, and unique across the project | `IMPORTED_VERIFIED` | the generated name collides with one the project already declares |

A `natural` entity type imports nothing: it is MetricFlow's marker for a key that is not
unique, so no cardinality follows from it. `unique` is admitted alongside `primary` because
both assert at most one row per value, which is the whole of what `many_to_one` needs.

**Absence imports nothing.** A model with no `primary` entity contributes no target and the
importer refuses the `foreign` elements pointing at it, rather than emitting a weaker edge —
there is no weaker edge in `DependencyBasis` to emit (RFC 0044 D3).

### 5.3 Where the provenance lives

The importer writes a normal `relationships:` block into a spec document, plus one key:

```yaml
relationships:
  - name: order_items__order
    from: order_item
    to: order
    via: {order_id: order_id}
    cardinality: many_to_one
    imported_from: metricflow:semantic_manifest.json
```

`imported_from` is a free string naming the artifact, and its **presence** is the fact:
a relationship carrying it is `IMPORTED_VERIFIED`, one without it is `DECLARED`. A string
rather than a boolean because the refusal has to name the artifact for a reader to act on
it, and a boolean would need a second key to do that.

It is a spec key and never enters `MartIR` or any other IR node — the same placement RFC
0065 row 17 argued for `requires_evidence`, and for the same reason: `project_fingerprint`
walks the IR dataclass tree, so a field there moves every fingerprint in the corpus for
projects that import nothing.

`weak_bases` therefore changes shape. It takes routes as sets of `(basis, via)` pairs
rather than of basis strings, and consults a per-relationship map built from the authored
`EntityModel`:

```python
def weak_bases(
    routes: Iterable[AbstractSet[tuple[str, str | None]]],
    imported: Mapping[str, str],
) -> tuple[str, ...]: ...
```

**A mapping, not a set**, and the paragraph above is why: §1 says the refusal names the
artifact a relationship came from, and a set of names cannot supply one — the caller would
have to go back to the spec for it, which is the indirection the alternatives below reject
in another form.

`via` is `None` for `ENTITY_KEY`, which has no relationship and stays `DECLARED`. A step
whose `via` is in `imported` grades `ASSUMED` whatever its basis says.

### 5.4 When two relationships are the same relationship

RFC 0044 D4 refuses a conflict between an imported and a declared fact and does not say
what makes them the same fact. They are the same relationship when they have the same
`(from, to, via)` — the endpoints and the join. Not the same `name`: an importer generates
names and an author picks them, so name equality would report every import as a conflict
and every renamed import as none.

Same triple, same `cardinality`: the import is redundant and is accepted silently, because
two statements that agree are not a contradiction.

Same triple, different `cardinality`: refused, naming both provenances and the artifact.

Different triple: two relationships, which is already what the ambiguity guard reads.

### 5.5 The command

```bash
bloomery import metricflow <artifact> --into <directory>
```

Writes one document, `imported.yaml`, into the spec directory; refuses rather than
overwriting an existing one. It is the first command in this CLI that writes, and that is
why it is a *command* and not part of load: compilation stays a pure function of the specs
on disk (RFC 0003), and what the importer produces is specs.

`--stdout` prints instead of writing, for a caller that wants to review before committing.

### Alternatives considered

- **Import at load time, composing the artifact with the specs in memory.** No file to
  review, no diff to read, and the compile is then a function of an artifact nobody
  committed — which breaks the reproducibility RFC 0003 exists for. Writing a document the
  author commits keeps the input set visible.
- **A separate `provenance:` document mapping relationship names to origins.** Keeps the
  relationship block clean, and puts the fact one indirection from the thing it describes,
  where a renamed relationship silently loses its provenance. Rejected for the reason
  RFC 0038 D5 rejected a second spelling.
- **A `provenance:` enum on `Relationship` rather than `imported_from:`.** More general and
  presently unusable: `DECLARED` and `IMPORTED_VERIFIED` are the only two values a spec
  could carry, `DERIVED` is not authorable, and an enum invites a future author to write
  `declared` on something they did not read. Presence of an artifact name cannot be written
  by accident.
- **Keying `BASIS_PROVENANCE` by `(basis, relationship)`.** One map instead of two, and it
  makes a module-level constant depend on the project — the table is a vocabulary, not
  project state.

## 6. Tests

- **The mapping, per row of §5.2's table.** One hand-authored manifest per refusal
  condition: no `primary` for a named `foreign`, two models claiming one `primary`, a
  missing `expr`, an `expr` that is not a bare column, an entity name no project declares.
  Each asserts the refusal names the model and the entity element.
- **`natural` imports nothing**, asserted positively rather than by its absence from a
  count — a `natural` element alongside a valid pair, and the pair still imports.
- **The producer, end to end.** Import a manifest into a fixture, compile, and assert the
  relationship's dependencies grade `ASSUMED` — the first test in the corpus where a fact
  the compile path mints is not `LOCKED`.
- **RFC 0065's refusal, from a project rather than a monkeypatch.** A mart with
  `requires_evidence: locked` whose measure is carried through an imported relationship is
  refused, with the message naming the relationship. `logs/T-0040.md` records the existing
  test restoring a pre-row-14 mapping by hand; that test stays as the regression guard for
  row 14 and stops being the only exercise of the refusal.
- **`weak_bases` directly**, as today: no fixture reaches a column two ways, so the
  "strongest route acquits" rule is asked rather than exercised — including the new case, a
  column reached by one imported and one authored route, which the authored route acquits.
- **Determinism.** The written `imported.yaml` is byte-identical across processes and hash
  seeds, and importing twice into a clean directory produces the same bytes (RFC 0003).
- **No fingerprint movement.** Every corpus fingerprint is unchanged by this branch, which
  is what D3 claims and what row 17's hazard would break.

## 7. Docs

A how-to for the adoption path — import, overlay, `check` — under `pages/docs/how-to/`,
and `requires_evidence`'s reference page gains the case that now exists: what a `locked`
mart does when a relationship came from an artifact. The migration note has nothing to say:
nothing that compiles today changes, because a project with no `imported_from:` takes the
same grades it takes now.

## 8. Out of scope

- **The dbt importer.** Exact the moment it requires a `relationships` test *and* a
  `unique`/`primary_key` on the named target, both in one manifest. Named as the escape
  hatch; not built, because one importer is what proves the provenance path and two is
  twice the mapping table to argue about.
- **Importing grain, additivity, units or currency.** §4's non-goal, and the overlay is the
  point.
- **`bloomery check` reading an artifact directly.** RFC 0044 D1 (`LOCKED`) keeps `check`
  free of external inputs; the importer writes specs and `check` reads specs.
- **Re-import and drift detection.** Whether a committed `imported.yaml` still matches its
  artifact is a real question and a different one; it needs the artifact at check time,
  which D1 forbids.

## 9. Risks

- **`imported_from:` reads as documentation and gets hand-written.** It is load-bearing —
  writing it by hand on an authored relationship silently lowers that relationship's grade,
  which is the safe direction but is still a wrong fact. Mitigated only by the key being
  odd enough to look generated; there is no way for the compiler to tell.
- **The `weak_bases` signature change touches the one guard RFC 0065 shipped.** Its callers
  are two and its tests are direct, but a mistake here weakens a safety check rather than
  breaking a build. §6 asks for the pre-row-14 regression test to stay for exactly this.
- **One importer may be the wrong generalisation.** The mapping table is written against
  MetricFlow's entity types, and a second importer could find that `imported_from:` wants
  structure rather than a string. Accepted: a string is the cheapest thing to widen.
- **Nothing verifies the artifact was not edited.** `IMPORTED_VERIFIED` says the *rule* was
  exact, not that the file was honest — RFC 0039 §4 already says so, and this is where a
  reader will first want it repeated.

## 10. Unresolved questions

- **Whether `imported.yaml` is one document or one per source model.** One is simpler and
  makes a large import a large diff; per-model matches how a Semantic Layer project is laid
  out. Implementation may settle it (D6).
- **What `bloomery import` exits with when it refuses.** `check` has an exit contract
  (RFC 0044 P1) and the other commands do not; a writer command's contract is not obviously
  either. Settle it against what `check` prints today.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Provenance attaches to the relationship, not to the basis kind.** `BASIS_PROVENANCE` is keyed by `DependencyBasis` value, so today every `many_to_one` in a project shares one provenance and an imported edge cannot be told from an authored one — which is why `IMPORTED_VERIFIED` has no producer and RFC 0065's refusal has no project that can trip it. Locked because it is the whole of what makes the grade mean anything at the point a consumer asks; reversing it makes every other row here decoration. `FunctionalDependency.via` already carries the key such a lookup needs. Proposed by execution — see [`logs/T-0053.md`](../logs/T-0053.md) (D2, attempt 1). |
| 2 | `LOCKED` | **A dbt `relationships` test alone imports nothing.** It asserts every value exists in a target column and says nothing about the target being unique, so reading it as `many_to_one` invents the cardinality that makes the edge determine anything — RFC 0044 D3's failure, by its own example. `many_to_one` from dbt requires the `relationships` test *and* a `unique`/`primary_key` on the named target. Locked because the tempting version of this importer is the one that skips the second test, and it would be indistinguishable in review from the correct one. Proposed by execution — see [`logs/T-0053.md`](../logs/T-0053.md) (D3, attempt 1). |
| 3 | `LOCKED` | **No IR node gains a provenance field.** `project_fingerprint` walks the IR dataclass tree, so a field there moves every fingerprint in the corpus for projects that import nothing — RFC 0065 row 17's hazard, arriving from the same direction a second time. The fact is read from the authored `EntityModel` at the guardrail stage, the shape `requires_evidence` already uses. |
| 4 | `LOCKED` | **Two relationships are the same relationship when `(from, to, via)` match, and a cardinality disagreement between an imported and a declared one refuses naming both.** RFC 0044 D4 mandates the refusal and leaves the predicate undefined, which makes it unimplementable. Not `name`: an importer generates names and an author picks them, so name equality reports every import as a conflict and every renamed import as none. Agreement on the same triple is not a contradiction and is accepted silently. |
| 5 | `ASSUMED` | **The first importer reads MetricFlow, and only relationships.** MetricFlow states cardinality in the artifact where dbt does not (§5.1), and relationships are the only facts `weak_bases` reads — so they are the shortest path to a producer that is observable. Not `LOCKED` because a second importer may show the mapping table wants a shape the first did not need. |
| 6 | `OPEN` | **Whether the importer writes one `imported.yaml` or one document per source model.** One is a simpler contract and a worse diff on a large import; per-model matches the layout of the project being imported from. Decide it against what a real manifest produces, and log the decision. |
| 7 | `ASSUMED` | **`imported_from:` is a free string naming the artifact, and its presence is the fact.** A boolean would need a second key for the refusal to name the source, and an enum invites an author to write `declared` on something they did not read (§5's alternatives). Not `LOCKED` because a second importer may want structure; a string is the cheapest thing to widen. |
| 8 | `ASSUMED` | **P1 relabels the grade a consumer reads and leaves the proof leaf saying `declared`.** `BASIS_PROVENANCE` has two consumers, not the one §3 names: `weak_bases` reads the grade, and `_dependency_proof` mints `SemanticFact(provenance=BASIS_PROVENANCE[basis])`, which is the literal producer a reader of §1 looks for. Closing the second needs an IR field, which D3 forbids, or a spec-aware planner — and `planner/coverage.py` holds no `Project` anywhere from `resolve_request` down to `prove_rollup`. One relationship therefore reports two provenances until P2. It mislabels an account without changing a verdict, since `IMPORTED_VERIFIED` closes an obligation. Added by execution 2026-09-13 — see [`logs/T-0053.md`](../logs/T-0053.md) (unlisted, attempt 1). |
| 9 | `ASSUMED` | **The imported set is read from `project.entity_model` in `check_evidence`**, beside the `requires_evidence` read it already does. One walk of the authored spec, two facts — so a project cannot be strict about a relationship the same function decided was authored. Added by execution 2026-09-13 — see [`logs/T-0053.md`](../logs/T-0053.md) (unlisted, attempt 1). |
| 10 | `LOCKED` | **A relationship's name is unique across a project.** Nothing made it so and every consumer treats it as a key, each resolving a collision differently and silently: a mart's `via:` takes the first match, `plan` keeps the last of a `{name: rel}` dict, and D1's lookup marked every same-named authored edge as imported. Refused at resolution rather than fixed per reader — the readers are four and the fact is one. Locked because D1's lookup is keyed by that name, so relaxing it reintroduces a wrong refusal rather than an ambiguity. Added by execution 2026-09-13 — see PR #115 review. |

## 12. Phasing

**P1 — the provenance path.** `imported_from:` on `Relationship`, the per-relationship
lookup, `weak_bases` re-signed, and RFC 0065's refusal reached from a fixture rather than a
monkeypatch. No command yet: the fact can be authored into a fixture, which is what proves
the path end to end.

> **Landed 2026-09-13** (PR #115), with the relationship-name uniqueness guard row 10
> records. Rows 8 and 9 are what it had to decide that §12 did not settle.

**P2 — the importer and the command.** The MetricFlow mapping of §5.2, its refusals, and
`bloomery import`.

Splitting them this way puts the safety-relevant change — the one that touches a shipped
guard — in a phase whose whole diff is that change, and leaves the artifact parsing to a
phase that cannot weaken anything.
