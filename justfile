set quiet
set shell := ["bash", "-cu"]

# ----------------------- #
# Paths / constants

_uv_sync := "uv sync --all-groups > /dev/null 2>&1"

# ....................... #

_pwd := justfile_directory()

# ----------------------- #
# Default command

[no-exit-message]
_default:
    echo "Available commands:"
    echo
    just --color=always --list | sed '1d'

help:
    just

# ----------------------- #
# Helpers

# Run a command and print the result based on the output
[no-cd]
_uv_cmd name strict *command:
    @printf "%-30s" "{{ name }}..."

    @out="/tmp/{{ name }}.$$$$" \
    trap 'rm -f "$$out"' EXIT; \
    if uv run {{ command }} >"$$out" 2>&1; then \
        echo "✅"; \
    else \
        echo "❌"; \
        echo ""; \
        cat "$$out"; \
        echo ""; \
        if {{ strict }}; then \
            exit 1; \
        fi; \
    fi

# ----------------------- #
# CI

# engine, e2e, chaos and perf are opt-in markers (Docker / nightly lanes — RFC 0009)
# Run the default test tiers (unit/golden/property/execution)
test *args='':
    {{ _uv_sync }}

    uv run pytest -m "not engine and not e2e and not chaos and not perf" --refusal-census {{ args }}

# Run the full suite including the engine matrix and target e2e (Docker required)
test-all *args='':
    {{ _uv_sync }}

    uv run pytest -m "not chaos and not perf" {{ args }}

# The diff is reviewed like source code — an unexplained golden diff fails review
# Regenerate the golden artifact files (RFC 0009 §5.4)
snapshot-update:
    {{ _uv_sync }}

    uv run pytest tests/golden --snapshot-update

# Run the default tiers with coverage, then the three floors: the global one
# from pyproject.toml, and a scoped report for each package that is not at it.
#
# `guardrails/` at 100% is the oldest floor and the reason the rest exist — an
# untested guardrail branch is an unshipped guardrail (RFC 0009 D9). `steps/` is
# the newest package and carries the run-time contract, so it is named rather
# than rounded into the global number.
#
# ponytail: the global floor cannot see one package rotting while another
# covers for it. A per-package table can, and this repo had one — 15 rows, 13 of
# them 98 or 99, behind a 116-line reader and a 271-line test of the reader. If
# a package ever does rot behind the total, add a fourth scoped line here for
# it, not the table back.
coverage *args='':
    {{ _uv_sync }}

    uv run pytest -m "not engine and not e2e and not chaos and not perf" \
        --refusal-census --cov=src --cov-report=term {{ args }}
    uv run coverage report --include='src/bloomery/guardrails/*' --fail-under=100
    uv run coverage report --include='src/bloomery/steps/*' --fail-under=92

# The single quality authority, byte-for-byte the same locally and in CI (RFC 0001 D4; CI runs `-s`)
# Run all quality checks
[arg("strict", long, short="s", value="true", help="Enable strict mode (fail on error in any check)")]
quality strict="false":
    {{ _uv_sync }}

    just _uv_cmd "Linting" {{ strict }} ruff check "src"
    just _uv_cmd "Formatting" {{ strict }} ruff format --check "src"
    just _uv_cmd "Types" {{ strict }} mypy "src"
    just _uv_cmd "Imports" {{ strict }} lint-imports
    just _uv_cmd "Dead code" {{ strict }} vulture
    just _uv_cmd "Dependencies" {{ strict }} deptry .
    just _uv_cmd "RFC corpus" {{ strict }} python tools/check_rfc_corpus.py .
    just _uv_cmd "Workflows" {{ strict }} zizmor --collect=default .github/
    just _uv_cmd "Secrets" {{ strict }} pre-commit run gitleaks --all-files

# ----------------------- #
# Docs

# Serve the documentation with live reload
[working-directory("pages")]
serve-docs:
    uv run zensical serve

# Build the documentation site into pages/site.
#
# `--strict` because without it the build *reports* a broken internal link and
# exits 0 — so every "no issues found" was read by a human and enforced by
# nobody. The link half of RFC 0025 §5.1 item 3 is Zensical's; the repo-path
# half a page cites in backticks is invisible to it and lives in
# `tests/unit/test_docs_floor.py`.
[working-directory("pages")]
build-docs:
    uv run zensical build --strict

# ----------------------- #
# Utils

_worktree_dir := join(_pwd, "..", "worktrees")

# Create a worktree for a branch
[arg("new", long, value="true", help="Create a worktree for a new branch")]
worktree branch new="false":
    mkdir -p {{ _worktree_dir }}

    if {{ new }}; then \
        git worktree add {{ _worktree_dir }}/bloomery-{{ branch }} -b {{ branch }} main;
    else \
        git worktree add {{ _worktree_dir }}/bloomery-{{ branch }} {{ branch }};
    fi
