"""The chaos meta-test (RFC 0016 §6, §8.10) — a test **about the tests**.

    "Mutate the lowering (invert a comparison, drop a stage, swap a
    disposition); at least one test must fail per mutation, or the dirty
    corpus has a hole."

Every other suite asks "is the lowering right?". This one asks "would we
notice if it were not?" — the only question that tells a curated corpus from a
decorative one. Cleansing bugs are silent by nature: the pipeline is green and
the numbers are wrong, so a suite that cannot detect a deliberate defect
provides no evidence at all.

**It is honest by construction.** A surviving mutation fails this test and
names itself; nothing is marked expected-to-survive, and the control run —
unmutated, all green — is asserted first so a battery that was broken for
unrelated reasons cannot masquerade as detection.

Each mutation runs in a **subprocess**, because applying one monkeypatches the
lowering irreversibly for the process. The battery is the M12 quality suite;
one failing test in it is enough (``-x`` stops at the first).

Not part of ``just test``: marked ``chaos``, an opt-in lane. CI runs it in
the scheduled ``chaos`` job — nightly and on force-full runs, blocking. Run
it locally with::

    uv run pytest tests/chaos -m chaos
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — a pytest subprocess, argv-only, no shell
import sys
from pathlib import Path

import pytest
from support.chaos import MUTATIONS

from tests.conftest import CHAOS_ENV

pytestmark = pytest.mark.chaos

ROOT = Path(__file__).resolve().parents[2]

#: The M12 suite a mutation has to get past. Deliberately the *quality* suites
#: only: this measures whether the data-quality tests detect data-quality
#: defects, and padding the battery with unrelated tiers would inflate the
#: result without strengthening it.
#:
#: ``test_quality_precedence`` was missing from this list for a wave, and the
#: omission had a cost: it is the only module that reads a **mart**, so the
#: battery could not see a defect in ``has_quality_flags`` at all. A battery
#: that excludes a quality suite is not a smaller battery — it is a blind spot
#: with a green tick on it.
BATTERY = (
    "tests/execution/test_dirty_corpus.py",
    "tests/execution/test_dedupe_and_audits.py",
    "tests/execution/test_quality_mart.py",
    "tests/execution/test_quality_precedence.py",
    "tests/execution/test_quarantine_replay.py",
    "tests/property/test_conservation.py",
)

_ARGS = ("-x", "-q", "--no-header", "-p", "no:cacheprovider", "--timeout=300")


def _run(mutation: str | None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop(CHAOS_ENV, None)
    if mutation is not None:
        env[CHAOS_ENV] = mutation
    return subprocess.run(  # nosec B603 — fixed argv, no shell, repo-local
        [sys.executable, "-m", "pytest", *BATTERY, *_ARGS],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def control() -> subprocess.CompletedProcess[str]:
    """The unmutated battery. If this is red, every "mutation detected" below
    would be meaningless — so it is asserted before anything else is
    interpreted."""
    return _run(None)


def test_the_unmutated_battery_is_green(control: subprocess.CompletedProcess[str]) -> None:
    assert control.returncode == 0, (
        "the chaos control run failed, so no mutation result below means "
        f"anything:\n{control.stdout[-4000:]}"
    )


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_at_least_one_test_fails_for_each_mutation(
    control: subprocess.CompletedProcess[str], mutation: str
) -> None:
    """A mutation that survives is a **hole**, reported as one.

    The message names the mutation and points at what it deformed, because the
    fix is never "delete the mutation" — it is a specimen the corpus is missing
    or an assertion the suite never made.
    """
    assert control.returncode == 0, "control run red; see test_the_unmutated_battery_is_green"
    result = _run(mutation)
    assert result.returncode != 0, (
        f"MUTATION SURVIVED: {mutation!r} deformed the lowering and the whole M12 "
        f"quality battery stayed green. Per RFC 0016 §6 that is a hole in the dirty "
        f"corpus or in the suite — add the specimen or the assertion that would have "
        f"caught it (see tests/support/chaos.py for what the mutation does).\n"
        f"{result.stdout[-4000:]}"
    )
