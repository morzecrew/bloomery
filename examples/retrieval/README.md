# retrieval/

A document-chunk corpus compiled to its retrieval manifest. No containers, no
provider account, no embeddings: everything here is decided at compile time.

```bash
uv run python examples/retrieval/run.py
```

## What the specs declare

| File | Spec kind | What it declares |
|---|---|---|
| `entity_model.yaml` | EntityModel | The `document` entity: key, typed fields |
| `mapping_documents.yaml` | Mapping | How the `cms__documents` bronze source becomes `document` |
| `steps.yaml` | StepSet | The wiring for `chunk_and_embed@1` — inputs, outputs, parameters, seed |
| `marts.yaml` | MartSet | One wide mart at chunk grain, with a `published` date role |
| `retrieval.yaml` | RetrievalSet | One semantic space and two profiles over the corpus |
| `step_manifests/chunk_and_embed.yaml` | StepManifest (data) | The step's contract, including the `vector(float32, 1536)` column |

The `chunk` entity is in no entity model. It is produced by the step, and its
columns — including the embedding — are declared by the step's manifest, which
`run.py` hands to the compiler as a `StepRegistry`. That is the only route a
vector column can take: **a vector is assignable only from an identical vector
and is produced by no transform**, so no mapping chain can populate one.

## What the manifest carries

`out/retrieval_manifest.json` holds every profile with its semantic space
**inlined** rather than referenced by name — dimensions, scalar, distance, and
the document and query encoder identities, repeated on each profile that claims
the space. The consumer is a runtime with no access to this spec tree, so a
manifest naming `chunk_text` and nothing else would send its reader looking for a
file bloomery does not emit.

Each profile also carries the corpus relation resolved through the naming policy
(`silver.chunk`, `gold.mart_chunks`), the vector field, the lexical side and
fusion method where there is one, the filterable columns and the projection.

An encoder is three opaque strings. Nothing in the compile computes an embedding,
reads one, or asks a provider whether a model exists — and there is no float
anywhere in the grammar: a space declares a *shape* and an *identity*, fusion is
rank-based, and RRF needs no weight to tune.

## Only the retrieval target

Compiling these specs to SQLMesh refuses, and the refusal is the boundary rather
than a gap:

```
dialect 'duckdb' has no physical type for vector(float32, 1536): a declared
vector is not a column this port emits DDL for.
```

The relation holding the vectors is written by the platform's step. What bloomery
contributes is the contract for querying it — which is why the retrieval manifest
is its own target rather than a file inside another framework's tree: a project's
retrieval contract does not depend on which analytical framework it compiles for.

## What the guardrails refuse

Six refusals fire against these specs if you break them, all at compile time. Try
editing `retrieval.yaml`:

| Edit | Refusal |
|---|---|
| `dimensions: 768` in the space | the field's 1536 dimensions differ from the space's |
| `scalar: float16` in the space | a float32 corpus scored against a float16 query is a silently different space |
| `field: body` on a profile | the field is declared `string` rather than a vector |
| a different `model:` in a profile's `producer` | dimensions agreeing is not spaces agreeing |
| `grain: [document_id]` on a profile | the corpus relation's key is `chunk_id` — one vector per retrievable item |
| `return: [author]` on a profile | the corpus relation carries no such column |

Each names the profile, what it declared, what the corpus actually has, and a
fix. `examples/refusals/` is the same idea for the analytical side.

## consume.py

A **demonstration**, not a test: it reads the emitted manifest the way a retrieval
service would, builds the top-k SQL each profile describes, and — if duckdb is
installed — asks duckdb to prepare it against a table shaped like the corpus.
Nothing is executed; there is no corpus and no query vector.

```bash
uv run python examples/retrieval/consume.py
```

Which index to build, where to put the vectors, how to merge two rank lists: all
of that is the runtime's, and the manifest is deliberately silent about it.
