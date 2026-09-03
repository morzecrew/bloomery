# Retired RFCs

Every RFC that has landed or been rejected, and a commit its document can still be read at.

**This is an index, not an archive.** It exists because source, tests and docs cite
decisions by number — `RFC 0016 D84`, `RFC 0010 §5.1` — and those numbers name files that
are deliberately not in the tree ([`INDEX.md`](INDEX.md) argues why). Without this table a
reader following a citation has to know the retirement policy, hold the full history, run
`git log --diff-filter=D -- rfcs/`, and match a number to a filename they have never seen.
With it, they need the number they already had.

## Reading a citation

The filename is not stored — it is derived, which is what keeps this table to three
columns and therefore unable to drift:

```bash
git ls-tree --name-only 33bc4f9 rfcs/ | grep 0016
#   rfcs/0016-data-quality.md
git show 33bc4f9:rfcs/0016-data-quality.md
```

**The commit is one the document still exists at, not the one that deleted it** — so there
is no `^`, and the same two commands work for every row. That is not a cosmetic choice. A
retirement is written in the change that deletes the document, and under squash-merge the
deleting commit does not exist until *after* that change lands: its SHA is the branch's,
which the squash discards. So a column meaning "the commit that deleted it" cannot be
filled in correctly by the change that fills it in — the rule was unsatisfiable, and the
one row ever written to it in flight (0025) recorded a SHA no clone of `main` can resolve.
A commit the document is readable *at* is known before the retirement starts, and stays
true afterwards.

In practice that is the branch point: whatever `main` was when the retirement began.

This needs the git object, and therefore a full clone — `git clone --depth 1`, and the
shallow checkouts most CI jobs get, cannot print the document. What the table gives such a
reader is the title and an exact command to run against a full clone, which is the whole of
what three columns can honestly promise.

## The table

**Number, title, a commit it is readable at — never a summary.** A fourth column describing
what an RFC decided would be a second account of behaviour the code already defines,
drifting from it silently; that is the failure the retirement policy exists to prevent, and
it would arrive here first. Three columns describe no behaviour and so cannot be wrong.

| # | Title | Readable at |
|---|---|---|
| 0001 | Project foundations: packaging, tooling, CI, docs | `33bc4f9` |
| 0002 | Spec layer and error model | `33bc4f9` |
| 0003 | Intermediate representation and determinism contract | `33bc4f9` |
| 0004 | Logical types and the transform registry | `33bc4f9` |
| 0005 | Resolution: dependency DAG, recipes, reachability | `33bc4f9` |
| 0006 | Guardrails: refusing plausible-but-wrong arithmetic | `33bc4f9` |
| 0007 | Plan: spec diff and change classification | `33bc4f9` |
| 0008 | Ports and emitters: targets, dialects, naming | `7ba117b` |
| 0009 | Testing strategy and fixture corpus | `7ba117b` |
| 0010 | Marts and role-playing dimensions | `33bc4f9` |
| 0011 | Native planner: MetricRequest → QueryPlan | `33bc4f9` |
| 0012 | CompiledSemantic: serializable planner artifact | `33bc4f9` |
| 0013 | MetricFlow backend: manifest emitter and planner adapter | `33bc4f9` |
| 0014 | Hydration and caching of the planner artifact | `33bc4f9` |
| 0015 | Query vocabulary: filters, sort, pagination | `33bc4f9` |
| 0016 | Data quality: declarative cleansing, dispositions, quarantine | `33bc4f9` |
| 0017 | The step registry: referenced implementations | `33bc4f9` |
| 0018 | Public surface and stability policy | `7ba117b` |
| 0019 | Lowering decomposition | `ed8d72b` |
| 0020 | Authoring ergonomics: schema export, CLI, fix suggestions | `d5b6f16` |
| 0021 | Capability boundaries: identity resolution, dialects, closed questions | `68353d7` |
| 0022 | `SpecEvidence`: spec analysis as a first-class output | `cc8c691` |
| 0023 | Temporal joins: SCD2 flattening and currency conversion | `aeca6f1` |
| 0025 | v0.1.0 release readiness | `e7f71a4` |
| 0026 | The dbt singular-test surface | `d51daf8` |
| 0027 | ISO 8601 timestamps across dialects | `f4ca53d` |
| 0028 | `timestamp` is zoneless UTC, on every port | `558b31c` |
| 0029 | Transform types the engine agrees with | `558b31c` |
| 0030 | The unresolved-work report | `bcae31d` |
| 0031 | Lineage | `bcae31d` |
| 0032 | Mapping identity | `3f7b574` |
| 0034 | Metrics over time | `6b71926` |
| 0035 | The reject table on a merged entity | `8287f75` |

## Not in the table

The five input documents the corpus grew from — `_original-smelter-spec.md` and the
`_bloomery-*.md` set, removed in `b0c0d3d` — carry no RFC number, so they have no row here.
[`INDEX.md`](INDEX.md) names them in prose, which is where a reader would look for
something that was never numbered.
