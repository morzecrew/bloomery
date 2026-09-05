"""The corpus loader is tested, not merely present (RFC 0042 D2/D3).

A harness that skips a malformed case reports green for work nobody did, which
is the failure this corpus exists to catch in *other* people's pipelines. These
plant each way a case can be incomplete in a throwaway tree and assert the
loader refuses it.

The cases worth naming, because a hand-run sweep found them and would not have
preserved them:

* **An expectation declared with no spec beside it is caught, and so is the
  reverse.** Either alone would let the corpus grow a case that asserts nothing
  — a directory of YAML no outcome names, or an outcome no spec can produce.
* **An empty corpus is a failure, not a vacuous pass.** ``cases()`` returning
  nothing would make every parametrized test collect zero cells and the suite
  would still be green.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from support import semantic_corpus
from support.semantic_corpus import REQUIRED, Outcome, cases

pytestmark = pytest.mark.unit

#: The real corpus, for the one check that is about its content rather than
#: about the loader refusing malformed input.
REAL = cases()

OUTCOME = {"one": {"outcome": "accepted", "rule": "RFC 0010 D2"}}


def _plant(root: pathlib.Path) -> pathlib.Path:
    """A minimal well-formed case, for the tests below to break one part of."""
    case = root / "900-planted"
    (case / "schema").mkdir(parents=True)
    (case / "data").mkdir()
    (case / "expected").mkdir()
    (case / "bloomery" / "one").mkdir(parents=True)
    (case / "problem.md").write_text("planted", encoding="utf-8")
    (case / "schema" / "schema.sql").write_text("SELECT 1;", encoding="utf-8")
    (case / "data" / "rows.sql").write_text("SELECT 1;", encoding="utf-8")
    (case / "naive.sql").write_text("SELECT 1;", encoding="utf-8")
    (case / "correct.sql").write_text("SELECT 1;", encoding="utf-8")
    (case / "expected" / "result.json").write_text('{"naive": {}, "correct": {}}', "utf-8")
    (case / "expected" / "semantic_outcome.json").write_text(json.dumps(OUTCOME), "utf-8")

    return case


@pytest.fixture
def planted(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    monkeypatch.setattr(semantic_corpus, "CORPUS", tmp_path)

    return _plant(tmp_path)


def test_the_planted_case_loads(planted: pathlib.Path) -> None:
    """The control. Without it every assertion below could be passing because
    the fixture is broken in some way none of them names."""
    (case,) = cases()

    assert case.name == "900-planted"
    assert [e.name for e in case.expectations] == ["one"]


@pytest.mark.parametrize("part", REQUIRED)
def test_a_case_missing_any_required_part_is_refused(planted: pathlib.Path, part: str) -> None:
    (planted / part).unlink()

    with pytest.raises(AssertionError, match="incomplete case"):
        cases()


def test_a_declared_expectation_with_no_spec_is_refused(planted: pathlib.Path) -> None:
    (planted / "bloomery" / "one").rmdir()

    with pytest.raises(AssertionError, match="declared with no spec"):
        cases()


def test_a_spec_with_no_declared_outcome_is_refused(planted: pathlib.Path) -> None:
    (planted / "bloomery" / "two").mkdir()

    with pytest.raises(AssertionError, match="spec with no declared outcome"):
        cases()


def test_an_empty_corpus_is_a_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a vacuous pass: every corpus test is parametrized over `cases()`, so
    an empty tuple collects nothing and the suite stays green while asserting
    nothing at all."""
    monkeypatch.setattr(semantic_corpus, "CORPUS", tmp_path)

    with pytest.raises(AssertionError, match="corpus cannot be empty"):
        cases()


def test_a_case_that_pins_nothing_is_refused(planted: pathlib.Path) -> None:
    """The hole the other two agreement checks leave open: an empty outcome map
    and an empty ``bloomery/`` agree, so the case loads and asserts nothing
    about bloomery while still contributing its SQL assertions."""
    (planted / "bloomery" / "one").rmdir()
    (planted / "expected" / "semantic_outcome.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AssertionError, match="no expectations"):
        cases()


def test_an_unknown_outcome_word_is_refused(planted: pathlib.Path) -> None:
    """The vocabulary is closed. A typo would otherwise read as a new outcome
    nothing asserts."""
    (planted / "expected" / "semantic_outcome.json").write_text(
        json.dumps({"one": {"outcome": "probably-fine", "rule": "RFC 0010 D2"}}), "utf-8"
    )

    with pytest.raises(ValueError, match="probably-fine"):
        cases()


@pytest.mark.parametrize("case", REAL, ids=[c.name for c in REAL])
def test_the_statement_names_what_the_outcome_file_pins(case: object) -> None:
    """`problem.md` is the only prose in a case, and it restates every fact the
    machine-readable half holds — the expectation names, the outcomes, the
    rules. Nothing reads it at runtime, which is exactly why it can drift: a
    reviewer checking the case by hand reads the prose, and a prose table
    citing a decision the JSON does not is a case that misleads the one person
    it exists for.

    Asserted as containment rather than as a shape, so the statement stays
    free to be a document instead of a serialization.
    """
    statement = (case.directory / "problem.md").read_text(encoding="utf-8")  # type: ignore[attr-defined]

    for expectation in case.expectations:  # type: ignore[attr-defined]
        assert expectation.name in statement, (
            f"{case.name}: problem.md never mentions the {expectation.name!r} expectation"  # type: ignore[attr-defined]
        )
        assert expectation.rule in statement, (
            f"{case.name}: problem.md never cites {expectation.rule}, which "  # type: ignore[attr-defined]
            f"{expectation.name!r} is pinned against"
        )
        assert expectation.outcome.value in statement, (
            f"{case.name}: problem.md never says {expectation.name!r} is "  # type: ignore[attr-defined]
            f"{expectation.outcome.value}"
        )


def test_every_outcome_has_an_assertion_behind_it() -> None:
    """A canary, not a tautology.

    ``test_bloomery_does_what_the_case_says`` branches on ``REFUSED`` and lets
    the other two fall through to "nothing refused", which is right for both —
    what distinguishes them is asserted separately, against whether the cited
    RFC has landed. A **fourth** member would fall through too, and silently
    inherit an assertion written for a different meaning.

    That is the same shape as a ``match`` ending in a catch-all: the new member
    takes its neighbour's behaviour and every existing test still passes. This
    fails instead, and points whoever added it at the two places to decide.
    """
    assert set(Outcome) == {Outcome.REFUSED, Outcome.ACCEPTED, Outcome.UNGUARDED}
