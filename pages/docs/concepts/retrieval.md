# Retrieval

A project can declare a **retrieval surface**: which relation is a corpus, which column
holds its vectors, what space those vectors live in, and what a query may filter on and
get back. That declaration compiles to one artifact, `retrieval_manifest.json`, and to a
set of refusals. It compiles to no index, no DDL, and no embedding.

A project that declares no retrieval document is untouched by everything on this page.

## Three things this is not

The word "vector" names three different layers, and conflating them is the fastest way
to misread what bloomery does here.

- **A columnar vector *file format*** — Lance, Parquet with a fixed-size-list column, a
  vendor's on-disk index. bloomery names none of them. It has no opinion on how the bytes
  of an embedding are stored, because it never writes them.
- **A vector *runtime*** — pgvector, Qdrant, LanceDB, an OpenSearch cluster. These build
  indexes, hold vectors, and answer a top-k query. bloomery does not target one, does not
  emit DDL for one, and does not read a manifest back. A vendor-oriented emitter is
  deliberately available as a registered extension target and deliberately not shipped in
  core, because a vendor member of the target enum is a compatibility promise nobody has
  run yet.
- **bloomery's *logical retrieval semantics*** — what this page is about. A space, a
  profile, a grain, a projection: the declarations that say what a query *means*, checked
  against the relations the project already builds. Physical deployment is the runtime's
  and is out of scope by design.

The manifest is the seam between the third and the second. A runtime reads it and decides
everything the manifest is silent about: which index to build, where the vectors live, how
it merges two rank lists.

## The vocabulary

### A semantic space

A space is what makes two vectors comparable. It carries a **shape** — `dimensions`,
`scalar`, `distance` — and an **identity**: the encoder that wrote the documents, and the
encoder a query is written with. Both encoders are records of three strings.

```yaml
semantic_spaces:
  chunk_text:
    dimensions: 1536
    scalar: float32
    distance: cosine
    document_encoder: {family: openai, model: text-embedding-3-small, input_kind: document}
    query_encoder: {family: openai, model: text-embedding-3-small, input_kind: query}
```

Two corpora in one space are searchable together. Two corpora in two spaces are not, even
where the dimensions happen to match, and that is the whole reason a space is a named
thing rather than a pair of numbers repeated on each profile.

### A profile

A profile is one retrievable surface over one relation the project already builds — an
entity or a mart. It names the vector side, optionally a lexical side and the fusion that
merges the two, what a query may filter on, and what it gets back.

```yaml
profiles:
  chunk_hybrid:
    relation: {entity: chunk}
    grain: [chunk_id]
    vector:
      field: embedding
      space: chunk_text
      producer: {family: openai, model: text-embedding-3-small, input_kind: document}
    lexical:
      fields: [body]
    fusion:
      method: rrf
    filterable: [document_id]
    return: [chunk_id, document_id, ordinal, body]
```

`filterable` and `return` are two declarations rather than one because searchable is not
filterable: a column a query may narrow on and a column a caller gets back are different
permissions over the same relation, and collapsing them into one list would grant both
wherever either was wanted.

Fusion is **reciprocal rank fusion and nothing else** in this version of the kind. A rank
based fusion needs no score calibration, so there is no weight to tune and no float to
compare; weighted fusion reopens only with a portable normalization contract behind it.
Any other method is refused by the grammar rather than by a guardrail.

## No float enters, at any point

A vector's scalar type is a **type name** and its dimension an **int**. `vector(float32,
1536)` is a string and a number, and that is the entire footprint of vectors in the type
system — no embedding value is parsed, stored, rendered, or compared anywhere in the
compile. The package-wide [float ban](determinism.md) takes no exemption for this feature,
and the determinism guard that proves it is the same one every other artifact goes
through.

A vector also accepts **no transform**: its input domain is empty in every transform spec.
That is not an omission waiting to be filled. Admitting a transform over a vector would
put float arithmetic inside a lowered expression, which is exactly what the ban stops. The
consequence a spec author meets is concrete: a `vector(...)` column is assignable only
from an identical vector, so no mapping chain can populate one. It arrives from a step's
declared output, which is why `examples/retrieval/` builds its corpus through a step
manifest rather than a mapping.

## Encoder identities are opaque

bloomery never resolves `text-embedding-3-small` against a provider. An encoder identity
is three strings compared for equality with three other strings.

Verifying that the model exists would catch a typo, and would also make the compiler a
network client and its output a function of the day — which is the one thing the whole
architecture is built to refuse. The typo is caught a different way: by comparing a
profile's declared `producer` against its space's `document_encoder`. Two declarations
that disagree is a refusal; a declaration nobody checks against an API is not. A future
change that looks a model name up against a provider is the erosion this rule exists to
halt, and it is locked rather than merely preferred for that reason.

## What is checked

Six refusals, all at compile time, all against the resolved project rather than the raw
documents — every one of them needs a *type* or a *key*, and neither exists until the
entity model is resolved and the marts are flattened. They are batched with every other
guardrail violation, so a profile got wrong in four ways reports four leaves rather than
costing four round trips. The messages are listed in
[Retrieval refusals](../reference/errors.md#retrieval-refusals).

The one worth drawing out is the **grain** rule, because it is the [grain
argument](wide-marts.md) in another domain: a profile's grain must be exactly the corpus
relation's key. A mart at document grain carrying chunk embeddings has either duplicated a
vector across rows or collapsed several into one, and both make top-k meaningless — the
same reason a measure may not sit at a grain coarser than the rows it sums. So it is
refused rather than emitted.

## The manifest

One artifact, from a target of its own:

```python
compile_project(project, target="retrieval", dialect="duckdb")
# → retrieval_manifest.json
```

A target of its own rather than a file alongside SQLMesh's or dbt's tree, because a
project's retrieval contract is independent of which analytical framework it compiles for.
`retrieval` is therefore the one member of the target enum naming an *artifact* rather
than a consumer — no framework reads it — and that asymmetry is the cost the choice is
paid for with.

Each profile carries its space **inlined** rather than referenced by name:

```json
{
  "profiles": {
    "chunk_hybrid": {
      "relation": {"kind": "entity", "name": "chunk",
                   "namespace": "silver", "table": "chunk"},
      "vector": {
        "field": "embedding",
        "space": {"name": "chunk_text", "dimensions": 1536, "scalar": "float32",
                  "distance": "cosine", "document_encoder": {"...": "..."}}
      }
    }
  },
  "retrieval_manifest_version": 1
}
```

The manifest is larger for it, and a space shared by several profiles is repeated once per
profile. In exchange it is readable by a consumer with no access to the spec tree — a
manifest naming `chunk_text` and nothing else would send its reader looking for a file
bloomery does not emit.

The corpus relation arrives resolved through the naming policy, as a `namespace`/`table`
pair beside the logical name. Split rather than dotted: the grammar promises nothing about
quoting, so a consumer that has to quote each part cannot recover them from one string.

## What a runtime still owes

Everything physical. Index type and parameters, where the vectors are stored, the storage
URI, how `rrf` is actually computed over two candidate lists, and what k is. The manifest
is silent about all of it, and the silence is deliberate — those are deployment decisions
a compiler has no information to make.

Nor does bloomery claim any runtime consumes the manifest correctly. It cannot: it ships
no consumer. `examples/retrieval/consume.py` reads the manifest the way a service would
and builds the SQL each profile describes, and it is a **demonstration** rather than
evidence — a dev-only script with an optional dependency, never part of the test suite.

## Where to look next

- `examples/retrieval/` — a document-chunk corpus compiled to its manifest, and the six
  refusals as six edits you can make
- [Spec schemas](../reference/spec-schemas.md) — the `RetrievalSet` grammar, field by
  field
- [Retrieval refusals](../reference/errors.md#retrieval-refusals) — what each guardrail
  says and why
