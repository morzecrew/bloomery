# Contributing to bloomery

Thank you for your interest in contributing to **bloomery**. This document describes the development workflow, coding conventions, and contribution guidelines.

## Reporting bugs

If you encounter a bug, please report it using the GitHub issue tracker:

https://github.com/morzecrew/bloomery/issues

When reporting a bug, please include:

- steps to reproduce the issue (a minimal spec project is ideal)
- expected behavior
- actual behavior
- relevant error output, stack traces, or the offending emitted artifact
- environment information (bloomery version, Python version, OS)

## Feature requests

Feature requests can also be submitted using the GitHub issue tracker.

Please describe the use case and why the feature would be useful.

## Before a large change: write an RFC

Design decisions in this repository live in `rfcs/` — the RFC corpus is a committed
deliverable, indexed by [`rfcs/INDEX.md`](rfcs/INDEX.md). Before a large change (a new
compile stage, a new emitter target, a change to the IR or the determinism contract),
write an RFC first: it is far cheaper to review a design than to review an implementation
of the wrong design. Small fixes and additions within a live RFC's scope do not need one.

The corpus holds only designs that have not yet landed. **When the work an RFC describes is
complete — or the design is rejected — retire the RFC in the same change**: `git rm` the
file, drop its row from the index, and **add a row to [`rfcs/RETIRED.md`](rfcs/RETIRED.md)**
— number, title, and the SHA of the retiring commit. The code, tests and docs become the
account of shipped behaviour.

**The row lands in a second commit, and it has to.** A commit cannot contain its own SHA, and
amending does not help — amending produces a new commit with a new SHA, so the row would name
one that never existed. So: commit the retirement (`git rm` plus the index row), then commit
the `RETIRED.md` row naming it. Both in the same pull request.

The consequence is worth knowing rather than discovering: **the first of those two commits
does not pass `just quality` on its own**, because its number is briefly neither live nor
retired. CI runs the branch head, so the pair is green; a bisect landing between them is not.
That is the price of a row that names its own retiring commit, and it is cheaper than a row
that names the wrong one.

That table is what makes the citations in this codebase followable: source, tests and docs
cite decisions as `RFC 0016 D84`, and the file that defines D84 is deliberately not in the
tree. `RETIRED.md` maps the number to the commit; `git show <commit>^:rfcs/<file>` prints
the document back.

## Development Setup

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/)
- Docker (optional — only for the opt-in engine matrix and e2e test tiers)

Clone the repository and install all dependencies, including development tools and documentation dependencies:

```bash
git clone https://github.com/morzecrew/bloomery
cd bloomery
uv sync --all-groups
```

### Running Tests

Run the default tiers (unit, golden, property, execution — no Docker needed):

```bash
just test
```

Run a subset:

```bash
just test tests/unit
just test -m property
```

Run the full suite including the engine matrix and target e2e tiers (**requires Docker** —
these tiers start real engines via testcontainers):

```bash
just test-all
```

Regenerate golden artifact files after an intentional compiler behavior change:

```bash
just snapshot-update
```

Golden diffs are reviewed like source code — an unexplained golden diff fails review.
See [tests/README.md](tests/README.md) for the tier table and marker taxonomy.

### Code Quality

Run all quality checks (lint, formatting, types, import contracts, dead code, dependencies, security, workflow lint, secret scanning):

```bash
just quality
```

Strict mode (fail on any issue — this is exactly what CI runs):

```bash
just quality -s
```

`just quality` runs [gitleaks](https://github.com/gitleaks/gitleaks) on the full tree (including `tests/`) via pre-commit. Do not commit real credentials or API keys anywhere in the repository; use synthetic fixtures in tests.

All checks must pass before submitting a pull request.

### Determinism

Compilation is a pure function: same specs in, byte-identical artifacts out. Concretely
(RFC 0003):

- no `datetime.now()`, `time.time()`, `uuid4()`, `random`, `os.environ`, filesystem, or
  network access anywhere under `src/bloomery/` — ruff's `TID251` bans the lot, from the
  `banned-api` table in `pyproject.toml`, as part of the `ruff check "src"` step of
  `just quality`, so CI enforces it rather than only a local commit hook
- never iterate a `set` where order can reach output; IR collections are sorted tuples
- no floats in the IR or emission paths — `Decimal` or int only

The determinism guard test enforces this per-commit by compiling in subprocesses with
different `PYTHONHASHSEED` values.

### Documentation

Documentation lives in `pages/docs/` and is built with [Zensical](https://zensical.org/). See `pages/zensical.toml` for navigation and structure.

Serve the documentation with live reload while editing:

```bash
just serve-docs
```

Diagrams are authored as [d2](https://d2lang.com/) sources under `pages/diagrams/`, one
file per diagram. `just build-diagrams` renders each to a light and a dark SVG under
`pages/docs/_diagrams/`, which is generated and gitignored; `just build-docs` and
`just serve-docs` run it first, so editing a `.d2` and rebuilding is the whole loop.

Embed the pair, never one of them — the site serves whichever matches the reader's theme:

```markdown
![alt text](../_diagrams/light/<name>.svg#only-light){ data-src="../_diagrams/light/<name>.svg#only-light" }
![alt text](../_diagrams/dark/<name>.svg#only-dark){ data-src="../_diagrams/dark/<name>.svg#only-dark" }
```

Consistency:

- Update documentation when behavior changes; keep docs aligned with code.
- Add or update pages under `pages/docs/` and adjust `pages/zensical.toml` navigation as needed.
- Follow markdownlint rules (see `.markdownlint.yaml`) for style consistency.

## Structural contracts

Some invariants are enforced by `just quality` rather than by review, and a change that
breaks one fails the gate with the rule named. Five import contracts run under
`lint-imports`:

- **Layered bloomery compile pipeline** — the package order from `cli` and `planner`
  down to `errors`. A lower layer never imports a higher one. `bloomery.cli` is the top
  layer, so the command line may read the library and no library module may read it
  (RFC 0020 D5).
- **Emitters never import the spec layer** — the emit side consumes IR. That is what
  having an IR is for.
- **Lowering is target-independent** — nothing in `bloomery/emit/lower/` may import
  `emit/sqlmesh`, `emit/dbt`, `emit/cube` or `emit/metricflow`.
- **Targets never import each other** — each assembles from the shared lowering and
  nothing else on the emit side.
- **Lowering stages compose downward** — `predicates` → `silver`/`marts` → `reconcile`
  → `quality_mart`. A stage may read a lower one and never a higher or lateral one.

**Adding a lowering stage** means adding a module under `bloomery/emit/lower/`, placing
it in that layer list, and re-exporting its public names from
`bloomery/emit/lower/__init__.py` — the surface emitters import. If a new stage needs
something from a stage above it, the layering is wrong rather than the contract.

The **purity** half of the gate is the `[tool.ruff.lint.flake8-tidy-imports.banned-api]`
table in `pyproject.toml`, enforced by `TID251` inside the `ruff check "src"` step. It
refuses imports that make I/O possible (`os`, `pathlib`, `requests`, …) and calls that
read a clock or a random source, resolving each name through the import that bound it —
so `from datetime import datetime as dt` followed by `dt.now()` is caught by the entry
that names `datetime.datetime.now`. Compilation takes its inputs as arguments; a clock
read in the package breaks byte-identical recompilation. `tests/` is out of scope — ruff
excludes it, and a test legitimately touches the filesystem.

An exemption is a `# noqa: TID251` on the **one line** that needs it, never a per-file
ignore. `cli/io.py` carries the only one in the tree, on its `pathlib` import — the
command line's single door to a disk (RFC 0020 D12). A file-scoped carve-out would also
exempt a `datetime.now()` in that same file, and reaching a disk justifies nothing about
reading a clock; `RUF100` fails an exemption that has stopped being needed.

## Commit Messages

Commits follow **Conventional Commits** with a **gitmoji** prefix:

```
<gitmoji> <type>[scope]: <description>
```

| Gitmoji | Type | Purpose |
|---------|------|---------|
| ✨ | feat | new features |
| 🚸 | feat | UX improvements |
| 📊 | feat | analytics / tracking |
| 💬 | feat | text / literals |
| 🌱 | feat | seed data |
| 🗃 | feat | database changes |
| 🧵 | feat | multithreading / concurrency |
| 🦺 | feat | validation |
| 🦖 | feat | backwards compatibility |
| 🛂 | feat | authorization / permissions |
| 🧭 | feat | feature flags |
| 🩺 | feat | healthchecks |
| 🥚 | feat | easter egg |
| 💥 | feat | breaking changes |
| 🐛 | fix | bug fix |
| 🚑 | fix | critical hotfix |
| 🩹 | fix | small fix |
| 🚨 | fix | fix linter / compiler warnings |
| 🎯 | fix | catch errors |
| ♻️ | refactor | refactor code |
| 🔥 | refactor | remove code/files |
| 💩 | refactor | bad code needing improvement |
| 🚚 | refactor | move/rename files |
| 🗑 | refactor | deprecate code |
| ⚰️ | refactor | remove dead code |
| 🏗 | refactor | architectural changes |
| 🎨 | style | code formatting / structure |
| ⚡️ | perf | performance improvements |
| 📝 | docs | documentation |
| 💡 | docs | code comments |
| ✏️ | docs | fix typos |
| 🧪 | test | tests |
| 🤡 | test | mocks |
| 📸 | test | snapshots |
| 📦 | build | packages / compiled files |
| ⬆️ | build | upgrade dependencies |
| ⬇️ | build | downgrade dependencies |
| 📌 | build | pin dependencies |
| ➕ | build | add dependency |
| ➖ | build | remove dependency |
| 🧱 | build | infrastructure |
| 👷 | ci | CI configuration |
| 💚 | ci | fix CI build |
| 🔧 | chore | maintenance |
| 🔨 | chore | dev scripts |
| 🙈 | chore | .gitignore |
| 🕵️ | chore | data exploration |
| 🧑‍💻 | chore | developer experience |
| 🔖 | chore | release / version tags |
| 🚀 | chore | deployment |
| 🚧 | chore | work in progress |
| 🔀 | chore | merge branches |
| 🔒 | security | security changes |
| ⏪ | revert | revert commit |

Examples:

```text
✨ feat(guardrails): fail closed on grain fan-out
🐛 fix(emit): stable-sort cube measures before rendering
📝 docs: add the semi-additive metrics concept page
```

Commits may include an optional body after the subject line. The body should be separated from the subject by a blank line and may contain additional context, rationale, or a list of changes.

Guidelines:

- Use **imperative mood** for the description
- Keep the subject line concise (≤72 chars)
- Do not end the subject line with a period
- If additional context is needed, add a body separated by a blank line
- Bullet lists are recommended for describing multiple changes

## Pull Requests

Pull request titles follow the same format as commit messages.

Guidelines:

- Submit **one logical change per pull request**
- Ensure tests and quality checks pass (`just test`, `just quality -s`)
- Rebase or squash commits before merging if needed
- Update documentation when behavior changes
- Regenerate goldens (`just snapshot-update`) in the same PR as the change that moves
  them, and explain the diff — except sqlglot pin bumps, which regenerate goldens in a
  dedicated PR so the rendering delta is reviewable in isolation

## Testing Guidelines

Test layout (six tiers, fastest first — see [tests/README.md](tests/README.md) and RFC 0009):

```text
tests/
  unit/         # tier 1 — mirrors src/bloomery
  golden/       # tier 2 — checked-in artifacts per (fixture × target × dialect)
  property/     # tier 3 — Hypothesis suites
  execution/    # tier 4 — in-process DuckDB execution of compiled SQL
  engines/      # tier 5 — testcontainers engine matrix (Docker, opt-in)
  e2e/          # tier 6 — sqlmesh / dbt / cube acceptance (Docker, opt-in)
  fixtures/     # the shared YAML spec corpus
  support/      # shared helpers (Hypothesis strategies, seeding, extraction)
```

Mirror the `src` structure in `tests/unit` when possible:

```text
src/bloomery/spec/parse.py -> tests/unit/test_spec/test_parse.py
```

Conventions:

- Test files: `test_*.py`; test classes: `Test*`; test functions: `test_*`
- `just test` runs tiers 1–4 (`-m "not engine and not e2e and not perf"`); tiers 5–6
  carry `engine(<name>)` / `e2e` markers and need Docker
- New pytest markers must be registered in `pyproject.toml` before use
  (`--strict-markers` makes an undeclared marker a collection error)
- Fixtures are loaded only through the public `load_project`/`load_catalog` API — the
  corpus doubles as the documentation example set, so it must exercise the surface
  callers use
- Numeric assertions in execution tests use `Decimal`, never float
- Schema goldens live in `tests/golden/schema/` and move when Pydantic renders a
  constraint differently or a transform joins the registry — both intended, both reviewed
  like any other golden diff

## Changelog

User-facing changes must be recorded in `CHANGELOG.md` under the `[Unreleased]` section.

Categories:

- **Added** — new APIs, features, modules
- **Changed** — behavior changes, refactors affecting usage
- **Fixed** — bug fixes

Exclude internal changes such as CI updates, test-only changes, or trivial refactors.

**Keep entries concise.** One bullet = a headline, the key public API/migration, and any
breaking note — not an essay. Leave out the *why*, the implementation mechanics, and
"verified by …" (those live in the PR and commits). Always preserve **breaking** markers
and new public symbol names. Edit only `[Unreleased]` — never rewrite an already-released
version section.

## Release Process

Releases are tag-driven; there are no version strings in the repository.

Creating a tag `vX.Y.Z` (on a commit contained in `main`) triggers GitHub Actions to:

1. Re-run full CI (including the Docker-backed tiers)
2. Assert the hydration budgets — the `perf` lane, blocking here and informational nightly
3. Build the package
4. Publish it to PyPI via Trusted Publishing
5. Create a GitHub release with the matching changelog section
6. Deploy the versioned documentation

**Cut the changelog section before tagging, not after.** `hatch-vcs` derives the version
from the tag, so a section written afterwards describes a release that already shipped —
and step 5 reads `CHANGELOG.md` for a section named exactly `X.Y.Z`, so a missing one
fails the release *after* the PyPI upload, which cannot be taken back. Rename
`[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, open a fresh empty `[Unreleased]` above it, and
add both link references at the foot of the file.

Below 1.0, a breaking change bumps the **minor** — `0.1.x` to `0.2.0`. A patch release
never breaks anything.

## Questions

If you have questions about contributing or the codebase, please open an issue or start a discussion on GitHub.
