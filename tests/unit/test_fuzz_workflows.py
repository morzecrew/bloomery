"""The fuzz lane's pull-request run (S-0009).

The job is a minute of fuzzing beside the test matrix, and everything worth
asserting about it is a property no green run would reveal: that it is
path-filtered rather than universal, that a superseded run is cancelled rather
than queued, and above all that it is **non-blocking** — S-0009/D-5 makes
promotion to a required check a deliberate act with a stated condition, and the
failure this file guards against is someone wiring it into branch protection
during the weeks when the harness is still wrong.

The lane's own red/green pair lives in `tests/unit/test_fuzz_corpus.py` (the
planted crash artifact) and `tests/unit/test_fuzz_replay.py` (the planted
nondeterminism); this file asserts the pull-request job carries that verdict
rather than re-planting it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "fuzz.yaml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def load(path: Path) -> dict:
    """`on:` parses as the boolean `True` under YAML 1.1, which is why the
    trigger block is read through this rather than by its name."""
    return yaml.safe_load(path.read_text())


@pytest.fixture
def workflow() -> dict:
    return load(WORKFLOW)


@pytest.fixture
def pr_job(workflow: dict) -> dict:
    return workflow["jobs"]["pr"]


# ....................... #
# What triggers it


def test_the_pull_request_run_is_filtered_to_src_and_fuzz(workflow: dict) -> None:
    """The two trees that can change what a target does. A docs-only pull
    request has nothing here to find, and a lane that runs on it is one people
    learn to ignore."""
    paths = workflow[True]["pull_request"]["paths"]

    assert "src/**" in paths
    assert "fuzz/**" in paths
    # The seed sources too: a changed example or fixture is a changed seed.
    assert "examples/**" in paths
    assert "tests/fixtures/**" in paths
    assert ".github/workflows/fuzz.yaml" in paths


def test_a_superseded_pull_request_run_is_cancelled(workflow: dict) -> None:
    """Keyed per ref, so one branch's run never cancels another's."""
    concurrency = workflow["concurrency"]

    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_a_scheduled_run_is_never_cancelled_mid_corpus(workflow: dict) -> None:
    """The corpus save is the batch job's last step, so a cancelled weekly run
    loses the exploration it just paid for (S-0009/D-3). Cancellation is scoped
    to pull requests for that reason, and `true` here would be the defect."""
    assert workflow["concurrency"]["cancel-in-progress"] is not True


def test_the_short_run_and_the_weekly_lane_do_not_overlap(workflow: dict) -> None:
    """One runs on pull requests and only there; the other never does."""
    assert workflow["jobs"]["pr"]["if"] == "github.event_name == 'pull_request'"
    assert workflow["jobs"]["batch"]["if"] == "github.event_name != 'pull_request'"


# ....................... #
# That it does not block


def test_the_pull_request_job_is_non_blocking(pr_job: dict) -> None:
    """S-0009/D-5. Non-blocking for at least a month, and longer while findings
    are still arriving: the early weeks are when the harness is wrong, and a red
    required check during them is how a fuzzing setup gets deleted."""
    assert pr_job["continue-on-error"] is True


def test_no_fuzz_job_is_part_of_the_required_check() -> None:
    """`required-ci` in `ci.yml` is the sole branch-protection check. Promotion
    is D-5's to make, so until it is made no fuzz job may appear there — and
    `ci.yml` may not call this workflow, which would promote it by the back
    door."""
    ci = load(CI)
    fuzz_jobs = set(load(WORKFLOW)["jobs"])

    assert fuzz_jobs.isdisjoint(ci["jobs"]["required-ci"]["needs"])
    assert not any("fuzz" in job.get("uses", "") for job in ci["jobs"].values())


def test_one_red_leg_does_not_cancel_the_others(pr_job: dict) -> None:
    """A finding on one target says nothing about the next, and a non-blocking
    lane that reports one of six is worth less than the minute it costs."""
    assert pr_job["strategy"]["fail-fast"] is False


# ....................... #
# That it is the short run, and still the same harness


def test_the_run_is_short(pr_job: dict, workflow: dict) -> None:
    """S-0009/D-6: a tenth of the weekly budget. A pull-request run costing more
    than the suite it rides beside is one someone turns off."""
    steps = {step.get("name"): step for step in pr_job["steps"]}
    batch_steps = {step.get("name"): step for step in workflow["jobs"]["batch"]["steps"]}

    assert "-max_total_time=60" in steps["Fuzz"]["run"]
    assert "-max_total_time=600" in batch_steps["Fuzz"]["run"]


def test_every_target_rides_the_short_run(pr_job: dict) -> None:
    """A target written and never added here is one no pull request fuzzes."""
    from fuzz.seeds import targets

    # `parse_doors` is left out while its known open finding stands (the
    # target's module docstring): a 60s run reaches it, and a leg red on
    # every pull request from day one is what S-0009/D-5 exists to avoid.
    assert sorted(pr_job["strategy"]["matrix"]["target"]) == [
        t for t in targets() if t != "parse_doors"
    ]
    assert "seed" not in pr_job["strategy"]["matrix"], "one seed; D-6's matrix is weekly"


def test_the_short_run_reads_the_corpus_and_never_writes_it(pr_job: dict) -> None:
    """S-0009/D-3: the weekly lane owns the corpus. A branch's cache entry is
    visible to every later run on that branch, so a save here would let a pull
    request decide what the corpus is."""
    uses = [step.get("uses", "") for step in pr_job["steps"]]

    assert any(action.startswith("actions/cache/restore@") for action in uses)
    assert not any(action.startswith("actions/cache/save@") for action in uses)


def test_a_crash_still_turns_the_leg_red(pr_job: dict) -> None:
    """A time-boxed run can end green with an artifact on disk, so the file is
    the finding whatever libFuzzer's exit code said — and the input has to be
    fetchable, or a red non-blocking job is a notification nobody can act on.
    The planted-crash twin for the verdict itself is in
    `tests/unit/test_fuzz_corpus.py` (S-0002/D-2)."""
    steps = {step.get("name"): step for step in pr_job["steps"]}

    assert "fuzz/corpus.py crashes" in steps["Assert no crash artifacts"]["run"]
    assert steps["Assert no crash artifacts"]["if"] == "${{ !cancelled() }}"
    assert steps["Upload the crash artifacts"]["uses"].startswith("actions/upload-artifact@")


def test_the_short_run_is_plain_atheris_on_setup_python(pr_job: dict) -> None:
    """S-0009/D-1, for the new job as much as for the weekly one: no
    Dockerfile, no OSS-Fuzz base image, no ClusterFuzzLite."""
    steps = pr_job["steps"]

    # The interpreter is pinned where uv resolves it.
    uv = next(step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@"))
    assert uv["with"]["python-version"] == "3.12"
    assert not any(step.get("uses", "").startswith("actions/setup-python@") for step in steps)
    assert not any("clusterfuzzlite" in step.get("uses", "").lower() for step in steps)
    assert "--with 'atheris>=2.3'" in next(s for s in steps if s.get("name") == "Fuzz")["run"]


def test_the_replay_job_reads_every_corpus_the_batch_grew(workflow: dict) -> None:
    """Without the restores the replay compared only the checked-out
    documents, and the determinism claim never reached what the fuzzer found."""
    from fuzz.seeds import targets

    steps = workflow["jobs"]["replay"]["steps"]
    restored = sorted(
        step["with"]["path"].removeprefix("fuzz/corpus/")
        for step in steps
        if step.get("uses", "").startswith("actions/cache/restore@")
    )

    assert restored == targets()
    assert not any(step.get("uses", "").startswith("actions/cache/save@") for step in steps)


def test_the_replay_job_still_leads(workflow: dict) -> None:
    """S-0009/D-2: the replay job lands before the fuzzing jobs and no later
    phase may reorder it behind them. Adding a job to this file is exactly the
    moment that ordering gets lost."""
    jobs = list(workflow["jobs"])

    assert jobs[0] == "replay"
    assert jobs.index("replay") < jobs.index("pr")
