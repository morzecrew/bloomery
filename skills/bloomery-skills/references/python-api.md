# Python API

Load, compile and analyse a project from Python, and extend bloomery with a transform or
a target. Everything in `bloomery.__all__` is importable from `bloomery` itself; import
those names from the root. Two families live one level down and are imported from there:
the planner's request parsers (`parse_filter_json`, `parse_page_json`, `KNOWN_UNSUPPORTED`)
in `bloomery.planner`, and the error leaves (`UnsupportedFilter` and every other subclass of
`BloomeryError`) in `bloomery.errors`. The library is pure:
strings in, values out. It reads no file, opens no connection and runs nothing. The CLI is
a thin shell over exactly these functions and is the only part that touches a filesystem.

## Load

Every function takes text you read. `load_project` takes a mapping of document name to
YAML text. The name prefixes every error's source path, so use the filename stem. Read
`.yaml` and `.yml` alike, as the CLI does, and load the catalog on its own:

```python
from pathlib import Path

from bloomery import load_catalog, load_project

specs = Path("specs")
documents = sorted(path for path in specs.iterdir() if path.suffix in {".yaml", ".yml"})
sources = {path.stem: path.read_text(encoding="utf-8") for path in documents if path.stem != "catalog"}
project = load_project(sources)
catalog_path = next(path for path in documents if path.stem == "catalog")
catalog = load_catalog(catalog_path.read_text(encoding="utf-8"))
```

Each document identifies its kind by its version key. Every failure across every document
is batched into one `SpecParseError`; its `collected` holds them individually.
`Project`, `Catalog` and `ProjectIR` are **handles**: pass them back, never read their fields.

## Compile

```python
from pathlib import Path

from bloomery import Target, compile_project

artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
for artifact in artifacts:
    destination = Path("build") / artifact.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(artifact.content)
```

| Argument | Meaning |
|---|---|
| `target` | `Target.SQLMESH`, `DBT`, `METRICFLOW`, `CUBE`, or a registered emitter's name |
| `dialect` | `"bigquery"`, `"databricks"`, `"duckdb"`, `"postgres"`, `"redshift"`, `"snowflake"` or `"trino"`; shapes SQL, never which artifacts exist |
| `naming` | a `NamingPolicy`; default `DefaultNaming()` gives `silver.<entity>`, `gold.mart_<name>` |
| `catalog` | the `Catalog` the specs read against |
| `steps` | the `StepRegistry` for a `steps:` document; refused without one |
| `upstream` | `{alias: ProjectIR}` for imports from another project |

Each `EmittedArtifact` carries `path`, `content`, `kind` and `checksum`. Same specs in,
byte-identical artifacts out. Write into a clean directory.

## Analyse without emitting

| Call | Returns |
|---|---|
| `build_project_ir(project, catalog, *, steps=...)` | the frozen `ProjectIR`: input to `plan`, `project_fingerprint`, the planner |
| `project_fingerprint(ir)` | the `blm1:` hash stamped in every artifact; stable within a bloomery version |
| `resolve(project, catalog)` | `Resolution`: `reachable_metrics`, `unreachable_metrics`, `provenance`, order, `graph` |
| `evaluate(project, *, catalog=..., steps=...)` | `SpecEvidence`: everything knowable, refusals as values |
| `lineage(graph, root, direction, *, max_depth)` | the reachable sub-DAG; see [lineage](lineage.md) |
| `plan(old_ir, new_ir)` | the classified change set; see [plan-a-change](plan-a-change.md) |
| `timeline(history, node)` | one node across versions; see [history-and-reproduction](history-and-reproduction.md) |
| `MetricFlowPlanner(...).plan(ir, request, ...)` | SQL for a request; see [plan-a-metric-request](plan-a-metric-request.md) |

`build_project_ir` runs the same resolution, typecheck and guardrails as
`compile_project`, and a refusal there raises. Emission can still refuse afterwards for a
particular target or dialect: an unknown dialect, a pattern the dialect cannot carry, or a
construct the target cannot express.
`evaluate` **never raises for a spec refusal**; it returns what completed beside what
refused:

```python
from bloomery import Stage, evaluate

evidence = evaluate(project, catalog=catalog)
if evidence.stage_reached is not Stage.COMPLETE:
    for refusal in evidence.refusals:
        print(refusal)
for metric in evidence.unreachable:
    print(metric.name, "missing", metric.missing, "via", metric.via)
for decision in evidence.unresolved:
    print(decision.canonical, decision.gap, [option.id for option in decision.options])
```

Read `stage_reached` first: an empty tuple means "nothing found" only at `COMPLETE`, and
"never computed" before it. Treat `Stage` as open: compare against `COMPLETE` only.
`fingerprint` is `None` unless complete. See [errors-and-refusals](errors-and-refusals.md)
and [guardrails-and-evidence](guardrails-and-evidence.md).

## Schemas

```python
from bloomery import SpecKind, all_spec_schemas, spec_json_schema

metrics_schema = spec_json_schema(SpecKind.METRICS)
every_schema = all_spec_schemas()
```

The nine kinds are `CATALOG`, `ENTITY_MODEL`, `EXPORTS`, `EXPOSURES`, `IMPORTS`, `MAPPING`,
`MARTS`, `METRICS`, `STEPS`. Each
schema is generated from the parser's model, so an editor validating against it agrees
with `load_project`. `bloomery schema --kind metrics --out schemas/` writes the same.

## Errors

Every error subclasses `BloomeryError`: `str(error)` is the message, `error.source_path`
addresses the offending spec node, `error.collected` holds the members of a batch.

```python
from bloomery import BloomeryError, compile_project

try:
    compile_project(project, target="dbt", dialect="duckdb", catalog=catalog)
except BloomeryError as error:
    print(type(error).__name__, error.source_path, error)
```

Five refusals carry a structured fix: `UnknownMember.did_you_mean`,
`UnreachableAtGrain.covering_marts`, `GrainViolation.offending_measures`,
`UnknownStep.available_versions`, `UnsupportedFilter.nearest_supported`.

## Extension points

Both registries are process-global; register at import time, before any thread compiles
or plans.

- **A transform.** `register_transform(spec)` adds a `TransformSpec` (name, argument
  kinds, input type domain, output type, and a builder returning a dialect-neutral SQLGlot
  AST, never string SQL) after the built-in whitelist. A name collision raises
  `TransformRegistrationError`. Mappings then use it by name; see
  [mappings-and-transforms](mappings-and-transforms.md).
- **A target.** `register_emitter(emitter)` takes an object with a `name` and
  `emit(ir, ctx) -> tuple[EmittedArtifact, ...]`; SQL arrives dialect-neutral in the IR
  and renders through `ctx.dialect`. Its `name` becomes a valid `target=` string. A
  collision raises `EmitError`.
- **Steps.** A `StepRegistry` of `StepManifest`s is an argument, not a registration; see
  [steps-and-macros](steps-and-macros.md).

```python
from bloomery import TargetEmitter, compile_project, register_emitter


def install(emitter: TargetEmitter) -> None:
    register_emitter(emitter)  # once, at import time


install(my_emitter)  # an object with name = "lakehouse_yaml" and emit(ir, ctx)
artifacts = compile_project(project, target="lakehouse_yaml", dialect="trino")
```

## Thread safety

`MetricFlowPlanner` and `LruManifestHydrator` are safe to share across threads. Mutating a
`NamingPolicy` or registering while others compile is not promised.

## Stability

The names in `bloomery.__all__` are the public surface. Any type in a public signature is
exported from the root too, so nothing needs a deep import. A name absent from `__all__` is
internal and may change in any release, as may a handle's fields.

Documentation: [API reference](https://morzecrew.github.io/bloomery/latest/reference/api/).
