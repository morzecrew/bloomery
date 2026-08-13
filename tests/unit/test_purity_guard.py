"""The purity gate is tested, not merely present (RFC 0019 §6).

A guard that has never failed is indistinguishable from one that is
misconfigured. These plant each banned construct in a throwaway tree and assert
the checker reports it — and, just as important, plant the two shapes that look
banned and are not.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "check_purity.py"


def load_checker() -> object:
    """Import the gate by path — `tools/` is not a package, deliberately: it is
    developer tooling rather than shipped code."""
    spec = importlib.util.spec_from_file_location("check_purity", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_purity"] = module
    spec.loader.exec_module(module)
    return module


def findings_for(tmp_path: pathlib.Path, source: str) -> list[str]:
    checker = load_checker()
    module = tmp_path / "planted.py"
    module.write_text(source)
    return [f.message for f in checker.inspect_module(module, tmp_path)]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import os\n", "imports 'os'"),
        ("import pathlib\n", "imports 'pathlib'"),
        ("from tempfile import mkdtemp\n", "imports 'tempfile'"),
        ("import requests\n", "imports 'requests'"),
        ("import duckdb\n", "imports 'duckdb'"),
        ("x = datetime.now()\n", "calls datetime.now()"),
        ("x = datetime.datetime.now()\n", "calls datetime.datetime.now()"),
        ("x = time.time()\n", "calls time.time()"),
        ("x = uuid.uuid4()\n", "calls uuid.uuid4()"),
        ("x = random.random()\n", "calls random.random()"),
        # The attribute rule alone misses this: the call is spelled
        # `choice(...)` and names no module, so the import ban is what
        # catches it. Found by auditing the guard rather than by using it.
        ("from random import choice\n", "imports 'random'"),
        ("import secrets\n", "imports 'secrets'"),
        ("x = os.environ['HOME']\n", "reads os.environ"),
    ],
)
def test_a_planted_violation_is_caught(
    tmp_path: pathlib.Path, source: str, expected: str
) -> None:
    assert any(expected in message for message in findings_for(tmp_path, source)), (
        f"the guard did not report {expected!r} for {source!r}"
    )


@pytest.mark.parametrize(
    "source",
    [
        # A bloomery module sharing a banned name — the dialect, not the driver.
        "from bloomery.dialects.duckdb import DuckDBDialect\n",
        "import bloomery.dialects.duckdb\n",
        # A relative import reaches nothing outside the package.
        "from .lowering import lower\n",
        # A method of one's own that happens to be spelled like a clock.
        "x = self.now()\n",
        "x = context.time()\n",
    ],
)
def test_what_only_looks_banned_is_not_reported(tmp_path: pathlib.Path, source: str) -> None:
    assert findings_for(tmp_path, source) == [], f"false positive on {source!r}"


def test_the_allowlist_exempts_the_run_time_contract(tmp_path: pathlib.Path) -> None:
    """`steps/contract.py` runs inside a generated wrapper in a warehouse, not
    during compilation (RFC 0017), so the import ban does not apply to it."""
    checker = load_checker()
    assert "steps/contract.py" in checker.ALLOWLIST  # type: ignore[attr-defined]
    exempt = tmp_path / "steps" / "contract.py"
    exempt.parent.mkdir()
    exempt.write_text("import os\n")
    assert checker.inspect_module(exempt, tmp_path) == []  # type: ignore[attr-defined]

    ordinary = tmp_path / "steps" / "other.py"
    ordinary.write_text("import os\n")
    assert checker.inspect_module(ordinary, tmp_path)  # type: ignore[attr-defined]


def test_the_pygrep_hook_it_replaces_is_gone() -> None:
    """Two guards over one invariant drift apart (RFC 0019 D6). The AST check is
    a superset of the hook's four spellings, so the hook is removed in the same
    change — this pins that it stays removed."""
    config = (pathlib.Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml").read_text()
    assert "no-nondeterminism-sources" not in config
    assert "pygrep" not in config


def test_the_gate_runs_it() -> None:
    """A guard CI does not run is a convention, which is the defect D6 names."""
    justfile = (pathlib.Path(__file__).resolve().parents[2] / "justfile").read_text()
    assert "tools/check_purity.py" in justfile
