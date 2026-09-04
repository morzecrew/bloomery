"""E2E tier (RFC 0009 §5.2 tier 6): SQLMesh reads the emitted project.

The sibling of ``test_dbt_parse.py``, for the target that had no such test
because it emitted nothing for one to read. RFC 0054 §3 measured two things by
hand; this module is those measurements turned into checks that run.

**Everything here goes through a subprocess, and that is not incidental.**
Importing ``sqlmesh`` extends SQLGlot *globally* — the reason
``reject_when_matched`` builds assignment nodes rather than an ``exp.Whens``
(RFC 0016 D21) — so a test that imported it in-process would make the compiled
bytes of every other test in the session a function of collection order. dbt's
tier can use ``dbtRunner`` in-process precisely because dbt does no such thing.

The gateway comes from the environment, which is the contract this feature
asserts: bloomery emits the project half and never the connection half, exactly
as it emits ``dbt_project.yml`` and never ``profiles.yml``.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from support.compiling import compile_fixture, load_fixture

pytestmark = pytest.mark.e2e

#: The fixture with both properties this tier needs: a catalog date dimension,
#: so `start` is derivable, and two INCREMENTAL_BY_TIME_RANGE models, so the
#: window it produces is observable.
FIXTURE = "ecom_basic"

_TIMEOUT = 300


def _sqlmesh() -> pathlib.Path:
    """The interpreter's own environment, not whatever is on ``PATH``."""
    return pathlib.Path(sys.executable).parent / "sqlmesh"


def _write_project(root: pathlib.Path) -> list[str]:
    paths = []
    for artifact in compile_fixture(FIXTURE, dialect="duckdb"):
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content)
        paths.append(artifact.path)
    return paths


def _run(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    binary = _sqlmesh()
    if not binary.exists():  # pragma: no cover — the dev environment installs it
        pytest.skip(f"sqlmesh is not installed at {binary}")
    return subprocess.run(  # noqa: S603 — a fixed binary path and literal arguments
        [str(binary), *args],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(root),
            "SQLMESH__GATEWAYS__LOCAL__CONNECTION__TYPE": "duckdb",
            "SQLMESH__GATEWAYS__LOCAL__CONNECTION__DATABASE": str(root / "warehouse.duckdb"),
            "SQLMESH__DEFAULT_GATEWAY": "local",
        },
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def test_sqlmesh_reads_the_emitted_project(tmp_path: pathlib.Path) -> None:
    """The tier's whole contract. Before `config.yaml` the answer was "SQLMesh
    project config could not be found" — not a worse project, no project — and
    no golden could see it, because a golden reads the bytes and SQLMesh reads
    the directory.
    """
    paths = _write_project(tmp_path)
    models = sum(1 for path in paths if path.startswith("models/"))
    result = _run(tmp_path, "info")
    assert f"Models: {models}" in result.stdout, result.stdout + result.stderr
    assert "connection succeeded" in result.stdout, result.stdout + result.stderr


def test_the_backfill_window_opens_at_the_catalogs_first_year(tmp_path: pathlib.Path) -> None:
    """RFC 0054 D2's regression, and the reason the artifact carries a `start`.

    Without one SQLMesh backfills every INCREMENTAL_BY_TIME_RANGE model over a
    **single day** and reports success — a plan that goes green having loaded
    one partition of history. This is the test that fails if someone later
    simplifies the config down to `dialect`, and it is the only place that
    failure is visible: the artifact is still well-formed, still deterministic,
    still byte-identical to its golden.

    The expected year is read off the fixture's catalog rather than retyped, so
    a derivation that stopped reading the catalog would fail here rather than
    keep passing against a hard-coded 2020.
    """
    _project, catalog = load_fixture(FIXTURE)
    assert catalog is not None
    start = f"{catalog.date_dimension.start_year}-01-01"

    _write_project(tmp_path)
    result = _run(tmp_path, "plan", "--no-prompts")
    output = result.stdout + result.stderr
    assert "Models needing backfill" in output, output
    assert f"[{start} -" in output, output
