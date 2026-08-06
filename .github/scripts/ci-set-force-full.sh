#!/usr/bin/env bash
# Normalize the force_full input into a definite boolean step output. The
# nightly schedule always runs the full lane (there is no diff to scope by).
# Reads FORCE_FULL, EVENT_NAME; writes force_full to $GITHUB_OUTPUT.
set -euo pipefail

if [[ "${FORCE_FULL:-false}" == "true" || "${EVENT_NAME:-}" == "schedule" ]]; then
	echo "force_full=true" >>"$GITHUB_OUTPUT"
else
	echo "force_full=false" >>"$GITHUB_OUTPUT"
fi
