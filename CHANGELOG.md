# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A node can keep its identity across a rename.** Every spec kind that mints
  a lineage node — a metric, a catalog canonical field, a wired step — takes an
  optional `id:`. Where one is present the node id is built from it instead of
  the name, so `metric.mtr_7f3a9c` stays put while the metric is renamed and
  `lineage` traverses across the rename in both directions.

  The value is opaque: compared for equality, never parsed, never resolved to a
  path or an ordering. References keep naming nodes by name — `requires`,
  `requires_metrics`, a step input — and resolve through the same map the graph
  is built from, so adopting an id on one metric does not strand the edges that
  point at it from elsewhere.

  **Two nodes of one kind may not mint the same id**, and that is refused when
  the document is parsed: a copied `id:`, and an `id:` equal to another node's
  *name* where only one of the two adopted one. The second is the one a partial
  rollout writes by accident. Refused at parse rather than by a guardrail
  because `resolve()` returns the graph before the guardrail stage runs, and a
  duplicate caught there would already have collapsed two nodes into one in a
  graph the caller is holding.

  **A project with no `id:` anywhere is byte-identical.** The field never
  reaches the IR — it lives on the spec models and is consumed where the graph
  is built — so no fingerprint moves and no artifact changes.

- **`bloomery explain` shows where each semantic fact came from.** Every fact
  a plan rests on now prints with an evidence grade: `LOCKED` where a person
  declared it in a spec, `ASSUMED` where the compiler obtained it mechanically
  — a default, an inference from a type, a propagation through a proof rule.
  `ASSUMED` is not a criticism; such a fact is sound under the closed-world
  floor, and the grade records where it came from rather than whether it is
  right.

  `EvidenceGrade` is a projection of `Provenance`, five members onto three, and
  the mapping is total and tested: a provenance added without a grade raises at
  the first fact that carries it. It is **derived and never written** — there
  is no field, no argument and no spec key, because a grade an author could
  assert would be an unchecked claim about a claim.

  Nothing is required and nothing is refused. The grades exist so a project can
  see how much of its semantics is declared and how much is defaulted, which is
  the number a consumer would need before it could ask for more.

- **`bloomery check` — a semantic gate for CI.** Load, resolve, type-check,
  prove the static invariants, report; no target emission, no warehouse, no
  credentials and no network, because compilation was already pure and this
  exposes it rather than establishing it. It prints one line per semantic
  surface it checked — entities, relationships, measures, marts, conversions,
  temporal joins — and the refusals, and exits `1` on a refusal like every
  other command.

  It is a separate command from `resolve` rather than an exit contract grown
  onto it, and the two cannot disagree about that exit code: both read one
  `SpecEvidence`. What differs is the question. `resolve` is an author's
  worklist — which metrics are computable, what is missing for the rest;
  `check` is a gate's summary of whether what the project declares holds.

  Each verb names the process a count came from rather than a verdict: marts
  are `checked`, never *safe*, because a guardrail refusal is reported over the
  draft it was handed. The bloomery-owned quality mart is not counted — it
  attaches after the guardrails, so nothing checked it and nobody wrote it.

  **No total and no percentage**, which would imply a coverage nobody proved,
  and where analysis stopped before an IR existed the counts are reported
  *unavailable* rather than zero — a zero reads as a surface checked and found
  empty. `SpecEvidence` gains `checked`, a `CheckedSurfaces` or `None`, so a
  Python caller reads the same numbers.

  An unreachable metric and an open decision are reported and do not fail the
  gate: they say the mappings are incomplete, not that what is written is
  wrong.

- `bloomery.transforms` exports `CONVERT_TRANSFORM`, the `convert` chain
  step's authored name, beside `CONVERT_MARKER`, which is the SQL token it
  lowers to. Two places name it now — the registration and the surface count —
  and a count spelling it differently would report every project as converting
  nothing.

- **A rollup now has to answer two questions, and they are asked separately.**
  `can_roll_up` says whether values may travel from one grain to another; it
  has never said anything about what may be done with them on arrival, and
  nothing in the semantic package read a measure's additivity at all. Two
  rules close that:

  - **R011** — an additive measure may be summed across a rollup its grain
    proof permits. The grain proof is carried as a premise rather than
    restated, so one tree holds both facts a reader needs.
  - **R012** — a ratio is recomputed from operands that each roll up, never
    summed. Its premises are R011 answers, one per operand, because a ratio is
    sound at the target grain exactly when its inputs are.

  They compose rather than nest, and the order is what makes a refusal useful:
  a measure whose grain proof fails gets the grain refusal, so an author is
  sent to the relationships; a measure whose grain proof passes and whose
  additivity is wrong gets a refusal naming the metric. A single rule
  answering both could not tell those apart. Both are expressed *beside* the
  additivity guardrail rather than replacing it (RFC 0039 D3).

- **Four semantic corpus cases**, completing the set RFC 0042 §3 named:
  `008-ratio-rollup` (averaging per-order quotients weights the orders instead
  of the items), `009-null-denominator` (a zero-denominator row contributes to
  the numerator and moves cost onto units that did not incur it),
  `010-many-to-many-bridge` (every edge is `many_to_one` and the fan-out is a
  property of the path), and `011-timezone-boundary` (a zoneless local
  timestamp read as UTC puts an order in the wrong month).

  Two of them are the corpus's first **`unguarded`** cases — the word RFC 0042
  minted for a case whose guard does not exist yet, unused until now. Both
  compile, plan, and return the wrong number, and say so rather than being
  written as fictions or left out.

- **A request whose measures live on different grains is answered, where the
  join can be proven safe.** It used to refuse: summing across grains
  double-counts, and no single mart holds both measures at their own grain.
  There is a correct answer that no single scan can give — aggregate each
  measure on the mart that owns it, then join the results — and the planner now
  builds it.

  Each branch is planned exactly as the single-mart request it is, and bloomery
  composes the join itself: the branches become CTEs, their keys are `UNION`ed
  into the domain of groups the answer has, and each branch is left-joined back
  onto that domain on `IS NOT DISTINCT FROM`. So a group present in one branch
  only survives, and a NULL group meets the other branch's NULL group instead
  of splitting in two. It is a full outer join written the long way — the same
  shape the reconcile emitter already uses, and for the same reason:
  PostgreSQL will not plan a `FULL JOIN` on a null-safe condition. No join
  happens before an aggregate, so nothing can fan out; joining raw rows at
  query time stays refused.

  One condition is checked before anything is planned, and a request failing it
  keeps the refusal it had: every requested dimension is present on **every**
  branch and is the *same* dimension on each — same source entity, same source
  column. A name both marts carry and mean different things by (`order_id` on a
  mart based at `order` and on one based at `order_item`, where it is the
  foreign key) is refused, and the message names both origins.

  **Filters and the row policy** are held to that same rule and to nothing
  else. Each is placed on every branch, resolved to that branch's own spelling
  of the dimension — `region` on the mart based at `order`, `order_region` on
  the one that flattened its way there — and never duplicated onto a column
  that merely shares a name. A restriction one branch cannot evaluate refuses
  the whole request: applied to some branches and not others it does not
  narrow the answer, it puts a restricted number beside an unrestricted one at
  the same key and reports nothing. The refusal names each mart and what it
  carries, because the fix is a mart change.

  **`order_by` and `limit`** apply to the joined result. Both would be wrong
  inside a branch — an order is undone by the join and a limit answers from a
  prefix of one branch — so they are rendered on the composed statement, with
  `RFC 0011`'s clamp unchanged. The ordering states `NULLS LAST` in both
  directions rather than leaving it to the engine: the join mints a NULL group
  on purpose, and where a NULL sorts is a per-engine *setting*.

  **A metric whose components live on different marts is computed above the
  join.** A ratio becomes `SUM(num) / NULLIF(SUM(den), 0)` and a `derived:`
  metric its own expression, each operand aggregated by the mart that owns it
  and combined once over the joined result — which is not the number a
  row-level expression aggregated afterwards gives. The branches are asked for
  the components; the requested name exists only in the composed projection.
  Two shapes stay refused: a component that itself needs two marts, and a
  derived input read at a time offset, which names a grain no branch produced.

  `QueryPlan.marts` names every mart a plan read — `mart` keeps its meaning as
  the first of them — and the explanation prints one `branch:` line per mart.
  The semantic plan gains a `JoinAggregates` node carrying **R010**: each
  branch holds one row per key because of the aggregate beneath it,
  structurally, never because the data happened to look that way. Where a
  metric is computed above the join the semantic plan is withheld rather than
  stated: the node vocabulary is a scan, a filter, an aggregate, a projection
  and a join, and naming the metric in the projection would claim the join
  produced a column it does not produce.

- **A distinct count has a word of its own: `additivity: distinct_count`.** A
  `count_distinct` measure could not be declared at all. `additive` was
  refused — summing per-group distinct counts double-counts an identity present
  in several groups — and the refusal's own advice, `non_additive` with a
  `derived:` block, named a decomposition a plain distinct count does not have.

  `distinct_count` declares what the measure is: `count_distinct` over the
  column that identifies what is counted, computed from rows at whatever grain
  a request asks and never rolled up from a coarser result. MetricFlow and
  Cube emit it as the measure they already knew how to; the planner states it
  in the single-mart semantic plan and keeps it out of the aggregate-then-join
  path, where a branch is a rollup and two branches' distinct counts would be
  summed without the disjointness proof nothing supplies. The explanation
  reads `distinct count — …` rather than `additive`. Either half without the
  other is refused: `distinct_count` over any other aggregation, and
  `count_distinct` under `additive`, whose remedy now names the word.

  `snapshot` stays in the resolved vocabulary and out of the authored one. Its
  declaration already exists — `semi_additive: {over: <axis>, rule: last|first}`
  names the axis and the time selection a snapshot needs before any cross-time
  aggregation — and a second word for the same fact is the two-spellings
  problem `ratio` just left behind.

  **Migrating.** This change refuses nothing that compiled without it. A distinct
  count kept out of a project because no word accepted it can now be declared. Corpus
  case 007 pins both outcomes: the `additive` claim refused, the
  `distinct_count` declaration planned to the correct number.

- **`additivity: additive` is checked rather than trusted.** The additivity
  guard read only metrics declared `non_additive` or `semi_additive`, so the
  one declaration nothing verified was the one most projects write. Two false
  shapes are now refused as `FalseAdditivityClaim`:

  - an `avg` or `median` declared additive — rolling one up re-aggregates an
    aggregate, weighting each group equally instead of each row, so the answer
    is wrong wherever groups differ in size. A `count_distinct` fails for a
    different reason: summing per-group distinct counts double-counts any
    entity present in more than one group;
  - a measure whose entity key carries a date or timestamp **and whose mart
    offers that column as a dimension** — `one row per account per day` means
    each row is a point-in-time snapshot, and a mart flattening `as_of_day` is
    what makes summing across the period possible in the first place.

  The mart half of the second rule is not a technicality. A key alone cannot
  tell a snapshot from a redundant composite: an entity keyed
  `(payment_id, paid_at)` is one row per payment, and telling that author to
  declare `semi_additive` over `paid_at` would assert a rollup axis that does
  not exist. Where no mart exposes the column, there is nothing to sum across
  and nothing to refuse.

  Both compiled clean before, and both answer with a plausible wrong number,
  which is the failure class this compiler exists to refuse.

  **The accepted aggregations are an allowlist**, not a list of bad ones:
  `sum`, `min`, `max` and `count` roll up soundly, and an `additive` claim over
  anything else is refused — including a spelling bloomery does not recognise,
  since `agg:` is a free string that nothing validates. Each refusal names the
  repair for its own aggregation; an unrecognised one says plainly that the
  claim could not be checked rather than that it is false.

  **Only `sum` triggers the snapshot rule.** A `min`, `max` or `count` over a
  snapshot asks an honest question — the lowest balance in the period, the
  number of account-days — that repeated state does not corrupt.

  **Migrating.** Neither refusal is silent and both name the fix. An average
  becomes `additivity: non_additive` with `ratio: {numerator, denominator}`
  over the two additive quantities it divides — the quotient is then computed
  at query time, from sums, which is the only way it rolls up correctly. A
  snapshot becomes `additivity: semi_additive` with
  `semi_additive: {over: <the date in the key>, rule: last}`; the message names
  both the axis to declare and the ones the measure stays additive across.

  A temporal column *outside* the key is untouched: an `order` keyed on
  `order_id` with an `ordered_at` timestamp is an event, not a snapshot, and
  summing its amounts was never in question. So is a mart that flattens some
  other date, or that carries a different measure.

  `Additivity` also gains `ratio`, `distinct_count` and `snapshot` as members.
  The authored `additivity:` keyword still accepts its three words — the new
  members are the resolved vocabulary, not new syntax, and nothing mints them
  yet.

- **dbt is a complete quality target.** `quarantine:` and `reconcile:` on an
  entity, and the quality mart that counts over both, compiled for SQLMesh and
  raised `UnsupportedByTarget` for dbt. All three now emit: a
  `models/silver/<entity>__reject.sql` incremental model, a
  `macros/replay_<entity>.sql` run-operation, a
  `models/silver/<check>__reconcile.sql` comparison with its singular test, and
  `models/gold/mart_data_quality.sql`.

  The three refusals were one claim — a target-coverage sentence written when
  this emitter produced no audits at all — and it outlived the emitter it
  described by two releases. A `flag` rule on a Tier 2 step output was the last
  thing to hit it: the rule has nothing to do with steps, it just puts a quality
  mart in the project.

  **Replay is `dbt run-operation replay_<entity>`.** Rebuild the reject table
  first: replay re-runs the current mapping against the rows the table holds, so
  one built before your correction landed still says the row fails. The macro
  form is forced rather than chosen — the statements name relations through
  `{{ ref(...) }}`, which resolves inside dbt's Jinja and nowhere else, so a
  loose `.sql` file would be runnable by neither dbt nor a SQL client. The three
  statements run in one explicit transaction. bloomery still executes nothing.

  **Two operational facts.** A re-delivery keeps `first_seen` and advances
  `last_seen`, which is what the retention window measures from. And
  `dbt build --full-refresh` **loses resolved reject rows** — the rebuild sees
  only what is currently quarantined. That is accepted rather than prevented:
  the history derives from bronze the refresh is rebuilding anyway, and a model
  that refused to full-refresh would be one you could not recover.

  `run_id` is filled on dbt, from `invocation_id`, and stays declared-but-NULL
  on the pinned SQLMesh, which exposes no run-identifier macro.

  Still refused, and unrelated to each other: Tier 3 `python_model` steps, and
  `on_fail: quarantine` on a *step output* — the latter on **every** target,
  since a step output has no ingestion-metadata key for a reject table and a
  `steps:` wiring has no `quarantine:` block. It shares a word with the
  entity-level policy and nothing else.


- **A merged entity can be cleaned.** `quality:` rules, `dedupe:` and
  `quarantine:` — with its reject table and replay — now work on an entity built
  from more than one mapping. Union merge shipped without them, which covered
  only pre-cleaned sources; dirty bronze landing as text and being cleaned on the
  way to silver is the shape the project's own lakehouse example is built to
  demonstrate, and the two did not compose.

  The rules are **one set, evaluated once over the merged relation, whose inputs
  are per source**. A coercion rule compares the produced column against the raw
  paths *that branch* reads; an `in_enum` rule admits what *that branch's*
  `enum_map` chain maps. Each branch computes its verdict below the union and the
  rule reads the result, so one rule judges rows from sources sharing no column
  name. Carrying one mapping's paths into a rule the union evaluates — the
  shipped shape's reason for refusing this outright — would have read a JSONPath
  off a relation that need not have it.

  Every mapping must declare the **same** rules for a column they both produce;
  two that disagree are refused with both documents named, because a rule set
  taken from one would silently drop what the others wrote. A column only one
  mapping produces is not refused: its rules join the entity's set, and on a
  branch that maps nothing the coercion marker reads "no sources, no evidence"
  rather than reporting every one of that source's rows as a failed cast.

  `dedupe:` sorts by `_source` immediately ahead of `_source_row_id`, which is
  unique only within one source relation — without it two rows from different
  sources on one key compare equal and the survivor is undefined. The reject
  table stays **one per entity**, and each row records which mapping produced it,
  so replay re-runs that row's own mapping instead of applying one of them to
  all. The collision audit moves off the model onto the union stage: with dedupe
  in between, a key held by two sources is collapsed before the model exists, and
  an audit reading the model would pass on exactly the data it exists to refuse.

  `_source` is now a column of the merged silver relation on every path to it.
  It reached the relation before only because a merged entity carried no rules
  and the model was `SELECT *` over the union.

- **Metrics over time: period-over-period, cumulative windows and metric filters.**
  "Revenue vs. the same month last year" is expressible. A metric may now be
  `derived:` — an expression over other metrics, each read through an alias and
  optionally at an `offset:` of a fixed `window:` ("1 year") or the start of a
  containing period (`to_grain: month`). The alias is the mapping key rather than a
  field, because the interesting case names one metric twice.

  `cumulative:` lowers at last, in both its forms: a trailing `window:` and a
  `grain_to_date:` accumulation. It sits beside `agg:`/`expr:` rather than replacing
  them — the additivity describes the measure, the window describes how the measure
  accumulates.

  A metric may carry a `filter:` — typed clauses, never a SQL string — so
  `paid_revenue` is a metric rather than a convention every caller has to remember.
  Values are checked against the flattened column's declared type at compile time and
  are never cast; the restriction is reported in the plan's explanation, so a filtered
  number is never presented as its unfiltered sibling. The dimension must be a bare
  `^[a-z][a-z0-9_]*$` identifier — the one place a member name reaches a template that
  does not quote it, where every other field name reaches SQL through SQLGlot.

  Two boundaries stated up front. A cumulative metric asked for at a grain coarser
  than it accumulates to collapses each period to one value, and `period_agg:`
  says how — **`last` by default**, so a month-to-date metric asked for by month
  reports the accumulation at the month's end. That is this project's one
  deliberate divergence from MetricFlow, whose default is `first`: on a month
  totalling 257 it reported 100, the running total on the first day. Write
  `period_agg: first` or `average` to ask for something else. And
  `cumulative:` on a `semi_additive` metric is refused: the
  `over:` dimension is a date role and a window accumulates along that same axis,
  so the two lower into a number with no reading.

  A derived metric's inputs are its dependency edges: they need not be repeated in
  `requires_metrics:`, and reachability, cycle detection and the planner's coverage
  precheck all follow them. **Cube refuses derived and cumulative metrics** with
  `UnsupportedByTarget` naming the construct — it compares periods at query time
  rather than as a stored measure definition, and has no `grain_to_date` equivalent —
  and emits metric filters as measure filters. The MetricFlow manifest carries all
  four. RFC 0034.

- **Currency conversion.** `convert` now lowers, against a dated rate relation the
  catalog declares as `fx_rates:` — the relation plus its from/to/rate/valid_from/
  valid_to columns. The transform reads
  `{convert: [<from>, <to>, <date field>]}` and emits an as-of lookup of the rate
  that was current on the anchor's date, so a EUR amount becomes the USD it was
  worth *then*. A multi-currency business can express a converted metric: write the
  conversion into a field the catalog declares in the target currency, and adding it
  to a native amount in that currency is ordinary same-currency arithmetic.

  A date that no rate interval covers converts to `NULL` rather than to a neighbouring
  rate, and both interval ends are required — one end is not an interval, and a
  lookup with only a lower bound matches every rate at or before the anchor. Without
  `fx_rates:` in the catalog `convert` is still refused at emit, now with a message
  naming the declaration that would lift it. RFC 0023 §5.4.

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

- **`direct:` now works on a merged entity.** It was refused outright: `direct:` is
  declared per mapping, so an entity built from several could carry a path on one source
  and none on another, leaving the `<field>__direct` shadow NULL for the other's rows —
  indistinguishable from a genuinely NULL direct value, with the reconciliation audit
  either reporting a disagreement that is not there or quietly no longer checking.

  What actually blocked it was arity, not NULLs: one shadow projection stood for every
  source, so each branch would have carried the other's extraction — a `$.price` read off
  a relation that has no `$.price`. The shadow now fans out per source like every other
  lowering, and each branch reconciles against the path *its own* mapping named. The
  entity still gets one shadow column and one reconciliation audit.

  What is refused is narrower and is disagreement about whether the conflict exists:
  among the mappings that produce a column, all record a `direct:` path or none does,
  with both documents named. A column only one mapping produces is unaffected.

- **The SQLMesh target emits `config.yaml`.** Its output was not a project:
  `sqlmesh` answered "SQLMesh project config could not be found" and read none of
  the models, while the dbt target had emitted `dbt_project.yml` all along. The
  file carries the dialect you compiled for and a `model_defaults.start` derived
  from the catalog's `date_dimension.start_year`.

  The start is the substance. Without one SQLMesh backfills every
  `INCREMENTAL_BY_TIME_RANGE` model over a **single day** and reports success, so
  a config carrying only the dialect would have handed you a project that plans
  green with one partition of history.

  No `gateways:` block, for the reason no `profiles.yml` is emitted for dbt: a
  connection carries hosts and credentials and the compiler reads no environment.
  Supply one through `SQLMESH__GATEWAYS__…` rather than by editing the emitted
  file — SQLMesh keeps the connection beside the project settings, so the next
  compile overwrites it. A project that backfills by time and declares no catalog
  date dimension gets no `config.yaml` at all, because there is no honest start to
  put in it — where "backfills by time" means the kind a model is *emitted* with, so
  an entity declaring `scd: type2` does not withhold the file: it is snapshotted, not
  time-ranged, and reads no start.

- **MetricFlow is a compile target.** `--target metricflow` (or
  `Target.METRICFLOW`) writes one `semantic_manifest.json` — the same manifest
  `emit_manifest` has always returned and the planner has always hydrated, which
  until now no CLI invocation could put on disk. A project with no marts emits no
  artifact, the rule the Cube target already applies: MetricFlow has no silver
  surface, and an empty manifest is a file claiming a semantic layer that is not
  there.

- **`on_fail: flag` on a Tier 2 step output.** A `sql_model` output carrying a
  `flag` rule now emits `_quality_flags` and `_quality_ok` on its relation, built
  by the same lowering every silver entity goes through. RFC 0017 made quality
  rules on step outputs the reason data quality and the step registry ship as a
  pair, and one of three dispositions had landed.

  The refusal it replaces was true about Tier 3 and wrong about Tier 2: `flag`
  needs a `SELECT` to project into, a `python_model` writes its rows in Python and
  has none, and a `sql_model` *is* one. An output with no `flag` rule is
  unchanged — the two columns follow the rule, not the tier.

  `on_fail: quarantine` stays refused on both tiers, now permanently and with the
  reason: routing a row means writing `<output>__reject`, which is keyed on the
  ingestion metadata a step wrote none of, and `quarantine.retention` is required
  wherever the disposition appears with no `quarantine:` block in a `steps:`
  wiring to declare it. Route in a downstream mapped entity instead.

### Changed

- **A conversion out of an undeclared currency is refused.** *This is a breaking
  change; the fix is one line per converting field.* `convert`'s first argument
  says what the column holds before the conversion, and nothing checked it — so
  `{convert: [JPY, USD, paid_at]}` written over euros read the yen rate, applied
  it to euros, and compiled clean. Every cast succeeds and the rate relation has
  the row asked for; the answer is wrong by whatever the two rates differ by.

  The input now needs a fact to be checked against, declared on the mapping's
  field:

  ```yaml
  amount_usd:
    currency_in: EUR                     # new; required where the chain converts
    from: "$.amount"
    transform: [{to_decimal: [12, 4]}, {convert: [EUR, USD, paid_at]}]
  ```

  It goes on the mapping rather than the canonical field because a canonical
  field is shared across mappings, and one fed by a euro feed and a dollar feed
  would need two answers for one declaration. A key field takes it too, on the
  same terms.

  **A chain declares once**, which is the other half of the change: each step's
  input is the previous step's output, so converting through a bridge currency
  where no direct rate exists needs one declaration and is now *accepted* —
  `EUR → CHF → USD` was refused before this, on the intermediate step, with a
  message written for a single conversion. The column's currency is what the
  last conversion produces.

  Refusals name what was being held where the chain broke, and cite `R009`.
  Per-row denomination — `currency_in: {column: currency_code}` — parses and is
  refused as *unbuilt* rather than invalid.


- **A ratio metric declares `additivity: ratio`, and `non_additive` with a
  `ratio:` block is now refused.** *This is a breaking change; the fix is one
  word per metric.* A ratio is stored as its operands and never as the
  materialized quotient — `SUM(num)/SUM(den)` and `AVG(ratio)` differ, and the
  second is what a numeric-looking column invites — and until now the only way
  to say so was to declare the metric `non_additive` and put a `ratio:` block
  beside it. That spelling made the additivity a field the compiler read for
  one thing and the author wrote for another.

  ```yaml
  average_order_value:
    requires_metrics: [revenue, order_count]
    additivity: ratio                      # was: non_additive
    ratio: {numerator: revenue, denominator: order_count}
  ```

  A `ratio:` block under any other word, and `additivity: ratio` with no
  `ratio:` block, are both refused as `InvalidMetricShape` naming the fix.
  Nothing else moves: the metric is still recomputed at query time, still
  never a stored measure, still lowered to MetricFlow's `RATIO` metric and to
  Cube's `{num} / NULLIF({den}, 0)`. **Artifacts change in two places** — Cube
  writes `meta.additivity: ratio` on the calculated measure, and the metrics
  and catalog JSON schemas publish the new word — so every fingerprint
  downstream of a project with a ratio moves with them.

  A generated metric moved too: `quality_quarantine_rate`, the rate the data
  quality mart carries, is now a `ratio`.


- **`DialectPort` requires `begin_transaction`**, and `register_dialect` now
  refuses a port missing any protocol member instead of letting it fail with an
  `AttributeError` mid-emission. A `Protocol` is structural, so an extension
  port can satisfy a type checker and omit a member; the registry is global, so
  such a port is a latent failure for whichever code path reaches it next. Every
  shipped port subclasses `SQLGlotDialect` and is unaffected: it supplies the
  `BEGIN` default, which the Trino port overrides to `START TRANSACTION` —
  Trino rejects `BEGIN` outright, which is why the member exists.


- **`canonical`, `metric`, `source` and `step` are reserved entity names.** Those
  four are the lineage node-id prefixes, and an entity field is `<entity>.<field>`
  with no prefix — so an entity named `metric` with a field `revenue` produced the
  same id as a metric named `revenue`, in `lineage`, in `explain`, and in anything
  keying on `Node.name`. The ids are published, so the collision is refused rather
  than the ids re-spelled.

  Breaking for a project using one of the four: rename the entity. The refusal is
  unconditional rather than fired only on a real collision — a spec whose validity
  depends on a metric someone adds later, in another file, teaches an author about
  the reservation at the worst possible moment. A step output is bound by it too:
  it is named after the last segment of the relation its wiring binds.

- `convert` takes **three** arguments where it took one: `{convert: [EUR, USD,
  paid_at]}` instead of `{convert: USD}`. A rate is a dated fact, so the old
  signature named no rate that exists — it was incomplete rather than merely
  unimplemented, which is why it was refused at emit rather than finished later. No
  spec that compiled before is affected: every spec carrying the old spelling was
  already refused.

- `CurrencyMismatch` names the fix that is available rather than one fixed sentence:
  converting, where the catalog declares rates; declaring rates or deriving upstream,
  where it does not. The rule itself is unchanged and still has no escape token.

- `ProjectIR.bloomery_ir_version` is **11** (was 6), across five shape changes in this
  release: `MartJoinIR` gained `as_of` (7), `ProjectIR` gained `fx_rates` (8),
  `MetricIR` gained `cumulative`/`derived`/`filter` (9), `CumulativeIR` gained
  `period_agg` (10), and `SourceColumnIR` gained the branch facts a merged entity's
  rules read — `sources`, `enum_values`, `enum_spellings` (11).
  `plan()` refuses to diff across versions; recompile both sides with one compiler.
  Every project's fingerprint moves, because the version is itself part of the
  canonical stream — `as_of` on its own would have moved only the fingerprints of
  projects that have mart joins, which is why the version had to move for the rest.

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

- **A catalog year below 1000 is written as four digits.** `start_year` accepts
  anything from 1, and the date spine interpolated it unpadded:
  `GENERATE_SERIES(CAST('1-01-01' AS DATE), …)`, which means whatever the engine's
  date style guesses. The same value now reaches the SQLMesh `config.yaml`, where
  `'1-01-01'` is not rejected but *reinterpreted* as `2001-01-01` — two millennia
  of backfill lost to a file the compiler wrote. Both sites pad.

- **A timestamp carrying a UTC offset is no longer silently truncated.**
  `{parse_ts: ISO8601}` over `2026-01-06T12:00:00+01:00` produced `12:00` on
  DuckDB, PostgreSQL and Trino alike — the offset discarded, the instant an hour
  wrong, and no error, no NULL and no audit anywhere in the pipeline to say so.
  `parse_ts` reads a *local wall clock* and `to_utc` is the only door into UTC, so
  such text states something the declaration already claimed to know; it now
  produces NULL, identically on every engine.

  NULL is what the rest of the system can already see: the implicit `coercible`
  rule flags it, `on_fail: quarantine` diverts the row, and the ingestion-metadata
  audit stops the run for `_ingested_at`. A `Z` suffix is deliberately kept — it
  names the zone the `timestamp` type is already in, so dropping it loses nothing.

  **This moves data on upgrade.** A source whose timestamps carry offsets stored
  plausible wrong values before and stores NULLs now. Add a `coercible` rule on
  the affected columns before promoting the upgrade, and normalise the offsets
  upstream — bloomery does not convert them, because reading the offset would make
  one declaration mean a local clock on one row and an instant on the next.

- **`{parse_ts: ISO8601}` no longer stops the run on a lowercase `t` on DuckDB.**
  ISO 8601 permits `2026-01-06t12:00:00`, PostgreSQL and Trino both read it, and DuckDB's
  cast raises *invalid timestamp field format* — so a bare entity aborted and a
  quality-carrying one quarantined the row, on text the other two ports read fine. The
  DuckDB port normalizes both separators before the cast now, through the same function
  the Trino port already used for its own version of this.

- **A `direct:` path on an entity in the quality system no longer aborts the run.** Every
  cast on such an entity is NULL-on-failure so the implicit `coercible` rule can see the
  failure — every cast except the `<field>__direct` shadow, which is built after the
  builder has run and did not inherit the shape. A direct value that would not cast raised
  an engine conversion error from the middle of the model SELECT, naming neither the
  column nor the reconciliation check. It lands as NULL now and the reconciliation audit
  reports the row as a disagreement, which is what it is.

- A metric declaring `cumulative:` no longer compiles as a plain simple metric —
  per-period aggregation where a running total was declared, which is what 0.2.0
  did, silently. It is lowered now (see Added). It was briefly refused outright
  earlier in this same unreleased window, which no release ever carried; what
  survives that refusal is narrower and named per case (`InvalidMetricShape`).

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

- **`quarantine:` on an `scd: type2` entity.** The pair compiled and produced a
  replay merge that could not work: replay admits a row by the entity's own
  columns, and a type 2 relation carries the validity interval its framework
  maintains as well — plus dbt's `dbt_scd_id`. The merge named none of them, so
  it inserted a version with `valid_from`, `valid_to` and `dbt_scd_id` all NULL
  and **reported success**. The row is present, queryable, and skipped by every
  as-of join, which is what a type 2 relation is for. Measured on both targets.

  **What to write instead**, depending on which half you need. If the history
  matters more than the recovery, declare the entity `scd: type1` and keep
  `quarantine:` — you lose versioning and keep the reject table and replay. If
  the recovery matters more, keep `scd: type2` and reduce the entity's rules to
  `flag` dispositions: no row is diverted, `_quality_flags` still records every
  failure, and the quality mart still counts them. A rule that must divert *and*
  a relation that must keep history is the combination with no correct lowering
  today.

  This is a removal of something that never worked rather than of a capability.
  No fixture combined the two, which is why replay and native SCD2 had never
  been observed failing to compose. Bringing it back is RFC 0060.

- `UnsupportedCumulative`. The class named reserved surface no stage lowered, and
  the surface is no longer reserved. A metric that cannot mean what it says is now
  `InvalidMetricShape`; a filter that cannot be lowered is `MetricFilterInvalid`.

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
