#!/usr/bin/env bash
# Publish the JSON Schema export to the gh-pages **root**, at the path each
# schema's own `$id` claims (RFC 0020 §7):
#
#   https://morzecrew.github.io/bloomery/schemas/v1/<kind>.json
#
# Root rather than inside a mike version directory, deliberately. The version in
# that URL is the *document* version — the `<kind>_version: 1` the parser
# accepts — not the bloomery release, and those move on different clocks. A
# consumer pins to the spec dialect their YAML is written in, which is the thing
# that would break them, and a docs release must not silently repoint it.
#
# Idempotent: rewrites the six files and pushes only when something changed.
# Run after mike has deployed, so both workflows serialize through one
# concurrency group and this never races mike's own push. Run from anywhere in
# the repo.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

staging="$(mktemp -d)"
worktree="$(mktemp -d)"
cleanup() {
	cd "$repo_root"
	git worktree remove --force "$worktree" 2>/dev/null || true
	rm -rf "$staging" "$worktree"
}
trap cleanup EXIT

uv run bloomery schema --out "$staging"

# Full fetch, not `--depth=1`: the checkout is already unshallow, and making
# one ref shallow is how a later push gets refused for a reason nothing in the
# log explains. `mktemp -d` already created the directory, so `--force` is what
# lets the worktree land in it.
git fetch origin gh-pages:refs/remotes/origin/gh-pages
git worktree add --force --detach "$worktree" origin/gh-pages
cd "$worktree"

# Replace the directory rather than copy over it. `cp` alone leaves a schema
# for a kind the export no longer produces sitting there forever, still serving
# a `$id` that claims to be current — and it would never show up as a diff,
# because nothing writes that path again.
rm -rf schemas/v1
mkdir -p schemas/v1
cp "$staging"/*.json schemas/v1/

git add --all schemas/v1
if git diff --cached --quiet -- schemas/v1; then
	echo "spec schemas unchanged; nothing to publish"
	exit 0
fi

git commit -m "📝 docs(schema): publish the spec JSON Schemas"
git push origin HEAD:gh-pages
echo "published $(find schemas/v1 -name '*.json' | wc -l) schema(s)"
