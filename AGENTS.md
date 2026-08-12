# bloomery — agent notes

**bloomery** is an entity-first spec compiler: declarative entity/mapping/metric specs are
compiled — as a pure function — into SQLMesh, dbt, and Cube artifacts.

## Design source of truth

The RFC corpus under [`rfcs/`](rfcs/) is the design authority for work **not yet landed**,
indexed by [`rfcs/INDEX.md`](rfcs/INDEX.md). Before a large change, write or amend an RFC;
code that contradicts a live RFC is the bug, not the RFC.

A landed RFC is retired — deleted — in the change that completes it, so that the code, tests
and docs stay the single account of shipped behaviour. Citations like `RFC 0016 D84`
throughout the source therefore name documents no longer in the tree: they record where a
decision came from; `git log --diff-filter=D -- rfcs/` finds the commit that retired the
document and `git show <commit>^:rfcs/<file>` prints it.

## Gates

- `just quality -s` — the single quality authority (lint, format, types, import contracts,
  dead code, dependencies, security, workflow lint, secrets). CI runs exactly this.
- `just test` — default test tiers (unit/golden/property/execution). Engine/e2e tiers need
  Docker: `just test-all`.

## Determinism invariants (RFC 0003 — non-negotiable)

- Compilation does **no I/O**: no filesystem, network, `os.environ` — inputs are strings,
  outputs are artifacts.
- **No ambient nondeterminism**: `datetime.now`, `time.time()`, `uuid4`, `random` are
  banned under `src/bloomery/` (pre-commit pygrep hook enforces).
- **Tuples, not sets**: IR collections are explicitly sorted tuples; never iterate a set
  where order can reach output.
- No floats in IR or emission paths — `Decimal` or int only.
- Same specs in ⇒ byte-identical artifacts out, across processes and hash seeds.

## Commits

Gitmoji + Conventional Commits (`✨ feat(scope): …`) — the vendored
`gitmoji-conventional` skill is the authority; the table lives in
[CONTRIBUTING.md](CONTRIBUTING.md).
