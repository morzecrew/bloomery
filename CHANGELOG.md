# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Historical dimensions can be used in marts.** A `flatten:` step onto an
  `scd: type2` entity now takes an `as_of:` anchor — a date or timestamp column of
  the mart's base — and emits a validity predicate, so each fact carries the
  dimension version that was current when the fact happened. Point-in-time
  attribution ("revenue by the segment as it was then") is expressible; without an
  anchor the flatten is still refused, and a `base:` on a historical entity still is
  too. RFC 0023 §5.3.

- The CLI's exit-code contract gained `3`: an exception no handler claims prints
  its traceback under an "internal error, please report" line instead of escaping
  raw, and a broken pipe (`bloomery schema | head`) now exits `0` quietly.

- The YAML spec loader refuses adversarial shape with the limit named: documents
  over 5,000,000 characters, nesting past 120 levels, aliases expanding a document
  past 10× its written nodes (floor: 10,000, so small documents get slack), and an
  alias inside its own anchor (a recursive value) are `SpecParseError`, never a
  `RecursionError` or memory exhaustion. Ordinary anchors and aliases are unaffected.

### Changed

- `ProjectIR.bloomery_ir_version` is **7** (was 6): `MartJoinIR` gained `as_of`, so the
  canonical IR shape moved. `plan()` refuses to diff a version 6 IR against a version 7
  one; recompile both sides with one compiler. Every project's fingerprint moves, because
  the version is part of the canonical stream — `as_of` on its own would have moved only
  the fingerprints of projects that have mart joins, which is why the version had to move
  for the rest.

- Emitted artifacts name an `scd: type2` entity's validity interval `valid_from` /
  `valid_to` on **both** targets: the SQLMesh kind clause states them explicitly
  (they were already its defaults) and dbt snapshots rename theirs from
  `dbt_valid_from` / `dbt_valid_to`. Bloomery owning the two names is what lets one
  as-of predicate serve both targets. **Migration:** a dbt project with existing
  snapshot tables must rename their `dbt_valid_from` / `dbt_valid_to` columns to
  `valid_from` / `valid_to`; dbt locates a version's interval by the configured
  names, so a table still carrying the old ones no longer matches the config that
  reads it. Rename before the next `dbt snapshot` run, on a backup.

- A `type2` entity may no longer declare a field named `valid_from` or `valid_to`
  (`ResolutionError`); the snapshot writes those, so the relation would hold two
  columns of one name. On a `type1` entity both stay legal.

### Fixed

- A metric declaring `cumulative:` is now refused at compile time
  (`UnsupportedCumulative`). It was accepted and silently compiled as a plain
  simple metric — per-period aggregation where a running total was declared. A
  spec that compiled with `cumulative:` now fails until the clause is removed.

- A `coalesce`/`nullif` literal that cannot survive the cast into its column's
  decimal type — too wide for the declared `(p, s)`, or not a number — is now
  refused at typecheck. It compiled and then failed on the engine with a
  conversion error at run time.

- The SQLMesh target now refuses `incremental_by_partition` when the first
  `partition_by` column is not a date or timestamp, instead of emitting an
  `INCREMENTAL_BY_TIME_RANGE` model whose time column is not time.

- Compiling for a registered extension dialect now checks `pattern` quality
  rules against that dialect (a regex surface, literal transport) and refuses
  what it cannot carry. Extension dialects previously had patterns rendered
  with no check at all; the shipped three dialects are unaffected.

### Removed

- The unenforced target-capability surface: `Feature`, `TargetCapabilities`,
  each emitter's `capabilities()`, and `METRICFLOW_PLANNER_CAPABILITIES`.
  Nothing consulted them, and the tables claimed features no emitter emits.
  What a target cannot express is still refused with `UnsupportedByTarget`.

## [0.2.0] - 2026-08-31

**Known limitations, stated up front.** Keep a Changelog names six section types and none
of them is "things this release still refuses", so these are here rather than under a
heading of their own — a release note that omitted them would describe a version nobody
has.

- A merged entity may not carry `quality:` rules, `dedupe:` or `quarantine:`, may not
  declare `scd: type2`, and may not record a `direct:` path. Each is refused at compile
  time with a message naming the reason. `assert:`, `references:` and `coverage:` are
  unaffected.
- **`divide` is inexact on DuckDB.** That engine has no exact decimal division — `/` is
  float division and `//` is integer division — so the division happens in binary floating
  point and the result is narrowed back to the declared decimal. PostgreSQL and Trino
  divide exactly. Prefer `{multiply: "0.01"}` to `{divide: 100}` on DuckDB, as the shipped
  examples do.

### Added

- **The unresolved-work report** — `SpecEvidence.unresolved` states every decision a spec
  leaves open: the unavailable canonical field, **which of two edits would close it**, the
  recipes the catalog declares for it, and the metrics waiting on it. Until now a metric
  blocked because nothing carries `canonical: cogs` and one blocked because a field
  carries it and no mapping produces it came back identically, and they need edits to two
  different documents. `Gap.UNLINKED` is an entity-model edit; `Gap.UNMAPPED` is a mapping
  field, and it is where a recipe id is recorded.

  `options` is what the catalog declares, in catalog order — never ranked, never scored,
  and never chosen, including where there is exactly one. Catalog order is authored
  information (recipes are ordered by reliability), so it is the one collection on this
  surface that is not sorted. An entry appears only where it names **one** edit: a
  canonical field belonging to an entity that several mappings build is left out, because
  such an entity's columns are per mapping; the metric blocked on it is still reported
  unreachable.

  `SpecEvidence.provenance` returns alongside it — direct, recipe (with the id), or native,
  per mapped field. It was computed on every `resolve()` and discarded, and it is what a
  loop reads to know what it has already decided. `bloomery resolve` prints the open
  decisions with the ids the catalog offers; `--format json` carries each recipe's alias
  slots too. Three names bind under SemVer: `OpenDecision`, `Gap`, `RecipeOption`. See
  [Close an open decision](https://morzecrew.github.io/bloomery/how-to/close-an-open-decision/).

- **`bloomery lineage`** — the lineage walk on the command line, as a deterministic edge
  list. `bloomery lineage <dir> --node metric.gross_revenue` prints the chain back to the
  source columns with the label on each edge saying how; `--direction downstream` gives
  the blast radius of a column change, and `--format json` emits the same value the Python
  call returns. A mistyped id is refused with the spelling it thinks you meant rather than
  a bare "not found", and where nothing is close it names the id kinds instead. See
  [Trace where a metric comes from](https://morzecrew.github.io/bloomery/how-to/trace-lineage/).

- **`Direction.BOTH`** — deferred from the first release because its return shape was open.
  It merges the two walks: `nodes` and `edges` are the union of what each reached, **not**
  the subgraph induced on that union. Where an ancestor of the root also feeds a descendant
  of it directly, that bypass edge is real lineage but is not the root's, and inducing
  would carry it. For a single direction the two rules coincide, so nothing about
  `UPSTREAM` or `DOWNSTREAM` changed.

- **Lineage** — `lineage(graph, root, direction)` walks the dependency graph
  `resolve()` has always built and returns the **reachable sub-DAG**: the nodes and the
  labelled edges that say where a metric comes from, or what a source column change would
  reach. `Resolution` now carries that `graph`, which it previously computed and threw
  away, keeping only its topological order — every node in dependency order with no edges,
  which could not answer the question the structure exists for.

  Five names bind under SemVer: `Graph`, `Edge`, `Lineage`, `Direction`, and `lineage`.
  `Resolution.graph` has **no default**, so any code constructing a `Resolution` by hand
  must pass it — a `Resolution` whose graph disagrees with the one its reachability came
  from is not a state worth being able to represent.

  Sub-DAG rather than paths, deliberately: a DAG's path count is exponential in its width,
  so paths make the output size unpredictable from an input the caller holds. A caller
  wanting paths enumerates them from the sub-DAG under its own budget. `max_depth` bounds
  the walk and `truncated` says when it did — a root with no lineage returns one node and
  `truncated=False`, because bounding to nothing and finding nothing are different facts.

- **The dbt target emits singular tests** — `tests/<check>.sql`, a file whose query
  returns the rows that fail. Five constructs that raised `UnsupportedByTarget` now
  compile there, and they were one missing artifact rather than five limitations: a
  **merged entity** (lifting the SQLMesh-only restriction on the union merge), a mart
  **`assert:`** clause, a **`coverage:`** check, a step output's **audits**, and the
  **ingestion-metadata** audit an entity with `dedupe:` carries. Each names its model
  through `ref()`, so dbt orders the test after what it judges, and `on_fail` maps to
  dbt's `severity` — `fail` → `error`, `flag` → `warn`. No package and no `dbt deps`:
  a singular test is a file of SQL.

  **Read the operator contract before you run it.** On dbt a check is a separate node,
  so it runs under `dbt build` and **not** under `dbt run` — a project built with
  `dbt run` materializes its models with every bloomery check unevaluated. And
  `--warn-error` promotes a flagging check into a build failure. Both sentences are on
  the [dbt page](https://morzecrew.github.io/bloomery/how-to/emit-dbt/) **and in the
  emitted `dbt_project.yml`**, because the person who runs a generated project need not
  be the person who compiled it. A reader who has one sentence and not the other has the
  wrong model of the target. This is the one place
  bloomery's three-value disposition model does not survive intact to a target.

  Still refused there, each for a reason of its own: `quarantine:` and `reconcile:` need
  *models* rather than tests, and Tier 3 Python steps need an adapter bloomery does not
  ship a dialect for. dbt does not reach parity with SQLMesh, and this did not change
  that — what it closed was a gap in bloomery's emitter, not one in dbt.

- **Union merge** — several mappings may target one entity, and it is emitted as a
  `UNION ALL` of one projection per source in lexicographic order of source relation. No
  new syntax: two mappings name the same `target:`. Covers one shared key space with
  disjoint key sets — two shops on one platform, a region-sharded table, a post-migration
  merge. See [Merge sources into one entity](https://morzecrew.github.io/bloomery/how-to/merge-sources/).
- A `_source` provenance column on merged entities, carrying the relation each row came
  from, and a generated **blocking** `<entity>_source_collision` audit that stops the run
  when one key appears in more than one source. Disjointness is the one condition of a
  merge that compilation cannot establish.

- `bloomery.transforms.neutral_type(logical) -> exp.DataType` — the dialect-neutral
  SQLGlot type for a logical type, which `bloomery.ir.generic_type` now delegates to. A
  transform builder needs it and sits below `ir`, so the mapping has one home instead of
  two that can disagree.
- `TransformSpec.types` — a transform declaring it is passed `input_type=`, the logical
  type entering its step. The `Builder` signature is unchanged, so existing registered
  extension builders keep working.

### Changed

- **A mapping document has a name, and field provenance uses it.** `Mapping.document` is
  the name the document was loaded under — already the key that orders `Project.mappings`
  and already the prefix on that document's refusals, and until now discarded. It is set
  by the loader and is not part of the mapping vocabulary: a document declaring
  `document:` is refused rather than overwritten, and the schema `bloomery schema` exports
  is unchanged, because its audience is a spec author and this field is not theirs to
  write.

  `FieldProvenance` gains `mapping` and now carries **one entry per
  `(entity, field, mapping)`**. Where several mappings build one entity (a merged entity)
  and implement one field differently, each says so in its own entry; previously the
  collection keyed on the field alone and reported the last mapping in document order, so
  the others were not representable and the entry looked identical to a single-mapping
  one. Across the fixture corpus this recovers 4 facts that could not be stated. An entity
  built by one mapping reports the same fields it always did, each now naming that
  document. `FieldProvenance.mapping` binds under SemVer on the top-level surface;
  `Mapping.document` binds on `bloomery.spec`, where `Mapping` is exported.

  **`SpecEvidence.unresolved` is unchanged.** It still omits an open decision whose entity
  is built by more than one mapping. The identity it was waiting on now exists; what
  remains is what a worklist entry means when any one of N documents could close the gap,
  which is a decision about that report's promise rather than about names. See
  [Close an open decision](https://morzecrew.github.io/bloomery/how-to/close-an-open-decision/).


- **MetricFlow moves to 0.212**, and the emitted MetricFlow manifest changes with it:
  `minor_version` reads `"212"` where it read `"211"`. That field is part of every emitted
  manifest, so the artifact bytes move for every project even where nothing else did —
  and the hydration cache key carries the MetricFlow version (RFC 0014 D2), so the first
  planning call after upgrading is a miss by construction rather than a stale hit. No
  emitted SQL and no output-column order changed. The dependency stays pinned to one
  minor (`==0.212.*`): 0.212 renamed the output-column-order parameter with no overlap,
  so a range spanning 0.211 and 0.212 would admit a version the planner cannot call.
- **`_source` is a reserved member name**, unconditionally — a field, dimension or role
  may not be called `_source` even in a project that merges nothing, because a name that
  is legal until a second mapping arrives is a trap laid for the change that adds one.
  **This can stop a `spec_version: 1` document loading**: an entity model that already
  declares a field, dimension or role called `_source` is now refused, and the fix is to
  rename it — the error names the column bloomery generates under that name. `spec_version`
  stays at 1, which is the one exception the
  [stability reference](https://morzecrew.github.io/bloomery/reference/stability/) allows
  and bounds: a reserved name can refuse a document but never reinterpret one. This is the
  first reserved name added since a release, and the exception was written down with it.
- **Two artifacts at one path are refused on dbt, as they already were on SQLMesh.**
  An audit's name comes from author-chosen parts — a mart `a` asserting `b_c` and a mart
  `a_b` asserting `c` both lower to `a_b_c` — and neither declaration is wrong on its
  own, only the pair. SQLMesh has refused this since RFC 0017; the dbt emitter could not,
  because until now it wrote no audit artifacts to collide. **A project in that shape
  stops compiling for dbt** and the error names the path, which is the point: it
  previously emitted both files and left whichever was written last, so a declared
  quality gate silently did not exist. Rename one of the two.
- The dbt `reconcile:` refusal no longer claims dbt has no non-blocking test — a
  singular test carrying `severity='warn'` is exactly one. The refusal stands on the
  half of its argument that survives: bloomery writes no comparison model for dbt, and
  the audit has nothing to read without one. The message says so.
- `emit/steps.py`'s shared audit producers return a body rather than a finished SQLMesh
  artifact, and each target supplies its own envelope. Internal, but it is what made one
  audit body reachable from two targets instead of one.
- `EntityIR.source` is now `EntityIR.sources`, a tuple. `bloomery_ir_version` moves 5 → 6,
  so every fingerprint changes and `plan()` refuses to diff a v5 IR against a v6 one.
  Emitted SQL for single-source entities is unchanged; only the fingerprint header moves.

- **Two names leave the public surface, one of them a `Protocol`.**
  `bloomery.dialects.registered_dialects()` enumerated the process-global dialect registry.
  Nothing inside bloomery ever called it — a compile that read the registry would not be a
  pure function of its specs (RFC 0016 D56) — and D56's escape hatch does not need it: a
  caller that registered a port already holds it, so
  `unsupported_dialects(pattern, dialects=(*shipped, MyDialect()))` says the same thing
  more precisely than merging a registry it does not control.
  `bloomery.runtime.ManifestHydrator` was a `Protocol` with one implementation, used only
  to annotate `MetricFlowPlanner`'s first parameter; that parameter now names
  `LruManifestHydrator` directly. The caching seam callers actually use is the
  `fetch_l2` hook, which is unchanged.

- **`bloomery.ir.generic_type` is gone** — it was `return neutral_type(t)` and nothing
  else. Import `bloomery.transforms.neutral_type`, which is where the map has always
  lived and what a builder declaring `types` already called. One definition had two
  spellings; now it has one.

- **`bloomery.cli.serialize` is a `json.JSONEncoder`.** `as_json_value` and
  `artifacts_as_json` are replaced by `SpecEncoder`, which the CLI dumps through.
  `--format json` output is byte-identical — lists, tuples, dicts and every `StrEnum`
  now recurse through the encoder that was going to run anyway, rather than through a
  parallel walker maintained to agree with it.

- **The purity gate is ruff configuration, not a program.** `tools/check_purity.py`
  walked every module's AST to refuse `os`, `pathlib`, a clock or a random source under
  `src/bloomery/`. Ruff's `TID251` does all of it from the `banned-api` table in
  `pyproject.toml` — including the one trick the script existed for, resolving a dotted
  name through the import that bound it, so `from datetime import datetime as dt`
  followed by `dt.now()` is caught by the entry naming `datetime.datetime.now`. Purity
  now rides `ruff check "src"`, which was always going to run. The filesystem carve-out
  for `cli/io.py` is a line-scoped `# noqa: TID251` rather than a file-scoped allowlist
  entry, which is strictly narrower: a clock call in that same file is still refused.

- **The coverage gate is three `coverage report` calls.** The per-package floor table
  (fifteen rows, thirteen of them 98 or 99) and the tool that read it are replaced by the
  global floor — raised from 80 to **98**, which is what the tree has measured for a long
  time — plus one scoped report each for the two packages that are not at it:
  `guardrails/` at 100 (RFC 0009 D9) and `steps/` at 92.

- **`bandit` and `radon` are no longer dev dependencies.** Ruff's `S` rules are
  flake8-bandit, and they find the one thing bandit found here; the thirteen
  `# nosec B701` markers on `jinja2.Template` calls were suppressing nothing (B701 only
  inspects `Environment`), so they are gone and the prose above each template still says
  why autoescaping is wrong for SQL. `radon` was a dependency and a config block that no
  gate had ever read.

- **The M4.5 MetricFlow spike is retired, write-up included.** `spikes/metricflow/*.py`
  was exploratory code no gate ran and nothing imported. Its write-up outlived it by one
  release and is gone too: every finding it recorded is now asserted by something that
  runs — the row-policy audit in `tests/support/planning.py`, the semi-additive cases in
  `tests/execution/test_planner_numbers.py`, the hydration budgets in
  `tests/bench/test_hydration.py`, the import-order gotcha as a comment in
  `bloomery.emit.metricflow`, and the pin itself in `tests/unit/test_metricflow_canary.py`.
  Its dependency tables measured 0.211 and this release ships 0.212. `git log
  --diff-filter=D -- spikes/` finds the commit and `git show` prints it back — the same
  doctrine that retires a landed RFC.

### Fixed

**These change the values your models produce.** Every item in the first group below
altered emitted SQL on at least one engine; rebuild the affected models from bronze rather than incrementally, or
one column carries two meanings with no boundary marked. Nothing announces the need —
these are port-level fixes, so the IR and `project_fingerprint` are byte-identical across
the upgrade and a `plan` reports nothing.

- **`timestamp` is zoneless UTC on every port.** `to_utc` produced a zone-*aware* value, so
  a mart's date role bucketed by the reader's session zone on DuckDB and PostgreSQL, and by
  the mapping's own zone on Trino — two rows at one instant, mapped from two shops in two
  cities, landed in different days. See
  [Dialects](https://morzecrew.github.io/bloomery/reference/dialects/) for how to find and
  restate the affected models.
- **`parse_ts` with an explicit format** stored a different instant depending on who ran
  it, on PostgreSQL: `to_timestamp(text, text)` returns `timestamptz`, attaching the
  session zone to the clock it had just parsed.
- **`regex_extract` ignored its capture group** on DuckDB and Trino, returning the whole
  match for any group index. The canonical-text round trip re-bound the argument and both
  generators then dropped it silently.
- **`divide` emitted a binary float** on PostgreSQL and Trino. It is now exact decimal
  division on both. DuckDB has no exact decimal division and is covered under Limitations.
- **Decimal arithmetic emitted a wider type than it declared** — `multiply`, `round`,
  `abs` and `coalesce` widened past the tracked `(p, s)`, differently on each engine, which
  also made the 38-digit precision cap unenforceable.
- **Transforms that did not run at all on PostgreSQL** now do: `regex_extract`,
  `strip_suffix`, `to_int` over a `bool` field and `to_bool` over an `int` field, each of
  which compiled clean and failed on the first run.
- **`coalesce` and `nullif` did not plan on Trino** over any non-`string` field: Trino does
  not coerce a literal to the column's type the way DuckDB and PostgreSQL do.
- **`json_path` on PostgreSQL** returned `json` where `variant` is `JSONB` for a nested
  path, and did not run at all for a single-key path over a `string` field.

**This one changes no emitted SQL** — it is the planner's cache, not a port.

- **`LruManifestHydrator` is safe to share across threads again.** While this release's
  rewrite of its LRU was in review, the IR reached the rebuild path through an instance
  attribute rather than an argument. Two threads calling `get()` with different specs
  could interleave between that write and its read, and the manifest built from one
  thread's IR was then cached under the other thread's key — where, since nothing evicts
  a poisoned entry, every later hit returned it. The cache is now keyed on the
  `(HydrationKey, ProjectIR)` pair, so a hydration is a function of its arguments and
  holds no state between calls. Shipped versions are unaffected: this never reached a
  release.

- **A node-id collision is no longer reported as a cycle.** Entity-field ids carry no
  kind prefix (`<entity>.<field>`), so they can collide with any other kind's: an entity
  named `metric` with a field `revenue` produces the id `metric.revenue`, and so does a
  metric named `revenue`. `build_graph` already kept both nodes and sorted them by
  `(name, kind)`, but `toposort` keyed them by name alone and collapsed the two into one.
  `len(order)` then disagreed with `len(graph.nodes)` on an acyclic graph, so the cycle
  path ran — where nothing was actually blocked, and `min()` over an empty set raised a
  bare `ValueError` out of a package whose contract is named refusals. `toposort` now
  keys by the same `(name, kind)` pair the graph sorts by, and `CircularDerivation` still
  renders names alone. `bloomery lineage` refuses such an id as ambiguous, naming the
  kinds it collided, rather than silently walking whichever node it found first.

  The same comparison lied a second way, for callers who assemble a `Graph` themselves:
  `Graph.nodes` is a plain tuple, so a node listed twice was indistinguishable from a node
  the walk never reached, and raised the identical `ValueError`. `toposort` now compares
  against the number of distinct nodes, so a repeat collapses to the one node it names.

  No project without a collision is affected: the graph, the topological order, every
  cycle message and the fingerprint are byte-identical.

- **A mapped field that binds no source path exists in the graph.** Both alias-bound
  field shapes can bind zero `from:` paths — a `sql_macro` computing from its
  `parameters` alone, which is what an omitted `from` means, and a recipe with an empty
  `requires` and an `expr`, which compiles to a constant column. The dependency graph
  took its entity-field nodes from its edges alone, so such a field had no node at all:
  it was absent from `Resolution.topo_order`, `bloomery lineage --node <entity>.<field>`
  refused it as a name the project has no node for and suggested a sibling field instead,
  and `SpecEvidence.provenance` did not report it — for a field the entity model declares
  and the emitter writes a column for. Mapped fields are now nodes whether or not
  an edge reaches them. No project in which every mapped field binds at least one path is
  affected, which is every project that does not use those two shapes: the graph, the
  topological order and the fingerprint are byte-identical.

- **An empty L2 payload is a cache miss, not a manifest.**
  `LruManifestHydrator`'s documented contract has always been that it rebuilds from the
  IR "when absent or empty", but the check read `data is None`. An injected `fetch_l2`
  answering `b""` — a cache key created and not yet filled, which is the shape an L2
  produces under a crash — therefore reached `parse_raw` and raised a pydantic
  `ValidationError` out of what the caller had every reason to treat as a cache lookup.
  Callers with no `fetch_l2`, which is the default, were never affected.

## [0.1.0] - 2026-08-15

First release. Everything bloomery does is new here, so this section is one `Added` —
`Changed`, `Deprecated`, `Removed`, `Fixed` and `Security` describe movement away from a
version somebody could have installed, and there is not one yet. They begin at 0.2.0.

From this tag the [stability promises](https://morzecrew.github.io/bloomery/reference/stability/)
bind: SemVer over the Python API, per-kind versioning over spec YAML, and emitted
artifacts explicitly **not** stable across bloomery versions.

### Added

**The compiler**

- `compile_project(project, *, target, dialect, naming=None, catalog=None, steps=EMPTY_REGISTRY)`
  — declarative specs to target artifacts as one pure function. No filesystem, no
  network, no clock, no randomness: the same specs produce byte-identical artifacts
  across machines, processes and `PYTHONHASHSEED` values.
- **Six spec document kinds**, each strict YAML that self-identifies by its version key:
  Catalog (`catalog_version`), EntityModel (`spec_version`), Mapping (`mapping_version`),
  MetricSet (`metrics_version`), MartSet (`marts_version`) and StepSet (`steps_version`).
  Unknown keys, duplicate YAML keys and grammar violations are refused, batched per
  document with a source path each. A version bloomery does not implement is refused
  rather than read as one it does.
- Deterministic intermediate representation with a `blm1:` content fingerprint
  (`build_project_ir`, `project_fingerprint`), stamped into every artifact header.
  `bloomery_ir_version` is **5**; it covers each node's field names and count, so an IR
  shape change moves every fingerprint by construction.
- A closed whitelist of 24 typed mapping transforms with a compile-time typecheck of
  every chain, decimal precision and scale tracked through arithmetic, and
  `register_transform` for vetted extensions.
- Resolution (`resolve`): cross-spec reference validation, recorded-recipe validation,
  cycle detection, and metric reachability naming the specific missing leaf.
  `UnreachableMetric.via` names the chain when a metric is blocked *through* another one.

**Guardrails**

- Fail-closed unit, tax-basis, currency, grain and additivity checks; mart fan-out and
  grain protection; `assert:` clauses lowered to target-native audits. Every violation is
  a typed error with a source path, and stages batch so a spec is fixed in one round trip.
- Two constructs that used to compile clean and could not be right are refused:
  `HistoricalFanout` for a mart flattening an `scd: type2` dimension with no validity
  predicate (each base row multiplied by that key's version count, with every declared
  cardinality still honest), and `UnsupportedByTarget` for the `convert` transform, which
  lowered to a `CONVERT_CURRENCY` call no engine defines. `convert` stays registered and
  typechecked; currency conversion needs a dated rate relation bloomery does not model.

**Data quality**

- Cleansing as spec surface: a closed rule catalogue (`coercible`, `not_null`, `range`,
  `length`, `pattern`, `in_enum`, `in_set`, `unique`, `normalize`, `charset`), entity row
  rules (`expression`, `referential`), `dedupe:`, `quarantine:`, document-level
  `reconcile:`, and cross-entity `coverage:` checks. Every rule carries an explicit
  `on_fail` — `flag`, `quarantine`, `fail` or `repair` — and rules evaluate under a
  strict three-valued discipline, so a NULL-involved comparison never fires.
- `pattern` speaks a portable regex allowlist, refused at parse with the construct named;
  `range` bounds are exact (int, decimal, or a string carrying an exact decimal or ISO
  date/timestamp); `charset` declares admissible characters as `U+` codepoints.
- One replayable `<entity>__reject` table per entity with a `reject_id` recomputable from
  the row, a replay artifact that re-runs the current mapping under the pipeline's own
  dedupe order, `retention:` and `redact:`. bloomery emits the artifact and never runs it.
- `gold.mart_data_quality` — an ordinary mart with one row per rule evaluation plus an
  accounting row per entity, so quarantine rate is a plain `MetricRequest`. Five reserved
  metrics come with it.
- Every silver model projects `_quality_flags` and `_quality_ok`; a mart over a
  rule-carrying base flattens them into a `has_quality_flags` dimension.

**Steps: referenced implementations**

- A project may wire platform-owned steps through a `steps_version: 1` document —
  `use: ref@version`, input/output bindings, parameters within the manifest's declared
  bounds, `expression` quality rules on outputs, and `canonical:` links so metrics and
  `reconcile` can read a step output. Manifests reach the compiler as a frozen
  `StepRegistry` passed to `compile_project(..., steps=…)`: bloomery reads no step files
  and has no dynamic loading path, so a spec can never name code to load.
- Three tiers emit — `sql_macro` splices into the consuming SELECT, `sql_model` emits an
  ordinary model, and `python_model` emits one generated wrapper per declared output,
  each carrying a non-optional `assert_step_contract` call. Step outputs are entities:
  a mart may reference one exactly as it would any silver entity, and `plan()` diffs them.
- `bloomery.steps.assert_step_contract` — the run-time contract, and the only bloomery
  name intended for import outside compilation. It imports nothing but `bloomery.errors`.

**The gold layer and the emitters**

- Wide marts: relationship flattening with mandatory prefixes, role-playing date
  dimensions (`ordered_month`, `shipped_month`, …), a generated `dim_date` owned by the
  catalog, and aggregate `assert:` clauses lowering to target-native audits.
- Emit targets for **SQLMesh** (models, audits, native SCD2, reject/replay, quality
  audits), **dbt** (models through `ref()`/`source()`, sources, snapshots, schema tests,
  a self-contained expression-test macro) and **Cube** (cubes and views with additivity
  metadata, ratios as calculated measures), rendering over **DuckDB**, **Trino** and
  **PostgreSQL**. `register_emitter` adds extension targets. Where a target cannot express
  a declaration it raises `UnsupportedByTarget` rather than dropping it silently.

**Request-time planning**

- `MetricFlowPlanner`: a structured `MetricRequest` becomes SQL over a wide mart plus
  typed columns, warnings, a deterministic explanation and a fingerprint — refusing
  unknown members, cross-grain requests and ambiguous dimensions instead of guessing.
  MetricFlow is embedded and render-only, never connected to a database. Bind result rows
  by `ColumnDescriptor.sql_alias`; display `name`.
- Filters are typed CNF clauses (`Predicate` / `AnyOf` — implicit AND, one level of OR),
  with `RowPolicy` for row-level scoping and `parse_filter_json` / `parse_sort_json` /
  `parse_page_json` as the Mongo-flavoured JSON front door. Unsupported constructs raise
  `UnsupportedFilter` with a stable reason code from the closed, drift-guarded set
  exported as `bloomery.planner.KNOWN_UNSUPPORTED`.
- `LruManifestHydrator` / `HydrationKey`: in-process manifest hydration keyed by spec
  fingerprint and library versions, with an optional caller-owned byte store.

**Assessing and evolving a spec**

- `evaluate(project) -> SpecEvidence` — everything knowable about a spec without touching
  data, as one value: reachable metrics, unreachable ones with the missing leaf, batched
  refusals with source paths, mart shapes, entities, fingerprint. **Refusals are the
  return value**, and analysis that completed before the refusal comes back with them.
  `InvariantViolated` and every programming error still propagate.
- `plan()` — every change between two compiled versions classified as additive, widening,
  rename, restating or breaking, with backfill scope, replay scope for the reject tables a
  change invalidates, downstream metric impact and an enforced expand/contract workflow.
- Structured fix suggestions on five refusals: `UnknownMember.did_you_mean`,
  `UnreachableAtGrain.covering_marts`, `GrainViolation.offending_measures`,
  `UnknownStep.available_versions`, `UnsupportedFilter.nearest_supported`. Always present
  — `()` or `None` when there is nothing to suggest, never absent and never fabricated.

**Surfaces**

- A total error hierarchy rooted at `BloomeryError`: every failure is typed, carries a
  source path into the offending spec node, and is documented in the errors reference.
- **A command line** — `bloomery compile|plan|resolve|explain|schema|fingerprint`, plus
  `bloomery --version`. Each command is a thin argument shell over one public function;
  `--format json` emits the same values the Python API returns. A refusal exits `1` and a
  usage error `2`, so a pipeline can tell "your spec is wrong" from "your command is
  wrong". Nothing is executed: `bloomery run` does not exist.
- **JSON Schema per spec kind** — `spec_json_schema(kind)`, `all_spec_schemas()`, and
  `bloomery schema --out DIR`. Generated from the Pydantic models so they cannot drift
  from the parser, with every closed set enumerated. Also published at
  `https://morzecrew.github.io/bloomery/schemas/v1/<kind>.json`.
- `bloomery.__all__` is **closed over its own signatures**: every type named in a public
  signature is importable from the root, enforced by a test that walks the whole surface.
  `bloomery.__version__` reports the installed release.
- Documentation: get-started, concepts, how-to guides for every target and the planner,
  full spec/transform/error/API/stability references, and a runnable `examples/quickstart/`.

[Unreleased]: https://github.com/morzecrew/bloomery/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/morzecrew/bloomery/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/morzecrew/bloomery/releases/tag/v0.1.0
