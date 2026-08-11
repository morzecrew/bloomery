# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Steps: referenced implementations (RFC 0017). A project may now wire platform-owned steps through a new `steps_version: 1` document — `use: ref@version`, input/output bindings, parameters within the manifest's declared bounds, and `expression` quality rules on outputs. Manifests reach the compiler as a frozen `StepRegistry` passed to `compile_project(..., steps=…)`; bloomery reads no step files and has no dynamic loading path, so a spec cannot name code to load. Three tiers emit: `sql_macro` splices into the consuming SELECT, `sql_model` emits an ordinary model, and `python_model` emits one generated SQLMesh Python-model wrapper *per declared output*, each carrying a non-optional `assert_step_contract` call.

- `bloomery.steps.contract.assert_step_contract` — the run-time step contract, the only bloomery module intended for import outside compilation. It imports nothing but `bloomery.errors`: every check is expressed against the dataframe protocol the step already returned, so it needs no pandas of its own.

- A step emits a blocking consistency audit per reference its manifest **declares** between sibling outputs (`references: {column: sibling}`), attached to the model holding the reference, and that model declares the sibling in `depends_on` so SQLMesh resolves it to the plan's snapshot rather than a virtual-layer view. Mutual references are refused: each one orders the two models. This is the check for the one risk one-wrapper-per-output creates — a step misdeclared as `pure` producing siblings that disagree *within a single run*, which no run-to-run gate and no contract assertion can see.

- Step outputs are entities: a mart or downstream model may reference `silver.customer` written by a step exactly as it would any silver entity, and `plan()` diffs those entities like any other. `EntityIR` gains `produced_by`, naming the step that writes the relation, so the emitter leaves its model to the step's generated wrapper.

- A step wiring may declare `canonical: {<output>: {<column>: <canonical_field>}}`, which is what lets **metrics** and **`reconcile`** read a step output — a metric resolves against canonical fields, and only mapped entity fields could previously draw that link. The link lives on the wiring rather than in the manifest, because canonical names are the authored spec's vocabulary and a manifest naming them could not be reused by a project spelling them differently. It is never inferred from a matching column name.

- Tier 1 is wired: a mapping may splice a `sql_macro` into a field, either as a field shape (`step: ref@version` with `from:` binding each accepted column to a source path) or as a `{step: ref@version}` link in a transform chain, so whitelist transforms and a macro compose on one field. A macro is referenced inline rather than wired in `steps:` — it writes no relation, and one wiring per ref would make it usable in exactly one mapping. The splice happens at lowering, so the model stays one query and column-level lineage sees through it.

- A `sql_macro` manifest declares its signature with `accepts: {column: type}`, never inferred from the body's placeholders. The body is checked against the declaration at the registry, call sites are checked against it (so the error names what the macro expects), and a chain is typechecked *around* the link — the transforms before it against what it accepts, those after it from what it produces. A polymorphic macro must pick a concrete type, the same constraint a Tier 0 transform carries through its input domain.

- Steps not wired in the `steps:` document are refused rather than silently dropped: a `sql_macro` (which belongs at its call site) and a `sql_model` with no registry body. (Per-target coverage is stated further down: dbt emits Tier 2 and refuses Tier 3; Cube is asked nothing.)

- An `expression` quality rule on a step output with `on_fail: fail` lowers to a blocking audit over the relation, attached to that output's own model so SQLMesh runs it. `flag` and `quarantine` stay compile errors: both work by rewriting the silver `SELECT` — the `_quality_flags` projection and the routing `WHERE` — and a step-produced relation has none, because its wrapper writes the rows.

- A `sql_model` body takes its parameters as sqlglot `:name` placeholders, substituted as AST literal nodes so a spec value is data wherever it lands and cannot carry SQL into the body. The declared type picks the literal: `int`/`decimal` render as numbers, `bool` as a boolean, and `string`/`date`/`timestamp` as string literals the engine compares in the column's own type. Body and parameters must name the same *resolved* set — a placeholder nothing declares, a placeholder whose parameter has neither default nor wiring, and a resolved parameter the body never mentions are each a compile error. A `variant` parameter cannot be substituted, because the three supported engines do not spell a semi-structured literal alike.

- `bloomery.typing.render_type` — the spec-layer spelling of a logical type, now public because `plan()`, the step manifest embedded in a generated wrapper, and anything reporting a type to a human must all use one spelling.

- Two rules join the closed quality catalogue (RFC 0016 D86). `{rule: normalize, form: nfc}` fires when a value is not already in Unicode NFC — the case where `café` spelled with a combining acute and `café` spelled precomposed are one value to a reader and two to every join, `unique` and dedupe. `{rule: charset, allow: [...]}` / `{rule: charset, forbid: [...]}` declares the admissible characters as `U+` codepoints and inclusive ranges (exactly one side), which is how a column says it holds no zero-width space, no bidi override, and no Cyrillic letter drawn like a Latin one. Codepoints rather than the characters themselves: every character these rules exist to catch is invisible, and a literal one in a YAML file is unreadable in review.

- Cross-entity `coverage:` checks (RFC 0016 D90) — "every customer has at least one order", declarable. A check names a declared relationship and a minimum, and lowers to an audit asserting that every row of the referenced entity has at least that many rows referencing it. `on_fail` is `fail` (blocking) or `flag` (non-blocking): the audit is attached to the *dependent* entity's model, so it cannot route a row of the referenced one, and pretending otherwise would be silent degradation. The dbt target refuses a project carrying one; Cube is not asked.

- A **Cube container tier** and the **three-way equivalence tier** (RFC 0009 D24), completing every tier RFC 0009 §5.2 names. Cube now loads the emitted schema in a real container, answers a query, and is compared against the MetricFlow-backed planner over one Postgres — with hand-written reference SQL as the third leg on every request that declares one. The equivalence corpus is smaller than §5.8's sketch of ~40 requests; the classes it covers are what buy the coverage.

- Known limitation, now written down (RFC 0009 D24): `QueryPlan.columns` carries the *requested* dimension name (`ordered_month`) while the SQL MetricFlow generates aliases it differently (`order_item__ordered_day__month`). Binding a result frame positionally works — which is what every consumer does — but binding by name finds nothing.

- A **Trino engine tier** and a **`dbt parse` e2e tier** (RFC 0009 D21/D22). Three decisions previously verified against Trino by hand are now permanent tests, including the one D75 said was impossible — the reject table materializes there, and its `reject_id` is checked against the digest computed in Python, so the engines are held to agreeing with each other rather than each with itself. `dbt parse` runs over every dbt-compilable fixture plus a Tier 2 step project, with a deliberately malformed model as its own control.

- Known limitation, now written down (RFC 0009 D22): `dbt build` on an emitted project does not work. bloomery's dbt models name their inputs by literal relation (`FROM silver.order_item`) rather than through `{{ ref(...) }}`/`{{ source(...) }}`, so dbt has no dependency edges to order them by and materializes each into the profile's target schema while the `FROM` clause names another. `dbt parse` — the tier RFC 0009 specifies — passes.

- The dbt target now emits `sql_model` steps as ordinary dbt models (RFC 0017 D52), carrying the same SELECT the SQLMesh target emits. `sql_macro` steps already worked everywhere — they are spliced into the consuming model before any emitter sees them. `python_model` steps are still refused on dbt, now for a concrete reason: dbt's Python models run on Snowflake, BigQuery and Databricks only, and none of bloomery's dialects is one of them.

- The Cube target no longer refuses a project that wires steps. Cube builds nothing — it emits cubes and views over marts and no silver model, reject table, replay statement or audit for anything — so refusing steps singled them out among every other build-side declaration it already leaves to whoever maintains the tables.

- Marts may declare aggregate `assert:` clauses (RFC 0016 D89) — `{measure, agg, by, min/max, on_fail}`, lowering to a SQLMesh audit the mart model names. This is "no month has zero revenue", declarable. They are **assertions and not quality rules**: a mart row is derived, with no source identity, no reject table and no replay, so no disposition applies to it — `on_fail` accepts `fail` (blocking) and `flag` (non-blocking) only. An assertion sees the groups that exist; a period with no rows at all is invisible to it unless the aggregate is `count`.

- The dbt target refuses a project whose marts carry assertions, rather than dropping them: its schema tests are per-column or per-model predicates with no grouped form, and a project that compiles clean while its declared gate does not exist is worse than one that refuses. Cube is not asked — it emits no audit for anything.

- Reject tables gain a `last_evaluated_at` column (RFC 0016 D88): when replay last read the row. It answers the question `last_seen` deliberately cannot — `last_seen` is the data's clock, and advancing it would keep an unresolved row alive forever under retention. This one is read by nothing, which is what makes it free to move; retention still ages unresolved rows from `last_seen` and resolved ones from `resolved_at`. A re-delivery preserves it rather than overwriting it, so a row cannot forget it was replayed because the source delivered it again.

- `on_fail: repair` (RFC 0016 D87). A rule may now name a **recipe** that rewrites the value it fired on, instead of only deciding where the row goes: `repair: {via: strip_invisible@1, fallback: quarantine}`. The recipe is a registered Tier 1 `sql_macro` — versioned, signature-declared, `runtime_lock`-pinned — because specs reference implementations and never contain them; `fallback` is required and disposes of any row the recipe did not actually fix, so a still-broken value can never land in silver marked as fixed.

- Repaired rows are recorded in a new `_quality_repairs` column, deliberately separate from `_quality_flags`: "repaired, now correct" and "currently suspect" are different facts, and `has_quality_flags` keeps meaning the second one. The column appears only on entities that carry a repair rule. `repair` is refused where there is no repairable value in hand — on `coercible` (which fires because the projection is already NULL), on `unique`, on a row rule, on a column the dedupe order reads, and twice on one column.

- A confusables *table* was considered and deliberately not built. It is versioned Unicode data, so embedding it would make a row's disposition depend on which Unicode revision bloomery happened to ship — and `charset`'s allow-list reading covers the homoglyph case more completely than any denylist, since it enumerates what a column may contain rather than guessing what it may not.

### Changed

- `bloomery_ir_version` is now `3` — `ProjectIR` gained a `steps` tuple, so every artifact's `fingerprint:` header changes and `plan()` refuses to diff a v2 IR against a v3 one. The bump moves fingerprints even for projects with no steps: the canonical encoder covers each node's field *names and count*, not merely its values, so an IR shape change is loud by construction.

- `plan()` diffs steps by `ref`: a `runtime_lock` bump, a version upgrade, a changed parameter, a new seed or rewired inputs each classify `RESTATING` and put the step's output relations in `backfill_scope`. Keyed by `ref@version` an upgrade would have read as one step removed and another added, losing the backfill exactly where it matters most. Removing a step is `BREAKING` and names the relations nothing produces afterwards.

- Planner filter vocabulary is now CNF (breaking, pre-0.1): `FilterExpr` becomes `Predicate`, filters accept one level of OR via `AnyOf` groups, `between` and `contains` are removed (compose `gte`+`lte`; write `like`/`ilike` patterns with your own wildcards), `is_null` takes exactly one bool, and `RowPolicy.as_filter()` is renamed `as_clause()`.

- Float filter values are now accepted and normalized to exact decimals at the request boundary instead of being refused; non-finite values (`NaN`/`Infinity`, in float or string form) are rejected with a typed `InvalidLiteral`.

- `bloomery_ir_version` is now `2` — the IR gained the data-quality shape, so every artifact's `fingerprint:` header changes and `plan()` refuses to diff a v1 IR against a v2 one. The bump itself rewrites only that header; the emitted SQL moves for the separate reason below.

- Every silver model now projects `_quality_flags` and `_quality_ok`. An entity with no quality rules carries the empty collection and `TRUE`, so the change is two projections rather than a behaviour change — but it moves every silver golden, every dbt model, and every fingerprint. A mart whose base entity carries rules flattens the pair into a `has_quality_flags` dimension, so "revenue excluding flagged rows" is an ordinary `MetricRequest` filter.

- An entity that declares any `quality:`/`quarantine:` surface lowers its transform chains `TRY_CAST`-shaped: a failed coercion produces a marker the implicit `coercible` rule disposes of, instead of aborting the run. Entities with no quality surface keep the shipped produce-or-raise lowering, and the implicit `coercible` rule does not exist for them — joining the quality system is per entity and explicit (`dedupe:` alone does not opt in).

- Changing a quality rule, a disposition (in either direction, `referential`'s `on_missing` included, where `unknown_member` and `flag` are distinct changes although both keep the row), or a `dedupe` block classifies as `RESTATING`. `replay_scope` is reported rather than only a backfill where quarantined rows can actually come back — the rule removed, its disposition now `flag`, or its parameters relaxed (a widened bound, a widened `in_enum`/`in_set` membership, including an `enum_map` widened only by a new spelling for an existing target). A tightening — a narrowed bound, or `quarantine → fail` — backfills and does not replay: those rows sit in the reject table and still fail the rule.

- Reserved field/dimension/role names now cover the generated data-quality and ingestion-metadata columns (`_quality_flags`, `_quality_ok`, `_load_id`, `_ingested_at`, `_source_row_id`, `has_quality_flags`) alongside `metric_time`; the refusal message names the RFC that owns each. The quality mart's five metric names are reserved in the same way.

- Postgres hosts quality-carrying entities. `TRY_CAST` renders there as a guard around `pg_input_is_valid` — Postgres' own input parser, not a regex approximation of it — so it accepts exactly what `CAST` accepts and yields NULL exactly where `CAST` would raise. Verified by executing the pipeline on postgres 16, not by reading the SQL. One deliberate narrowing: `now`, `today`, `tomorrow` and `yesterday` are refused for date and timestamp columns, because Postgres resolves them to the transaction timestamp and a cell spelling `now` would otherwise coerce to a different value on every run. Such a cell is a coercion failure the `coercible` rule quarantines, rather than a row no backfill can reproduce.

- Note that cast *semantics* still differ between engines — DuckDB coerces `'1.5'` to an int and Postgres does not — so the same spec can quarantine different rows on different engines. That is inherent to running on different engines and is not changed here.

- The reject table's two constructions — the `reject_id` SHA-256 digest and the `raw`/`key_values` JSON payloads — are now spelled by the dialect port rather than emitted as one AST, so **Trino hosts a reject table**. Both were verified by executing the emitted model against `trinodb/trino:483`, and its `reject_id` is byte-identical to the digest the other engines produce. Postgres declared support for both and had neither: its `sha256` returns `bytea`, so `reject_id` would have been bytes rather than hex — silently disagreeing across engines — and it has no positional `json_object` at all. Postgres now has correct spellings too — unreachable when this landed, and reachable since it gained a NULL-on-failure cast in the entry above.

### Removed

- `Mapping.on_unmapped_enum` (breaking, pre-0.1): a spec still carrying the key is now refused as an unknown key. Unmapped enum values become a data-quality concern — they fail the `in_enum` rule and take that rule's disposition, superseding RFC 0008 D7's never-implemented emitter convention.

### Fixed

- **Security: a Tier 1 step parameter could splice SQL into a projection.** `parameter_literal` builds an *unquoted* literal for `int`/`decimal` — the branch its own docstring called the injection boundary — and never checked the text was a number. A mapping spelling `parameters: {factor: "1 OR 1=1"}` emitted `CAST(amt * 1 OR 1 = 1 AS DECIMAL(12, 4))`. The check now lives below both SQL tiers, where the rendering happens, rather than at the call site Tier 1 was missing (RFC 0017 D53) — and it matches SQL numeric-literal *syntax* rather than parsing with `Decimal`, which accepts `1_0`, `Infinity` and `1e400`; `int` is held to integer syntax, so `"1.5"` no longer emits `1.5` (D56).

- A `coverage:` check crashed emission with a bare `StopIteration` when its referenced entity was declared but unmapped, and emitted an audit attached to no model when the dependent side was step-produced — a check that reports clean because it never runs. Both are guardrail refusals now (RFC 0016 D91).

- A chain link (`{step: ref@v}`) whose macro declared a parameter with no default left the placeholder unresolved, so `CAST(nm AS TEXT) || $factor` reached the emitted SQL of a model that compiled clean (RFC 0017 D54).

- Postgres' run-dependent datetime deny-list (D84) was defeated by a tab. It read `LOWER(BTRIM(value)) IN ('now', …)`, and `BTRIM` trims **spaces only** while Postgres' datetime scanner skips tabs, newlines and carriage returns — so `'now\t'` passed the guard and cast to the transaction timestamp. Verified on PostgreSQL 16 (RFC 0016 D93).

- `StepRegistry` accepted a key disagreeing with its manifest's identity, which silently dropped that step's canonical links and `on_fail: fail` rules; `Reconcile.on_fail` accepted `quarantine`/`repair`, neither of which means anything for an aggregate comparison; and the reconcile "known columns" message omitted the key columns the check accepts (RFC 0017 D55, RFC 0016 D92).

- `bloomery_ir_version` is now **4** — `ProjectIR` gained `coverage` and `MartIR` gained `asserts`, and the bump was missed. Fingerprints moved anyway (the encoder covers field names and count), so nothing failed; what the bump buys is `plan()` refusing to diff a coverage-carrying IR against one without, rather than both calling themselves v3.

- The declared dbt floor was `>=1.10`, which is wrong: nested generic-test `arguments` needs dbt's `require_generic_test_arguments_property` behaviour flag through 1.10.7 and only defaults on at **1.10.8**. Measured across eight installs; the floor is now `>=1.10.8,<2`.

- The emitted `schema.yml` nests generic-test arguments under `arguments:`, and the supported dbt range is declared for the first time: **`>=1.10,<2`** (RFC 0008 D22). dbt 1.10 moved test arguments there and deprecated the flat form bloomery emitted; the two are mutually exclusive rather than stylistic, measured on four real installs — flat compiles on 1.9 through 1.12 (warning from 1.10), nested is a compilation error on 1.9 and clean on everything after. The only version this costs is 1.9. `not_null` is unaffected: it takes no arguments and stays a bare name.

  The larger gap it exposed: which dbt versions the *emitted artifact* works on had never been written down. `dbt-core>=1.9` was a dev dependency — the test environment, not the product — and unbounded, so CI tested against whatever resolved that day. It is now bounded like the sqlmesh and metricflow pins already were, stated in the emitter's docstring, and pinned by a test carrying the measured matrix, so the bound and the emitted form cannot move apart.

- The emitted dbt project declared a test it never defined. `min`/`max`/`regex`/`reconcile` asserts lowered to `dbt_utils.expression_is_true` and no `packages.yml` was emitted, so `dbt compile` stopped at ``'dbt_utils' is undefined … install package dependencies with "dbt deps"`` for any project carrying one of those clauses. bloomery now emits `macros/bloomery_expression_is_true.sql` — the `dbt_utils` body minus the `column_name` branch it never used, so the semantics are unchanged — iff `schema.yml` declares the test. Defining it rather than pinning the package keeps the artifacts a pure function of the specs: a `packages.yml` would complete the project only after a network fetch (RFC 0008 D18). `dbt_project.yml` gains `macro-paths`.

- The dbt e2e tier ran `dbt parse`, and its own documentation claimed parse validates "whether a declared test is a thing dbt recognizes". It does not — parse checks the shape of a `schema.yml` entry and never resolves the macro behind the name, accepting a test called `utter_nonsense_not_a_test` in silence. That is why the tier built to catch the defect above did not catch it. Every fixture now compiles as well as parses (RFC 0008 D19).

- `dbt build` could not pass on an emitted project, and now does. Models named their inputs by literal relation (`FROM silver.order_item`), so dbt had no dependency edges to order them by *and* materialized each into the profile's target schema while the `FROM` clause said `silver`. RFC 0009 D22 recorded the two candidate fixes as alternatives; they are not — `+schema` config alone leaves ordering absent, and `ref()` alone resolves names through dbt's schema config so the naming policy stops owning the namespace. Both ship (RFC 0008 D20): `ref()` for every relation bloomery emits and `source()` for bronze, a `+schema` per model directory, and a `generate_schema_name` override returning the namespace verbatim instead of dbt's default `<target>_<custom>`. An SCD type 2 entity resolves to its snapshot, the only thing this target builds for it. The e2e tier builds every fixture, with a control on the half a green build does not visibly prove — delete the override and everything still builds, just in the wrong schemas.

  Two consequences worth knowing. A dbt model body is now a *template* rather than SQL, so anything reading it as SQL must resolve the references first. And RFC 0008 D5's port-abstraction proof no longer compares the two targets' SELECTs byte for byte, because the `FROM` clauses differ by construction; it compares them with references resolved and namespaces dropped, which still pins that no lowering is duplicated.

- An `in_enum` rule on a chain with no `enum_map` step lowered to `NOT col IN ()` — invalid SQL on every dialect, and a rule that rejects every row. Refused at compile, naming `in_set` as the way to state members directly.

- `in_enum` quarantined **every correctly-mapped row** when the transform chain applied any step after its `enum_map` (`{enum_map: [paid, paid]}` then `upper` compared `PAID` against a set spelling `paid`). The chain is now refused at compile naming the offending step; a further `enum_map` may still follow.

- The implicit `coercible` rule fired on values a transform nulls *deliberately*, quarantining rows for obeying their own mapping — `{nullif: 'N/A'}` says the sentinel means missing, and the marker cannot tell that from a failed cast. Transforms now declare `nullifies` (`nullif`, `json_path`, `split_part`, `regex_extract`); the implicit rule is skipped on such a chain and an authored `coercible` there is refused.

- The quarantine-replay `MERGE` compared row constructors, which order NULL as the largest value — the inverse of the `DESC NULLS LAST` the pipeline ranks by. With a nullable `dedupe.field`/`tie_break`, a candidate that ranked first was not merged (and its reject row was stamped `(superseded)` anyway), and a candidate with a NULL sort value evicted a non-null incumbent. The comparison is now the per-column NULL-aware form the dedupe order actually means.

- A recipe's `direct:` path never reached the reject table's `raw` payload, so every replayed row rebuilt its `<field>__direct` shadow from an absent key — NULL for all of them, fed to the reconcile audit that exists to compare it. The path is now a recorded source field, and redacting it is refused.

- A `reconcile` side naming a declared-but-unmapped entity passed the guardrail stage and failed later as an unbatched `EmitError`; a side repeating a `by` column emitted two columns of one name and an ambiguous join; two `referential` rules through one relationship emitted two joins under one alias. All three are now batched compile-time refusals.

- An authored mart named `data_quality` was silently replaced by the synthesized quality mart (SQLMesh emitted that mart twice at one path; Cube wrote two different files to one). The name is now reserved unconditionally, like the five quality metric names.

- A `range` rule with ISO date/timestamp bounds (RFC 0016 D57) had every bound change reported as undecidable, because the replay decision parsed bounds as `Decimal` only — so a pure temporal *tightening* scheduled a replay that can free nothing, and under `quarantine → fail` fed the replay runner rows that trip the new blocking audit. Bounds now parse in their own carrier and compare when like-typed; an aware/naive pair stays undecidable rather than guessed.

- `plan()` reported no `replay_scope` for a rule change that *swaps* rather than widens — `in_set ["a"] → ["b"]`, or `range 0..10 → 5..20`. Neither is a relaxation by the superset/interval reading, but both admit values the old rule rejected, so rows quarantined on `b` (or at 15) had become admissible and stayed in the reject table with nothing naming them. Replay now asks whether the new parameters admit anything the old ones rejected.

- `plan()` classified removing a `quarantine:` block as ADDITIVE "policy only", although it stops the `<entity>__reject` model being emitted and discards every unresolved row in it — now BREAKING, with the replay scope beside it. Separately, narrowing an `in_set` that contains the literal `"false"` reported as a *relaxation*, because the rule's `numeric_*` type markers carry `"true"`/`"false"` as values and were flattened in with the membership literals.

- An `in_set` rule declared with integer members (`values: [1, 2]`) emitted string literals — `tier NOT IN ('1', '2')`. DuckDB and Postgres coerce that and answer correctly; Trino refuses the comparison, so the same spec ran on one engine and failed on another. Members now carry their declared type. A set written entirely with strings is unaffected, down to the artifact bytes.

- The generated conservation audit carried a second condition, `surviving_rows > bronze_rows`, that could never be true: the survivor set is the bronze relation with the dedupe `QUALIFY` over it, so the comparison was a count against a filter of itself. It is removed; `bronze_rows` remains a reported column so the deduped count is visible when the audit does fire. Only the audit's `WHERE` changes, and only for entities with a reject table.

- The emitted quarantine-replay `MERGE` assigned to *qualified* target columns (`_target.col = …`), which DuckDB, Postgres and Trino all reject — the artifact could not run on any shipped dialect. The `SET` target is now the bare column standard SQL requires.

- The replay `MERGE` for an entity that declares `quarantine:` without `dedupe:` rendered an empty row comparison (`WHEN MATCHED AND () > ()`), i.e. invalid SQL. Without a dedupe block the total order degenerates to its final sort key, the stable `_source_row_id`, and the comparison stays total.

- Docs site root no longer 404s before the first release: the dev docs deploy
  now sets the gh-pages root redirect while no released version exists.

### Added

- Declarative data quality (RFC 0016): cleansing becomes spec surface. Mapping fields take a `quality:` list from a closed catalogue (`coercible`, `not_null`, `range`, `length`, `pattern`, `in_enum`, `in_set`, `unique`); entities take row rules (`expression`, `referential`), a `dedupe:` block, and a `quarantine:` policy; the entity model takes a document-level `reconcile:` list. Every rule carries an explicit `on_fail` — `flag`, `quarantine`, or `fail`, with deliberately no `drop` and no `repair` in v1 — and the pipeline order is fixed: extract → transform → dedupe → field rules → row rules → route.

- `pattern` rules speak a **portable regex subset** defined as an allowlist: literals, `.`, character classes, `\d`/`\w`/`\s` and their negations, the anchors `^`/`$`, the quantifiers `* + ? {n} {n,} {n,m}`, alternation, and non-capturing groups `(?:…)`. Everything else is refused at parse with the construct named — capturing groups, backreferences, atomic groups, possessive and lazy quantifiers, lookaround, named groups, inline flags, POSIX classes, `\A`/`\Z`/`\b`, and anything unrecognized. Patterns must be anchored by the author (`^[0-9]{5}$`, not `[0-9]{5}`, which would accept `abc12345xyz`), one pair per top-level alternative.

- `range` bounds are exact: an int, a decimal, or a string carrying one exactly — an exact decimal literal or an ISO date/timestamp. `"nan"`, `"inf"` and `"1e10"` are refused at parse; the first two compare open on some engines and closed on others, and the third renders as a float literal.

- Rules evaluate under a strict three-valued discipline: a rule fires only when its violation predicate is definitively TRUE, so a NULL-involved comparison never fires and a NULL foreign key is not an orphan. `not_null` and `coercible` are the only rules that own nulls.

- One replayable `<entity>__reject` table per entity, with a `reject_id` recomputable from the row itself, plus a replay artifact that re-runs the current mapping against the quarantined payload under the pipeline's own dedupe order — applied to the candidates against each other as well as against the incumbent, so two rejects resolving to one key produce one entity row — and re-stamps `failed_rules` on the rows that still fail. A candidate that passes every rule and merely loses its entity key is marked with the reserved `(superseded)` entry rather than left with an empty reason. A re-delivery lands on the same reject row and keeps its original `first_seen` while `last_seen` advances; `last_seen` is the latest delivery's `_ingested_at` and only that, since retention measures unresolved rows from it and a replay run advancing it would keep them forever. bloomery emits the artifact and never executes it. `retention:` is required whenever anything can quarantine, and `redact:` strips JSONPaths at write time.

- SQLMesh emits the full set: the dedupe `QUALIFY` (rendered natively on DuckDB, as a `ROW_NUMBER` subquery elsewhere), the two-way entity/reject split, the reject model, a blocking audit on the bronze ingestion-metadata contract, a blocking audit per `on_fail: fail` rule — read over the rows the pipeline evaluated **and** the rows already in the entity, so a row that quarantines *and* trips a blocking rule still stops the run, and so does one that reached the entity by replay after its bronze source aged out — and the replay merge. dbt raises `UnsupportedByTarget` for the reject/replay artifacts and for `reconcile` — the honest port-proof scope. Cube consumes the quality mart like any other mart.

- `reconcile.on_fail` decides whether the check's audit blocks: `fail` stops the run — the pipeline-stopping gate RFC 0016 §5.3 nominates reconcile for — while `flag` reports and carries on so a disagreement never withholds the comparison table.

- A blocking `<entity>_conservation` audit per entity with a reject table: every bronze row lands in exactly one of the entity, an unresolved reject, or the deduped count, checked on every production run rather than only in the test suite. Skipped for the one shape an audit body cannot express — a routing predicate that reads a sibling entity (`referential` with `on_missing: quarantine`).

- `gold.mart_data_quality`, an ordinary mart carrying one row per rule evaluation plus one accounting row per entity (`rule = '(entity)'`), so every count is additive and quarantine rate is a plain `MetricRequest` groupable by entity or run month. `rows_failed` is the per-rule count; `rows_evaluated`, `rows_quarantined` and `rows_deduped` describe the entity's population and ride on its accounting row. Five reserved metrics come with it: `quality_rows_evaluated`, `quality_rows_failed`, `quality_rows_quarantined`, `quality_rows_deduped`, and the `quality_quarantine_rate` ratio. `run_id` is emitted declared-but-NULL — the pinned SQLMesh exposes no run-identifier macro — with a comment naming what the caller supplies.

- `Plan.replay_scope` (`ReplayScope`) alongside `backfill_scope`: the entities whose reject tables a spec change invalidates.

- Compile-time data-quality guardrails, batched into the same aggregate as everything else: `DedupeTieBreakMissing`, `DedupeDispositionConflict`, `QuarantineRetentionMissing`, `IngestionMetadataMissing` and `RedactionConflict`, plus bare refusals for a `pattern` regex the shipped dialect ports cannot express, `unknown_member` on a non-string or composite foreign key, a `referential` rule whose `via` names no relationship or names one declared from another entity (pointing back at its own entity included), a `dedupe` clause ordering by a column the entity does not declare, a malformed `reconcile` side, an entity-level rule name that a rule generated from the mapping already owns, and a project metric colliding with a reserved quality-mart name.

- `DialectFeature.ARRAY` and `DialectFeature.TRY_CAST`. Dialects without arrays lower `_quality_flags` to a lexicographic comma-delimited string; Postgres has no NULL-on-failure cast, so compiling a `coercible`-carrying entity for it refuses loudly instead of silently degrading quarantine into an aborted run (RFC 0016 D30). The refusal reaches one entity shape that carries no rules at all: the ingestion-metadata audit asserts `_ingested_at` casts to timestamp, which is itself a `TRY_CAST`, so an entity declaring only `dedupe:` is `UnsupportedByTarget` on Postgres on the audit's own account (D31).

- Documentation: a "Data quality" concept page and an "Add quality rules" how-to guide, plus the full rule/dedupe/quarantine/reconcile schemas and the new refusals in the spec-schema, error, and API references.

- Initial project scaffold: packaging, quality gate, CI, docs infrastructure (RFC 0001).

- Spec layer: strict YAML loaders (`load_project`, `load_catalog`) for the five spec kinds — Catalog, EntityModel, Mapping, MetricSet, MartSet — with unknown keys, duplicate keys, and grammar violations refused, and all parse failures batched with source paths.

- Total error hierarchy rooted at `BloomeryError`: every failure is typed, carries a source path into the offending spec, and batching stages report every problem in one round-trip.

- Deterministic intermediate representation with a `blm1:` content fingerprint (`build_project_ir`, `project_fingerprint`): same specs in, byte-identical artifacts out, across machines and hash seeds.

- Closed whitelist of 24 typed mapping transforms with a compile-time typecheck of every chain, decimal precision/scale tracking through arithmetic, and `register_transform` for vetted extensions.

- Resolution stage (`resolve`): cross-spec reference validation, recorded-recipe validation, cycle detection, and metric reachability with specific missing leaves.

- Fail-closed guardrails: unit, tax-basis, currency, grain, and additivity checks; mart fan-out and grain protection; `assert:` clauses lowered to target-native audits.

- Wide-mart gold layer: relationship flattening with mandatory prefixes, role-playing date dimensions (`ordered_month`, `shipped_month`, …), and a generated `dim_date` calendar owned by the catalog.

- Emit targets for SQLMesh (models, audits, native SCD2), dbt (models, sources, snapshots, schema tests), and Cube (cubes and views with additivity metadata, ratios as calculated measures), rendering over DuckDB, Trino, and Postgres dialects; `register_emitter` adds extension targets.

- Request-time metric planner (`MetricFlowPlanner`): a structured `MetricRequest` becomes SQL plus typed columns, warnings, a deterministic explanation, and a fingerprint — refusing unknown members, cross-grain requests, and ambiguous dimensions instead of guessing. Row-level scoping via `RowPolicy`.

- Manifest hydration for the planner (`LruManifestHydrator`, `HydrationKey`): an in-process LRU keyed by spec fingerprint and library versions, with an optional caller-owned byte store.

- Spec-diff planning (`plan`): every change between two compiled versions classified as additive, widening, rename, restating, or breaking, with backfill scope, downstream metric impact, and an enforced expand/contract workflow.

- Documentation site: get-started, concepts, how-to guides for every target and the planner, full spec/transform/error/API references, and a runnable `examples/quickstart/` project.

- JSON filter front door: `bloomery.planner.parse_filter_json` parses Mongo-flavoured filter documents into typed clauses, normalizing (De Morgan, complement inversion, capped CNF distribution) before refusing, with `parse_sort_json` and `parse_page_json` alongside.

- Closed refusal list for the query vocabulary: unsupported constructs raise a typed `UnsupportedFilter` with a stable reason code, and the complete set of raisable codes is exported as `bloomery.planner.KNOWN_UNSUPPORTED`.
