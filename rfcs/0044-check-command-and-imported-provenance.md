# RFC 0044 — `bloomery check` and imported semantic provenance

- **Status:** 📝 Draft — proposed. P1 (native-spec `check`) needs only today's compiler and
  can start once the refusal vocabulary is stable; P2 (mechanical imports) depends on
  [RFC 0039](0039-semantic-proof-ir.md)'s provenance model.
- **Scope:** A low-friction CI command performing semantic validation and proof without
  emission or execution, and a conservative provenance model for importing facts from
  external project artifacts.
- **Related:** [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py) — the
  existing `compile`, `plan`, `resolve`, `lineage`, `explain`, `schema` and `fingerprint`
  commands; RFC 0003 (determinism contract, retired), RFC 0030 (unresolved-work report,
  retired).

---

## 1. Summary

The first adoption surface should not require bloomery to reverse-engineer business
semantics from arbitrary SQL.

```bash
bloomery check <project>
```

meaning: load, resolve, semantic type-check, prove static invariants, report. No target
emission. No warehouse execution. No guessed semantics.

External dbt or MetricFlow artifacts may later contribute facts, but every imported fact
carries provenance and only sufficiently strong provenance participates in correctness
proofs.

## 2. Current state

The CLI already has `compile`, `plan`, `resolve`, `lineage`, `explain`, `schema` and
`fingerprint` (`cli/__init__.py`). There is no `check`, and `resolve` is the nearest thing —
it resolves and reports but is not shaped as a CI gate with an exit-code contract.

Compilation is already pure: no filesystem beyond reading specs, no network, no clock
(RFC 0003). So P1's "must not require credentials or network" is a property the compiler
already has, and this RFC's job is to expose it as a command rather than to establish it.

## 3. `bloomery check`

Deterministic and CI-friendly.

```text
✓ 18 entities resolved
✓ 42 relationships checked
✓ 31 measures type-check
✓ 7 marts safe
✓ 64 requested semantic obligations proven

0 refusals
```

```text
✗ metric gross_margin

currency mismatch:
  revenue  Money<USD>
  cost     Money<EUR>

No declared conversion path EUR -> USD is available.
```

Exact presentation belongs to CLI design; machine-readable output is mandatory.

### Exit codes

`0` when all requested and static obligations are proven; non-zero on at least one refusal
or an invalid project; distinct machine-readable error categories available without parsing
prose. Warnings and advisories do not fail unless an explicit strict policy says so.

### Scope of P1

Native bloomery specs only. It must not require dbt, SQLMesh, warehouse credentials,
network access, or target emission — which makes it suitable for pre-commit and CI.

P1 reports counts for semantic surfaces **actually checked**, not vanity totals: entities,
relationships, measures, marts, conversions, temporal joins, and explicitly configured
metric requests or examples. It does not claim that all possible future queries are proven
merely because the project compiles.

### Machine output

```json
{
  "status": "refused",
  "refusals": [
    {
      "code": "currency_mismatch",
      "subject": "gross_margin",
      "proof_obligation": "compatible_units"
    }
  ]
}
```

Proof and refusal rule IDs align with RFC 0039.

## 4. Why not start with `bloomery check dbt_project/`

Arbitrary dbt SQL often does not declare business grain, measure origin grain, additivity,
unit or currency, SCD interpretation, or intended entity identity. Inferring those facts
heuristically and then using them as proof would violate the closed-world model
(RFC 0039 D1). Import is therefore a separate phase.

## 5. P2 — mechanical imports

Importers may read machine artifacts where a fact has an exact documented mapping:

```bash
bloomery import dbt target/manifest.json
bloomery import metricflow semantic_manifest.json
```

An importer documents, field by field: the source artifact field; the bloomery semantic
fact produced; the transformation; the confidence and provenance class; and the conditions
under which the import refuses.

**No importer may convert absence into a guessed default that strengthens semantics.**

### Overlay model

Imported structure and native declarations compose as an overlay. The likely adoption path
is: import names, relations and types mechanically; author a small bloomery semantic
overlay for grain, additivity and units; run `bloomery check`; optionally compile or plan
through bloomery later.

### Conflict handling

If imported and declared facts conflict, do not pick one silently. Refuse with both
provenances and require an explicit resolution. Declared facts are not automatically "more
true"; they are simply authored, and a contradiction is evidence that the model needs
attention.

## 6. CI integration

```yaml
- name: bloomery semantic check
  run: bloomery check .
```

Bounded, stable output suitable for logs, and a structured artifact suitable for richer CI
annotations.

## 7. Unresolved questions

- **Whether `check` is a new command or `resolve` grown an exit-code contract.** The
  surfaces overlap; two commands that mostly agree is its own defect.
- **What "requested semantic obligations" counts before the planner exists.** §3's fifth
  line has no denominator until RFC 0040 lands, and a count nobody can reproduce is a
  vanity total by another name.

## 8. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **P1 requires no dbt, no SQLMesh, no credentials, no network and no emission.** It is what makes the command usable in pre-commit and on an untrusted CI runner, and every one of those dependencies is easy to acquire accidentally and hard to remove afterwards. The compiler is already pure under RFC 0003; this keeps the command honest to that. |
| 2 | `LOCKED` | **Only `Declared`, `Derived` and narrowly specified `ImportedVerified` facts close a proof obligation.** `InferredHeuristic` produces advisories and never acceptance. This is RFC 0039 D1 restated at the import boundary, which is the one place where relaxing it would be most tempting and least visible — a foreign artifact is exactly where a guessed default enters wearing a fact's clothes. |
| 3 | `LOCKED` | **No importer converts absence into a guessed default that strengthens semantics.** The dangerous direction is specific: a missing additivity becoming `Additive`, a missing grain becoming the entity's. Silence in a foreign artifact means unknown, and unknown is not safe. |
| 4 | `LOCKED` | **A conflict between an imported and a declared fact refuses, naming both provenances.** Neither side wins by default — "declared is more true" is the rule that looks obvious and quietly overwrites a mechanically verified fact with an authored guess. A contradiction is a finding about the model, not a merge to resolve. |
| 5 | `ASSUMED` | **Counts report surfaces actually checked, never totals that imply unproven coverage.** A green `check` must not read as "every future query is safe", which is precisely what a large round number invites. Not `LOCKED` because the right *set* of categories is a presentation question execution may adjust. |
| 6 | `ASSUMED` | **Machine-readable output is mandatory and its refusal codes align with RFC 0039's rule IDs.** One vocabulary for the CLI, the proof IR and the corpus, or the three drift and CI asserts on the weakest of them. |
| 7 | `OPEN` | **Whether `check` is a new command or `resolve` gaining an exit-code contract.** The surfaces overlap substantially and two near-identical commands is its own defect; so is overloading a command whose current output people already parse. Decide it against what `resolve` actually prints today, and log the decision. |
| 8 | `OPEN` | **What the "obligations proven" count means before a planner exists.** Until RFC 0040 lands there is no request surface to count against, and a number nobody can reproduce is the vanity total D5 refuses. Either define the pre-planner denominator or omit the line until there is one. |

## 9. Phasing

**P1 — native `check`.** Deterministic human and machine output, stable refusal codes, a
documented CI exit contract, and nothing outside today's compiler.

**P2 — mechanical imports.** At least one external artifact importer, provenance on every
imported fact, heuristic facts unable to prove safety, explicit conflict refusal, and
adoption through semantic overlays rather than a full DSL migration.
