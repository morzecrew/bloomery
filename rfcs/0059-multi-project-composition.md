# RFC 0059 — Multi-project composition

- **Status:** 📝 Draft — the large one. Schedulable in the sense that it is not blocked on
  another design, and not small: it is the only member of the platform-metadata split that
  changes what a *project* is.
- **Scope:** One project reading entities, marts or metrics that another project declares
  — dbt's cross-project `ref()`, and the general question underneath it. Covers what
  crosses the boundary, what a fingerprint means when it does, and which refusals become
  possible when the graph spans two documents sets. Deliberately does **not** cover
  packaging, registries or distribution.
- **Related:** [`src/bloomery/compile.py`](../src/bloomery/compile.py),
  [`src/bloomery/resolve/build.py`](../src/bloomery/resolve/build.py),
  [`src/bloomery/guardrails/lineage.py`](../src/bloomery/guardrails/lineage.py),
  [`src/bloomery/plan/`](../src/bloomery/plan/),
  RFC 0003 (determinism — the constraint that shapes every option here),
  RFC 0018 (public surface and stability policy; retired at `7ba117b`).
- **Origin:** The ceiling review's third item. Split out because it is the only member
  that is *large* rather than blocked, duplicated or refused — and because grouping it
  with owner tags made the whole line unschedulable.

---

## 1. Summary

`compile_project` takes one directory of documents and returns artifacts. There is no way
for a project to say "this entity is defined over there", so a platform team publishing
conformed dimensions and a domain team building marts on them have to be one spec
directory or two disconnected ones.

The question this RFC answers is not "how do we resolve a cross-project reference" — that
is a dictionary lookup. It is **what may cross the boundary, and what a compile means when
something does.** A compiler whose determinism guarantee is byte-identical artifacts from
identical inputs has to say precisely what the inputs are once one project reads another,
and that is the whole design.

## 2. Motivation

**The single-project assumption is load-bearing in three places and stated in none.**
`load_project` reads one directory; `build_project_ir` resolves every reference within one
`ProjectIR`; `project_fingerprint` hashes one project's IR. Each is correct and none says
"one project" as a decision.

**dbt has the feature and its shape is instructive.** Cross-project `ref()` resolves
through a *manifest* of the upstream project — a build artifact, not source. That is the
right shape for bloomery too and it has a consequence RFC 0003 cares about: the upstream
input to a compile is then a file, and a compile that reads a file is a compile whose
determinism depends on which version of that file it read.

**The refusals get better, which is the part worth building for.** Today a domain project
declaring its own `customer` entity beside the platform's is two entities that happen to
share a name, and nothing notices. With composition, that is a collision the guardrail
stage can refuse — and `bloomery plan` can say that changing the platform's `customer`
grain breaks four downstream projects, which is the question a platform team actually has.

**It is large, and pretending otherwise is how it gets started badly.** It touches
loading, resolution, lineage, fingerprinting, `plan()`, and every emitter's reference map.
Naming that here is most of what this document is for.

## 3. Current state

Verified against the tree.

- **`load_project`** reads a directory keyed by filename stem; a catalog is recognised by
  name and refused inside the project. One directory, one project.
- **`build_project_ir`** resolves entity, mart and metric references against the IR it is
  building. An unknown name is a refusal, and the refusal assumes the name should have
  been local.
- **`project_fingerprint`** hashes the canonical serialized `ProjectIR`, including
  `bloomery_ir_version` — not the spec documents. It is the value every artifact header
  carries and the thing "same specs in ⇒ byte-identical artifacts out" is about, one step
  removed: two document sets that resolve to one IR share a fingerprint, and a bloomery
  version bump moves every fingerprint by design (RFC 0003 D3).
- **Lineage node ids** are `<kind>.<name>` — `metric.gross_revenue`, a dot — with no
  project component, so two projects'
  graphs cannot be composed without collision — `check_lineage_names` reserves the kind
  prefixes and knows nothing about a project prefix.
- **Emitter reference maps** are keyed `(namespace, relation)` and produce `ref()` /
  `source()`. A cross-project reference on dbt is a *different* call shape
  (`ref('project', 'model')`), so this is not a lookup-table change.
- **`Target.SQLMESH`** has no cross-project concept at all; SQLMesh composes by config,
  not by reference.

## 4. Goals / Non-goals

**Goals**

- A project may declare a dependency on another project's **published surface**, and
  reference entities, marts and metrics from it.
- The published surface is explicit: an upstream project says what it exports. A
  reference to something not exported is refused, naming the export list.
- Determinism holds, with the upstream input named in the fingerprint (§5.3).
- Cross-project name collisions and grain conflicts become refusals.
- `plan()` answers "what does changing this break", across the boundary.

**Non-goals**

- **A registry, a package manager, or distribution.** How the upstream artifact reaches
  the downstream compile is the caller's problem — a path, a checkout, a CI artifact.
  bloomery reads what it is handed.
- **Reading over a network.** RFC 0003. The upstream input is a value passed to
  `compile_project`, exactly as a `StepRegistry` is.
- **Cycles.** Two projects importing each other is refused, not resolved.
- **Cross-project *quality* composition.** An upstream entity's reject table stays
  upstream. A downstream project reads the entity, never its quality surface.
- **Runtime federation.** Both projects still compile to relations in one warehouse.

## 5. Design

### 5.1 What crosses

An **export list**, declared upstream. Not "everything public by default": a project that
exports its whole spec has no boundary, and the first refactor breaks four teams. What may
be exported is an entity, a mart or a metric — never a mapping, a step, or a quality
surface, because those are how a thing is built rather than what it is.

### 5.2 How it is handed over

A compiled artifact of the upstream project — its IR, serialized — passed to
`compile_project` as an argument, the way a `StepRegistry` already is. Not a path bloomery
opens (RFC 0003), and not the upstream's spec documents, because re-resolving them
downstream would make the downstream compile depend on the upstream's *mappings*, which
§5.1 says are not part of the boundary.

This is the same shape as dbt's manifest and for the same reason: the boundary is what was
built, not what was written.

### 5.3 Fingerprints, which is the real decision

"Same specs in ⇒ byte-identical artifacts out" needs "specs" to include the upstream. So
the downstream fingerprint is over its own IR **and** the upstream fingerprint — both
being IR fingerprints, which is what makes composing them meaningful: an upstream whose
documents were reformatted but whose IR did not move disturbs nothing downstream —
which is already a value, already in every upstream artifact header, and already exactly
"what the upstream compiled to".

The consequence, stated because it will surprise someone: an upstream change that alters
nothing the downstream reads still moves the downstream fingerprint. That is the honest
answer — the fingerprint is an identity, not a diff — and the alternative, hashing only
the exports the downstream touched, makes the fingerprint depend on analysis and stop
being a cheap identity.

### 5.4 Node ids and refusals

Lineage node ids gain a project component for imported nodes. `check_lineage_names`
extends to refuse a local name colliding with an imported one, which is the refusal §2
names as the payoff.

Grain conflict is the second: a downstream mart over an imported entity is at that
entity's grain, and RFC 0010's rule applies across the boundary unchanged.

### 5.5 Targets

- **dbt**: `ref('upstream_project', 'model')`, plus the `dependencies.yml` entry that
  makes it resolvable. A different call shape from the local `ref()`, so the reference map
  gains a project component rather than a special case.
- **SQLMesh**: the imported relation is named directly. SQLMesh has no cross-project
  reference, and the relation exists in the warehouse under the naming policy both
  projects share — which is a *constraint* worth stating: two projects composing must
  agree on a naming policy, or the downstream names relations the upstream never created.
- **Cube / MetricFlow**: an imported mart is a mart. Nothing special.

## 6. Tests

- **Unit:** export-list enforcement, collision refusal, cycle refusal, grain conflict
  across the boundary.
- **Fingerprint:** the downstream moves when the upstream does, and is byte-identical
  when neither moves — the §5.3 decision as a test rather than a paragraph.
- **Golden:** a two-project fixture, both projects' artifacts.
- **e2e:** `dbt parse` over the pair with `dependencies.yml`, because a cross-project
  `ref()` that resolves in bloomery and not in dbt is the failure mode that matters.
- **A test that a single-project compile is byte-identical to today.** The whole corpus
  is that test, and it is named here because "no existing project changes" is the claim
  most worth pinning in a change this size.

## 7. Docs

- A how-to: publishing a surface, and consuming one.
- The determinism page: §5.3's consequence, in the section that defines what "same specs"
  means.
- The naming page: the shared-policy constraint from §5.5.

## 8. Out of scope

- Registries, packaging, versioning of the exported surface beyond the fingerprint.
- Network access of any kind.
- Cross-project quality surfaces (§4).
- The other four members of the platform-metadata split.

## 9. Risks

- **Fingerprint churn.** §5.3 makes every upstream change move every downstream
  fingerprint, which means artifact headers change on projects nothing about which
  changed. Acceptable and surprising; the docs have to meet it head on.
- **Naming-policy coupling.** §5.5 requires two composing projects to agree on a naming
  policy, and nothing enforces it. A refusal is possible only if the upstream IR records
  the policy it was compiled under — worth deciding at build time rather than discovering.
- **Scope creep into a package manager.** "How do I get the upstream artifact" is a real
  question with a tempting answer. The non-goal is the mitigation and it will be tested.
- **The blast radius is the whole compiler.** Loading, resolution, lineage,
  fingerprinting, planning, three emitters. This is the risk that argues for §12's
  ordering — refusals before references.

## 10. Unresolved questions

- Whether the upstream IR should carry its naming policy, so a mismatch is a refusal
  rather than a run-time surprise (§9).
- Whether a downstream project may *extend* an imported entity — adding fields — or only
  read it. Extension is what people will want and it makes the boundary a subclassing
  relationship, which is a much larger claim.
- Whether `bloomery resolve` should report imported-but-unused exports. It is the
  upstream's dead code, visible only downstream.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | The boundary is an **explicit export list**, never "everything by default". A project that exports its whole spec has no boundary, and its first refactor breaks every consumer. |
| 2 | `LOCKED` | What crosses is the upstream's **compiled IR**, passed as an argument — not its spec documents, and not a path bloomery opens. Mappings, steps and quality surfaces are how a thing is built, not what it is, and re-resolving upstream documents downstream would put all three inside the boundary. |
| 3 | `LOCKED` | The downstream fingerprint includes the upstream fingerprint whole. An upstream change that touches nothing the downstream reads still moves it — a fingerprint is an identity, and making it depend on which exports were touched makes it depend on analysis. |
| 4 | `LOCKED` | Import cycles are refused, not resolved. |
| 5 | `LOCKED` | Quality surfaces do not cross. An upstream entity's reject table, replay and quality mart stay upstream; the downstream reads the entity. |
| 6 | `ASSUMED` | Lineage node ids gain a project component for imported nodes only. Local ids keep their spelling, so every existing id and every published citation stays valid. |
| 7 | `ASSUMED` | Two composing projects must share a naming policy. Whether that is enforced depends on §10's first question. |
| 8 | `LOCKED` | No registry, no packaging, no network. How the upstream artifact reaches the compile is the caller's, exactly as a `StepRegistry` is. |

## 12. Phasing

Five commits, refusals first — the ordering exists because the refusals are cheap and the
references are not, and a half-built boundary that resolves without refusing is worse than
none:

1. **The export list**, upstream only. A project declares what it exports; nothing
   consumes it yet. Additive, no downstream concept.
2. **The import declaration and the refusals** — unknown export, cycle, collision, grain
   conflict. Still no emitted reference: a downstream project can be refused before it can
   be compiled.
3. **Resolution and lineage** — imported nodes in the graph, node ids with a project
   component.
4. **The fingerprint**, with §5.3's test.
5. **Emitters** — dbt's `ref('project', 'model')` and `dependencies.yml`, SQLMesh's direct
   relation, and the corpus-wide assertion that a single-project compile did not move.
