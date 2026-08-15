<!--
Title: <gitmoji> <type>[scope][!]: <description>   (gitmoji-conventional)
Below 1.0: a breaking API change may ship in a minor release, but never silently —
it needs a CHANGELOG entry naming what moved and what to write instead.
-->

## Summary

<!-- What changed and why, in 2–4 sentences. -->

Closes #
RFC: <!-- rfcs/NNNN -->

## Type

- [ ] Feature
- [ ] Fix
- [ ] Refactor (no behaviour change)
- [ ] Docs
- [ ] Chore / CI / dependencies
- [ ] Breaking change

## Determinism

- [ ] No clock, RNG, `uuid`, environment read, or filesystem access added
- [ ] Compiled the same specs twice in separate processes under different
      `PYTHONHASHSEED` — output byte-identical
- [ ] Every newly emitted collection has an explicit, total sort key
- [ ] No `set` iteration order and no `dict` insertion order is load-bearing
      in emitted output

## Semantics

- [ ] Guardrail violations still fail closed with a named reason — no path
      added where a wrong number can pass silently
- [ ] Grain, additivity, and contract behaviour unchanged
- [ ] Changed intentionally — stated here and in the RFC:

## Targets & dialects

Touched: [ ] spec layer  [ ] IR  [ ] SQLMesh  [ ] dbt  [ ] Cube  [ ] planner

Exercised on: [ ] duckdb  [ ] trino  [ ] postgres

- [ ] One emitter changed alone, and that asymmetry is intentional
- [ ] Cross-target equivalence considered

## RFC alignment

- [ ] Consistent with the accepted RFC
- [ ] The RFC is amended in this PR — code contradicting an accepted RFC is
      the bug, not the RFC

## Verification

- [ ] `just ci` green; new behaviour seen red before it went green

Test tiers run:

## API

- [ ] Public signature change — recorded in `CHANGELOG.md` `## [Unreleased]`

## Golden artifacts

<!-- If emitted artifacts changed, say in one sentence what semantic change
     the diff represents. A diff nobody can summarise is a diff nobody reviewed. -->