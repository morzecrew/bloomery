"""The batch fuzzing job's scripts, and the shape of the job itself (S-0009).

``fuzz/seeds.py`` generates each target's seeds from ``examples/**`` and
``tests/golden/**`` (D-7); ``fuzz/corpus.py`` counts what the ``actions/cache``
corpus holds (D-3) and fails on a crash artifact. Both are asserted in each
colour — the planted crash is what says the job can actually go red, and a
check never observed to fail is indistinguishable from one that never fires.

The workflow tests are over the job's shape rather than its behaviour: the
matrix width and the cache round-trip are decisions (D-3, D-6), and a target
added without a matrix entry is a target nothing ever fuzzes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

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
        env=os.environ,
    )


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def batch(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["batch"]


# ....................... #
# The seed generator


def test_every_target_gets_the_examples_and_the_goldens(tmp_path: Path) -> None:
    """D-7: the seeds are derived, so a new example is a new seed without
    anyone copying it."""
    result = run(SEEDS, "--out", str(tmp_path))
    assert result.returncode == 0, result.stderr

    generated = {directory.name: sorted(p.name for p in directory.iterdir()) for directory in tmp_path.iterdir()}
    assert generated, "no target seed directories were written"
    for target, names in generated.items():
        assert any(name.startswith("examples-") for name in names), target
        assert any(name.startswith("tests-golden-") for name in names), target
        assert all(name.endswith((".yaml", ".yml")) for name in names), target


def test_the_seed_directories_cover_every_fuzz_target(tmp_path: Path) -> None:
    assert run(SEEDS, "--out", str(tmp_path)).returncode == 0
    targets = {path.stem.removeprefix("fuzz_") for path in (REPO_ROOT / "fuzz").glob("fuzz_*.py")}
    assert {directory.name for directory in tmp_path.iterdir()} == targets


def test_seeds_from_nested_directories_do_not_displace_each_other(tmp_path: Path) -> None:
    """A dozen goldens each carrying a `config.yaml` is a dozen seeds, not one."""
    root = tmp_path / "src"
    for name in ("first", "second"):
        (root / name).mkdir(parents=True)
        (root / name / "config.yaml").write_text(f"name: {name}\n")
    (root / "first" / "notes.txt").write_text("not a seed\n")

    out = tmp_path / "out"
    result = run(SEEDS, "--out", str(out), "--root", str(root), "--target", "parse_doors")
    assert result.returncode == 0, result.stderr
    assert len(list((out / "parse_doors").iterdir())) == 2
    assert "parse_doors=2" in result.stdout


def test_a_root_holding_no_documents_is_a_failure(tmp_path: Path) -> None:
    """A moved root would otherwise hand every target an empty seed directory,
    and a fuzzer starting from nothing reports the same green as one that did
    not."""
    (tmp_path / "empty").mkdir()
    result = run(SEEDS, "--out", str(tmp_path / "out"), "--root", str(tmp_path / "empty"))
    assert result.returncode == 1
    assert "no YAML documents" in result.stderr


# ....................... #
# The corpus counts


def test_the_corpus_count_names_every_target(tmp_path: Path) -> None:
    (tmp_path / "parse_doors").mkdir()
    (tmp_path / "parse_doors" / "a").write_bytes(b"a")
    (tmp_path / "parse_doors" / "b").write_bytes(b"b")
    (tmp_path / "cli").mkdir()

    result = run(CORPUS, "count", "--root", str(tmp_path), "--label", "corpus after")
    assert result.returncode == 0, result.stderr
    assert "corpus after: cli=0 parse_doors=2 (total 2)" in result.stdout


def test_the_generated_seeds_are_not_counted_as_corpus_entries(tmp_path: Path) -> None:
    """`fuzz/corpus/.seeds/` is working state the job regenerates every run —
    counted, it would hide a cache that stopped round-tripping behind a
    four-figure number."""
    (tmp_path / ".seeds" / "parse_doors").mkdir(parents=True)
    (tmp_path / ".seeds" / "parse_doors" / "seed.yaml").write_text("a: 1\n")

    result = run(CORPUS, "count", "--root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "empty" in result.stdout


def test_an_empty_corpus_fails_the_after_count(tmp_path: Path) -> None:
    """The cache round-trip check: a run that ends with nothing to keep
    explored nothing, and must not be green."""
    result = run(CORPUS, "count", "--root", str(tmp_path), "--min-total", "1")
    assert result.returncode == 1
    assert "expected at least 1" in result.stderr


# ....................... #
# The planted crash


def test_a_planted_crash_artifact_turns_the_job_red(tmp_path: Path) -> None:
    (tmp_path / "parse_doors-crash-deadbeef").write_bytes(b"(((((((")
    result = run(CORPUS, "crashes", "--root", str(tmp_path))
    assert result.returncode == 1
    assert "parse_doors-crash-deadbeef" in result.stdout
    assert "1 artifact(s)" in result.stderr


def test_a_run_that_found_nothing_stays_green(tmp_path: Path) -> None:
    result = run(CORPUS, "crashes", "--root", str(tmp_path / "absent"))
    assert result.returncode == 0, result.stderr
    assert "none under" in result.stdout


# ....................... #
# The job's shape


def test_the_batch_job_fuzzes_three_hash_seeds_without_fail_fast(batch: dict[str, Any]) -> None:
    """S-0009/D-6: three seeds is the width; `fail-fast` off because a crash in
    one target says nothing about the others."""
    assert batch["strategy"]["fail-fast"] is False
    assert batch["strategy"]["matrix"]["seed"] == ["0", "1", "random"]


def test_every_fuzz_target_has_a_matrix_entry(batch: dict[str, Any]) -> None:
    targets = {path.stem.removeprefix("fuzz_") for path in (REPO_ROOT / "fuzz").glob("fuzz_*.py")}
    assert set(batch["strategy"]["matrix"]["target"]) == targets


def test_the_corpus_is_restored_at_job_start_and_saved_at_job_end(batch: dict[str, Any]) -> None:
    """S-0009/D-3: one `actions/cache` entry per target, shared by the seed
    legs — so the restore prefix carries the target and nothing else."""
    steps = batch["steps"]
    restore = next(s for s in steps if s.get("uses", "").startswith("actions/cache/restore@"))
    save = next(s for s in steps if s.get("uses", "").startswith("actions/cache/save@"))

    assert steps.index(restore) < steps.index(save)
    assert restore["with"]["path"] == save["with"]["path"] == "fuzz/corpus/${{ matrix.target }}"
    assert restore["with"]["key"] == save["with"]["key"]
    assert restore["with"]["restore-keys"].strip() == "fuzz-corpus-${{ matrix.target }}-"


def test_the_counts_bracket_the_fuzz_run(batch: dict[str, Any]) -> None:
    """Before and after, because a cache that stopped round-tripping is
    otherwise indistinguishable from a healthy one."""
    names = [step["name"] for step in batch["steps"]]
    assert names.index("Count the corpus before the run") < names.index("Fuzz")
    assert names.index("Fuzz") < names.index("Count the corpus after the run")
    assert names.index("Save the corpus") < names.index("Fail on a crash artifact")
