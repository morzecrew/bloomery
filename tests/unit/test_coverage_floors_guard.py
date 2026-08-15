"""The per-package coverage floors are tested, not merely declared (RFC 0025 §5.2).

A floor nobody has seen fail is indistinguishable from a floor that measures
nothing — and this one has a specific way of measuring nothing: `coverage
report --include=<glob>` over a glob that matches no file exits non-zero and
says "No data to report", which a naive reader of the exit code would treat as
a failure and a naive reader of the percentage would treat as a pass. Neither
is right; the honest answer is that the floor did not run.

That case is not hypothetical. The floors are globs into `src/bloomery/`, so
renaming a package silently retires its floor. `guardrails/` is the one that
matters most (RFC 0009 D9) and would be the quietest to lose.

The checker is loaded by path, as `test_purity_guard` and
`test_rfc_corpus_guard` load theirs: `tools/` is not a package, and the thing
under test is the file CI runs.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "check_coverage_floors.py"

_PYPROJECT = """\
[project]
name = "throwaway"

[tool.bloomery.coverage-floors]
{floors}
"""


def load_checker() -> object:
    spec = importlib.util.spec_from_file_location("check_coverage_floors", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


def _tree(tmp_path: pathlib.Path, floors: str) -> pathlib.Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT.format(floors=floors))
    return tmp_path


# ....................... #
# The table itself


def test_the_declared_floors_are_read(tmp_path: pathlib.Path) -> None:
    root = _tree(tmp_path, '"src/a/*" = 95\n"src/b/*" = 100\n')
    assert CHECKER.floors(root) == {"src/a/*": 95.0, "src/b/*": 100.0}


def test_a_missing_table_is_a_finding_not_a_pass(tmp_path: pathlib.Path) -> None:
    """The whole file becoming a no-op is the failure with no symptom: every
    package would be 'at its floor' because no package has one."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "throwaway"\n')
    (findings,) = CHECKER.check(tmp_path)
    assert "no [tool.bloomery.coverage-floors] table" in findings


def test_a_non_numeric_entry_is_ignored_rather_than_crashing(
    tmp_path: pathlib.Path,
) -> None:
    root = _tree(tmp_path, '"src/a/*" = 95\n"src/b/*" = "later"\n')
    assert CHECKER.floors(root) == {"src/a/*": 95.0}


# ....................... #
# Measuring


def test_a_glob_matching_nothing_is_a_finding(tmp_path: pathlib.Path) -> None:
    """The vacuous pass this file exists for. A renamed package leaves its
    floor pointing at nothing, and 'no files' must not read as 'no problem'."""
    root = _tree(tmp_path, '"src/bloomery/no_such_package/*" = 90\n')
    (finding,) = CHECKER.check(root)
    assert "no coverage could be measured" in finding
    assert "always passes" in finding


def test_every_package_below_its_floor_is_reported_not_just_the_first(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batched for the same reason the guardrail stage batches: a contributor
    fixing coverage should see the whole list in one round-trip."""
    root = _tree(tmp_path, '"src/a/*" = 90\n"src/b/*" = 90\n"src/c/*" = 10\n')
    monkeypatch.setattr(CHECKER, "measured", lambda _root, glob: 50.0 if glob < "src/c" else 99.0)
    findings = CHECKER.check(root)
    assert [f.split(":")[0] for f in findings] == ["src/a/*", "src/b/*"]
    assert "50.0% is below its floor of 90%" in findings[0]


def test_a_package_exactly_at_its_floor_passes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary is `<`, not `<=`: a floor of 92 against a measured 92.0
    must not fail, or every floor would have to be set below its own name."""
    root = _tree(tmp_path, '"src/a/*" = 92\n')
    monkeypatch.setattr(CHECKER, "measured", lambda _root, _glob: 92.0)
    assert CHECKER.check(root) == []


def test_an_unreadable_coverage_report_is_a_finding_not_a_crash(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`measured` shells out, and a `coverage` that is absent or broken must
    end the run in a finding rather than a traceback — the same rule the RFC
    corpus checker follows for a missing `git`."""
    root = _tree(tmp_path, '"src/a/*" = 90\n')

    class _Broken:
        @staticmethod
        def run(*_args: object, **_kwargs: object) -> object:
            class _Result:
                returncode = 1
                stdout = "No data to report.\n"

            return _Result()

    monkeypatch.setattr(CHECKER, "subprocess", _Broken)
    (finding,) = CHECKER.check(root)
    assert "no coverage could be measured" in finding


# ....................... #
# Reading `coverage report`'s output
#
# Most tests above monkeypatch `measured`, which left the parsing itself
# uncovered — and the parsing is the part that breaks when `coverage`'s output
# format moves, silently turning every floor into "could not measure". Found by
# measuring this file's own coverage rather than by reading it.


def _with_output(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0) -> None:
    class _Fake:
        @staticmethod
        def run(*_args: object, **_kwargs: object) -> object:
            class _Result:
                pass

            result = _Result()
            result.returncode = returncode  # type: ignore[attr-defined]
            result.stdout = stdout  # type: ignore[attr-defined]
            return result

    monkeypatch.setattr(CHECKER, "subprocess", _Fake)


_HEADER = "Name    Stmts   Miss Branch BrPart  Cover\n----\n"


def test_a_total_line_is_read(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_output(monkeypatch, _HEADER + "TOTAL   692      1    276      1  99.8%\n")
    assert CHECKER.measured(tmp_path, "src/a/*") == 99.8


def test_a_single_file_report_is_read_without_a_total(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`coverage report` over a glob matching one file prints the file row and
    no TOTAL. A parser that only looked for TOTAL would report "could not
    measure" for the smallest packages — the ones whose floor is easiest to
    hold and so least likely to be noticed missing."""
    _with_output(monkeypatch, _HEADER + "src/bloomery/a/b.py   12   0   4   0  100.0%\n")
    assert CHECKER.measured(tmp_path, "src/bloomery/a/*") == 100.0


def test_a_report_with_nothing_to_read_is_none(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_output(monkeypatch, "No data to report.\n")
    assert CHECKER.measured(tmp_path, "src/a/*") is None


def test_an_unparseable_percentage_is_none_not_a_crash(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A TOTAL row whose last column is not a number — a format change, or a
    `coverage` that grew a column. Reported as unmeasured rather than raising
    mid-gate."""
    _with_output(monkeypatch, _HEADER + "TOTAL   692      1    276      1  n/a\n")
    assert CHECKER.measured(tmp_path, "src/a/*") is None


def test_the_last_matching_line_wins(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TOTAL comes after the file rows, so the scan runs from the bottom. Read
    top-down it would return the first file's percentage and call it the
    package's."""
    _with_output(
        monkeypatch,
        _HEADER
        + "src/bloomery/a/b.py   12   6   4   0  50.0%\n"
        + "src/bloomery/a/c.py   12   0   4   0  100.0%\n"
        + "TOTAL                 24   6   8   0  75.0%\n",
    )
    assert CHECKER.measured(tmp_path, "src/bloomery/a/*") == 75.0


# ....................... #
# The real table


def test_the_shipped_table_covers_every_package_under_src() -> None:
    """A floor per package, with no package quietly outside the table.

    Adding a package and forgetting its floor is the omission that makes a
    per-package ratchet decorative — the new code is exactly the code with no
    floor. `__pycache__` and the version file are not packages.
    """
    declared = {glob.removeprefix("src/bloomery/").removesuffix("/*") for glob in CHECKER.floors(ROOT)}
    present = {
        path.name
        for path in (ROOT / "src" / "bloomery").iterdir()
        if path.is_dir() and path.name != "__pycache__"
    }
    assert present - declared == set(), f"packages with no declared floor: {sorted(present - declared)}"


def test_the_modules_outside_any_package_have_a_floor() -> None:
    """The other half of the table's completeness, and the half a
    directory-shaped rule cannot express.

    `test_the_shipped_table_covers_every_package_under_src` walks
    `src/bloomery/` for *directories*, so six modules sitting beside them —
    `errors.py`, the root of the entire refusal hierarchy, among them — were
    outside every glob and had no floor at all. Nothing failed, because a
    package with no floor is exactly as green as one that holds.
    """
    assert "src/bloomery/*.py" in CHECKER.floors(ROOT)
    top_level = {
        path.name
        for path in (ROOT / "src" / "bloomery").iterdir()
        if path.suffix == ".py" and path.name != "_version.py"
    }
    assert top_level, "no top-level modules found — the glob above now measures nothing"


def test_the_guardrails_floor_is_still_a_hundred() -> None:
    """RFC 0009 D9 through RFC 0025 D3: the one floor that is exact rather
    than one notch below, and explicitly not up for renegotiation."""
    assert CHECKER.floors(ROOT)["src/bloomery/guardrails/*"] == 100.0


def test_the_tool_runs_as_a_script() -> None:
    """`just coverage` and CI invoke it as a subprocess, so the entry point is
    part of the contract — a module that imports cleanly and cannot be run is
    a gate that never runs."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Per-package coverage floors" in result.stdout
