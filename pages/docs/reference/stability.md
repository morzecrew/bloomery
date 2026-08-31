# Stability

bloomery makes three promises, to three different surfaces. They are not the same
promise, and the third is the one that gets misread.

| Surface | Promise |
| --- | --- |
| **Python API** — `bloomery.__all__` and each subpackage's `__all__` | SemVer. A breaking change is never silent, and below 1.0 it requires a minor — see [what binds at 0.1](#what-binds-at-01-and-what-waits-for-10). |
| **Spec YAML** | Per-kind document versioning. Additive within a version; a breaking change mints a new version. |
| **Emitted artifacts** | **Not stable.** Byte-reproducible for fixed inputs; not comparable across bloomery versions. |

## The Python API

`bloomery.__all__` is the contract. What is in it follows SemVer: a name will not be
removed, and a signature will not narrow, without a version bump that says so — a minor
while bloomery is below 1.0, a major from 1.0 onward. Either way it is in the changelog
with the migration; the section at the foot of this page is the exact split.

The list is **closed over its own signatures**. If a type appears in the signature of
anything exported — as a parameter, a return, a generic argument, a field of a returned
dataclass, a constructor argument, or a property — that type is exported too. So you can
always name what the API hands you:

```python
from bloomery import compile_project, Catalog, NamingPolicy, EmittedArtifact
```

None of `Catalog`, `NamingPolicy` or `EmittedArtifact` is something you would think to
look for. Each appears in `compile_project`'s signature, so each is public. A test walks
the whole surface and fails the build if a new export arrives without the types it
mentions — the rule is enforced mechanically, not by review.

The walk stops at three **handle types** — `Catalog`, `Project` and `ProjectIR`. You
receive these and pass them back; you do not read fields off them. Descending into
`ProjectIR` would drag the entire intermediate representation into the public namespace,
which is internal and changes freely.

### Deep imports carry no promise

`from bloomery.emit.lowering import something` is not covered. If a name is not in a
declared `__all__`, it can move or disappear in a minor release. Two consequences:

- Anything you need should be reachable from `bloomery` or from a subpackage's `__all__`
  (`bloomery.planner`, `bloomery.steps`, `bloomery.errors`, …). If it is not, that is
  worth reporting — it usually means the closure rule found a gap.
- `bloomery.errors` is a declared `__all__`, so importing a specific error class from it
  is supported. The root deliberately exports only `BloomeryError`, because
  root-exporting the whole hierarchy would swamp the namespace.

One name is public because *generated code* imports it. Step wrappers that bloomery emits
into your repository contain `from bloomery.steps import assert_step_contract`, so that
path is a promise like any other.

## Spec YAML

Every spec document declares its version, and the key also says which kind of document it
is:

```yaml
spec_version: 1       # entity model
mapping_version: 1    # mapping
metrics_version: 1    # metric set
marts_version: 1      # mart set
steps_version: 1      # step set
catalog_version: 1    # catalog
```

The key is required. A document without one cannot be identified, and bloomery refuses it
rather than guessing.

Within a version, changes are additive: new optional fields appear, existing documents
keep loading. A breaking change mints a new version number, and bloomery **refuses** a
version it does not implement rather than reading it as one it does. That refusal is the
point — a spec written for a newer bloomery is a mistake worth stopping, not worth
interpreting.

### The one exception: a new reserved name

There is exactly one way a `spec_version: 1` document that loaded before can stop loading
without a version bump, and it is written down here rather than discovered on upgrade.

bloomery generates columns — `_quality_flags`, `_source_row_id`, `metric_time` and the
rest — and an authored field, dimension or role may not claim one of those names, because
the generated column would collide with it silently. When a release adds a generated
column, its name joins that reserved list, and a project that had already used the name
stops compiling.

**Why this does not mint a new version.** A version bump exists to stop bloomery reading a
document as something it is not, and that risk comes from *meaning* changing under a
stable spelling. A reserved name cannot do that. The document either loads exactly as
before or is refused outright, with a message naming the name, the layer that owns it and
the instruction to rename:

```
'_source' is a reserved name (RFC 0024 D7: the generated union-merge provenance
column); pick a different field/dimension/role name
```

There is no third outcome, no silent reinterpretation, and the fix is a rename the error
states. Minting a version for it would make every author edit every document to record a
collision almost none of them have.

**What it costs, stated rather than buried.** `spec_version: 1` therefore means *your
document keeps its meaning*, not *your document is guaranteed to load*. That is weaker
than the paragraph above reads on its own, and it is the honest boundary.

The exception is bounded and does not widen:

- It covers **adding** a name to the reserved list. Removing one is additive — a name that
  was refused starts working — and renaming a spec key, changing a field's meaning,
  tightening a type, or making an optional key required all still mint a version.
- Every addition appears in `CHANGELOG.md` under **Changed**, naming the reserved name and
  the generated column it protects. A reserved name that arrives without a changelog entry
  is a bug in the release, not an application of this exception.
- The reason string is part of the contract, not decoration. Each reserved name carries one
  (`bloomery.spec.common`), and the refusal quotes it, because "reserved" alone tells an
  author nothing about which layer owns the name or whether it will ever be released.

`spec_version` names the entity model rather than being spelled `entity_model_version`.
That is inconsistent, and it stays: renaming it would break every existing spec to buy
tidiness.

## Emitted artifacts

**The emitted SQL, YAML and manifests are not a stable interface.** Upgrading bloomery may
change them, and that is not a bug.

What bloomery does guarantee is *determinism*: the same specs, the same bloomery version
and the same pinned dependencies produce byte-identical artifacts, across machines,
processes and hash seeds. Every artifact carries a `blm1:` fingerprint header recording
exactly which inputs produced it.

Determinism and stability read alike and are different:

- **Determinism** — *these* inputs always produce *these* bytes. Guaranteed.
- **Stability** — a future version produces the same bytes for the same inputs. **Not**
  guaranteed.

So a diff in emitted SQL after a bloomery upgrade is expected. Review it the way you would
review any generated change; do not treat it as a regression on its own. If you pin
artifacts in your own repository, expect to regenerate them on upgrade.

`bloomery_ir_version` covers the intermediate representation, which is internal. It is
named here only to be clear that it is not one of the three promises above — though a bump
does move every fingerprint, which is deliberate: an IR shape change should be loud.

## Supported dialects

Three ship: **DuckDB**, **PostgreSQL** and **Trino**. Each is a `DialectPort` with a
declared `Feature` set, a column in the golden matrix, and a cell in the engine tier that
runs the emitted SQL against the real database.

Four more are costed and deliberately unbuilt. MetricFlow already ships a renderer for
each, so the work is a port, a golden column and an engine cell:

| Dialect | Estimate | Likely trigger |
|---|---|---|
| Snowflake | ~1 week | Enterprise ask; the most likely first |
| BigQuery | ~1 week+ | GCP ask. Costlier: `STRUCT`/`ARRAY` semantics and the partition model differ most from the shipped three, and it is the one most likely to need a new `Feature` rather than only an implementation |
| Databricks | ~1 week | Existing-lakehouse ask |
| Redshift | ~1 week | Least likely |

**The policy is demand-driven on a named consumer, never speculative.** The point of
costing them without building them is that "we don't support Snowflake" becomes "Snowflake
is about a week" — a different answer, and one that requires writing no code to give.

A new dialect **declares its `Feature` set honestly or is refused**, never silently
approximating. The Postgres `TRY_CAST` is the standard: implemented as a guard around the
engine's own parser rather than as an approximation of one, because a dialect that
approximates a feature produces plausible wrong rows instead of an error. A new port also
inherits its own cost questions — whether its regex engine backtracks decides whether a
`pattern` rule is a denial-of-service surface there, and that belongs in the port's own
assessment rather than being assumed from the three that ship.

## What binds at 0.1, and what waits for 1.0

The promises above are in force from **0.1.0**. They are not all in force to the same
degree, and the difference is what SemVer itself says about versions below 1.0.

| Promise | At 0.1 | At 1.0 |
| --- | --- | --- |
| **Spec YAML** — a document that loads keeps loading; a breaking grammar change mints a new `<kind>_version` | **Fully binding** | Unchanged |
| **Python API** — nothing in an `__all__` moves without a version bump and a changelog entry naming the migration | **Binding: never silent** | **Binding: never breaking outside a major** |
| **Emitted artifacts** — not stable across versions | Binding as stated (it is a *non*-promise, and it does not soften) | Unchanged |

The middle row is the whole split, so it is worth stating without the table:

- **Below 1.0, a breaking change to the Python API may ship in a minor release** — 0.1 to
  0.2 — which is exactly what SemVer reserves the `0.` series for. What binds now is that
  it may never be *quiet*: every breaking change appears in `CHANGELOG.md` with the name
  that moved and what to write instead, and a minor bump is the floor for one. A patch
  release never breaks anything.
- **From 1.0, breaking requires a major version.** That is the promise spec YAML already
  makes in the row above, extended to the Python surface once the surface has been used
  enough to be worth freezing.

Pinning follows from that: pin the minor (`bloomery>=0.2,<0.3`) if you want the API to
hold still, and read the changelog on every minor bump.

**The spec YAML promise does not wait**, and it is deliberately the strong one. A spec is
authored by people and lives in a repository far longer than the library version that
compiled it, so `spec_version: 1` documents keep their meaning — a breaking grammar change
gets a new version number rather than a new bloomery release. Those two clocks are
independent by design. The single exception, a newly reserved name, is
[above](#the-one-exception-a-new-reserved-name); it can refuse a document but never
reinterpret one.

### The installed version

`bloomery.__version__` and `bloomery --version` report the release you have. Both come
from the build rather than from a constant in the source, so they cannot disagree with
the wheel. Quote one of them in a bug report.
