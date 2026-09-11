# Reproduce a past artifact set

A number moved and nobody can say why. Half the answer is in the warehouse; the other half
is in your specs, as they stood back then. This is how you get the second half.

bloomery compiles the spec text you hand it. It has no notion of *when* a spec was written,
so "compile March" is not a feature — it is two steps, and only the second one is bloomery's:

1. Fetch the spec text as it stood.
2. Compile it.

## 1. Fetch the text as it stood

This step is yours, because only you know where your specs live. Two shapes, both common.

**From git**, if your specs are committed:

```console
$ git -C . show 'main@{2026-03-01}:specs/metrics.yaml'
```

**From a table**, if you version them in a database:

```sql
SELECT name, body FROM spec_versions
 WHERE valid_from <= '2026-03-01' AND (valid_until IS NULL OR valid_until > '2026-03-01');
```

Object storage, a tarball per release, a config service — all fine. bloomery never sees the
store and has no opinion about it.

!!! note "Which question you are answering"

    This tells you **what your store said the definitions were** on that date. That is not
    the same as what was *true*: a definition changed on the 3rd and committed on the 5th
    reads as the 5th, and nothing can detect it. If your store records an effective date
    separately from a write date, prefer it — and if it does not, say "as recorded" when
    you report the result.

## 2. Compile it

Everything past here is an ordinary compile. `load_project` takes a mapping of document
name to YAML text — the name is the prefix you see in every error message, so keep it the
same as the filename stem.

```python title="reproduce.py"
from bloomery import build_project_ir, compile_project, load_catalog, load_project
from bloomery.ir import project_fingerprint

# whatever your step 1 returned: {"metrics": "...", "entity_model": "...", ...}
project = load_project(sources)
catalog = load_catalog(catalog_text) if catalog_text else None

ir = build_project_ir(project, catalog)
artifacts = compile_project(project, target="sqlmesh", dialect="duckdb", catalog=catalog)

print(project_fingerprint(ir))
for artifact in artifacts:
    print(artifact.path)
```

No filesystem, no clock, no network. The same strings produce the same bytes on any machine,
which is what makes the fingerprint worth comparing at all.

!!! note "If your project wires steps"

    A project with a `steps:` document needs the step manifests too, and those are
    caller-assembled for the same reason the specs are — bloomery reads no registry from
    disk. Pass the one that was in force:

    ```python
    artifacts = compile_project(project, target="sqlmesh", dialect="duckdb",
                                catalog=catalog, steps=registry)
    ```

    Without it the compile refuses rather than guessing: *"no step 'resolve_customers' is
    registered, and the registry is empty"*. Reproducing a past artifact set means
    reproducing the manifests as they stood, not only the specs.

## 3. Compare

Two fingerprints that match mean the definitions did not move, and the number came from the
data. Two that differ mean something in the specs changed, and `plan()` will say what:

```python
from bloomery import plan

report = plan(build_project_ir(load_project(march), catalog), ir)
for change in report.changes:
    print(change.change_class.value, change.subject)
```

`plan()` takes two IRs and does not care where either came from, so comparing two instants
needs nothing beyond step 1 run twice.

## Labels, if you keep several

When you hold more than two of these, name them so they sort: `2026-03-01T00:00:00Z` —
UTC, no offset, no fractional part — not `march` or `old`. bloomery does not read your
labels and will not sort them for you; that is deliberate, because sorting them means owning
time zones, resolution and clock skew over data it did not produce.

Exactly that spelling, rather than "ISO-8601" at large: only the narrow form sorts
lexicographically into chronological order, because `2026-03-01T00:00:00-01:00` sorts
*before* `2026-03-01T00:00:00Z` and is an hour *later*. Holding several of these is also
what [trace a definition over time](trace-a-definition-over-time.md) is for, and it reads
the same labels.

## What this is not

- **Not time travel for the warehouse.** You get March's definitions. What data they read is
  whatever the query runs against today.
- **Not a promise across bloomery versions.** Same specs and the same bloomery reproduce the
  same bytes. A different bloomery may legitimately emit different ones, and a fingerprint
  comparison across versions is meaningless rather than merely noisy.
- **Not a flag.** There is deliberately no `bloomery compile --as-of`. Adding one would
  oblige bloomery to know what a history *is* — which store, how an instant maps to a
  version, what to do when that is ambiguous — and every one of those has a different right
  answer per project. The same reasoning is why there is no `--steps`.
