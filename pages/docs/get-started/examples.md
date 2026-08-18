# Examples

Four runnable projects live in [`examples/`](https://github.com/morzecrew/bloomery/tree/main/examples).
Each one drives the public API end to end and executes what it claims, so nothing on this
page is a promise you have to take on trust.

Two need no setup at all. Two bring up containers and build real tables.

| Example | What it demonstrates | Infrastructure |
|---|---|---|
| `quickstart/` | The five core spec kinds: compile, then plan a metric request | none |
| `refusals/` | Six specs that look right and cannot be right | none |
| `targets/` | SQLMesh, dbt, Cube and the planner all actually running | one container |
| `lakehouse/` | Iceberg via Lakekeeper: union merge, quality rules, quarantine, a blocking audit | four containers |

Start with `quickstart/` if you want the shape of a project, `refusals/` if you want to
see the guardrails work, and `targets/` if you want proof that one spec set really does
produce one answer on three targets.

## Which one answers your question

### "What does a project look like?" — `quickstart/`

The smallest complete project: one `order` entity, one mapping, two metrics, one wide
mart. `run.py` compiles it to SQLMesh artifacts for DuckDB, then plans `revenue` by
`ordered_month` and prints the SQL alongside the deterministic explanation.

```bash
uv run python examples/quickstart/run.py
```

The [Quickstart](quickstart.md) walks through these same documents step by step.

### "Does it actually refuse things?" — `refusals/`

Six tiny projects, each one a spec that a hand-written dbt or SQL project would run
without complaint. Four of them return a silently wrong number: a dimension that keeps
history flattened into a mart, an order-grain cost duplicated per line, a `one_to_many`
flatten, EUR added to USD. The other two are unsupported rather than wrong, and name the
target that does support them.

The runner prints what each spec would have done, then the message bloomery gives instead.

```bash
cd examples/refusals && just show
```

!!! note "A case that compiles fails the run"

    The runner treats a clean compile as a failure. An example claiming a refusal that no
    longer happens would be worse than no example, so it refuses to be quietly wrong
    about its own subject.

### "Do the three targets really agree?" — `targets/`

One spec set, compiled to all three targets and each one run. SQLMesh builds the mart;
dbt builds the mart; **the two are compared row for row**. Then a planned metric request
executes against the warehouse they built, and Cube serves the same numbers over its REST
API.

The comparison is the point. "Two frameworks, one spec, one answer" is a claim about the
dialect port, and this turns it into a measurement that fails loudly if it ever stops
holding.

```bash
cd examples/targets && just demo
```

Only Cube needs a container — `dbt-duckdb` and SQLMesh run in-process.

### "What happens on a real lakehouse?" — `lakehouse/`

Eight spec documents compiled to SQLMesh, built into Apache Iceberg tables through a
[Lakekeeper](https://lakekeeper.io) REST catalog over MinIO, and queried by Trino.

It shows the two things a small project cannot: a [union merge](../how-to/merge-sources.md)
— two shops that agree about nothing, one `order_line` entity, a `_source` column, and the
*blocking* collision audit that stops the build if their key sets ever overlap — and the
[quality system](../concepts/data-quality.md), where a bad row is flagged and kept, a
duplicated key is resolved by declared policy, and a row whose cast fails is diverted to a
reject table with its raw payload rather than silently nulled.

```bash
cd examples/lakehouse && just demo
```

`just break-it` gives both shops the same key and shows the collision audit stopping the
plan; `just fix-it` puts it back.

## The seed data is deliberately dirty

`targets/` and `lakehouse/` read from `seed/` directories holding a nested JSON event
stream and CSV exports — the shapes a real bronze layer actually lands in, mess included:
padded and upper-cased emails, one segment vocabulary spelled five ways, `N/A` sitting in
a column that means "no value", prices in integer cents, an order reference carrying a
display prefix, a timestamp that reads `last tuesday`, and one customer arriving in two
loads.

None of that is cleaned by hand. Each run prints every source **before and after its
mapping**, so the declared transform chains — `enum_map`, `nullif`, `strip_prefix`,
cents-to-currency, a zone conversion — are visible as an effect on rows rather than as
YAML you take on faith.

That is the part worth studying if you are evaluating bloomery for real data: cleansing
here is *declared*, reviewed as a diff, and compiled into the same pipeline as everything
else — never written as a one-off SQL patch that no guardrail can see.

## Where next

- [Quickstart](quickstart.md) — the same project as `quickstart/`, explained document by
  document.
- [Add quality rules](../how-to/add-quality-rules.md) — the surface `lakehouse/` exercises.
- [Merge sources into one entity](../how-to/merge-sources.md) — the union `lakehouse/`
  builds.
- [Guardrails](../concepts/guardrails.md) — why every case in `refusals/` is an error
  rather than a warning.
