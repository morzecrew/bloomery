# RFC 0073 — Generating from the spec schema

- **Status:** 📝 Draft
- **Scope:** Reaching the guardrails with generated specs. bloomery exports JSON
  Schema per spec kind, which is a machine-readable grammar of valid input
  already maintained as a feature; this asks what to build on it. The answer
  argued here is **a property-tier generator, not a fuzz target** — the tier that
  already owns valid space, already depends on `hypothesis` and `jsonschema`, and
  already measures schema/parser drift over a fixed corpus. Touches
  `tests/property/` and the dev dependency group; changes no `src/bloomery/` code
  and adds no fuzz target. Gated on RFC 0071 P3.
- **Related:**
  [`tests/property/test_schema_agreement.py`](../tests/property/test_schema_agreement.py)
  (the drift measurement this generalises),
  [`src/bloomery/schema.py`](../src/bloomery/schema.py) (`all_spec_schemas`,
  `spec_json_schema`), RFC 0020 D10 (the schema is a pre-filter; the parser is the
  authority), RFC 0071 §5.6 (the seam this document is decided by), RFC 0072.
- **Origin:** §9 of the external fuzzing note, which proposed schema-directed
  generation as a seventh fuzz target. Its diagnosis holds and its placement does
  not — for reasons the note could not see from outside the repo (§3).

---

## 1. Summary

Random mutation of YAML almost never produces a document that is both
well-formed and schema-valid, so RFC 0071's text-layer targets rarely reach the
guardrails, where the semantic bugs live. Generating documents *from* the
exported JSON Schema fixes that by construction.

This document argues the result belongs in the **property tier**: it generates
valid input, which is that tier's definition, and its most valuable output is a
sharper version of a measurement the tier already makes.

## 2. Motivation

**The guardrails are the under-reached half of the compiler.** Grain fan-out,
additivity, unit mixing, tax-basis collision — the checks bloomery exists for —
sit behind six documents parsing, cross-resolving and type-checking. A mutated
byte string dies long before that. RFC 0071 §5.5 mitigates it with seeds and
dictionaries, and the mitigation has a ceiling: the fraction of mutations that
survive to resolution is small, and shrinks as the spec surface grows.

**bloomery has an unusual asset here.** `bloomery schema` exports JSON Schema per
spec kind, and `all_spec_schemas()` is a library call — a maintained,
machine-readable grammar of valid input, already a shipped feature, requiring no
CLI step and no filesystem to read. Generating from it means **every execution
reaches the guardrails** instead of dying at the parser.

**And the gap it lands in is already named.** RFC 0020 D10 makes the schema a
pre-filter and the parser the authority, and `test_schema_agreement.py` says the
consequence out loud:

> Two validators over one grammar drift. The drift is invisible until it reaches
> a user, and then it reads as bloomery being arbitrary: a proposal loop emits a
> document the schema accepted, the parser refuses it, and nothing in either
> artifact explains why.

That module measures the drift **by mutating a fixed corpus** — an unknown key, a
scalar swapped for a mapping, an out-of-enum value, sampled over the
documentation examples. Generating from the schema measures the same drift over
the *space* rather than over the corpus's neighbourhood. It is the same question
with the sampling fixed.

## 3. Current state

Verified against the tree, and it is the reason this document exists separately
from RFC 0071.

| Fact | Verified |
|---|---|
| `jsonschema>=4.23` is a dev dependency | Yes — annotated *"Test-only, and only for the schema-agreement property (RFC 0020 D10)"* |
| `hypothesis>=6.130` is a dev dependency | Yes; the property tier is eleven modules |
| Schema/parser agreement is already tested | `tests/property/test_schema_agreement.py`, 488 lines |
| It generates from the schema | **No** — it samples a fixed corpus and mutates it |
| The schema is reachable in-process | `all_spec_schemas()` / `spec_json_schema(kind)` |
| Known divergences are recorded | Yes — a float `tolerance`, a free-string metric `agg`, *"named at the bottom of this module rather than tolerated silently"* |

The note, writing from outside, proposed a `fuzz_schema_directed.py` with a
hand-written `generate_from_schema(schema, fdp)` driving every choice from
fuzzer bytes. Both dependencies that generator would need are already installed,
for this exact purpose, in a tier whose stated job is generated valid input.

One external option exists and is not obviously good:
`hypothesis-jsonschema` provides `from_schema()` and satisfies the repo's pins,
but its last release was **February 2024**. §5.3 treats that as a decision rather
than a detail.

## 4. Goals / Non-goals

**Goals**

- Reach the guardrails with generated specs, at a rate mutation cannot achieve.
- Measure schema/parser drift over the generated space, not the corpus's
  neighbourhood, and extend rather than duplicate `test_schema_agreement.py`.
- Keep generated specs runnable in `just test`, so the check fires on every PR
  rather than nightly.

**Non-goals**

- **Finding parser-level bugs.** Schema-valid generation cannot produce input the
  schema forbids, so it will never find them. That is RFC 0071's text layer, and
  §5.4 says the two are run together for that reason.
- **Replacing RFC 0071's targets.** Disjoint bug sets, deliberately.
- **Asserting the parser accepts everything the schema does.** The converse is
  false *on purpose* (RFC 0020 D10): parse validates shape and grammar only, so
  the schema is legitimately stricter wherever it carries a set the parser checks
  later. §5.2 is careful about which direction is asserted.
- **A protobuf mirror of the spec model.** `atheris_libprotobuf_mutator` offers
  structure-aware fuzzing with a mature mutator, at the cost of maintaining a
  second declaration of the spec. For a project already exporting JSON Schema
  that is duplicated effort, and a second grammar that can drift from the first.

## 5. Design

### 5.1 Why the property tier, and not a fuzz target

RFC 0071 §5.6 states the seam as a rule: *the fuzzer owns the text layer and the
accept/refuse boundary; the property tier owns the semantic layer inside valid
space.* Schema-directed generation produces valid input by construction. It is on
the property tier's side of a line this corpus drew before either document
existed, and D1 applies the rule rather than carving an exception into it.

Three consequences, all in the tier's favour:

- **It runs in `just test`**, on every PR, in seconds — not nightly against a
  cached corpus. A cheap check that runs often beats an expensive one that runs
  late.
- **Shrinking.** Hypothesis minimises a failing spec to something a person can
  read. libFuzzer's `-minimize_crash` does this for bytes; Hypothesis does it for
  *structure*, which is what a generated spec is.
- **Zero new infrastructure.** Both dependencies are installed. The fuzz route
  needs a target, a seed corpus, a dictionary and a CI slot to run the same
  generator.

What is genuinely lost is coverage-guided feedback: Hypothesis cannot steer
toward an unexplored guardrail branch the way libFuzzer steers toward an
unexplored line. §10 keeps that open rather than dismissing it, and D5 names the
signal that would reverse this decision.

### 5.2 What is asserted

Two properties over generated documents, and the asymmetry between them is the
whole design:

**Totality.** Any schema-valid document either compiles or raises a
`BloomeryError` carrying a `source_path`. Nothing else. This is RFC 0071 §5.1's
boundary oracle, restated over valid input instead of mutated bytes — and it is
the property that reaches the guardrails, since a generated document that
resolves is one that got far enough to be refused *for a semantic reason*.

**Drift, one direction only.** What the *parser* refuses, the schema should
refuse too — for the mutation classes JSON Schema can express. The converse is
not asserted, for the reason §4 gives. Where a generated document parses and the
schema rejects it, that is a finding; where the schema accepts and the parser
refuses, that is either a known divergence — the float `tolerance`, the free
metric `agg`, both already named — or a new one to name in the same place.

`test_schema_agreement.py` grows a generated-document strategy alongside its
corpus strategy; the existing corpus tests stay, because a corpus of real
documentation examples asserts something a generator does not: that the spelling
the docs teach is accepted.

### 5.3 The generator

`hypothesis-jsonschema`'s `from_schema()` does this off the shelf and satisfies
the repo's existing pins, but has not been released since February 2024. The
alternative is a small hand-written strategy over the subset of JSON Schema
bloomery actually emits — which is narrow, because the schemas are generated from
Pydantic models rather than hand-written, so the vocabulary is closed and known.

The trade is a stale third-party dependency against a maintained local one. D3
leaves it to execution with a stated tiebreak: measure what fraction of generated
documents reach the resolver. A generator that produces schema-valid noise
refused at the first cross-reference has not solved §2's problem, whichever
route produced it — and that measurement, not the dependency's release date, is
what should decide.

### 5.4 Running both, deliberately

Schema-directed generation and RFC 0071's text-layer targets find **disjoint bug
sets**, and the disjointness is structural rather than incidental: one can only
produce input the schema permits, the other mostly produces input it forbids.
Neither subsumes the other, and dropping either because the other is green is the
mistake this section exists to prevent.

One coupling runs between them, in RFC 0071's direction: a minimised corpus entry
that is *valid* and structurally interesting is a free example for this tier
(RFC 0071 §5.6).

## 6. Tests

- **The generator must reach the guardrails, measured.** Report the fraction of
  generated documents that reach resolution and the fraction refused by a
  guardrail rather than the parser. That number is the deliverable — a generator
  that does not move it has not done its job (§5.3), and reporting it is what
  distinguishes this from a check that passes because it never got anywhere.
- **Sabotage.** Widen a guardrail to accept a violation it should refuse; the
  totality property must go red. Same discipline as RFC 0071 §6.
- **The known divergences stay named.** The float `tolerance` and the free metric
  `agg` are asserted as *expected* divergences, so closing one turns the suite red
  and forces the note to be removed rather than left lying.
- **Not tested:** that generated documents are realistic. They are not, and do
  not need to be — RFC 0042's corpus owns production-shaped cases.

## 7. Docs

None user-facing: this generates test input and changes nothing bloomery does.
`tests/README.md` gains the strategy in its property-tier description. If
`hypothesis-jsonschema` is adopted, the dev-group entry carries the same
explanatory comment style `jsonschema` already has — *why* it is there, not just
that it is.

## 8. Out of scope

- **The text-layer targets** — RFC 0071. Explicitly complementary (§5.4).
- **CI scheduling** — RFC 0072. This runs in `just test`, which needs none.
- **Generating *catalogs*.** The catalog is a separate document with a separate
  schema and a different trust story. Reachable by the same mechanism, deferred
  until the project-document generator is earning.
- **Fixing divergences the generator finds.** Each is its own decision — the
  schema tightens, the parser loosens, or the divergence is named. RFC 0020 D10
  owns that call.

## 9. Risks

- **A generator that produces schema-valid noise.** The dominant failure mode:
  documents that pass the schema and die at the first cross-reference, reaching
  the guardrails no more often than mutation did. §6's fraction is the instrument;
  it is reported rather than assumed for exactly this reason.
- **`hypothesis-jsonschema` is unmaintained.** Two years without a release. It
  works today against the repo's pins; a Hypothesis major could end that with no
  upstream to fix it. D3's tiebreak is deliberately about capability rather than
  release cadence, but the risk is real and §5.3 names it.
- **Duplicating `test_schema_agreement.py`.** Two modules asserting overlapping
  things about the same pair of validators is the drift that module exists to
  prevent, reproduced one level up. D2 requires extension, not a sibling.
- **Slow property tests degrade `just test`.** The tier runs on every PR; a
  generator that makes it slow gets deadline-tuned down until it explores nothing.
  Budget it explicitly, and move it to RFC 0072's nightly if it cannot fit.
- **The seam is drawn wrong.** If coverage-guided feedback turns out to matter
  more than shrinking and PR-cadence, this is a fuzz target after all. D5 names
  the signal rather than leaving the decision unrevisitable.

## 10. Unresolved questions

- **Does coverage-guided feedback matter for reaching guardrail branches?**
  Unknown, and the crux of §5.1. Hypothesis explores by generation, libFuzzer by
  feedback; which reaches a deep guardrail faster is an empirical question nobody
  here has measured. §6's fraction, compared against RFC 0071's targets on the
  same corpus, is the measurement.
- **How much of the emitted JSON Schema vocabulary needs support?** The schemas
  are Pydantic-generated, so the vocabulary is closed — but nobody has enumerated
  it. Enumerating it decides §5.3 outright, and is an hour's work.
- **Do generated documents need to be cross-consistent?** A generated
  `marts.yaml` referencing a generated `entity_model.yaml` requires the generator
  to know names in both — otherwise every document is refused at resolution and
  §2's problem is untouched. This is probably the real difficulty of the whole
  document, and it is the one thing schema-directed generation does *not* get for
  free from the schema.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | Schema-directed generation lands in the property tier, not as a fuzz target. It produces valid input by construction, which is RFC 0071 §5.6's definition of that tier's territory; both dependencies are already installed for this purpose; and it gains shrinking and `just test` cadence. Locked because it applies an existing rule rather than making a new one — reversing it means reopening that seam, which D5 provides for. |
| 2 | `LOCKED` | It **extends** `tests/property/test_schema_agreement.py` rather than adding a sibling module. Two modules asserting overlapping things about one pair of validators is precisely the drift that module exists to measure, reproduced one level up. |
| 3 | `OPEN` | `hypothesis-jsonschema` versus a hand-written strategy over the emitted vocabulary. Tiebreak: the fraction of generated documents reaching the resolver (§6), not the dependency's release date. Execution measures and logs it. |
| 4 | `ASSUMED` | Only the parser-refuses-so-schema-should direction is asserted. The converse is false on purpose (RFC 0020 D10) and asserting it would refuse the schema's legitimate strictness. Assumed rather than locked because D10 is the authority here and this row merely inherits it. |
| 5 | `OPEN` | What would move this to a fuzz target after all. The candidate signal is §10's first question resolving against Hypothesis — guardrail branches reached materially faster under coverage feedback. Execution states what it measured, even if the answer is "no evidence either way", so the row is discharged rather than left implicitly open. |
| 6 | `ASSUMED` | Cross-document consistency (§10) is solved by generating names into a shared pool the documents draw from, rather than generating each document independently. Assumed as the obvious shape; depart if it proves to constrain the generated space more than it buys. |

## 12. Phasing

- **P1 — one kind, one property.** A generator for `entity_model.yaml` alone,
  with the totality property, and §6's reach fraction reported. One document
  needs no cross-document consistency, so it settles D3 before D6's harder
  problem is touched.
- **P2 — the project document set.** Cross-consistent generation over the five
  project kinds (D6), which is what actually reaches the guardrails.
- **P3 — the drift property.** The generated-space half of
  `test_schema_agreement.py`, once the generator is known to produce documents
  worth validating twice.

Gated on RFC 0071 P3: the seam in D1 is argued against a fuzz lane that exists,
and the comparison in §10 needs targets to compare against. Nothing here is
gated on RFC 0072.
