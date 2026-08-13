# JSON Schema export

The six spec kinds are strict Pydantic models, so a JSON Schema for each is one call
away. `bloomery.schema` exposes it:

```python
from bloomery import SpecKind, all_spec_schemas, spec_json_schema

schema = spec_json_schema(SpecKind.ENTITY_MODEL)
every = all_spec_schemas()          # {SpecKind: schema}, in SpecKind order
```

or from the command line:

```bash
bloomery schema --out schemas/
```

```text
schemas/catalog.json
schemas/entity_model.json
schemas/mapping.json
schemas/marts.json
schemas/metrics.json
schemas/steps.json
```

The documents are generated from the models, so they cannot drift from the parser except
in the two places JSON Schema cannot express — both measured, both listed below.

## What it is for

Four consumers, one artifact:

- **Editor completion.** Point `yaml.schemas` at a document and you get inline
  validation and completion while authoring.
- **Form validation** in a control plane, without transcribing the models into
  TypeScript and keeping the copy in step.
- **Reference documentation** generated from the same docstrings the schema carries as
  `description`, which is what stops it going stale.
- **Constrained generation** for machine-authored specs. This is the one that changes
  something structural: a generator constrained by the schema *cannot* emit a transform
  bloomery does not have, so the refusal that would have caught it never has to fire.

## Editor setup

VS Code, with the YAML extension:

```json
{
  "yaml.schemas": {
    "https://morzecrew.github.io/bloomery/schemas/v1/entity_model.json": "**/entity_model.yaml",
    "https://morzecrew.github.io/bloomery/schemas/v1/mapping.json": "**/mapping*.yaml",
    "https://morzecrew.github.io/bloomery/schemas/v1/metrics.json": "**/metrics.yaml",
    "https://morzecrew.github.io/bloomery/schemas/v1/marts.json": "**/marts.yaml",
    "https://morzecrew.github.io/bloomery/schemas/v1/steps.json": "**/steps.yaml",
    "https://morzecrew.github.io/bloomery/schemas/v1/catalog.json": "**/catalog.yaml"
  }
}
```

Six mappings rather than one bundled document, because an editor maps a *file glob* to a
schema and a bundle cannot discriminate within itself. Each schema's `$id` is the URL
above, so `$ref`-by-URL works the same way.

## Versioning

Every schema carries a `$id` containing the document version:

```text
https://morzecrew.github.io/bloomery/schemas/v1/entity_model.json
```

That version is read off the model's own pinned `<kind>_version: Literal[1]`, not written
down a second time — so the version a consumer pins to and the version the parser accepts
are the same fact. See [stability](stability.md) for what a version bump means.

## The enum guarantee

Every closed set in a spec appears as an enumeration, never a free string: `scd`,
`cardinality`, `materialization`, `on_fail`, the quality `rule` discriminator,
`additivity`, a mart measure's `agg`, catalog `unit` and `tax_basis`, and the document
version key itself.

The transform whitelist is included, in all three authored spellings:

```yaml
transform: [to_string]                    # bare name
transform: [{parse_ts: "ISO8601"}]        # single-key mapping
transform: [{name: to_string, args: []}]  # normalized form
```

The whitelist is read from the **live** registry, so a process that called
`register_transform` exports a schema describing the transforms it actually accepts.

Two entries in that list are worth being precise about:

- **Logical types are a pattern, not an enum.** `decimal(p, s)` is parameterized, so the
  closed set is a grammar rather than a list, and the schema carries the same regex the
  parser does. Regex-constrained decoders consume it the same way.
- **Filter operators appear nowhere.** Filters are request-time, not authored — no spec
  document carries one.

## Where the schema and the parser disagree

The schema is a **pre-filter**; the parser is the authority. Every fixture in the corpus
validates against its schema, and the mutation classes JSON Schema can express — an
unknown key, a wrong scalar type, an out-of-enum value — are refused by both. The
remaining gaps are measured rather than assumed:

| Divergence | Which is stricter | Why |
|---|---|---|
| An invented transform name | Schema | Transform existence is a *typecheck*-stage refusal, so the parser accepts the document and a later stage refuses it. The schema refuses it at the door, which is the export earning its keep. |
| `reconcile.tolerance: 0.01` | Parser | The parser refuses a YAML float (a binary approximation would reach emission); JSON Schema has one numeric type and cannot tell `0.01` from `1`. `tolerance: 0` is an int and parses, so the schema cannot simply forbid numbers. |
| `agg` on a metric | Neither | A mart measure's `agg` is a closed set; an authored metric's is a free string in the model, so the schema mirrors that. An out-of-vocabulary value parses and is inert. |

Only the second is a case where a document passes the schema and fails the parser — the
direction that costs a round-trip — and it is one key.

## Determinism

Keys are sorted at every depth and `required` lists are sorted, so the same registry
produces byte-identical schemas across processes and hash seeds — checked by the same
subprocess guard that covers compiled artifacts. The six documents are checked into
`tests/golden/schema/`, so a schema change arrives as a reviewable diff rather than as a
field that quietly stopped being required.

Two things move those goldens without a bloomery edit, and both are meant to: a Pydantic
upgrade that renders a constraint differently, and a transform added to the registry.
