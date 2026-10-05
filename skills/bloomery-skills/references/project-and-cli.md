# Project layout and the CLI

Install bloomery, lay out a spec directory, run the ten commands, read exit codes, script
with `--format json`, and gate a project in CI.

## Install

Python 3.12 to 3.14. Nothing else: no database, orchestrator or credentials.

```bash
uv add bloomery
pip install bloomery
bloomery --version
```

**Pin the minor** (`bloomery>=0.4,<0.5`): below 1.0 a minor release may carry a breaking
change, always with a changelog entry. SQLMesh, dbt and Cube are not dependencies; install
them wherever the emitted artifacts run.

## The spec directory

A project is a directory of `.yaml` / `.yml` documents. Each document's kind comes from its
version key, never from its filename. The filename stem prefixes every error message, so
name files after what they hold:

```text
specs/
  catalog.yaml          # the catalog, recognised by this exact name
  entity_model.yaml     # exactly one EntityModel
  mapping_orders.yaml   # one Mapping per (source, entity)
  mapping_customers.yaml
  metrics.yaml          # at most one MetricSet
  marts.yaml            # at most one MartSet
  exposures.yaml        # optional
```

The catalog is not part of the project. The CLI finds it by `--catalog path/to/catalog.yaml`
(the way to share one catalog across projects) or by a file named exactly `catalog.yaml` in
the directory. A catalog document loaded as a project document is refused by name.

A refusal reads `metrics: metrics.revenue.agg: …`: file stem, then the path into the YAML.

## The ten commands

Every command reads files, calls one public function, and writes stdout or a directory.
Nothing is executed or cached.

| Command | Answers |
|---|---|
| `compile` | emit target artifacts (or the IR) |
| `plan` | diff two spec directories into classified changes |
| `resolve` | which metrics are reachable, what is missing for the rest |
| `check` | the CI gate: what was checked, what refused |
| `lineage` | where a node comes from, or what a change to it reaches |
| `timeline` | how one node changed across several spec directories |
| `explain` | plan one metric request; print SQL, evidence and derivation |
| `schema` | the JSON Schema for each spec kind |
| `fingerprint` | the project's deterministic IR fingerprint |
| `import` | read relationships out of an external semantic artifact |

```bash
bloomery compile specs/ --target sqlmesh --dialect duckdb --out out/
bloomery compile specs/ --target dbt --dialect postgres --catalog shared/catalog.yaml --out dbt_out/
bloomery resolve specs/
bloomery check specs/
bloomery plan deployed/ proposed/
bloomery lineage specs/ --node metric.revenue --direction upstream
bloomery timeline q1/ q2/ q3/ --node metric.revenue
bloomery explain specs/ --metrics revenue --by ordered_month --limit 5
bloomery schema --out schemas/
bloomery fingerprint specs/
bloomery import metricflow semantic_manifest.json specs/
```

Notes that change what you type:

- `compile` without `--out` prints the artifacts as JSON (path, content, kind, checksum).
  `--target` takes `sqlmesh`, `dbt`, `cube`, `metricflow` or a registered emitter name;
  `metricflow` writes one `semantic_manifest.json`.
- A SQLMesh compile writes `config.yaml` with the dialect and `model_defaults.start` from
  the catalog's `date_dimension.start_year`. It never carries a gateway: supply the
  connection through `SQLMESH__GATEWAYS__…`. dbt gets no `profiles.yml` for the same reason.
- **Steps cannot be compiled from the CLI.** A project with a `steps:` document needs a
  `StepRegistry` passed from Python; `compile`, `resolve` and `timeline` refuse it with
  `UnknownStep`.
- `explain --where` takes a JSON filter document; `--policy 'dim op value'` applies a row
  policy.

There is no `run`, no `init`, no config file, no watch mode, and there never will be.

## Reading `resolve`

```text
Stage: complete
Fingerprint: blm1:46f0…

Reachable (3)
  average_order_value
  gross_revenue
  order_count

Unreachable (1)
  margin  missing: cogs
```

**Read the stage before the counts.** A refused draft still gets an answer: `resolve`
prints how far analysis got and every refusal with its source path, and exits `1`. At any
stage but `complete` the counts are a prefix, and `Unreachable (0)` means "never computed".

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | a **refusal**: bloomery read the spec and said no, with a source path |
| `2` | a **usage error**: missing path, unknown flag, bad `--where` JSON, mistyped `--target` |
| `3` | an **internal error**: a bloomery bug; the traceback goes to stderr |

A refusal is a correct outcome, so never retry on `1`. Branch on the code:

```bash
if ! bloomery compile specs/ --out out/; then
  case $? in
    1) echo "spec refused; fix the spec" ;;
    2) echo "bad invocation" ;;
    3) echo "bloomery bug; report it" ;;
  esac
fi
```

## Scripting with `--format json`

`plan`, `resolve`, `check`, `lineage`, `timeline` and `explain` take `--format json`. It
emits the same values the Python API returns, including fields the table omits. A
`Decimal` becomes a string, a type its spec spelling, and a refusal its `type`, `message`
and attributes such as `source_path`.

```bash
bloomery resolve specs/ --format json | jq '.unreachable[] | {name, missing, via}'
bloomery resolve specs/ --format json | jq '.refusals[] | {type, source_path}'
bloomery check specs/ --format json | jq -e '.stage_reached == "complete"'
```

There is no `status` field: the verdict is the exit code.

## Checking in CI

`check` runs the same analysis as `resolve`, summarised as a gate. It needs no warehouse,
credentials, network or target, so it runs in pre-commit and on a runner with no secrets.

```yaml fragment
- name: bloomery semantic check
  run: bloomery check .
```

Only a refusal fails `check`. An unreachable metric or an open decision does not: those
describe an incomplete draft, not a wrong one. Each printed count is a surface that was
checked; there is no total.

## Editor support

`bloomery schema --out schemas/` writes one JSON Schema per kind; point the YAML language
server at them for completion and inline errors.

## Published pages

- [Installation](https://morzecrew.github.io/bloomery/latest/get-started/installation/)
- [Quickstart](https://morzecrew.github.io/bloomery/latest/get-started/quickstart/)
- [Use the CLI](https://morzecrew.github.io/bloomery/latest/how-to/use-the-cli/)
