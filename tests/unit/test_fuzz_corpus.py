"""The batch job's seed generator and corpus reader (S-0009).

Two scripts and one workflow job, and the thing worth asserting about all
three is that the job can go red. A weekly lane that fuzzes an empty corpus,
restores nothing from the cache and reports no crash it cannot see is
indistinguishable from a lane that is working — for a week at a time.

So: the generator copies the examples and the fixtures behind the golden
tier (S-0009/D-7) and fails rather than writing an empty seed set; the counter
reads `0 entries` out of a cache that did not round-trip; and the crash check
goes red on a planted artifact and green on a clean tree (S-0002/D-2).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS = REPO_ROOT / "fuzz" / "seeds.py"
CORPUS = REPO_ROOT / "fuzz" / "corpus.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "fuzz.yaml"


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


@pytest.fixture(scope="module")
def batch_job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["batch"]


# ....................... #
# The seeds (S-0009/D-7)


def test_the_seeds_come_from_the_examples_and_the_fixtures(tmp_path: Path) -> None:
    """The golden tier's inputs, not its outputs: every `*.yaml` under
    `tests/golden/` is a generated gateway config, and a seed made of one
    mutates nothing a target reads."""
    result = run(SEEDS, "--dest", str(tmp_path), "--target", "cli")
    assert result.returncode == 0, result.stderr

    written = sorted(path.name for path in (tmp_path / "cli").iterdir())
    assert any(name.startswith("examples-") for name in written)
    assert any(name.startswith("tests-fixtures-") for name in written)
    assert not any(name.startswith("tests-golden-") for name in written)
    assert all(name.endswith(".yaml") for name in written)


def test_a_seed_carries_the_trailing_slot_byte(tmp_path: Path) -> None:
    """The harness reads the slot off the buffer's last byte; a bare copy
    of a document would hand its own last byte to that choice."""
    from fuzz.seeds import SLOT_BYTE, seed_name, seed_sources

    run(SEEDS, "--dest", str(tmp_path), "--target", "cli")
    source = seed_sources()[0]

    assert (tmp_path / "cli" / seed_name(source)).read_bytes() == source.read_bytes() + SLOT_BYTE


def test_every_target_gets_a_seed_directory(tmp_path: Path) -> None:
    from fuzz.seeds import targets

    result = run(SEEDS, "--dest", str(tmp_path))
    assert result.returncode == 0, result.stderr

    assert sorted(path.name for path in tmp_path.iterdir()) == targets()
    assert all(any(path.iterdir()) for path in tmp_path.iterdir())


def test_two_projects_carrying_one_filename_do_not_collide(tmp_path: Path) -> None:
    """`catalog.yaml` exists under most example projects: a flat copy keyed on
    the basename would seed one of them and silently drop the rest."""
    from fuzz.seeds import seed_sources

    sources = seed_sources()
    assert sum(1 for path in sources if path.name == "catalog.yaml") > 1

    run(SEEDS, "--dest", str(tmp_path), "--target", "cli")
    assert len(list((tmp_path / "cli").iterdir())) == len(sources)


def test_a_generator_that_copied_nothing_is_a_failure(tmp_path: Path) -> None:
    """The one outcome a working lane and a broken source root look the same
    from: a seed set nobody wrote."""
    result = run(
        SEEDS, "--dest", str(tmp_path), "--target", "cli", "--source", str(tmp_path / "absent")
    )
    assert result.returncode == 1
    assert "no seeds generated" in result.stderr


# ....................... #
# The corpus count


def test_the_count_is_the_files_under_the_directory(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a").write_bytes(b"x")
    (tmp_path / "nested" / "b").write_bytes(b"y")

    result = run(CORPUS, "count", str(tmp_path), "--label", "after")
    assert result.returncode == 0, result.stderr
    assert "after: 2 entries" in result.stdout


def test_a_cache_that_did_not_round_trip_reads_as_zero(tmp_path: Path) -> None:
    """A restore that brought nothing back is the failure mode `actions/cache`
    has and a storage repository does not (S-0009/D-3) — it has to be visible
    in the log, because nothing else about the job changes colour."""
    result = run(CORPUS, "count", str(tmp_path / "never-restored"), "--label", "before")
    assert result.returncode == 0, result.stderr
    assert "before: 0 entries" in result.stdout


# ....................... #
# The planted crash (S-0002/D-2)


def test_a_planted_crash_artifact_turns_the_job_red(tmp_path: Path) -> None:
    (tmp_path / "cli-crash-deadbeef").write_bytes(b"entities: {}\n\x00")

    result = run(CORPUS, "crashes", str(tmp_path), "--target", "cli")
    assert result.returncode == 1
    assert "cli-crash-deadbeef" in result.stderr
    assert "1 crash artifacts" in result.stderr


def test_a_clean_tree_stays_green(tmp_path: Path) -> None:
    """The other half: a check that cannot pass is as broken as one that
    cannot fail. Another target's artifact is not this target's finding."""
    (tmp_path / "parse_doors-crash-deadbeef").write_bytes(b"\x00")

    result = run(CORPUS, "crashes", str(tmp_path), "--target", "cli")
    assert result.returncode == 0, result.stderr
    assert "no crash artifacts" in result.stdout


# ....................... #
# The job the two scripts are for


def test_the_matrix_is_three_hash_seeds_and_does_not_fail_fast(batch_job: dict) -> None:
    """S-0009/D-6, and the reason for `fail-fast: false`: a hash-seed-dependent
    finding is what the other legs are there to tell you about."""
    strategy = batch_job["strategy"]
    assert strategy["fail-fast"] is False
    assert strategy["matrix"]["seed"] == ["0", "1", "random"]
    assert batch_job["env"]["PYTHONHASHSEED"] == "${{ matrix.seed }}"


def test_the_corpus_cache_is_keyed_per_target_and_round_trips(batch_job: dict) -> None:
    """S-0009/D-3: one corpus per target, restored at job start and saved at
    job end — and the count printed on both sides of the run."""
    steps = batch_job["steps"]
    names = [step.get("name", "") for step in steps]

    restore = steps[names.index("Restore the corpus")]
    save = steps[names.index("Save the corpus")]
    assert restore["uses"].startswith("actions/cache/restore@")
    assert save["uses"].startswith("actions/cache/save@")
    assert restore["with"]["key"] == save["with"]["key"]
    assert restore["with"]["restore-keys"].strip() == "fuzz-corpus-${{ matrix.target }}-"

    assert names.index("Count the corpus (before)") < names.index("Fuzz")
    assert names.index("Fuzz") < names.index("Count the corpus (after)")
    assert names.index("Count the corpus (after)") < names.index("Save the corpus")


def test_every_target_rides_the_matrix(batch_job: dict) -> None:
    """A target written and never added here is one nobody fuzzes."""
    from fuzz.seeds import targets

    assert sorted(batch_job["strategy"]["matrix"]["target"]) == targets()


def test_the_job_runs_plain_atheris_on_setup_python(batch_job: dict) -> None:
    """S-0009/D-1: no Dockerfile, no OSS-Fuzz base image, no ClusterFuzzLite."""
    steps = batch_job["steps"]
    # The interpreter is pinned where uv resolves it: a setup-python step
    # beside setup-uv installed a 3.12 that `uv run` never selected.
    uv = next(step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@"))
    assert uv["with"]["python-version"] == "3.12"
    assert not any(step.get("uses", "").startswith("actions/setup-python@") for step in steps)
    assert not any("clusterfuzzlite" in step.get("uses", "").lower() for step in steps)
    assert not (REPO_ROOT / "fuzz" / "Dockerfile").exists()

    fuzzing = next(step for step in steps if step.get("name") == "Fuzz")
    assert "--with 'atheris>=2.3'" in fuzzing["run"]
