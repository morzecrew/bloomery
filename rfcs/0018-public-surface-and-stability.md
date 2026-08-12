# RFC 0018 — Public surface and stability policy

- **Status:** 📝 Draft
- **Scope:** The boundary between bloomery's public API and its internals: a *signature
  closure* rule for `bloomery.__all__`, the promotion of `assert_step_contract` (which
  generated artifacts already import by module path), an additive fix to
  `QueryPlan.columns` (RFC 0009 D24's recorded binding defect), and a written stability
  policy distinguishing three surfaces with genuinely different promises — Python API,
  spec YAML schema, emitted artifacts. Does **not** schedule a release, add capability,
  or change any emitted SQL.
- **Related:** [RFC 0002](0002-spec-layer-and-errors.md) (error hierarchy),
  [RFC 0003](0003-ir-and-determinism.md) (`blm1:` fingerprint, `bloomery_ir_version`),
  [RFC 0008](0008-ports-and-emitters.md) (`EmittedArtifact`, `NamingPolicy`, `Feature`),
  [RFC 0009](0009-testing-strategy.md) D24 (the `QueryPlan.columns` finding),
  [RFC 0011](0011-native-planner.md) (the planner contract),
  [RFC 0015](0015-query-vocabulary.md) D9 (`KNOWN_UNSUPPORTED` export),
  [RFC 0017](0017-step-registry.md) (the step contract module).
  Blocks [RFC 0020](0020-authoring-ergonomics.md) (the CLI is a shell over this surface)
  and [RFC 0022](0022-spec-evidence.md) (which adds root exports).
- **Adoption audit:** [`_adoption-audit-0018-0022.md`](_adoption-audit-0018-0022.md) —
  §3's figures and §5.5's premise were corrected against the tree before adoption.

---

## 1. Summary

`bloomery.__all__` exports 29 symbols but not the types those symbols consume and return:
`compile_project` returns `tuple[EmittedArtifact, ...]` and accepts `NamingPolicy`,
`Catalog`, `Project` and `StepRegistry` — none of which a caller can name from the root
namespace.
This RFC adopts **signature closure** as the rule (anything appearing in a public
signature is itself public), enforced by a test rather than by review.

Separately, `assert_step_contract` is imported by *generated artifacts* as
`from bloomery.steps.contract import assert_step_contract` — a deep module path that has
become de-facto public API without ever being declared one. It is promoted to
`bloomery.steps.__all__` and the generated import rewritten.

`QueryPlan.columns` gains `sql_alias` alongside `name`, additively, closing RFC 0009 D24.

Finally, three stability promises are written down: SemVer over the Python API, per-kind
versioning over spec YAML, and an explicit **non**-promise over emitted artifact bytes.

## 2. Motivation

The subpackage namespaces are in good shape — `bloomery.planner` exports 19 symbols
including `KNOWN_UNSUPPORTED` and the three parse functions; `bloomery.steps` exports 10
including `StepRegistry` and `EMPTY_REGISTRY`; `bloomery.spec` exports the full spec
vocabulary. The gap is not missing exports but an **unstated layering policy**: the root
namespace is a curated subset, and nothing says what the curation rule is, so it has
drifted into exporting functions without their types.

That has three concrete costs. A caller annotating `compile_project`'s return must
deep-import `bloomery.emit`. A caller passing steps must deep-import `bloomery.steps`.
And every such deep import silently widens the surface bloomery must not break, because a
module path someone imports is a promise whether or not it was meant as one — which is
exactly what happened to `bloomery.steps.contract`, and there the importer is *bloomery's
own generated code shipped into user repositories*.

The release is not the driver. The surface is worth getting right on its own terms, and
getting it right is cheapest while nothing is bound to it.

## 3. Current state

Verified against `main` @ `3da72c5` (2026-08-12):

- `bloomery.__all__` — 29 symbols: `AnyOf`, `BackfillScope`, `BloomeryError`, `Change`,
  `ChangeClass`, `ColumnDescriptor`, `HydrationKey`, `LruManifestHydrator`,
  `MetricFlowPlanner`, `MetricRequest`, `Op`, `OrderSpec`, `Plan`, `Predicate`,
  `QueryPlan`, `ReplayScope`, `Resolution`, `RowPolicy`, `Target`, `TimeGrain`,
  `build_project_ir`, `compile_project`, `load_catalog`, `load_project`, `plan`,
  `project_fingerprint`, `register_emitter`, `register_transform`, `resolve`.
- **Absent from root**, each reachable only by deep import — and each already declared in
  its own subpackage's `__all__`, so the deep path is supported but unadvertised:
  `EmittedArtifact`, `ArtifactKind`, `NamingPolicy`, `DefaultNaming`, `Project`,
  `Catalog`, `StepRegistry`, `EMPTY_REGISTRY`, `Explanation`, `ProjectIR`, `Clause`,
  `Scalar`, `LogicalType`. Thirteen.
- **Absent from every `__all__`:** `ColumnRole`
  ([`planner/result.py:30`](../src/bloomery/planner/result.py)), the type of
  `ColumnDescriptor.role` — a root-exported dataclass. It is not deep-importable in the
  supported sense the bullet above describes, because no subpackage declares it. Closure
  reaches it, so it is the fourteenth addition and the one with no fallback path today.
- **`typing.get_type_hints` fails on 7 of the 29 exports** — `compile_project`,
  `build_project_ir`, `plan`, `resolve`, `ColumnDescriptor`, `Resolution`, `RowPolicy` —
  with `NameError`. Each module combines `from __future__ import annotations` with
  `if TYPE_CHECKING:` imports, so the annotation is a string naming something that does
  not exist at run time. Supplying the module globals does not help; the name was never
  imported. This is the mechanism decision 1 proposes to enforce the rule with (§5.1).
- `bloomery.planner.__all__` — 19 symbols, complete for its own surface.
- `bloomery.steps.__all__` — 10 symbols; **`assert_step_contract` is not among them.**
- [`emit/steps.py:246`](../src/bloomery/emit/steps.py) emits
  `from bloomery.steps.contract import assert_step_contract as _blm_assert` into every
  generated Python-model wrapper.
- `QueryPlan.columns` carries `ColumnDescriptor.name` = the *requested* dimension
  (`ordered_month`); MetricFlow's SQL aliases it `order_item__ordered_day__month`
  (RFC 0009 D24, recorded not fixed). There is no `sql_alias` field today.
- `README.md` — *"The API is not stable yet — anything may change before 0.1."* No policy
  describes what stable will mean.
- Versioning primitives already exist: `blm1:` fingerprint prefix, `bloomery_ir_version`
  at **4**, and a version key on every spec kind (§5.5).

## 4. Goals / Non-goals

**Goals**

- One stated rule for what belongs in the root namespace, enforced mechanically.
- No module path outside a declared `__all__` is imported by generated artifacts.
- `QueryPlan.columns` bindable by name, without breaking positional binding.
- Three stability promises written where a consumer will find them.

**Non-goals**

- Scheduling or gating a release. This RFC makes the surface correct; when to publish is
  a separate decision.
- Re-exporting *everything* at the root. Signature closure is deliberately narrower than
  a flat namespace — `bloomery.spec`'s 40-odd spec classes stay where they are.
- Deprecation machinery. Pre-0.1 there is nothing to deprecate; §5.4 specifies the policy
  that will apply, not tooling built now.
- Changing any emitted SQL, any IR shape, or any spec schema.

## 5. Design

### 5.1 Signature closure

**Rule:** if a type appears in the signature of a `bloomery.__all__` symbol — as a
parameter, a return, a generic argument, or an attribute of a returned dataclass — that
type is exported from `bloomery` too.

Applying it mechanically to the current surface yields **fourteen** additions:

| Symbol | Reached via |
|---|---|
| `EmittedArtifact`, `ArtifactKind` | `compile_project` return |
| `NamingPolicy`, `DefaultNaming` | `compile_project(naming=…)` |
| `Catalog` | `load_catalog` return, `compile_project(catalog=…)` |
| `Project` | `load_project` return, `compile_project(project)` |
| `StepRegistry`, `EMPTY_REGISTRY` | `compile_project(steps=…)` |
| `ProjectIR` | `build_project_ir` return, `plan(old, new)` params |
| `Explanation` | `QueryPlan.explanation` |
| `Clause`, `Scalar` | `MetricRequest.filters`, `Predicate.values` |
| `LogicalType` | `ColumnDescriptor.type` |
| `ColumnRole` | `ColumnDescriptor.role` |

**The rule has to terminate, and saying where is part of adopting it.** `ProjectIR` is
on the list, and `ProjectIR` is the root of a deep tree: `EntityIR` → `ColumnIR` →
`DecimalType`, `MartIR` → `MartColumnIR` → `DimensionRef`, and so on. Read as a fixpoint
over dataclass fields, closure pulls **65** names into the root namespace — measured, not
estimated — which is not a public API, it is the IR with a different import path.

So the rule stops at **handle types**: a type a caller receives and passes back without
destructuring. `ProjectIR` is one — `build_project_ir` returns it, `plan()` and
`project_fingerprint()` consume it, and nothing in the documented workflow reads a field
off it. Its internals stay under RFC 0003 and remain deep-importable. Closure descends
through `QueryPlan`, `Explanation`, `ColumnDescriptor`, `Resolution` and `MetricRequest`,
which callers genuinely read, and stops at `ProjectIR`, `Project` and `Catalog`, which
they do not. A handle that later grows a documented field stops being a handle, and the
count moves with it.

**The enforcement mechanism has a prerequisite** (§3): `typing.get_type_hints` raises
`NameError` on 7 of the 29 exports today, `compile_project` among them, because their
annotations are PEP 563 strings naming `TYPE_CHECKING`-only imports. The closure test
cannot walk what it cannot resolve, and resolving it is not a test-side fix — the names
must exist at run time. Lifting the `TYPE_CHECKING` guard on **public** signatures is
therefore the first task of the wave, ahead of the test itself. It costs a handful of
import cycles' worth of care and nothing else; the guards on internal signatures stay.

Errors are the deliberate exception. `errors.py` declares a large hierarchy and
root-exporting all of it would swamp the namespace; the root keeps `BloomeryError` (the
catch-all base) and callers needing a leaf import `bloomery.errors`, which is a declared
`__all__` and therefore a supported path. **The closure test carries an explicit allowlist
for this one case**, so the exemption is visible rather than implicit.

`bloomery.errors` also exports one non-class — `guaranteed` (RFC 0003 D11) — which the
closure walk must skip rather than treat as a type.

### 5.2 `assert_step_contract` is promoted

The strongest finding in this RFC, because the importer is bloomery itself.

RFC 0017's changelog entry already names it *"the only bloomery module intended for
import outside compilation."* It is therefore public in intent, private in declaration,
and shipped into user repositories inside generated wrappers by module path. If
`bloomery/steps/contract.py` were ever renamed or its module layout changed, every
previously-generated artifact in every consumer's repo would break at run time — a
failure mode with no compile-time warning and no test in bloomery that would catch it.

- `assert_step_contract` joins `bloomery.steps.__all__`.
- The generated import becomes `from bloomery.steps import assert_step_contract as _blm_assert`.
- It is **not** root-exported: it is imported by generated code, not by callers, and
  signature closure does not reach it.
- A golden-artifact assertion pins the generated import line, so changing it is a visible
  diff rather than an incident.

`bloomery.steps.contract` keeps working — this adds a supported path, it does not remove
an unsupported one.

### 5.3 `QueryPlan.columns` — additive alias (closes RFC 0009 D24)

```python
@dataclass(frozen=True)
class ColumnDescriptor:
    name: str            # unchanged: the requested dimension or metric ("ordered_month")
    sql_alias: str       # NEW: the alias the emitted SQL actually returns
    type: LogicalType
    role: Literal["dimension", "measure"]
    label: str | None = None
```

`sql_alias` is populated from the same `query_spec` the planner already reads, through
`planner/names.py` — no new MetricFlow surface is touched.

Additive is deliberate over the cleaner alternative (make `name` the alias, add
`requested_name`). Every consumer today binds positionally, which works; the clean version
would break each of them to satisfy a naming preference. The recorded defect is that
by-name binding finds *nothing* — that is fixed either way, and the additive form fixes it
without a migration.

`Explanation` continues to render `name`, since the explanation speaks the caller's
vocabulary. Documented on both fields, so the distinction is discoverable at the point of
confusion.

### 5.4 Stability policy

Three surfaces, three promises. The third is the one consumers get wrong.

| Surface | Promise | Mechanism |
|---|---|---|
| **Python API** — `bloomery.__all__` and each subpackage `__all__` | SemVer. Breaking changes require a major. Deep imports outside a declared `__all__` carry no promise. | The §6 closure test; `__all__` is the contract |
| **Spec YAML** | Per-kind document version, pinned to the version bloomery implements. Additive within a version; a breaking change mints a new version and both are accepted for one minor cycle. | The `<kind>_version` key each document already carries (§5.5) |
| **Emitted artifacts** | **Not stable.** Byte-reproducible for a fixed `(specs, bloomery version, pinned deps)` — the determinism guarantee — but a version bump may legitimately change output. | The `blm1:` fingerprint already stamped in artifact headers |

The third deserves its own paragraph in the docs. Determinism and stability read as the
same promise and are not: bloomery guarantees that *these* inputs always produce *these*
bytes, not that a future version produces the same bytes for the same inputs. A consumer
diffing emitted SQL across a bloomery upgrade should expect changes and review them — that
is what the golden matrix exists to make legible.

`bloomery_ir_version` (currently 4) covers the IR, which is internal; it is named here only
to record that it is *not* one of the three public promises.

### 5.5 The document version keys are already there — and four of them are inert

The draft of this RFC proposed generalizing `steps_version: 1` to the kinds that lacked
it, with "missing key means version 1, so no existing spec breaks". Both halves were wrong
in a way worth recording, because the truth is a live defect rather than a gap.

**Every kind already carries a version key**, and it is not decoration — it is the
document-kind **discriminator**. `spec/project.py` maps `spec_version → EntityModel`,
`mapping_version → Mapping`, `metrics_version → MetricSet`, `marts_version → MartSet`,
`steps_version → StepSet`, and `Catalog` carries `catalog_version`. A document with no
version key is refused: *"unknown spec kind: expected exactly one of …"*. Making the key
optional would not be backward-compatible; it would make a mapping indistinguishable from
a metric set.

What is actually wrong is the opposite of an absence — the keys do not *do* anything:

```text
spec_version: 99      accepted, silently treated as v1
mapping_version: 42   accepted, silently treated as v1
steps_version: 2      refused — "Input should be 1"
```

`steps_version` is `Literal[1]`. The other four are `int` with `ge=1`, so they accept any
future version number and apply v1 semantics to it. A spec written against a bloomery that
does not exist yet is **misread rather than refused**, which is precisely the failure a
version key exists to prevent.

The change is therefore smaller than the draft's and closes something real: pin
`spec_version`, `mapping_version`, `metrics_version` and `marts_version` to `Literal[1]`,
matching `steps_version`. No existing spec breaks — every fixture writes `1` — and the
next breaking spec change has a mechanism that will actually refuse the old reader.

`entity_model`'s key is spelled `spec_version` rather than `entity_model_version`, which
is inconsistent but load-bearing: renaming it is a breaking spec change for no benefit, so
it stays and is documented as the one irregular name.

## 6. Tests

Per RFC 0009 tiers. Everything here is unit-tier — no infrastructure, milliseconds.

| Tier | Test |
|---|---|
| Unit | **Signature closure**: walk every `bloomery.__all__` symbol's signature and dataclass fields via `typing.get_type_hints`; assert each referenced type is in `bloomery.__all__` or on the errors allowlist. Fails on the next symbol added without its types. |
| Unit | Every name in every `__all__` resolves — no stale entries. |
| Unit | The closure walk skips non-class exports (`bloomery.errors.guaranteed`) rather than treating them as types. |
| Unit | `assert_step_contract in bloomery.steps.__all__`. |
| Golden | The generated wrapper's import line is `from bloomery.steps import assert_step_contract as _blm_assert` — pinned in every step fixture's golden artifact. |
| Unit | `ColumnDescriptor.sql_alias` matches the alias in the rendered SQL, per fixture, for a dimension with a role and a time grain (the case D24 found). |
| Unit | Positional binding still works — the D24 status quo does not regress. |
| Unit | Each spec kind refuses a version other than 1, and accepts 1 — the four that currently accept 99 are the point. |
| Unit | A document with no version key is still refused as an unknown kind (the discriminator property, pinned so a future "optional version" change cannot silently break loading). |
| Docs | The stability table appears in `pages/docs/reference/` and the three promises are named. |

The closure test is the load-bearing one. It converts a review discipline nobody can hold
across 24k lines into a build failure.

## 7. Docs

- New `pages/docs/reference/stability.md` — the three surfaces, the deep-import caveat,
  and the determinism-is-not-stability paragraph.
- `pages/docs/reference/api.md` — regenerated against the widened root namespace.
- `pages/docs/concepts/step-registry.md` — the supported import path for
  `assert_step_contract`.
- `README.md` — replace "anything may change before 0.1" with a pointer to the policy
  page, keeping the pre-0.1 caveat.

## 8. Out of scope

- The release itself. This RFC ends at a correct surface.
- Deprecation tooling. Pre-0.1 there is nothing to deprecate; the policy in §5.4 describes
  what will apply.
- A flat root namespace. Signature closure is the rule precisely because it is narrower.
- `bloomery.errors` leaf exports at the root — the allowlist keeps this a decision rather
  than an oversight.
- Renaming `spec_version` to `entity_model_version` (§5.5): a breaking spec change for
  consistency alone.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Signature closure pulls in more than expected as the API grows | That is the intent — it makes surface growth visible at review. If a symbol's types are genuinely internal, the symbol probably should not be root-exported. |
| The closure test is brittle against `from __future__ import annotations` and string annotations | Resolve with `typing.get_type_hints(..., include_extras=True)` against the module globals; a fixture with a forward reference proves the resolution path. |
| `sql_alias` becomes a second thing to keep in sync with MetricFlow's naming | It is read from the same `query_spec` `names.py` already consumes — one source, two presentations, and the §6 test compares against rendered SQL rather than against a second derivation. |
| Pinning the four version keys to `Literal[1]` refuses a spec somebody already wrote | Every fixture and every documented example writes `1`; a spec writing anything else is today being silently misread, which is the defect. |

## 10. Unresolved questions

1. Should `bloomery.planner` and `bloomery.steps` symbols be **re-exported** at the root,
   or does signature closure alone suffice? Closure pulls in `StepRegistry` and
   `Explanation` regardless; the question is whether `MetricFlowPlanner`'s neighbours
   (`Clause`, `parse_filter_json`) belong there too. Leaning: no — subpackage imports are
   a supported, documented path and a flat root namespace obscures the layering.
2. Does the spec-YAML promise cover *refusals*? Adding a new quality rule is additive to
   the schema but may cause a previously-compiling spec to be refused if it collides with
   a reserved name. Probably needs a "reserved names" note per kind.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | **Signature closure** is the root-namespace rule: any type appearing in a public signature, return, generic argument, or returned-dataclass field is itself exported from `bloomery`. **Fourteen** types are added under it (§5.1), the walk stopping at handle types (decision 9). Enforced by a unit test walking `get_type_hints`, not by review — a walk that decision 10 has to make runnable first. |
| 2 | **Errors are the one exemption**, carried as an explicit allowlist in the closure test: the root keeps `BloomeryError`; leaves stay in `bloomery.errors`, which is a declared `__all__` and a supported import path. An exemption in code is visible; an exemption in someone's head is not. |
| 3 | **`assert_step_contract` is promoted to `bloomery.steps.__all__`** and the generated wrapper's import rewritten to the shallow path. The module path was de-facto public API — imported by bloomery's own artifacts shipped into consumer repositories — with no declaration and no test protecting it. `bloomery.steps.contract` keeps working; this adds a supported path rather than removing an unsupported one. A golden assertion pins the emitted import line. |
| 4 | **`ColumnDescriptor` gains `sql_alias`, additively** (closes RFC 0009 D24). `name` keeps meaning the requested dimension; `sql_alias` carries what the SQL returns. Additive beats the cleaner rename because every consumer binds positionally today and the rename would break them all to satisfy a preference; the recorded defect — by-name binding finding nothing — is closed either way. `Explanation` continues to speak `name`. |
| 5 | **Three stability surfaces, stated separately** (§5.4): SemVer over the Python API; per-kind document versioning over spec YAML; and **emitted artifacts are explicitly not stable** — byte-reproducible for fixed inputs and a fixed version, which is determinism, not a cross-version promise. The third gets its own docs paragraph because determinism and stability read alike and are not. |
| 6 | **Deep imports outside a declared `__all__` carry no promise**, stated in the policy. This is what makes decision 3 a fix rather than a courtesy, and what keeps the subpackage layering meaningful. |
| 7 | **The four permissive version keys are pinned to `Literal[1]`**, matching `steps_version`. The draft proposed *adding* keys on the belief that four kinds lacked them; every kind already has one, and the key is the document-kind **discriminator** — a document without it cannot be identified at all, so "missing means 1" would break loading rather than preserve it. The real defect is that `spec_version: 99` and `mapping_version: 42` are accepted and silently read as v1, so a spec written for a future bloomery is misread rather than refused. `spec_version` keeps its irregular name: renaming is a breaking change for consistency alone. |
| 8 | This RFC **does not schedule a release**. The surface is worth being correct independently, and the work is cheapest while nothing is bound to it. |
| 9 | **Closure stops at handle types**, named in §5.1: `ProjectIR`, `Project` and `Catalog` are received and passed back, never destructured, so the walk does not descend into them. Without this the rule is a fixpoint over the whole IR — measured at **65** additions — which would export RFC 0003's internals as public API under a naming rule. The cost is stated: a handle that grows a documented field stops being one, and the export list grows with it. |
| 10 | **The `TYPE_CHECKING` guard is lifted on public signatures before the closure test lands.** `typing.get_type_hints` currently raises `NameError` on 7 of the 29 exports, including `compile_project`, because `from __future__ import annotations` plus a `TYPE_CHECKING`-only import leaves the annotation naming something absent at run time. Decision 1's enforcement is unimplementable until those names are importable at run time — a prerequisite the design did not see, found by running the proposed walk rather than by reading it. Guards on internal signatures are untouched. |

## 12. Phasing

Design locked by this RFC; implementation lands as wave **M15**, ahead of RFC 0019–0022 —
RFC 0020's CLI is a shell over this surface and RFC 0022 adds root exports under
decision 1, so both assume the closure test exists. Independent of RFC 0019 (which moves
internal module paths only, none of them public under decision 6) and of RFC 0021.

Within the wave: the `TYPE_CHECKING` guards on public signatures are lifted first
(decision 10) — without that the test cannot run at all; then the closure test lands
**red**, listing the fourteen additions as its own failure output; then the additions;
then decisions 3–5; then decision 7. Landing the test before the additions is the point —
it proves the rule catches the thing before the thing is fixed.
