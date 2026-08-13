# Stability

bloomery makes three promises, to three different surfaces. They are not the same
promise, and the third is the one that gets misread.

| Surface | Promise |
| --- | --- |
| **Python API** — `bloomery.__all__` and each subpackage's `__all__` | SemVer. A breaking change requires a major version. |
| **Spec YAML** | Per-kind document versioning. Additive within a version; a breaking change mints a new version. |
| **Emitted artifacts** | **Not stable.** Byte-reproducible for fixed inputs; not comparable across bloomery versions. |

## The Python API

`bloomery.__all__` is the contract. What is in it follows SemVer: a name will not be
removed, and a signature will not narrow, without a major version.

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

## Before 0.1

bloomery is pre-0.1 and **the API is not stable yet**. Anything described here may change
before the first release. The promises above describe how bloomery will behave from 0.1
onward, and are written down now because the surface is cheapest to get right while
nothing depends on it.
