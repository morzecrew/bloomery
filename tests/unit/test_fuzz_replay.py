"""The replay script's own tests (S-0009/D-2).

``fuzz/replay.py`` is the corpus-scale version of
``tests/unit/test_determinism_guard.py``: it compiles every corpus entry twice
under different ``PYTHONHASHSEED`` values and once in the opposite order, and
diffs the artifacts. These tests keep it honest in both directions — a green
run over a real project, and a red run under each sabotage knob, because a
check never observed to fail is indistinguishable from one that never fires.

The corpus here is a two-project copy of one fixture rather than the day-one
default: this tier compiles nine target/dialect cells per entry three times
over, and the full corpus belongs to the weekly job, not to a unit test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "fuzz" / "replay.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "minimal"


def run_replay(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
    )


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Two copies of one project, so the reversed-order run really reverses
    something — a one-entry corpus is its own reverse."""
    root = tmp_path_factory.mktemp("replay-corpus")
    for name in ("first", "second"):
        shutil.copytree(FIXTURE, root / name)
    return root


def test_the_corpus_replays_identically(corpus: Path) -> None:
    result = run_replay("--root", str(corpus), "--corpus", str(corpus / "absent"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "identical across processes, seeds and order" in result.stdout


def test_a_hash_seed_dependent_compile_is_caught(corpus: Path) -> None:
    result = run_replay(
        "--root", str(corpus), env={"BLOOMERY_REPLAY_SABOTAGE": "seed"}
    )
    assert result.returncode == 1
    assert "PYTHONHASHSEED 0 vs 1" in result.stdout
    assert "differing entries" in result.stderr


def test_an_order_dependent_artifact_list_is_caught(corpus: Path) -> None:
    result = run_replay(
        "--root", str(corpus), env={"BLOOMERY_REPLAY_SABOTAGE": "order"}
    )
    assert result.returncode == 1
    assert "compile order:" in result.stdout


def test_an_empty_corpus_is_a_failure(tmp_path: Path) -> None:
    """The one outcome indistinguishable from a determinism claim that holds:
    comparing nothing to nothing."""
    result = run_replay("--root", str(tmp_path), "--corpus", str(tmp_path))
    assert result.returncode == 1
    assert "no corpus entries" in result.stderr


def test_the_day_one_corpus_needs_no_fuzzing_to_exist() -> None:
    """S-0009/D-7: the seeds are the examples and the golden tier's spec
    fixtures, so the lane has a corpus before any fuzzing job has run."""
    result = run_replay("--list")
    assert result.returncode == 0, result.stderr
    listed = [line.split("\t", 1)[1] for line in result.stdout.splitlines()]
    assert "examples/quickstart" in listed
    assert "tests/fixtures/minimal" in listed
    assert all(line.startswith("project") for line in result.stdout.splitlines())


def test_a_fuzz_corpus_blob_is_picked_up_when_one_exists(tmp_path: Path) -> None:
    """And only when one exists — `fuzz/corpus/` is absent until a fuzzing job
    fills it, which is why nothing above requires it."""
    (tmp_path / "deadbeef").write_bytes(b"entities: {}\n\x00")
    result = run_replay("--corpus", str(tmp_path), "--list")
    assert result.returncode == 0, result.stderr
    assert "blob\t" in result.stdout
