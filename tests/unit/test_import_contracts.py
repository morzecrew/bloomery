"""The import contracts are tested, not merely configured (RFC 0019 §6).

An import-linter contract that has never failed is indistinguishable from one
that is misconfigured — a typo in a module path yields a contract that passes
forever over nothing. Each test below plants the violation its contract exists
to forbid and asserts `lint-imports` reports it.

These shell out because that is the thing being tested: the contract as CI runs
it, config and all, not a reimplementation of what it ought to mean.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]


def lint_imports() -> subprocess.CompletedProcess[str]:
    """`lint-imports` as the gate runs it, with the cache off.

    The cache keys on file mtime and would happily report a planted violation
    as clean, which would make these tests pass for the wrong reason — the
    exact failure mode they exist to rule out.
    """
    executable = pathlib.Path(sys.executable).with_name("lint-imports")
    return subprocess.run(  # noqa: S603
        [str(executable), "--no-cache"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_contracts_pass_on_the_tree_as_it_stands() -> None:
    """The control. A planted violation proves nothing if the baseline is red."""
    result = lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("contract", "victim", "planted"),
    [
        (
            "Lowering is target-independent",
            "src/bloomery/emit/lower/silver.py",
            "from bloomery.emit.sqlmesh import emit_sqlmesh  # planted\n",
        ),
        (
            "Targets never import each other",
            "src/bloomery/emit/dbt/__init__.py",
            "from bloomery.emit.cube import emit_cube  # planted\n",
        ),
        (
            "Lowering stages compose downward",
            "src/bloomery/emit/lower/silver.py",
            "from bloomery.emit.lower.quality_mart import quality_mart_select  # planted\n",
        ),
        # RFC 0020 D5. `cli` is the top layer, so any library module importing
        # it inverts the one direction the carve-out depends on: the shell
        # reads paths and the library only ever sees strings. Planted in the
        # spec layer because that is the *furthest* module from the CLI — if
        # the contract catches it there it catches it everywhere.
        (
            "Layered bloomery compile pipeline",
            "src/bloomery/spec/project.py",
            "from bloomery.cli import main  # planted\n",
        ),
    ],
)
def test_a_planted_violation_breaks_its_contract(
    contract: str, victim: str, planted: str
) -> None:
    path = ROOT / victim
    original = path.read_text()
    backup = path.with_suffix(path.suffix + ".m16-backup")
    shutil.copy2(path, backup)
    try:
        # Append rather than prepend: a module docstring must stay first.
        path.write_text(original + "\n" + planted)
        result = lint_imports()
        assert result.returncode != 0, f"{contract} did not fail on a planted violation"
        assert contract in result.stdout, (
            f"{contract} was not the contract that broke:\n{result.stdout}"
        )
    finally:
        shutil.move(str(backup), str(path))
        assert path.read_text() == original
