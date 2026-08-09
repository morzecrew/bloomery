#!/usr/bin/env bash
# Combine the per-interpreter coverage data into one report.
#
# Never gates here. The floor is enforced by a later step, *after* the Codecov
# upload, so a coverage regression still reaches the service that reports it —
# a gate that runs first would abort the job and leave the PR with no coverage
# comment at all, which is the opposite of informational (RFC 0001 D4).
#
# Combining across 3.12/3.13/3.14 rather than reporting each leg separately is
# what makes version-gated code honest: a line reachable only on 3.14 is
# covered by the run that executes it, and uncovered everywhere else.
set -euo pipefail

mv coverage-data/.coverage.* . 2>/dev/null || true
# Non-fatal: with no data files downloaded, `combine` exits 1 ("no data to
# combine"). This step never gates, so it must not fail the job here — the
# threshold step below is what decides, and it fails loudly on an empty report.
uv run coverage combine || true
uv run coverage xml || true
