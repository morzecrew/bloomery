# Use the CLI

You want to compile a spec directory, or find out which metrics it can actually answer,
without writing a Python script. `bloomery` is that: six commands, each a thin argument
shell over one public function.

```bash
bloomery resolve specs/
```

```text
Stage: complete
Fingerprint: blm1:46f0d4f549273b5e43db9b6961ce4ef35919611d2987e1dc0f841c355840087c

Reachable (3)
  average_order_value
  gross_revenue
  order_count

Unreachable (1)
  margin  missing: cogs

Marts (1)
  order_items  grain: order_item
```

That is the command the rest exist alongside. "Did the spec I just wrote do what I
meant" is the question bloomery is best placed to answer, and the specific missing leaf
is the part a summary would throw away.

**A spec that is refused still gets an answer.** `resolve` calls
[`evaluate()`](evaluate-a-spec.md), which reports refusals rather than raising them, so a
draft mid-edit prints how far analysis got, what was reachable at that point, and every
refusal with its source path:

```text
Stage: guardrails
  analysis stopped here — every count below is a prefix, not a total

Reachable (2)
  landed_revenue
  shipping_cost

Unreachable (0)

Refusals (1)
  marts: marts.order_items.measures.shipping_cost
    GrainViolation: measure 'shipping_cost' has grain 'order' (one row per
      order), not the mart's grain 'order_item' …
```

Exit code `1` — the spec is still refused, and a pipeline branching on the code must not
start reading it as fine. **Read the stage before the counts**: at any stage but
`complete` they are a prefix, and `Unreachable (0)` there means "never computed" rather
than "nothing unreachable".

A project that wires a `steps:` document reports the unwired step here, because the CLI
passes no registry — see [Steps are the one thing the CLI cannot wire](#compiling) below.
`bloomery compile` on the same project refuses for the same reason.

## The six commands

```text
bloomery compile     <dir> [--target sqlmesh] [--dialect duckdb] [--catalog F] [--out DIR]
bloomery plan        <old-dir> <new-dir> [--catalog F] [--format table|json]
bloomery resolve     <dir> [--catalog F] [--format table|json]
bloomery explain     <dir> --metrics a,b [--by x,y] [--where JSON] [--grain month]
                           [--limit N] [--policy 'dim op value'] [--dialect duckdb]
                           [--format table|json]
bloomery schema      [--kind entity_model] [--out DIR]
bloomery fingerprint <dir> [--catalog F]
```

Every command reads files, calls the public API, and writes stdout or a directory.
Nothing is executed, nothing is cached, and there is no state anywhere.

One flag needs no command: `bloomery --version` prints the installed release and exits
`0`. It is a flag rather than a seventh command because the moment you most need it is
when something is wrong enough that you do not trust the rest of the surface.

## The spec directory

`<dir>` is a directory of `.yaml` / `.yml` documents. Each is keyed by its filename stem,
which is the prefix you will see in every error message — so a refusal reads
`metrics: metrics.revenue.agg: …` and you know which file to open.

A **catalog** is not part of a project, so it has to be told apart from the project
documents. Two ways, in order:

- `--catalog path/to/catalog.yaml` — explicit, and the only way to point several
  projects at one shared catalog.
- A file named `catalog.yaml` in the directory. Recognized by *name*, never by looking
  inside it.

If a catalog document ends up in the project by accident, `load_project` refuses it by
name and tells you to pass it separately. That is a loud failure, which is the point.

## Compiling

```bash
bloomery compile specs/ --target sqlmesh --dialect duckdb --out out/
```

```text
out/models/gold/dim_date.sql
out/models/gold/mart_order_items.sql
out/models/silver/order.sql
out/models/silver/order_item.sql
```

Without `--out`, the artifacts go to stdout as JSON — path, content, kind and checksum
for each — so you can place them yourself. `--target` takes `sqlmesh`, `cube`, `dbt`, or
the name of an emitter you registered.

**Steps are the one thing the CLI cannot wire.** A `StepRegistry` is assembled by the
caller and handed to `compile_project`; bloomery reads no step manifests from disk, by
design — that absence is what stops an authored spec from becoming a code-loading
surface. A flag would have to invent a manifest loader. A project using `steps:` compiles
through Python, and `UnknownStep` names the versions the registry does hold. `resolve`
reports that refusal too, rather than answering reachability as though the wiring were
not there.

## Planning a change

```bash
bloomery plan deployed/ proposed/
```

```text
Changes (2, 0 breaking)
  additive  field:discount    field added
  widening  field:unit_price  type widened

Backfill scope
  (none)

Downstream metrics
  gross_revenue
```

Both directories are compiled to IR and diffed. The breaking count is the number you
decide on; the rest is context. See [evolve a spec](evolve-a-spec.md) for what each
change class means.

## Explaining a request

```bash
bloomery explain specs/ --metrics gross_revenue --by ordered_month --limit 5
```

prints the SQL, then the provenance record — how each number was computed, which mart
served it, and whether a row policy applied. Filters arrive as the same JSON document
`parse_filter_json` takes:

```bash
bloomery explain specs/ --metrics gross_revenue \
  --where '{"customer_id": {"$neq": "internal"}}'
```

`--policy 'order_customer_id eq c1'` applies a row-level scoping filter — a dimension, an
operator, and a value, comma-separated for `in` / `not_in`. It is a filter, not an
identity: deciding whose policy applies is your side of the boundary.

**`explain` prints; it never runs anything.** There is no `bloomery run`, no connection
string, and no profile — not as an omission but as a decision. Execution belongs to
whatever already owns your warehouse credentials.

## Emitting the schemas

```bash
bloomery schema --out schemas/
bloomery schema --kind entity_model | jq .
```

See the [JSON Schema reference](../reference/json-schema.md) for what the documents
contain and how to point an editor at them.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | A **refusal**. Bloomery read the spec and said no, with a reason and a source path. |
| `2` | A **usage error**: a path that is not there, a flag that is not a flag. |

The line between them is *whose mistake it was*. `1` means bloomery read your spec and
said no. `2` means the invocation was wrong before any spec was opened — a path, a flag,
a `--where` document that is not JSON, a mistyped `--target`, `--dialect`, `--grain` or
`--policy`, a file that is not UTF-8 or cannot be read.

`main` **returns** these codes rather than raising, so a Python caller can read them:
`from bloomery.cli import main; code = main(["resolve", "specs/"])`. That holds for
argparse's own refusals too.

The split matters for scripting. A refusal is a *correct* outcome — the compiler did its
job — so a pipeline that retries on it will retry forever. Branch on the code:

```bash
if ! bloomery compile specs/ --out out/; then
  case $? in
    1) echo "spec refused; fix the spec" ;;
    2) echo "bad invocation" ;;
  esac
fi
```

Refusals go to stderr with their source path prepended:

```text
entity_model: entities.order.fields.total.type: String should match pattern '^(?:string|int|…
```

## Scripting with `--format json`

`plan`, `resolve` and `explain` take `--format json`, and it emits the **same values the
Python API returns** — not a summary of them. `bloomery resolve --format json` carries
each mart's measures and dimensions and the full text of every refusal even though the
table prints neither, because a script should not have to drop into Python for a field
the function already returned.

```bash
bloomery resolve specs/ --format json | jq '.unreachable[] | {name, missing, via}'
bloomery resolve specs/ --format json | jq '.refusals[] | {type, source_path}'
```

Three conversions are worth knowing. A `Decimal` becomes a string (never a float — see
[determinism](../concepts/determinism.md)). A logical type becomes the string a spec
writes it as, `decimal(12, 4)`. And a refusal — which is an exception, not a dataclass —
becomes its `type`, its `message`, and every attribute it carries, so `source_path` and
the [structured fix suggestions](../reference/errors.md) arrive as fields rather than as
prose to re-parse.

## What the CLI will never grow

No `run` and no engine connection. No config file, profile, or credentials. No
`bloomery init` or `bloomery new entity` — templates encode opinions about project layout
that this library deliberately does not hold. No watch mode and no daemon, both of which
imply state. Each of these is pinned by a test, because the pressure to add them arrives
as a small, reasonable-looking patch.
