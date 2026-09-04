# RFC 0053 — Retrieval semantics

- **Status:** 📝 Draft — **blocked on a domain decision** (§1). Nothing here is executable
  until the question in §1 is answered, and the honest answer may be no.
- **Scope:** A new optional spec kind (`retrieval_version: 1`) carrying **semantic
  spaces**, **vector-field annotations** and **retrieval profiles**, plus the guardrails
  that make them worth declaring and one deterministic manifest artifact. Storage- and
  vendor-neutral: no Lance, no LanceDB, no vector database, no ANN index, no embedding
  ever computed or read. The blast radius is larger than the surface suggests and §5.2
  measures it: `LogicalType` is a seven-member union with no array and no float, so a
  declared vector dimension is a new logical type, and that reaches `parse_type`,
  `assignable`, the transform domains and every dialect port's `physical_type`. Projects
  declaring no retrieval spec compile byte-identically.
- **Related:** [`src/bloomery/typing/types.py`](../src/bloomery/typing/types.py),
  [`src/bloomery/spec/project.py`](../src/bloomery/spec/project.py),
  [`src/bloomery/evidence.py`](../src/bloomery/evidence.py),
  [`src/bloomery/emit/metricflow/__init__.py`](../src/bloomery/emit/metricflow/__init__.py),
  RFC 0037 (the semantic grain model this eventually sits on),
  RFC 0043 (the capability matrix — a research task, not this),
  RFC 0003 (determinism; retired at `33bc4f9`), RFC 0010 (mart grain, same commit).
- **Origin:** An external feature request proposing retrieval-aware data-product
  semantics with Lance/LanceDB as the reference ecosystem. This RFC keeps its core claim,
  measures three of its premises against the tree, and finds one of them false (§3).

---

## 1. The question this RFC does not answer

> **Is bloomery a compiler for analytical data products, or for semantically validated
> data products more broadly?**

That is a maintainer's decision about what the project is, and no amount of design
settles it. It is stated first, and as a blocker, because everything below is worth
building only if the answer is the second one — and because the first answer is entirely
respectable. bloomery's distinctiveness is that it knows what a column *means*; whether
"means" extends past grain, units and additivity into embedding identity is a question
about scope, not about capability.

The reason it is worth asking at all: retrieval datasets fail in exactly bloomery's
signature way. A table with `embedding ARRAY<FLOAT>` whose rows came from two different
768-dimension models is type-valid, indexable, queryable, and semantically meaningless. A
profile pointing a text query at a 1024-dimension *image* embedding is mechanically
perfect and wrong. A cosine-trained model served against an L2 index answers, plausibly,
incorrectly. These are the shipping-charged-once-per-order bug in a different domain: the
SQL is right and the number is not.

The rest of this document assumes the answer is yes. If it is no, the correct outcome is
to reject this RFC and keep retrieval semantics downstream, where a runtime that already
knows its own vector store can enforce them.

## 2. Motivation

Four failure classes, none of which a type system catches:

| Failure | What is valid | What is wrong |
|---|---|---|
| Mixed producers | dimensions agree | half the rows are a different model's space |
| Wrong encoder side | dimensions agree | query encoded as a document (asymmetric models) |
| Wrong space | dimensions agree | a text query against an image embedding |
| Wrong metric | index builds | cosine-trained vectors scored by L2 |

Each is decidable from the spec alone, which is the test RFC 0016 §5.9 applies to decide
whether something is a guardrail or a data-quality rule. Nothing here needs to read a
row.

## 3. Current state

Three premises of the source proposal, measured.

**There is no array type and no float type.** `LogicalType` is
`StringType | IntType | DecimalType | BoolType | DateType | TimestampType | VariantType`
— seven members, no sequence, no float. So the proposal's "Option A vs Option B" (a
first-class `type: vector` versus an annotation over an array) is not a choice between two
available shapes: *neither* exists. Whichever is chosen, `LogicalType` grows. §5.2 costs
that out.

**The float ban is about values, not type names, and the distinction has to be argued.**
`Decimal` or int only, no floats in the IR or any emission path — enforced by a pre-commit
pygrep hook and by refusals like `Reconcile.tolerance`'s. An embedding is a list of
float32 *values*, which sounds fatal and is not: bloomery never sees an embedding. What a
spec declares is a scalar **type name** (`float32`) and an integer dimension count. No
float literal enters the IR, no float is rendered into SQL, and no arithmetic is performed
on one. The rule holds unchanged; it just needs saying before a reader stops at the word.

**bloomery has no intake for measured evidence, so one section of the proposal describes a
feature that does not exist.** `SpecEvidence`'s own docstring is "everything knowable
about a spec **without touching data**", and there is no surface anywhere for supplying a
null-rate or a freshness measurement. The proposal's "embedding_non_null: minimum_ratio"
rule is therefore not a retrieval feature at all — it is a *runtime-evidence intake*
feature that would apply equally to every existing column, and it is excluded here (§8)
rather than smuggled in under a retrieval heading.

**A manifest-only target already exists.** `Target.METRICFLOW` shipped in `2d38622`: one
`semantic_manifest.json`, no models, a project without marts emitting nothing. That is
structurally what a retrieval manifest is, and it is why §5.5 reaches a different
conclusion from the proposal's about whether this should be a `Target`.

**Spec kinds are a closed map.** `spec/project.py` keys documents by exactly one of
`spec_version` / `mapping_version` / `metrics_version` / `marts_version` /
`steps_version`; a new kind is a new entry there and a new `<kind>_version`.

**Grain is prose plus a key.** `EntityIR.grain` is a human sentence; `key` is the tuple
that actually identifies a row. Retrieval grain has to be built on `key`, not on the
sentence.

## 4. Goals / Non-goals

**Goals**

- A semantic space is a named, reusable declaration: dimensions, scalar type, distance,
  and the opaque identity of the encoders that produce it.
- A field can be declared to live in a space, and the compiler checks that it can.
- A retrieval profile declares a corpus, its grain, its vector side, its lexical side, its
  filters and its projection — and is refused when any of those disagree.
- One deterministic manifest, byte-identical across processes.
- A project with no retrieval spec is unchanged, to the byte.

**Non-goals**

- **Executing anything.** No `lancedb` import, no vector query, no index build, no object
  store, no credential, no provider call. The boundary is not weakened by this RFC; §5.6
  states where it would be.
- **A LanceDB target.** Rejected in §5.5, and for a sharper reason than the proposal
  gives.
- **Computing or reading embeddings.** bloomery never sees a vector value. This is what
  keeps the float ban intact rather than merely tolerated.
- **Runtime-evidence intake** (§3). A real and separable feature.
- **Multimodal compatibility groups, `weighted` fusion, index parameters.** §8.

## 5. Design

### 5.1 A separate spec kind

```yaml
retrieval_version: 1

semantic_spaces:
  support_text:
    dimensions: 1536
    scalar: float32
    distance: cosine
    document_encoder: {family: openai, model: text-embedding-3-small, input_kind: document}
    query_encoder:    {family: openai, model: text-embedding-3-small, input_kind: query}

profiles:
  support_search:
    relation: {mart: support_search}
    grain: [chunk_id]
    vector: {field: embedding, space: support_text}
    lexical: {fields: [text]}
    fusion: {method: rrf}
    filterable: [tenant_id, document_id]
    return: [chunk_id, document_id, text]
```

Its own kind rather than keys added to `entity_model` — the proposal's recommendation, and
the right one for a reason it does not give: `spec_version: 1` is a promise that a document
which loads keeps loading, and every optional key added to it is a key every future reader
of every entity model has to know about. A separate kind is invisible to a project that
does not use it, versions on its own clock, and can be refused wholesale by a target that
cannot serve it.

The encoder identities are **opaque strings compared for equality**. bloomery does not
know what `text-embedding-3-small` is, cannot verify it exists, and must never look it up
— a compile that consulted a provider would read the network, which RFC 0003 forbids
outright. What the identity buys is the comparison in R4: two things claiming the same
space must name the same producer.

### 5.2 The type-system cost, measured

The field has to carry its dimension, or R1 has nothing to check against:

```yaml
fields:
  embedding: {type: "vector(float32, 1536)"}
```

That is a new `LogicalType` member, and the honest blast radius is:

| Site | What changes |
|---|---|
| `typing/types.py` | an eighth union member; `TYPE_STRING_PATTERN` grows an alternative |
| `parse_type` / `render_type` | parse and spell the new form |
| `assignable` | a vector is assignable to nothing and from nothing |
| the transform whitelist | every transform's `input_domain` — a vector accepts **none** |
| every `DialectPort.physical_type` | three ports, three spellings, and a refusal where a dialect has none |
| `spec/common.py` | the type pattern the entity grammar validates against |

"A vector accepts no transform" is the design's cheapest correct default and should stay
that way until something needs otherwise: a transform chain over an embedding is a
different feature, and admitting one by accident would put float arithmetic inside a
lowered expression, which is precisely what the ban exists to stop.

This cost is the strongest argument for answering §1's question *before* building
anything. It is not a bolt-on.

### 5.3 Guardrails

The refusals are the feature. Ten in the source proposal; they collapse to six that are
decidable and distinct, and the collapsing matters — a guardrail nobody can state crisply
is one nobody maintains.

| # | Refusal | Because |
|---|---|---|
| G1 | field dimensions ≠ space dimensions | the arithmetic cannot run; the cheapest possible catch |
| G2 | field scalar ≠ space scalar | a float32 corpus scored against a float16 query is a silently different space |
| G3 | a profile's vector field is not a vector type | "any array will do" is how the mixed-model corpus happens |
| G4 | field's declared producer ≠ its space's producer | dimensions agreeing is not spaces agreeing (R4) |
| G5 | profile grain ≠ corpus relation key | one vector per retrievable item, or the corpus is not a corpus |
| G6 | a filterable / returned field is absent from the corpus relation | the query cannot be served, and finding out at run time is the failure mode this project exists to move earlier |

G5 is the one that most resembles bloomery's existing work: it is `GrainViolation`'s
argument in a different domain. A mart at document grain carrying chunk embeddings has
either duplicated a vector or collapsed several, and both make top-k meaningless. Strict
key equality against the corpus relation, the same rule RFC 0010 D2 applies to measures —
and when RFC 0037's grain vocabulary lands, both can be restated on it at once.

The proposal's R7 (returned fields must not change grain) folds into G5: a projection that
multiplies rows *is* a grain change, and refusing it needs no second rule. Its R9 (hybrid
needs both sides) is a schema requirement rather than a guardrail — `fusion:` is
meaningless without both, so the grammar makes it unrepresentable instead of refusing it
later. Its R10 (searchable ≠ filterable) is a *design* rule, honoured by requiring both
declarations, not a check that can fire.

**Fusion is `rrf` only.** Reciprocal rank fusion combines ranks, so it needs no shared
scale between a BM25 score and a cosine similarity; `weighted` needs a normalization
contract nobody can state portably, and a weight without one is a number that means
something different on every engine.

### 5.4 The manifest

One artifact, `retrieval_manifest.json`, sorted keys, deterministic, `ArtifactKind.MODEL`
— a semantic surface, exactly as the MetricFlow manifest is. It carries the resolved
profile: the relation under the naming policy, the grain, the vector field with its space
fully inlined (dimensions, scalar, distance, both encoder identities), the lexical fields,
the fusion method, the filters and the projection.

Inlined rather than referenced, because the consumer is a runtime that has no access to
the spec tree: a manifest naming `space: support_text` and nothing else would make the
reader go and find a file bloomery did not emit.

### 5.5 A target, and why — against the proposal

The proposal argues at length that `Target.LANCEDB` should not exist, which is right, and
then concludes that retrieval should not be a target at all, which does not follow.

`Target.METRICFLOW` emits one JSON manifest, no models, and nothing else. A retrieval
manifest is the same shape, and the argument that a target must be "a concrete artifact
ecosystem such as SQLMesh, dbt or Cube" stopped being true when that member landed.

The genuine difference is that `metricflow` names a consumer and `retrieval` names an
artifact — no framework reads it. That is a real asymmetry in the enum and the reason D6
is graded `ASSUMED` rather than locked. What settles it against the alternative is the
alternative's cost: emitting the manifest *alongside* the SQLMesh artifacts would make a
project's retrieval contract depend on which analytical framework it happens to compile
for, so a team on dbt would get a different retrieval story from a team on SQLMesh for
reasons that have nothing to do with retrieval.

A Lance-oriented emitter, if it is ever wanted, is `register_emitter` — the extension seam
that already accepts an out-of-tree `TargetEmitter` (RFC 0008 D8). It never needs to be in
core, and it should not be until it has an artifact contract someone has run.

### 5.6 Where the boundary would break

Stated so that a future reader can tell a feature from an erosion. This RFC's line holds
because nothing in it reads a vector, a catalog, or a provider. It would break at:

- computing an embedding, or calling a provider to validate a model name;
- reading a Lance table's schema to check a column;
- emitting an index build that bloomery then runs;
- anything that makes compilation depend on which vector store is reachable.

The first is the tempting one: verifying that `text-embedding-3-small` exists would catch
a typo, and would make the compiler a network client and its output a function of the day.
The typo is caught by G4 instead, comparing two declarations to each other.

## 6. Tests

- **Guardrails:** one refusal test per G1–G6, each on a spec that is otherwise valid, so
  what fails is the rule under test.
- **Determinism:** the manifest through the existing cross-process, cross-`PYTHONHASHSEED`
  guard, which is where an unsorted space or profile collection would surface.
- **The unchanged claim, as a test:** the whole fixture corpus emits byte-identically with
  the feature present and unused. This is the acceptance criterion most likely to be
  asserted in prose and never run.
- **Type-system reach:** a vector column refused by every transform, and a
  `physical_type` per shipped dialect — the three ports are where "we added a type" turns
  into "we added a type to three renderers".
- **Not tested:** that any runtime consumes the manifest correctly. bloomery cannot make
  that claim about a consumer it does not ship, and an example that imports LanceDB is a
  dev-only demonstration (§12 P2), never evidence.

## 7. Docs

A concepts page distinguishing three things a reader will otherwise conflate: the **Lance
format**, the **LanceDB runtime**, and bloomery's **logical retrieval semantics**, which
name neither. Plus the spec-schema reference for the new kind, and the guardrail messages
in the errors reference.

## 8. Out of scope

- **Runtime-evidence intake** — the null-rate and freshness checks of the proposal's
  quality section. bloomery has no surface for measured input (§3) and building one is a
  general feature, not a retrieval one.
- **Multimodal compatibility groups.** The cross-modal case (a text query against an image
  corpus in one CLIP space) needs spaces to be *compatible* rather than equal, which is a
  third relation between spaces. Named here so the v1 grammar does not make it
  impossible — a space is a record, and a `compatibility_group` is a field it can gain.
- **`weighted` fusion, ANN parameters, index DDL, storage URIs.** Physical deployment.
- **A Lance-compatible physical emitter** (the proposal's Phase 3). It is `register_emitter`
  and it is somebody's downstream package until it has a contract that has been run.
- **`Target.LANCEDB`.** §5.5.

## 9. Risks

- **The type-system change is the whole cost and it is easy to under-price.** §5.2 lists
  six sites; the transform domains and the three `physical_type` implementations are the
  ones that get discovered late, because they are where a new logical type stops being a
  dataclass and starts being three dialects' problem.
- **The manifest's consumer does not exist.** Every other artifact bloomery emits is read
  by a framework that already exists and can reject it. This one is read by whatever the
  user writes, so nothing external validates the contract — the failure mode is a manifest
  that is deterministic, well-formed and subtly unusable, discovered by the first
  integrator. Mitigated only by shipping that integrator as an example (§12 P2), which is
  a weaker check than `dbt parse` and should be described as such.
- **Scope gravity.** Every item in §8 has an obvious next step, and each one moves toward
  being a vector-database toolchain. §5.6 exists to make that visible rather than to
  prevent it.
- **The domain question gets answered by accident.** Building P1 *is* answering §1 yes.
  If the maintainer is undecided, the correct action is to leave this RFC in Draft, not to
  start on the small part.

## 10. Unresolved questions

- Whether a vector field belongs on an **entity** or only on a **mart**. Only marts are
  retrieval corpora in practice, and confining it there keeps the new type out of the
  mapping and transform paths entirely — which is most of §5.2's cost. Against: an
  embedding produced by a step is an entity column before it is a mart column, and a type
  that cannot be declared where it is produced is a type declared twice.
- Whether `distance` belongs to the **space** or the **profile**. The space is a property
  of the model; the metric is a property of how it is served, and the same space is
  legitimately served under different metrics. Putting it on the space is the safer
  default and the easier one to relax later.
- What a **spec-version bump** means for a kind nobody has adopted yet. The stability
  promise is written for kinds in use; `retrieval_version: 1` starts with no users, and
  saying so before the first release is cheaper than discovering the promise applies.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Retrieval semantics ship as their own spec kind (`retrieval_version: 1`), never as optional keys on `entity_model`. `spec_version: 1` promises that a document which loads keeps loading; every optional key added there is one every future reader must know. A separate kind is invisible to projects that do not use it and versions on its own clock. |
| 2 | `LOCKED` | bloomery never computes, reads, or validates an embedding value, and never resolves a model identity against a provider. Encoder identities are opaque strings compared for equality (G4). A compile that consulted a provider would read the network — the invariant, not a preference. |
| 3 | `LOCKED` | A vector's scalar type is a **type name** and its dimension an **int**; no float value enters the IR. This does not weaken the float ban and does not need an exemption from it — stated because a reader stops at the word `float32` otherwise. |
| 4 | `LOCKED` | A declared vector dimension requires a new `LogicalType` member. Neither of the proposal's two options avoids it: the union has no array type either. §5.2's six sites are the cost, and a vector accepts **no** transform — admitting one would put float arithmetic in a lowered expression. |
| 5 | `LOCKED` | Fusion is `rrf` only in v1. `weighted` needs a score-normalization contract that cannot be stated portably, and a weight without one means something different on every engine. |
| 6 | `ASSUMED` | The manifest is emitted by a **target**, not alongside another target's artifacts. `Target.METRICFLOW` set the precedent for a manifest-only target; the asymmetry is that `retrieval` names an artifact rather than a consumer, which is why this is not locked. The alternative loses because it would make a project's retrieval contract depend on which analytical framework it compiles for. |
| 7 | `ASSUMED` | The manifest inlines each profile's space rather than referencing it by name. Its reader is a runtime with no access to the spec tree. |
| 8 | `ASSUMED` | Retrieval grain is strict key equality against the corpus relation (G5), the rule RFC 0010 D2 already applies to measures. Restated on RFC 0037's vocabulary when that lands, rather than waiting for it. |
| 9 | `ASSUMED` | The proposal's R7 folds into G5, R9 becomes a grammar requirement, and R10 is a design rule rather than a check. Six statable guardrails beat ten overlapping ones. |
| 10 | `LOCKED` | A Lance-oriented emitter is `register_emitter` (RFC 0008 D8), out of tree, and stays there until it has an artifact contract someone has run. No `Target.LANCEDB`. |
| 11 | `OPEN` | Entity-level vector fields, or mart-level only. §10 states both sides; confining to marts avoids most of §5.2's cost and makes a step-produced embedding awkward. |
| 12 | `OPEN` | Whether `distance` is a property of the space or of the profile. §10 states the case for the space. |
| 13 | `ASSUMED` | Runtime-evidence intake is excluded (§8). The proposal's quality rules describe a surface that does not exist, and building it is a general feature that would apply to every column. |

## 12. Phasing

**P0 is not a phase, it is a gate.** §1's question is answered by a person, and building P1
answers it yes by default.

1. **P1 — the type, the kind, the guardrails.** `LogicalType` grows a member (§5.2), the
   spec kind loads, G1–G6 refuse. No manifest yet: the refusals are the feature, and they
   are worth having before anything is emitted.
2. **P2 — the manifest and one example.** The target, the artifact, the determinism guard,
   and `examples/retrieval/` compiling a document-chunk corpus. A dev-only script showing a
   runtime consuming it may live beside the example; it is a demonstration, not a test, and
   the dependency stays optional.
3. **P3 — a second backend, before the grammar is called stable.** The semantics are
   claimed to be vendor-neutral, and exactly one demonstrated consumer is not evidence of
   that. This is the phase most likely to be skipped and the one that decides whether the
   claim was true.
