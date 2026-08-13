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
trap 'rm -rf "$staging"' EXIT

uv run bloomery schema --out "$staging"

worktree="$(mktemp -d)"
trap 'rm -rf "$staging" "$worktree"' EXIT

git fetch origin gh-pages --depth=1
git worktree add --force "$worktree" origin/gh-pages
cd "$worktree"
git switch -C gh-pages-schemas

mkdir -p schemas/v1
cp "$staging"/*.json schemas/v1/

if git diff --quiet -- schemas/v1; then
	echo "spec schemas unchanged; nothing to publish"
else
	git add schemas/v1
	git commit -m "📝 docs(schema): publish the spec JSON Schemas"
	git push origin HEAD:gh-pages
	echo "published $(ls schemas/v1 | wc -l) schema(s)"
fi

cd "$repo_root"
git worktree remove --force "$worktree"
