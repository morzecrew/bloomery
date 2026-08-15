# Retired RFCs

Every RFC that has landed or been rejected, and the commit that deleted it.

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
git show --name-only --format= f4ae4a0 -- rfcs/ | grep 0016
#   rfcs/0016-data-quality.md
git show f4ae4a0^:rfcs/0016-data-quality.md
```

Note the `^`: the retiring commit is the one that *deleted* the document, so the content
lives in its parent.

This needs the git object, and therefore a full clone — `git clone --depth 1`, and the
shallow checkouts most CI jobs get, cannot print the document. What the table gives such a
reader is the title and an exact command to run against a full clone, which is the whole of
what three columns can honestly promise.

## The table

**Number, title, retiring commit — never a summary.** A fourth column describing what an
RFC decided would be a second account of behaviour the code already defines, drifting from
it silently; that is the failure the retirement policy exists to prevent, and it would
arrive here first. Three columns describe no behaviour and so cannot be wrong.

| # | Title | Retired in |
|---|---|---|
| 0001 | Project foundations: packaging, tooling, CI, docs | `f4ae4a0` |
| 0002 | Spec layer and error model | `f4ae4a0` |
| 0003 | Intermediate representation and determinism contract | `f4ae4a0` |
| 0004 | Logical types and the transform registry | `f4ae4a0` |
| 0005 | Resolution: dependency DAG, recipes, reachability | `f4ae4a0` |
| 0006 | Guardrails: refusing plausible-but-wrong arithmetic | `f4ae4a0` |
| 0007 | Plan: spec diff and change classification | `f4ae4a0` |
| 0008 | Ports and emitters: targets, dialects, naming | `ed8d72b` |
| 0009 | Testing strategy and fixture corpus | `ed8d72b` |
| 0010 | Marts and role-playing dimensions | `f4ae4a0` |
| 0011 | Native planner: MetricRequest → QueryPlan | `f4ae4a0` |
| 0012 | CompiledSemantic: serializable planner artifact | `f4ae4a0` |
| 0013 | MetricFlow backend: manifest emitter and planner adapter | `f4ae4a0` |
| 0014 | Hydration and caching of the planner artifact | `f4ae4a0` |
| 0015 | Query vocabulary: filters, sort, pagination | `f4ae4a0` |
| 0016 | Data quality: declarative cleansing, dispositions, quarantine | `f4ae4a0` |
| 0017 | The step registry: referenced implementations | `f4ae4a0` |
| 0018 | Public surface and stability policy | `ed8d72b` |
| 0019 | Lowering decomposition | `d5b6f16` |
| 0020 | Authoring ergonomics: schema export, CLI, fix suggestions | `bde63f2` |
| 0021 | Capability boundaries: identity resolution, dialects, closed questions | `828fd5b` |
| 0022 | `SpecEvidence`: spec analysis as a first-class output | `68353d7` |

## Not in the table

The five input documents the corpus grew from — `_original-smelter-spec.md` and the
`_bloomery-*.md` set, removed in `b0c0d3d` — carry no RFC number, so they have no row here.
[`INDEX.md`](INDEX.md) names them in prose, which is where a reader would look for
something that was never numbered.
