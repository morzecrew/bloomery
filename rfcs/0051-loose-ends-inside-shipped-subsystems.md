# RFC 0051 — Loose ends inside shipped subsystems

- **Status:** 🚧 In progress — **shipped; retired one change from now.** Every decision
  below is built and under test, and §12's five phases landed whole. It stays live only
  because a retirement row has to name a commit that already holds this document and is
  reachable from `main`, and no such commit exists until the change that ships it lands
  ([`RETIRED.md`](RETIRED.md) argues why that cannot be the deleting commit). Rows added
  by execution cite [`logs/T-0014.md`](../logs/T-0014.md).
- **Scope:** Five ends left dangling by RFCs that have otherwise landed, plus the
  documentation residue two of them left behind. Three are real gaps and get built:
  MetricFlow becomes a compile target so its manifest can be written to disk; the
  entity-field / metric node-id collision becomes a refusal instead of a comment; and
  `on_fail: flag` on a Tier 2 `sql_model` output stops being refused. Two are gaps that
  *closed* while the notes describing them stayed — Tier 1 macro fields and the
  `reconcile: on_fail: quarantine` refusal both shipped, and only their rationale is
  stale. No spec grammar changes and no `<kind>_version` bump: every surface this touches
  already parses today. `EntityIR` gains no field — §5.3 explains why that constraint is
  load-bearing rather than incidental.
- **Related:** [`src/bloomery/compile.py`](../src/bloomery/compile.py),
  [`src/bloomery/emit/__init__.py`](../src/bloomery/emit/__init__.py),
  [`src/bloomery/emit/metricflow/__init__.py`](../src/bloomery/emit/metricflow/__init__.py),
  [`src/bloomery/emit/steps.py`](../src/bloomery/emit/steps.py),
  [`src/bloomery/emit/lower/silver.py`](../src/bloomery/emit/lower/silver.py),
  [`src/bloomery/resolve/graph.py`](../src/bloomery/resolve/graph.py),
  [`src/bloomery/resolve/steps.py`](../src/bloomery/resolve/steps.py),
  RFC 0008 (emit targets), RFC 0013/0014 (the MetricFlow manifest), RFC 0016 (data
  quality), RFC 0017 (the step registry), RFC 0031 (the lineage graph).

---

## 1. Summary

`compile_project` grows a fourth core target, `metricflow`, whose single artifact is the
semantic manifest RFC 0013 already builds and RFC 0014 already caches — until now
reachable only by calling `emit_manifest` from Python, so the one thing the package's own
CLI could not do with it was write it out.

`Graph` node ids carry a kind prefix for every kind except one: an entity field is
`<entity>.<field>` bare, so an entity named `metric` with a field `revenue` produces the
same id as a metric named `revenue`. Sorting was fixed in `logs/T-0005.md` D-025 by adding
`kind` as a tiebreak, which restored determinism and left the collision. The ids are
published — `bloomery lineage --node metric.gross_revenue` is a documented invocation — so
this RFC refuses the collision rather than re-spelling the ids.

`on_fail: flag` on a step output is refused today with a true statement about Tier 3 and a
false one about Tier 2. A `python_model` writes its rows in Python and has no SELECT to
carry a `_quality_flags` projection; a `sql_model` **is** a SELECT, and the projection
that would wrap it is the same `_quality_pipeline` every silver entity already goes
through. Only `flag` lifts: `quarantine` needs a reject table keyed on ingestion metadata
a step output does not have, and a `quarantine:` retention block the wiring has nowhere to
declare.

## 2. Motivation

Each of the three gaps is the same failure in a different subsystem: a capability that is
*built* and *tested* and cannot be *reached*.

- **MetricFlow.** `emit_manifest` and `manifest_json` are public, exercised by golden
  tests, and hydrated by `LruManifestHydrator` on every plan. `Target` has three members
  and none of them is this one, so `bloomery compile --target metricflow` exits 2 and a
  caller who wants the manifest on disk must write Python. The artifact vocabulary
  (`EmittedArtifact`, `ArtifactKind`) was built for exactly this and is unused by it.
- **Node ids.** The comment at `resolve/graph.py` ends "RFC 0003 forbids exactly that" and
  describes a collision that is still legal. A project that hits it gets two distinct
  nodes rendering as one string in `lineage`, in `explain`, and in any consumer that keys
  on `Node.name` — which is what a published id invites a consumer to do.
- **Step-output quality.** RFC 0017 §1 makes quality rules on step outputs the reason
  RFC 0016 and 0017 ship as a pair. What shipped is one of three dispositions.

The two stale notes matter less but cost the same thing: `resolve/steps.py:_check_scope`
tells a reader that no spec surface references a macro step, and
`emit/lower/reconcile.py:reconcile_audit_blocking` tells a reader that a
`quarantine` reconcile disposition is treated as "report" pending a refusal. Both were
true when written. A reader who believes either one will design around a constraint that
no longer exists.

## 3. Current state

Verified against the tree at the branch point, not from memory.

**MetricFlow.** `src/bloomery/emit/metricflow/__init__.py` exports `emit_manifest(ir, *,
naming)` returning a transformed `PydanticSemanticManifest`, and `manifest_json(manifest,
*, indent=None)` returning sorted-key JSON. `emit/__init__.py`'s `_DEFAULT_EMITTERS` holds
`cube`, `dbt`, `sqlmesh`. `EmitContext` already carries `naming`, so the emitter needs
nothing the protocol does not already hand it. There is no `MetricFlowEmitter`.

**Node ids.** `source_column_node`, `canonical_field_node`, `metric_node` and `step_node`
all prefix (`source.`, `canonical.`, `metric.`, `step.`); `entity_field_node` returns
`f"{entity}.{field}"`. Because every other kind's id begins with one of those four
literals followed by a dot, a collision requires an entity *named* `source`, `canonical`,
`metric` or `step` — and `source.` cannot collide in practice, since its id has three
segments and a field name is a single identifier. Entity names reach the graph from two
places: `mapping.target`, and `step_entities`, which names a synthesized entity after the
last segment of the output relation it is bound to.

**Step-output quality.** `resolve/steps.py:_check_scope` refuses any rule whose `on_fail`
is not `fail`, for both SQL tiers and Python alike. `step_entities` synthesizes a complete
`EntityIR` per output — `sources` holds one `SourceIR` whose `relation` is the bound
relation and whose columns are identity projections — so the IR a quality lowering would
need already exists. `emit/lower/silver.py:_quality_pipeline(entity, ctx, extract)` takes
the extract SELECT as an argument and is already shared by the silver model and by
replay's candidate set. `emit/steps.py:_sql_model_artifact` renders `step.body` as the
model's SELECT; the wrapper for a `python_model` renders Python.

**Tier 1 macro fields.** `MacroFieldMapping` (a field's `step:`/`from:` pair) and
`TransformStep.step` (a macro as a chain link) both exist, are consumed by
`resolve/build.py`, and are covered by 25 tests in
`tests/unit/test_steps/test_macro_fields.py`. `_check_scope`'s refusal of a `sql_macro` in
the `steps:` wiring document is correct and permanent — a macro writes no relation, so it
has no output to bind — but its docstring gives "until the reference surface exists" as
the reason.

**Reconcile dispositions.** `spec/quality.py:Reconcile.on_fail` is
`Literal["flag", "fail"]`: `quarantine` has not parsed since RFC 0016 D92. The downgrade
`reconcile_audit_blocking` documents is unreachable, and its docstring calls the refusal
pending.

## 4. Goals / Non-goals

**Goals**

- The MetricFlow manifest is writable by `bloomery compile --target metricflow`.
- A node-id collision is a compile error naming the entity and the fix.
- `on_fail: flag` on a `sql_model` output produces the same `_quality_flags` /
  `_quality_ok` pair every silver entity carries, built by the same function.
- Every remaining rationale in the tree describing a gap that closed is corrected.

**Non-goals**

- **Re-spelling node ids with a kind prefix.** That is the fix the collision deserves and
  the one the published surface forbids; §5.2 argues it rather than assuming it.
- **`on_fail: quarantine` on a step output.** Not deferred — refused, with a reason
  (§5.3). Lifting it needs two things that do not exist and are not cheap.
- **A new spec grammar.** Every surface here already parses; this RFC changes what the
  compiler *does* with what it already accepts, and in one case what it refuses.
- **Making MetricFlow a planning target.** It already is one. This is the emit half.

## 5. Design

### 5.1 MetricFlow as a fourth core target

```python
class MetricFlowEmitter:
    name = "metricflow"

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]: ...
```

registered in `_DEFAULT_EMITTERS` and mirrored by `Target.METRICFLOW = "metricflow"`.

One artifact, at `semantic_manifest.json`, kind `ArtifactKind.MODEL` — the kind's own
definition is "anything defining a relation or **semantic surface**", and a semantic
manifest is the second of those exactly. Content is `manifest_json(manifest, indent=2)`
plus the single trailing newline RFC 0003 §5.5 rule 5 requires of every artifact.

A project with no marts emits **no artifact**, matching `CubeEmitter`'s rule for the same
reason: MetricFlow has no silver surface, so a martless project has nothing to describe,
and an empty manifest is a file that claims a semantic layer exists.

`emit_manifest` raises `EmitError` when marts exist without a catalog `date_dimension`.
That propagates unchanged: it is the same refusal the planner already gives, and a target
that swallowed it would emit a manifest `explain()` cannot use.

Steps need no handling. The manifest describes marts, and `refuse_python_models` exists
because dbt would emit a wrapper no adapter runs — MetricFlow emits no wrapper at all.

### 5.2 The node-id collision, refused at its cause

Every node id but one is prefixed. Rather than prefixing the last one, the compiler
refuses the four entity names that could collide:

```
entity 'metric' collides with the lineage node-id namespace: an entity field is spelled
'<entity>.<field>' and a metric is spelled 'metric.<name>', so this entity's field
'revenue' and a metric named 'revenue' are one id (RFC 0031 §5.3). Fix: rename the entity
— 'metric', 'canonical', 'source' and 'step' are reserved as the four node-id prefixes
```

Applied to every entity name the graph can see: authored entities, and the entities
`step_entities` synthesizes from a bound output relation's last segment. Both are the same
check over the same field, which is why it lives in one place rather than at the two
sites that produce names.

**Alternatives considered.** *Prefix the entity-field id* (`entity.order_item.unit_price`)
removes the collision at the source and needs no refusal. It loses because the ids are
published: `bloomery lineage --node metric.gross_revenue` is in the CLI docs,
`Node.name` is on the public `Graph`, and every stored lineage id in a downstream consumer
would change silently — the artifact-stability caveat covers emitted SQL, not the resolve
API. *Reserve nothing and disambiguate at render* keeps both ids and pushes the ambiguity
onto every consumer, which is where it hurts. *Refuse only on an actual collision* — an
entity named `metric` **and** a metric of the same name as one of its fields — is the
minimal refusal, and it is worse: the same spec compiles or does not depending on a metric
someone adds later, in a different file, so an author learns about the reservation at the
worst possible moment. The four names are reserved unconditionally.

### 5.3 `on_fail: flag` on a Tier 2 output

The refusal narrows from "any disposition but `fail`" to two precise cases:

| Tier | `fail` | `flag` | `quarantine` |
| --- | --- | --- | --- |
| `sql_model` | audit over the relation (today) | **lowers into the model's SELECT** | refused — §5.3.1 |
| `python_model` | audit over the relation (today) | refused — no SELECT to project into | refused — §5.3.1 |

For a `sql_model` output carrying at least one `flag` rule, `_sql_model_artifact` renders
`_quality_pipeline(entity, ctx, body)` instead of the bare body — the *same* function the
silver lowering calls, with the step's own SELECT as the extract. That is the whole
change: `_entity_projections` walks the synthesized identity columns,
`_carries_metadata` is false so no ingestion columns are projected, and
`_route_predicate(..., quarantined=False)` returns `None` because no rule routes. The
result is the `_quality_flags` / `_quality_ok` pair with the entity's `flag` **and** `fail`
rules named in it, per RFC 0016 D18.

A `sql_model` output with no `flag` rule is unchanged — bare body, no flags columns. This
is deliberate and it is the one asymmetry with a mapped entity, which carries the two
columns unconditionally: making them unconditional here would change every existing step
artifact and every golden for a property no consumer can yet rely on, since a
`python_model` output can never carry them.

That asymmetry decides how the rest of the package recognizes a flagged step output,
without an IR field:

```python
def carries_quality_flags(entity: EntityIR) -> bool:
    return entity.produced_by is None or any(
        rule.on_fail is OnFail.FLAG for rule in entity.quality
    )
```

`marts/flatten.py` (the `has_quality_flags` dimension) and `quality/mart.py` (the branch
count) both exclude `produced_by is not None` today, each with a comment describing the
binder error that taught them to. Both switch to this predicate. A `python_model` output
can never satisfy it, because `_check_scope` refuses the only disposition that would —
so the predicate is total without knowing the tier, and `EntityIR` needs no new field.

Not needing one is worth stating as a constraint rather than a convenience: the
fingerprint encoder is type-driven over field names and count, so a new `EntityIR` field
moves every fingerprint in the corpus, for every project, including those that wire no
steps at all.

#### 5.3.1 Why `quarantine` is refused rather than deferred

Two independent blockers, neither of which is work this RFC declined to do:

1. **The reject table has no key.** `<entity>__reject` writes the raw source payload and
   is keyed on the three ingestion-metadata columns a bronze extract carries. A step
   output has none — its wrapper wrote the rows, and `step_entities` gives each column an
   identity expression precisely because there is no extraction behind it.
2. **There is nowhere to declare retention.** `QuarantineIR.retention` is mandatory
   wherever a quarantine disposition exists, and the guardrail that enforces it reads
   `quarantine:` off an authored entity. A step output is synthesized from a `steps:`
   wiring, which has no such block — adding one is new spec grammar, which §4 excludes.

The refusal says both, so an author reads a reason rather than a "not yet".

### 5.4 The two stale rationales

`_check_scope`'s Tier 1 paragraph is rewritten to give the permanent reason (a macro
writes no relation, so a wiring binding it an output is refused) instead of the expired
one. `reconcile_audit_blocking`'s last paragraph drops "until that refusal lands" and
names the `Literal["flag", "fail"]` that landed it.

Neither is a behaviour change and neither is cosmetic: both docstrings currently describe
the compiler to a reader who cannot see they are out of date.

## 6. Tests

- **MetricFlow target.** A golden over the emitted manifest for the corpus project that
  already has a manifest golden — asserting the emitted artifact's content equals
  `manifest_json(emit_manifest(...), indent=2)` would test the test, so the golden is a
  file. Plus: martless project emits nothing; missing `date_dimension` propagates
  `EmitError`; the target is reachable through `compile_project` and through the CLI's
  `--target` parsing.
- **Node-id collision.** One refusal test per reserved name for an authored entity, and
  one for a step output bound to `silver.metric` — the second path is the one a check
  written against `entity_model` alone would miss.
- **Step-output `flag`.** The emitted `sql_model` artifact carries `_quality_flags` and
  `_quality_ok`; a `python_model` with the same rule is refused naming the tier;
  `quarantine` is refused on both naming both blockers; a mart over a flagged step output
  flattens `has_quality_flags`; the quality mart counts its branch. An execution-tier test
  runs the emitted model on DuckDB — the projection is over a subquery alias that no
  golden can prove binds.
- **Not tested:** that the manifest MetricFlow reads is the manifest the planner hydrates.
  They are the same function's output and RFC 0014's cache already pins it.

## 7. Docs

- `pages/docs/reference/api.md` and the CLI page: `metricflow` in the target list, with
  one sentence that it emits a manifest rather than models.
- `pages/docs/concepts/step-registry.md`: the disposition table gains the `flag` row and
  the two refusals with their reasons.
- `pages/docs/reference/spec-schemas.md`: the four reserved entity names.
- `CHANGELOG.md`: a new target is a feature; a newly reserved entity name is breaking for
  any project that used one, and says so.

## 8. Out of scope

- **A `quarantine:` block in the `steps:` wiring.** Named as what would unblock §5.3.1,
  not built. It needs the reject table's key question answered first, and that is a
  design, not a field.
- **Unconditional `_quality_flags` on every `sql_model` output.** Would remove §5.3's
  asymmetry at the cost of every step golden in the corpus, for a property Tier 3 can
  never share.
- **MetricFlow artifacts beyond the manifest.** No `dbt_project.yml` equivalent, no
  scaffolding — one file is the whole target.

## 9. Risks

- **The reservation is breaking.** A project with an entity named `source` compiles today
  and will not after. Accepted rather than mitigated: the alternative is a published id
  that means two things, and the four names are ones no domain model needs. The CHANGELOG
  says it in the breaking section.
- **`_quality_pipeline` over a step body meets an operand its callers never handed it.**
  Every existing caller passes an extract built by `_extract_select` from a bronze
  relation; this one passes authored SQL from a registry. The shape is the same
  (`exp.Select`), the risk is in what the body *contains* — a body that already projects a
  column named `_quality_flags` would collide. Mitigated by the same collision refusal
  RFC 0016 §5.5 applies to a mapped entity, which reads the manifest's `produces`.
- **A martless project emitting nothing reads as a bug.** Mitigated by matching Cube,
  which has the same rule and the same reason, and by saying so in the docstring rather
  than only here.

## 10. Unresolved questions

- Whether `semantic_manifest.json` should sit at the artifact root or under a `semantic/`
  namespace. The root matches how a dbt project holds a single top-level manifest and
  nothing else in the emitted tree competes for the name; if a second MetricFlow artifact
  ever ships, that answer changes. Delegated to execution (D5).

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | MetricFlow ships as a fourth **core** target (`Target.METRICFLOW`), not an extension registered through `register_emitter`. It is built in-tree, golden-tested and hydrated by the planner already; leaving it out of `Target` would make the enum a claim about maturity it does not otherwise make. |
| 2 | `ASSUMED` | One artifact, kind `MODEL`, content `manifest_json(..., indent=2)` + one newline. `MODEL` because the kind means "relation **or semantic surface**"; `CONFIG` would read as scaffolding a framework maintains. |
| 3 | `ASSUMED` | A project with no marts emits no MetricFlow artifact, matching `CubeEmitter`. An empty manifest is a file claiming a semantic layer that is not there. |
| 4 | `LOCKED` | `emit_manifest`'s missing-`date_dimension` `EmitError` propagates out of the emitter unchanged rather than being caught and re-raised as an emit-layer message. Two spellings of one refusal is how they come to disagree. |
| 5 | `OPEN` | The manifest's artifact path — `semantic_manifest.json` at the root, or under a namespace. Settled by execution; §10 states the case for the root. |
| 6 | `LOCKED` | The node-id collision is **refused**, not re-spelled. `Node.name` and the `lineage --node` argument are published surface, and the resolve API is not covered by the emitted-artifact stability caveat. Locks the bare `<entity>.<field>` spelling in: changing it later is a breaking change to every stored lineage id, which is exactly what this row buys. |
| 7 | `LOCKED` | `metric`, `canonical`, `source` and `step` are reserved as entity names **unconditionally** — not only when a real collision exists. A conditional refusal makes a spec's validity depend on a metric added later in another file. |
| 8 | `ASSUMED` | The reservation is checked in one place over every entity name the graph can see, authored and step-synthesized alike, rather than at each of the two sites that mint names. One quantifier, one message. |
| 9 | `LOCKED` | `on_fail: flag` lowers for `sql_model` outputs only, through `_quality_pipeline` — the same function the silver lowering calls, never a second copy of the projection. |
| 10 | `LOCKED` | `on_fail: quarantine` on a step output is **refused permanently**, and the message names both blockers: no ingestion-metadata key for the reject table, and no `quarantine:` retention surface in a `steps:` wiring. Not "pending". |
| 11 | `ASSUMED` | A `sql_model` output with no `flag` rule stays byte-identical — the flags columns are conditional on the rule, not on the tier. Accepts an asymmetry with mapped entities in exchange for leaving every existing step golden alone. |
| 12 | `LOCKED` | `EntityIR` gains no field. `carries_quality_flags` is derived from `produced_by` and the rule dispositions, because a new IR field moves every fingerprint in the corpus — including projects that wire no steps. |
| 13 | `ASSUMED` | The two stale docstrings are corrected in this change rather than left for the RFC that next touches those files. A rationale describing a constraint that no longer exists is read as current by everyone who reads it. |

## 12. Phasing

One PR, five commits, in dependency order — nothing here blocks anything else, so the
order is by blast radius, smallest first:

1. The two stale rationales (§5.4) — docs only.
2. MetricFlow target (§5.1) — additive, no existing artifact changes.
3. The node-id reservation (§5.2) — breaking, one refusal.
4. `flag` on a Tier 2 output (§5.3) — the refusal narrows, one emitter path widens.
5. Docs and CHANGELOG (§7).
