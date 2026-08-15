"""The RFC-corpus gate is tested, not merely present (RFC 0025 §5.4).

A guard that has never failed is indistinguishable from one that is
misconfigured — the same argument :mod:`test_purity_guard` makes for its
sibling in ``tools/``. These plant each way the corpus and its retirement index
can disagree in a throwaway tree and assert the checker reports it.

Two of them are worth naming, because they are the cases a hand-run sabotage
sweep found and would not have preserved:

* **A malformed row is caught, but by the completeness check rather than by
  parsing.** A row whose SHA is not backticked simply does not match, so its
  number stops being accounted for — which is why the "neither live nor
  retired" finding is the one that fires. The table cannot quietly hold a row
  nothing reads.
* **A spent number at or above the index's next-free claim is caught
  structurally**, not through git. That matters because the git half does not
  run in CI's shallow clone, and number reuse is exactly the failure a reader
  cannot detect from the outside.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "check_rfc_corpus.py"

#: A corpus with one live design (0002) and one retired (0001), which is the
#: smallest tree where every check below has something to say.
INDEX = "The next free number is **0003**.\n"
RETIRED_HEADER = "| # | Title | Retired in |\n|---|---|---|\n"


def load_checker() -> object:
    """Import the gate by path — ``tools/`` is not a package, deliberately: it
    is developer tooling rather than shipped code."""
    spec = importlib.util.spec_from_file_location("check_rfc_corpus", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_rfc_corpus"] = module
    spec.loader.exec_module(module)
    return module


def plant(tmp_path: pathlib.Path, *, retired_rows: str, live: tuple[str, ...] = ("0002-live",)) -> pathlib.Path:
    """A throwaway corpus. No git repository, so the SHA half degrades — which
    is the CI shape, and therefore the one worth exercising by default."""
    rfcs = tmp_path / "rfcs"
    rfcs.mkdir()
    (rfcs / "INDEX.md").write_text(INDEX)
    (rfcs / "RETIRED.md").write_text(RETIRED_HEADER + retired_rows)
    for name in live:
        (rfcs / f"{name}.md").write_text(f"# RFC {name[:4]} — a live design\n")
    return tmp_path


def findings_for(tmp_path: pathlib.Path, **kwargs: object) -> list[str]:
    checker = load_checker()
    root = plant(tmp_path, **kwargs)  # type: ignore[arg-type]
    return [f for f in checker.check(root) if not f.startswith("note:")]  # type: ignore[attr-defined]


def test_a_clean_corpus_is_silent(tmp_path: pathlib.Path) -> None:
    """The control. Every assertion below is worthless if the consistent case
    also reports — a gate that always fires is one that gets switched off."""
    assert findings_for(tmp_path, retired_rows="| 0001 | Retired thing | `abc1234` |\n") == []


def test_a_skipped_row_is_caught(tmp_path: pathlib.Path) -> None:
    """The failure the table exists to prevent: a document deleted and never
    recorded, so its citations lead nowhere."""
    findings = findings_for(tmp_path, retired_rows="")
    assert any("0001 is neither live nor retired" in f for f in findings)


def test_a_malformed_row_is_caught_as_a_missing_one(tmp_path: pathlib.Path) -> None:
    """A row whose SHA is not backticked does not parse, so its number stops
    being accounted for. The table cannot hold a row nothing reads."""
    findings = findings_for(tmp_path, retired_rows="| 0001 | Retired thing | abc1234 |\n")
    assert any("0001 is neither live nor retired" in f for f in findings)


def test_a_retired_number_still_in_the_tree_is_caught(tmp_path: pathlib.Path) -> None:
    """Both live and retired: a deleted design came back without its row going."""
    findings = findings_for(
        tmp_path,
        retired_rows="| 0001 | Retired thing | `abc1234` |\n| 0002 | Came back | `abc1234` |\n",
    )
    assert any("0002 is listed as retired, but" in f for f in findings)


def test_a_duplicated_row_is_caught(tmp_path: pathlib.Path) -> None:
    findings = findings_for(
        tmp_path,
        retired_rows="| 0001 | Retired thing | `abc1234` |\n| 0001 | Again | `abc1234` |\n",
    )
    assert any("0001 appears in more than one row" in f for f in findings)


def test_a_spent_number_above_the_next_free_claim_is_caught(tmp_path: pathlib.Path) -> None:
    """`INDEX.md` promises numbers are never reused, and this is the only check
    that keeps it: 0009 is retired while the index says 0003 is next, so the
    next three RFCs would mint numbers already spent.

    Structural on purpose — the git half does not run in CI's shallow clone,
    which is precisely where this would otherwise pass unseen.
    """
    findings = findings_for(
        tmp_path,
        retired_rows="| 0001 | Retired thing | `abc1234` |\n| 0009 | Ghost | `abc1234` |\n",
    )
    assert any("0009 is retired but the index's next free number is 0003" in f for f in findings)


def test_a_missing_table_is_caught(tmp_path: pathlib.Path) -> None:
    checker = load_checker()
    root = plant(tmp_path, retired_rows="| 0001 | Retired thing | `abc1234` |\n")
    (root / "rfcs" / "RETIRED.md").unlink()
    assert any("missing" in f for f in checker.check(root))  # type: ignore[attr-defined]


def test_an_index_without_a_next_free_claim_is_caught(tmp_path: pathlib.Path) -> None:
    """The claim is the upper bound of the completeness check, so losing it
    silently would disable that check rather than fail it."""
    checker = load_checker()
    root = plant(tmp_path, retired_rows="| 0001 | Retired thing | `abc1234` |\n")
    (root / "rfcs" / "INDEX.md").write_text("no claim here\n")
    findings = [f for f in checker.check(root) if not f.startswith("note:")]  # type: ignore[attr-defined]
    assert any("no 'next free number is" in f for f in findings)


def test_outside_a_repository_the_gate_degrades(tmp_path: pathlib.Path) -> None:
    """`tmp_path` is not a repository, so git runs and exits non-zero. The gate
    reports the skip and keeps its structural findings.

    Named for what it actually reaches: git is installed here, so this does not
    touch the `OSError` branch — the test below does, and it exists because a
    sabotage proved this one alone left that branch dead.
    """
    checker = load_checker()
    root = plant(tmp_path, retired_rows="")
    findings = checker.check(root)  # type: ignore[attr-defined]
    assert any(f.startswith("note: no usable history") for f in findings)
    assert any("0001 is neither live nor retired" in f for f in findings)


def test_a_missing_git_binary_degrades_rather_than_crashing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `git` on `PATH` raises `FileNotFoundError` from `subprocess.run`, and
    letting it escape would end a `just quality` run in a traceback instead of a
    finding — the one failure mode that makes a gate look broken rather than
    unmet.

    Forced rather than hoped for: every other test here runs where git exists,
    so replacing the catch with an unrelated exception type passed all of them.
    """
    checker = load_checker()

    def absent(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(checker, "subprocess", type("S", (), {"run": staticmethod(absent)}))
    root = plant(tmp_path, retired_rows="")
    findings = checker.check(root)  # type: ignore[attr-defined]
    assert any(f.startswith("note: no usable history") for f in findings)
    assert any("0001 is neither live nor retired" in f for f in findings)


def _git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def retired_in_a_real_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    """A repository where one RFC was genuinely retired.

    Returns the root, the SHA that deleted it, and one that did not. The SHA
    half of the gate only runs where history exists, so without this it is a
    detection branch nothing reaches — the tests above all run outside a
    repository, and coverage said so.
    """
    root = tmp_path
    (root / "rfcs").mkdir()
    (root / "rfcs" / "INDEX.md").write_text(INDEX)
    (root / "rfcs" / "RETIRED.md").write_text(RETIRED_HEADER)
    (root / "rfcs" / "0001-gone.md").write_text("# RFC 0001 — gone\n")
    (root / "rfcs" / "0002-live.md").write_text("# RFC 0002 — live\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "add")
    innocent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()[:7]

    (root / "rfcs" / "0001-gone.md").unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "retire 0001")
    retiring = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()[:7]
    return root, retiring, innocent


def test_a_row_naming_its_real_retiring_commit_passes(
    retired_in_a_real_repo: tuple[pathlib.Path, str, str],
) -> None:
    root, retiring, _ = retired_in_a_real_repo
    (root / "rfcs" / "RETIRED.md").write_text(
        RETIRED_HEADER + f"| 0001 | Gone | `{retiring}` |\n"
    )
    checker = load_checker()
    assert checker.check(root) == []  # type: ignore[attr-defined]


def test_a_row_naming_the_wrong_commit_is_caught(
    retired_in_a_real_repo: tuple[pathlib.Path, str, str],
) -> None:
    """A plausible SHA that did not delete the document. Worse than a missing
    row: it reads as recoverable and sends the reader somewhere the document
    never was."""
    root, _, innocent = retired_in_a_real_repo
    (root / "rfcs" / "RETIRED.md").write_text(
        RETIRED_HEADER + f"| 0001 | Gone | `{innocent}` |\n"
    )
    checker = load_checker()
    findings = checker.check(root)  # type: ignore[attr-defined]
    assert any(f"0001 names `{innocent}`" in f for f in findings)


def test_a_sha_that_resolves_to_nothing_is_caught(
    retired_in_a_real_repo: tuple[pathlib.Path, str, str],
) -> None:
    """A mistyped SHA — the realistic version of a wrong one. git errors rather
    than returning an empty answer, which is a different path through
    `deleted_in` than the wrong-but-real commit above, and reaches the same
    finding."""
    root, _, _ = retired_in_a_real_repo
    (root / "rfcs" / "RETIRED.md").write_text(f"{RETIRED_HEADER}| 0001 | Gone | `0000000` |\n")
    checker = load_checker()
    assert any("0001 names `0000000`" in f for f in checker.check(root))  # type: ignore[attr-defined]


def test_the_real_corpus_passes_its_own_gate() -> None:
    """The gate runs against this repository, which is the assertion `just
    quality` makes on every commit — kept here so a corpus edit that breaks it
    fails in the fast tier too."""
    root = pathlib.Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(TOOL), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
