"""The purity gate is tested, not merely present (RFC 0019 §6).

A guard that has never failed is indistinguishable from one that is
misconfigured — and a guard spelled as *configuration* is the shape where that
is easiest to believe, because there is no code to read. These plant each
banned construct in a throwaway tree, run the gate's own ruff settings over it,
and assert it is reported; and, just as important, plant the shapes that look
banned and are not.

The gate is ``TID251`` with the ``banned-api`` table in ``pyproject.toml``. It
replaced a hand-rolled AST checker whose one irreplaceable trick — resolving a
dotted name through the import that bound it, so ``dt.now()`` reads as
``datetime.datetime.now`` — ruff turned out to do already; the aliased cases
below are what pins that.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]


def findings_for(source: str) -> str:
    """Ruff's output for one planted module, under the repo's real settings.

    ``--config`` is not passed and ``--isolated`` is not either: the claim under
    test is that *the table the gate actually runs* refuses this, so the source
    goes in on stdin under a ``src/bloomery/`` filename and ``pyproject.toml``
    resolves from the repo root exactly as ``just quality`` resolves it.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select=TID251",
            "--no-cache",
            "--output-format=concise",
            "--stdin-filename=src/bloomery/planted.py",
            "-",
        ],
        input=source,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    return completed.stdout


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import os\n", "`os` is banned"),
        ("import pathlib\n", "`pathlib` is banned"),
        ("from tempfile import mkdtemp\n", "`tempfile` is banned"),
        ("import requests\n", "`requests` is banned"),
        ("import duckdb\n", "`duckdb` is banned"),
        ("from datetime import datetime\nx = datetime.now()\n", "`datetime.datetime.now`"),
        ("import datetime\nx = datetime.datetime.now()\n", "`datetime.datetime.now`"),
        ("import time\nx = time.time()\n", "`time` is banned"),
        ("import uuid\nx = uuid.uuid4()\n", "`uuid.uuid4` is banned"),
        ("import random\nx = random.random()\n", "`random` is banned"),
        # The member rule alone misses this: the call is spelled `choice(...)`
        # and names no module, so the module ban is what catches it. Found by
        # auditing the guard rather than by using it.
        ("from random import choice\n", "`random` is banned"),
        ("import secrets\n", "`secrets` is banned"),
        # Aliased imports: the local name matches no banned entry on its own, so
        # the root has to be resolved through the import that bound it.
        ("from datetime import datetime as dt\nx = dt.now()\n", "`datetime.datetime.now`"),
        ("import time as t\nx = t.time()\n", "`time` is banned"),
        ("from uuid import uuid4 as u\nx = u()\n", "`uuid.uuid4` is banned"),
        ("import os as o\nx = o.environ\n", "`os` is banned"),
    ],
)
def test_a_planted_violation_is_caught(source: str, expected: str) -> None:
    assert expected in findings_for(source), (
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
        # The types, which the planner's literal grammar needs, as opposed to
        # the clock and id calls that live on them.
        "from datetime import date, datetime\n",
        "from uuid import UUID\n",
    ],
)
def test_what_only_looks_banned_is_not_reported(source: str) -> None:
    assert "TID251" not in findings_for(source), f"false positive on {source!r}"


def test_the_filesystem_carve_out_is_one_line_not_the_cli_package() -> None:
    """RFC 0020 D12. ``cli/io.py`` may open a file; nothing else under ``cli/``
    may, and not even ``io.py`` may read a clock.

    A per-file ignore would pass every test that only checks ``cli/io.py`` may
    import ``pathlib``, while also exempting a ``datetime.now()`` in the same
    file — the tree claiming one door and the guard enforcing none. A
    line-scoped ``# noqa`` cannot do that, which is why the exemption is spelled
    as one, and the assertion that matters is that no file-scoped one exists.
    """
    config = (ROOT / "pyproject.toml").read_text()
    assert "[tool.ruff.lint.per-file-ignores]" not in config, (
        "a per-file ignore would exempt a clock in the same file as the door"
    )

    package = ROOT / "src" / "bloomery"
    exempted = [
        (path.relative_to(package).as_posix(), line.strip())
        for path in sorted(package.rglob("*.py"))
        for line in path.read_text().splitlines()
        if "# noqa: TID251" in line
    ]
    assert [path for path, _ in exempted] == ["cli/io.py"], exempted
    assert exempted[0][1].startswith("from pathlib import Path"), exempted


def test_the_carve_out_does_not_exempt_a_clock() -> None:
    """The exemption covers one *import*, which is all a filesystem needs. A CLI
    that read a clock would still make output depend on when it ran, and nothing
    about reaching a disk justifies that."""
    source = "from pathlib import Path  # noqa: TID251\nfrom datetime import datetime\nstamp = datetime.now()\n"
    assert "`datetime.datetime.now`" in findings_for(source)


def test_the_pygrep_hook_it_replaces_is_gone() -> None:
    """Two guards over one invariant drift apart (RFC 0019 D6). The banned-api
    table is a superset of the hook's four spellings, so the hook is removed —
    this pins that it stays removed."""
    config = (ROOT / ".pre-commit-config.yaml").read_text()
    assert "no-nondeterminism-sources" not in config
    assert "pygrep" not in config


def test_the_gate_runs_it() -> None:
    """A guard CI does not run is a convention, which is the defect D6 names.

    ``ruff check src`` is the gate's first line, and ``TID251`` is in ``select``
    — so unlike the standalone script this replaces, purity now rides the check
    that was always going to run anyway.
    """
    assert '"TID251",' in (ROOT / "pyproject.toml").read_text()
    assert 'ruff check "src"' in (ROOT / "justfile").read_text()
