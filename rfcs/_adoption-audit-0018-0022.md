# Adoption audit — RFCs 0018–0022

Every "Current state" claim in the five drafts was checked against `main` @ `3da72c5`
(2026-08-12) before adoption. This file records what was verified, what was corrected in
the documents, and the one finding that is a defect in the **library** rather than in a
draft.

The corpus is the design authority and code contradicting an accepted RFC is the bug — so
a false claim adopted here would make working code retroactively wrong. That is why this
pass happened before the files landed rather than after.

## Verified correct

- `bloomery.__all__` is exactly the 29 symbols RFC 0018 §3 lists.
- `bloomery.planner.__all__` = 19, `bloomery.steps.__all__` = 10 without
  `assert_step_contract`.
- `emit/steps.py:246` emits `from bloomery.steps.contract import assert_step_contract`
  — the line number is exact.
- All twelve types RFC 0018 proposes to root-export exist and are already in their own
  subpackage `__all__`, so the premise (reachable, but only by deep import) holds.
- `QueryPlan`'s `ColumnDescriptor` has no `sql_alias`: RFC 0009 D24 is genuinely open.
- Every LOC figure in RFC 0019 §3 and RFC 0021 §3 is exact, including the 30,845 test
  lines and the four emitter sizes.
- No CLI, no `[project.scripts]`, no `model_json_schema` anywhere in `src/`.
- `load_project` takes `Mapping[str, str]`; the no-I/O invariant is total.
- MetricFlow ships seven renderers and the four unimplemented are exactly Snowflake,
  BigQuery, Databricks and Redshift.
- `known_divergences.yaml` is `divergences: []`.
- **All five of RFC 0019 §5.2's proposed contracts already hold**, which answers its
  unresolved question 3 (a pre-existing contract-1 violation) without writing them: there
  is none.

## Corrected before adoption

| RFC | Claim as drafted | Correction |
|---|---|---|
| 0018 §3, §5.4 | `bloomery_ir_version` at 3 | It is **4**. PR #13 bumped it on 2026-08-11 for `ProjectIR.coverage` and `MartIR.asserts`. |
| 0018 §3 | `SpecKind` is absent from root, reachable by deep import | `SpecKind` **does not exist**. RFC 0020 §5.1 introduces it. Removed from the list. |
| 0018 §5.1, INDEX | "eleven additions" | The table has **twelve** rows. |
| 0018 §5.5, D7 | Four kinds "gain" a `<kind>_version` key; missing key means 1 | See below — rewritten. |
| 0019 §5.2 | Contract 4 is "the existing layering, now written down" | It is already written down **and enforced**: `pyproject.toml` carries a `layers` contract over the full pipeline. Contract 4 is redundant; contracts 1–3 are genuinely new. |
| 0019 §5.4 | The invariants are "enforced behaviourally today" | A **static** pre-commit `pygrep` hook already bans `datetime.now`, `uuid4`, `time.time(` and `os.environ` under `src/bloomery/`. The real gap is narrower and better: that hook is not a CI gate — `just quality` runs only `pre-commit run gitleaks`. |
| 0019 §10 Q3 | "Unknown until the contract is written" | Answered: no pre-existing violation, verified by grep over the tree. |
| 0020 §3, D7 | `UnknownMember` carries `did_you_mean` | It does **not**. The attribute does not exist; only its docstring mentions one. `UnsupportedFilter.reason` *is* a real attribute, so one of the two cited precedents is real and one is prose. |
| 0020 §5.1 | "the five spec kinds", with a six-member `SpecKind` | Six kinds are loadable (`catalog` via `load_catalog`, five via `load_project`). Wording reconciled. |
| 0018/0019/0021 header | "Verified against `main` @ 2026-08-11" | The LOC figures match 2026-08-12 (`3da72c5`), the `ir_version` figure matches before 2026-08-11. Dated to the tree actually measured. |

RFCs **0021 and 0022 needed no correction**; every claim checked out.

## The finding that is a library defect

RFC 0018 §5.5 proposed generalizing `steps_version: 1` to the other kinds, with "missing
key means version 1, so no existing spec breaks". Both halves are wrong, and the way they
are wrong points at a real defect.

**The version key is the document-kind discriminator.** `spec/project.py` maps
`spec_version → EntityModel`, `mapping_version → Mapping`, and so on; a document carrying
no version key is refused with *"unknown spec kind: expected exactly one of …"*. Making
the key optional would not be backward-compatible — it would make document kinds
unidentifiable. And every kind already has one, so there is nothing to generalize.

What is genuinely wrong is the opposite of an absence:

```
spec_version: 99     accepted, treated as v1
mapping_version: 42  accepted, treated as v1
steps_version: 2     refused — "Input should be 1"
```

`steps_version` is `Literal[1]`; the other four are `int` with `ge=1`. So four of the five
accept **any** future version number and silently apply v1 semantics — which is precisely
the failure the version key exists to prevent. A spec written against a future bloomery
would be misread rather than refused.

D7 is rewritten to that: pin the four permissive kinds to `Literal[1]`, matching
`steps_version`, so a version bloomery does not implement is refused loudly. That is a
smaller change than the draft proposed and it closes a real hole rather than an imagined
one.
