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
        # Aliased imports: `dotted()` reports the alias, which matches no
        # banned suffix, so the root has to be resolved through the import
        # that bound it. Review found this one.
        ("from datetime import datetime as dt\nx = dt.now()\n", "calls dt.now()"),
        ("import time as t\nx = t.time()\n", "calls t.time()"),
        ("import uuid as u\nx = u.uuid4()\n", "calls u.uuid4()"),
        ("import os as o\nx = o.environ\n", "reads o.environ"),
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


def test_the_filesystem_carve_out_is_one_file_not_the_cli_package(
    tmp_path: pathlib.Path,
) -> None:
    """RFC 0020 D12. ``cli/io.py`` may open a file; nothing else under
    ``cli/`` may.

    A package-wide exemption would pass every test that only checks
    ``cli/io.py`` is exempt, while letting the argument parser or the renderer
    reach a disk — the tree claiming one door and the guard enforcing none.
    So the second half is the assertion that matters.
    """
    checker = load_checker()
    assert "cli/io.py" in checker.ALLOWLIST  # type: ignore[attr-defined]
    assert not any(  # type: ignore[attr-defined]
        entry.rstrip("/") == "cli" for entry in checker.ALLOWLIST
    )

    (tmp_path / "cli").mkdir()
    door = tmp_path / "cli" / "io.py"
    door.write_text("from pathlib import Path\n")
    assert checker.inspect_module(door, tmp_path) == []  # type: ignore[attr-defined]

    for sibling in ("__init__.py", "render.py", "serialize.py"):
        neighbour = tmp_path / "cli" / sibling
        neighbour.write_text("from pathlib import Path\n")
        assert checker.inspect_module(neighbour, tmp_path), sibling  # type: ignore[attr-defined]


def test_the_carve_out_does_not_exempt_a_clock(tmp_path: pathlib.Path) -> None:
    """The allowlist covers *imports*, which is all a filesystem needs. A CLI
    that read a clock would still make output depend on when it ran, and
    nothing about reaching a disk justifies that."""
    checker = load_checker()
    (tmp_path / "cli").mkdir()
    door = tmp_path / "cli" / "io.py"
    door.write_text("from datetime import datetime\nstamp = datetime.now()\n")
    assert checker.inspect_module(door, tmp_path)  # type: ignore[attr-defined]


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
