# RFC 0001 — Project foundations: packaging, tooling, CI, docs

- **Status:** 📝 Draft
- **Scope:** Everything that is not compiler code: repository layout, packaging
  (uv + hatchling + hatch-vcs), quality tooling (ruff, mypy strict, import-linter, vulture,
  deptry, bandit, zizmor, pre-commit), the `justfile`, GitHub workflows, documentation
  infrastructure (`pages/` on zensical + mike), community files (CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, CODEOWNERS, CHANGELOG), and the RFC process itself. No compiler design — that is
  RFCs 0002–0009.
- **Related:** House conventions ported from the sibling repos
  `~/GitLibrary/Morze/forze` (Python reference) and `~/GitLibrary/Morze/morzer`
  (meta-conventions); [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §2, §10.
- **Origin:** forze's scaffold, collapsed from a 29-package monorepo to a single-package
  library.

---

## 1. Summary

`bloomery` adopts the Morze house scaffold wholesale, scaled down: src layout with a single
`src/bloomery/` package, uv-managed with PEP 735 dependency groups, git-tag versioning via
hatch-vcs, a `just quality` gate that runs identically locally and in CI, seven SHA-pinned
GitHub workflows, zensical docs under `pages/` deployed with mike, and committed `rfcs/`
with the INDEX convention.

## 2. Motivation

The compiler's value proposition is trust — determinism, fail-closed guardrails,
reviewability. A repo whose CI can drift from local checks, whose actions are tag-pinned, or
whose coverage authority is an external service undermines that story before the first
release. forze has already paid the iteration cost on this scaffold; diverging from it
needs a reason, and there is none.

## 3. Current state

The repo contains: vendored agent skills (`.agents/skills/`, `skills-lock.json`,
`.claude/skills` symlink), a GitHub-template Python `.gitignore`, MIT `LICENSE`, a 2-line
`README.md`, an **empty** `justfile`, empty `src/ tests/ pages/ .github/` directories, and a
`.vscode/settings.json` copied verbatim from the Go repo morzer (excludes `go.sum`,
`morzer.key` — to be replaced). Nothing else.

## 4. Goals / Non-goals

**Goals**

- Local `just quality -s` ≡ CI quality job, byte-for-byte the same commands.
- Release = pushing a `vX.Y.Z` tag; no version strings in the repo.
- Every workflow action SHA-pinned; every job hardened (`step-security/harden-runner`).
- Docs versioned per minor release, deployed to `gh-pages`.

**Non-goals**

- forze's sharded CI matrix, conformance census, DST campaigns, perf-gate burn-in — a
  single-package pure library doesn't need them at birth; the ratchet scripts can arrive
  with scale.
- devcontainer — nothing here needs Docker except opt-in engine tests.

## 5. Design

### 5.1 Layout

```
AGENTS.md                # CLAUDE.md -> AGENTS.md (symlink)
CHANGELOG.md             # Keep a Changelog 1.1.0, SemVer
CODEOWNERS               # * @misery7100
CODE_OF_CONDUCT.md       # Contributor Covenant 2.1
CONTRIBUTING.md
LICENSE                  # MIT (exists)
README.md
SECURITY.md              # private disclosure to misery7100@gmail.com
justfile
pyproject.toml
uv.lock
.pre-commit-config.yaml
.markdownlint.yaml
.github/{workflows,scripts,ISSUE_TEMPLATE,dependabot.yml,codeql/}
src/bloomery/
tests/{unit,golden,property,execution,engines,e2e,fixtures,support}/
examples/                # quickstart specs, tested
pages/{zensical.toml,docs/}
rfcs/                    # COMMITTED (unlike forze) — the RFC corpus is a deliverable here
```

### 5.2 pyproject

- Build: `hatchling` + `hatch-vcs`, `version-file = "src/bloomery/_version.py"`
  (gitignored). `requires-python = ">=3.12,<3.15"` — the original spec promises 3.12; CI
  tests 3.12–3.14.
- Runtime deps (RFC 0002 D5 adds PyYAML to the spec's list): `pydantic>=2.9`,
  `sqlglot` (exact-pinned in `uv.lock`, `>=X,<X+1` in metadata per RFC 0003 D2 §5.5),
  `jinja2>=3.1`, `pyyaml>=6`.
- `[dependency-groups]` — `dev`: pytest (+cov, xdist, timeout, mock), hypothesis,
  pytest-snapshot, duckdb, sqlmesh, ruff, mypy[faster-cache], import-linter, vulture,
  deptry, bandit, pre-commit, zizmor, radon; `engines`: testcontainers[postgres];
  `docs`: zensical, mike (squidfunk fork, commit-pinned), pymdown-extensions, pygments.
- Tool tables copied from forze with package lists collapsed: pytest
  (`--strict-markers --strict-config`, `pythonpath = ["src", "tests"]`, timeout 300,
  markers from RFC 0009), coverage (`branch = true`, `fail_under = 80`,
  `relative_files = true`, ellipsis-stub excludes), mypy `strict = true`, ruff
  line-length 100 with forze's select/ignore sets, vulture, deptry, radon.
- import-linter contracts encode the compiler's layering (spec §10):
  `emit`/`dialects` may import `ir`/`typing`/`errors` but never `spec`;
  `spec` imports nothing internal but `errors`; `resolve`/`guardrails`/`plan` sit between.
  This mechanically enforces "emitters consume IR, not specs."

### 5.3 justfile

forze's header idioms verbatim (`set quiet`, `_uv_cmd` ✅/❌ helper, `_default` listing),
with morzer's convention of a prose comment above each recipe. Recipes:

| Recipe | Does |
| --- | --- |
| `test *args` | `uv run pytest -m "not engine and not e2e and not perf"` |
| `test-all` | full suite including engine/e2e (Docker required) |
| `quality strict="false"` | ruff check/format, mypy, lint-imports, vulture, deptry, bandit, zizmor, gitleaks |
| `snapshot-update` | regenerate golden files (RFC 0009) |
| `coverage` | pytest with `--cov=src` + `fail_under` gate |
| `serve-docs` / `build-docs` | zensical in `pages/` |
| `worktree branch` | `git worktree add ../worktrees/bloomery-<branch>` |

### 5.4 Workflows

Seven, filenames matching the house set: `ci.yml`, `codeql.yml`, `dependency-review.yml`,
`docs-dev.yaml`, `docs-release.yaml`, `release.yaml`, `scorecard.yaml`. House rules apply to
all: workflow-level `permissions: contents: read` widened per job; every job opens with
`step-security/harden-runner` (egress audit); every `uses:` SHA-pinned with a `# vX.Y.Z`
comment (pins copied from forze's current workflows); shared logic in `.github/scripts/`;
zizmor-clean.

`ci.yml`, scaled to a single package: `changes` (paths-filter) → `quality`
(`just quality -s`) → `test` (matrix over Python 3.12/3.13/3.14, DuckDB in-process; single
job, no sharding) → `coverage` (`--fail-under=80`, Codecov informational-only per morzer's
doctrine — the gate is ours, not the service's) → `required-ci` aggregator (`if: always()`,
no checkout) as the sole branch-protection check. Engine/e2e tiers run in a separate
`nightly.yml`-style schedule job inside `ci.yml` (`schedule:` + `workflow_dispatch`), not
per-commit.

`release.yaml`: tag `v*` → reuse `ci.yml` → `ensure-tag-on-main.sh` → `uv build` → PyPI
Trusted Publishing (`id-token: write`, environment `pypi`) → GitHub Release with the
changelog section extracted by `mindsers/changelog-reader-action`.

`dependabot.yml` copied wholesale: `uv` + `github-actions` ecosystems, weekly, cooldown
7/14 days, gitmoji commit prefixes.

### 5.5 Docs

zensical + mike on `gh-pages`, `pages/zensical.toml` with explicit nav following Diátaxis:
Home / Get Started (introduction, installation, quickstart) / Concepts (specs & the catalog,
compile pipeline, determinism, guardrails) / How-to (emit per target, evolve a spec) /
Reference (spec schemas, transforms, errors, API). Diagrams: **mermaid, not d2** — morzer's
retreat from d2 ("removed a CI binary and a build step") is the right default for a new
repo; d2 remains available if diagrams outgrow mermaid. Docs floors (link + nav integrity
checker under `.github/scripts/`) arrive with the first release, not day one.

### 5.6 Process files

- **CONTRIBUTING.md**: forze's structure + morzer's "Before a large change: write an RFC"
  section pointing at `rfcs/INDEX.md`.
- **Commits**: gitmoji + Conventional Commits (the vendored `gitmoji-conventional` skill is
  the authority); dependabot configured to match.
- **CHANGELOG.md**: Keep a Changelog 1.1.0 preamble verbatim from forze.
- **pre-commit**: gitleaks, end-of-file-fixer, trailing-whitespace, ruff-check/format on
  `src/`, plus pygrep bans as local hooks — bloomery's package-specific bans:
  `datetime.now`, `uuid4`, `time.time`, `os.environ` under `src/bloomery/` (RFC 0003 §5.5
  determinism rules made mechanical).
- **`.vscode/settings.json`**: replaced with forze's Python variant (strict pyright
  editor-only, ruff formatter, `extraPaths: ["src"]`).

## 6. Tests

The scaffold is itself tested where it can be: `tests/unit/test_determinism_guard.py`
(RFC 0003), a CI-matrix guard is unnecessary without sharding; zizmor covers workflows;
`just quality -s` is the meta-test.

## 7. Docs

This RFC *is* the docs-infrastructure decision record; the pages themselves ship with each
milestone per the Docs sections of RFCs 0002–0009.

## 8. Out of scope

- **Docs floors script, per-package coverage floors, perf gate** — ratchets need something
  to ratchet; they land at v0.1.0 release, not scaffold time.
- **OpenSSF Scorecard badge chasing** — the workflow ships; badge curation later.
- **devcontainer / Docker tooling** — engine tests document their Docker requirement
  instead.

## 9. Risks

- *Convention drift from forze over time* — accepted; forze is a reference, not a
  dependency. Where bloomery diverges deliberately (committed `rfcs/`, mermaid, no
  sharding), this RFC records it so the divergence is not read as accident.
- *hatch-vcs + no tags yet* → dev versions like `0.1.dev0+g<sha>` until the first tag;
  harmless.

## 10. Unresolved questions

- GitHub org/repo slug (assumed `morzecrew/bloomery` for URLs; trivially fixable at push
  time).

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | House scaffold adopted from forze; deliberate divergences: `rfcs/` is committed, mermaid over d2, no CI sharding/conformance/DST apparatus. |
| 2 | uv + hatchling + hatch-vcs; version derives from git tags only; release is tag-driven with PyPI Trusted Publishing. |
| 3 | `requires-python = ">=3.12,<3.15"`; CI matrix 3.12–3.14. |
| 4 | `just quality` is the single quality authority, run identically locally and in CI (`-s` in CI); Codecov is informational only. |
| 5 | import-linter mechanically enforces the compiler layering (emitters never import `spec`; `spec` imports only `errors`). |
| 6 | Determinism bans (`datetime.now`, `uuid4`, `time.time`, `os.environ` in `src/bloomery/`) are pre-commit pygrep hooks, not review vigilance. |
| 7 | All workflow actions SHA-pinned + harden-runner in every job; `required-ci` aggregator is the only branch-protection check. |
| 8 | Docs: zensical + mike under `pages/`, Diátaxis nav, versioned per minor release. |

## 12. Phasing

Lands first, before M1 — every subsequent RFC's code arrives through this gate. Docs pages
and ratchet scripts accrue per later RFCs' Docs sections.
