#!/usr/bin/env bash
# Point the gh-pages root redirect (mike's set-default index.html) at `dev`
# while no released version exists yet. Without this, the site root 404s until
# the first vX.Y.Z tag runs docs-release, which owns the redirect from then on
# (deploy-docs-version.sh sets it to `latest`). Run from anywhere in the repo.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)/pages"

if uv run mike list --branch gh-pages | grep -q '\[latest\]'; then
	echo "released docs exist; root redirect is owned by docs-release"
else
	uv run mike set-default --push --branch gh-pages dev
fi
