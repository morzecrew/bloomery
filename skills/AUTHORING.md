# Authoring bloomery-skills

The maintainer rules for `skills/bloomery-skills/`. The design is S-0089;
`tests/unit/test_skills.py` enforces everything below that a test can see.

## Audience

The skill is for people and agents **writing a bloomery project**: specs,
compiling, planning a change, quality rules, targets and the Python API. It
never teaches changing bloomery, and never tells a reader to read `src/`.
Contributor guidance stays in `AGENTS.md` and `.agents/skills/`.

## What ships

`skills/bloomery-skills/` holds `SKILL.md` and `references/*.md`, and nothing
else: the installer copies the directory whole into a consumer's skills
directory. Anything for maintainers (this file, `README.md`, the census) sits
in `skills/`, one level up. A stray file in the skill directory, such as an
`AGENTS.md` written by a projection, fails the test.

## The index

`SKILL.md` is a routing index, not a chapter. It holds:

- the frontmatter (`name: bloomery-skills` and a description);
- the mental model, in four sentences;
- the rule that a task needs its whole row;
- the routing table under `## Routing`: one row per task, naming every
  reference that task needs as backticked names, in reading order;
- the index under `## Index`: every reference, linked as
  `[name](references/name.md)`, grouped by area.

The index and `references/` agree in both directions, and every name in the
routing table is indexed.

## Splitting

A reference covers one job, never splits a procedure across files, and stands
alone: it answers its task without a second file for context. It runs 60 to
250 lines. A shorter one is listed under [Short references](#short-references)
with its reason; nothing may run longer.

The reference map in S-0089's design is the file set. Adding or removing a
reference amends that document in the same change that creates or deletes the
file.

## Links

- Between references: relative links that resolve and never leave
  `skills/bloomery-skills/`. Links into `skills/` or the repository break in a
  consumer's checkout.
- To the published documentation:
  `https://morzecrew.github.io/bloomery/latest/<page>/`, with `latest` and the
  trailing slash. A URL without a version segment is a 404.

## Examples

Every example is checked against the bloomery it ships with.

- A `yaml` block declares itself on its fence. ```` ```yaml spec=<kind> ````
  validates against the JSON Schema `bloomery schema --kind <kind>` exports, so
  it must be a whole document with its version key. ```` ```yaml fragment ````
  must parse and must *not* validate as a complete spec of any kind. A bare
  ```` ```yaml ```` fails.
- A `python` block parses, and imports only names in `bloomery.__all__`, from
  `bloomery` itself. Its calls are not executed; review catches a renamed
  method.
- A `bloomery …` line in a `console`, `shell`, `bash` or `sh` block names a
  command and flags the CLI accepts.

## The census

`skills/coverage.toml` has one entry per unit bloomery names: every spec kind
`bloomery schema` knows, every emit target, every CLI command and every
quality-rule kind. An entry is either `reference`, a reference that shows the
unit in a checked example, or `out_of_scope`, with the reason. The test reads
the units from bloomery itself, so a new kind, target, command or rule kind
fails until it has an entry, and so does an entry for a unit that no longer
exists. A unit named only in prose is not covered: what counts as showing each
kind of unit is stated at the top of the census.

Retrieval is out of scope until a project outside bloomery's own examples
declares a `RetrievalSpec`; that project's arrival adds the reference by
amending S-0089.

## Routing verification

Each routing-table row is checked once by behaviour, when it lands: a cold
agent gets `SKILL.md` and a task from that row, and nothing else. The row is
reached when the files the agent opened, observed from its tool calls rather
than asked of it, include every reference the row names. Order and extra
reads do not matter. A row added later adds a case here and runs it.

The cases ran on 2026-10-05 against the skill as this census landed, with
`claude -p` (claude-opus-5-5) in a directory holding only
`bloomery-skills/`, prompted to start from `SKILL.md` and write no files.

| Row | Task given | Reached |
|---|---|---|
| Start a project | Set up a new project for an online shop: lay out the specs, declare the catalog, an order entity, and map the raw orders table onto it. | yes |
| Bring in a new source | Add a second CRM's customer table to the existing customer entity, and send rows without an email to quarantine. | yes |
| Build a mart and its metrics | Build an orders mart with revenue and average order value, available to MetricFlow. | yes |
| Ship to dbt | Compile to dbt for Snowflake and check what the first deploy will change. | yes |
| Ship to SQLMesh | Compile to SQLMesh on DuckDB and check what the first deploy will change. | yes |
| Change a spec already in production | Rename the amount field on the order entity, already deployed to dbt. | yes |
| Make a refused compile go green | `bloomery compile` refuses with `FanoutDetected` on the orders mart; make it compile. | yes |
| Answer a metric request at run time | From a Python service, turn a request for revenue by month, filtered to EU customers, into SQL at run time. | yes |
| Compose two projects | The finance project needs the customer entity the core project owns. | yes |

All nine reached their row. Five agents read the row with one `cat` of every
named file rather than one read per file; that counts, since the files were
opened. Three read beyond the row: `Bring in a new source` and `Ship to dbt`
grepped `project-and-cli`, and `Make a refused compile go green` added `marts`
and `entities`.

## Short references

References under 60 lines, one per line as `` - `name` — reason ``.
