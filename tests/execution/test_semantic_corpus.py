"""The semantic bug corpus, executed (RFC 0042 §6).

Three assertions per case, and the first two are what make the third worth
anything:

1. **The naive query runs.** If it errored, the case would be an ordinary SQL
   bug and belong somewhere else — RFC 0042 D1's whole distinction from
   ``tests/fixtures/dirty/`` is that here every value is valid and every cast
   succeeds.
2. **It returns the wrong number**, and the corrected query returns the right
   one. Both asserted against the case's own ``expected/result.json``, so the
   arithmetic a reviewer checked by hand is the arithmetic the suite checks.
3. **bloomery does what the case says it does** — refuse with a named error,
   accept, or (RFC 0042 §8) not guard it at all.

The third one alone would be a test of bloomery. All three together are a test
that the *problem is real*, which is what a corpus is for: a refusal nobody can
demonstrate a wrong answer behind is a refusal nobody will keep.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
from decimal import Decimal

import duckdb
import pytest

from bloomery import (
    MetricRequest,
    Target,
    build_project_ir,
    compile_project,
    evaluate,
)
from support.execution import materialize, warehouse
from support.planning import make_planner
from support.semantic_corpus import Case, Expectation, Outcome, cases

pytestmark = pytest.mark.execution

CASES = cases()
IDS = [case.name for case in CASES]
REPO = pathlib.Path(__file__).resolve().parents[2]
PLANNER = make_planner()


def _seeded(case: Case) -> duckdb.DuckDBPyConnection:
    """A warehouse holding one case's schema and rows, and nothing else."""
    connection = warehouse("bronze", "silver", "gold")
    connection.execute(case.sql("schema/schema.sql"))
    connection.execute(case.sql("data/rows.sql"))

    return connection


def _row(conn: duckdb.DuckDBPyConnection, sql: str) -> dict[str, Decimal]:
    result = conn.execute(sql)
    names = [column[0] for column in result.description or ()]
    values = result.fetchall()
    assert len(values) == 1, f"a corpus query returns exactly one row, got {len(values)}"

    return dict(zip(names, values[0], strict=True))


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_naive_query_runs_and_is_wrong(case: Case) -> None:
    conn = _seeded(case)
    try:
        expected = case.results()
        naive = _row(conn, case.sql("naive.sql"))
        correct = _row(conn, case.sql("correct.sql"))
    finally:
        conn.close()

    assert naive == expected["naive"]
    assert correct == expected["correct"]
    # The two must differ, or the case is not a case: a naive query that
    # happens to be right proves nothing about the guard that refuses it.
    assert naive != correct, f"{case.name}: naive and correct agree — nothing is wrong here"


@pytest.mark.parametrize(
    ("case", "expectation"),
    [(case, expectation) for case in CASES for expectation in case.expectations],
    ids=[f"{case.name}-{e.name}" for case in CASES for e in case.expectations],
)
def test_bloomery_does_what_the_case_says(case: Case, expectation: Expectation) -> None:
    """Refuse with the named error, or plan and return one of the two numbers.

    The second half is what makes ``unguarded`` a claim rather than a label:
    the spec is compiled, materialized against the case's own warehouse, and
    the metric planned — and the number that comes back is asserted to be the
    **naive** one. Nothing here reads prose, and nothing infers the outcome
    from the state of the repository.
    """
    project, catalog = expectation.project()
    evidence = evaluate(project, catalog=catalog)
    raised = sorted({type(refusal).__name__ for refusal in evidence.refusals})

    if expectation.outcome is Outcome.REFUSED:
        assert expectation.error in raised, (
            f"{case.name}/{expectation.name} pins {expectation.error} "
            f"({expectation.rule}); got {raised or 'no refusal'}"
        )
        # One refusal, not a pile: a case that trips three guardrails is
        # pinning whichever one happens to be reported first.
        assert raised == [expectation.error], (
            f"{case.name}/{expectation.name} should isolate one failure mode, got {raised}"
        )
        return

    assert not raised, f"{case.name}/{expectation.name} expects no refusal; got {raised}"
    assert evidence.stage_reached == "complete"

    ir = build_project_ir(project, catalog)
    conn = _seeded(case)
    try:
        artifacts = compile_project(
            project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog
        )
        materialize(conn, artifacts, supplied=case.supplied)
        plan = PLANNER.plan(ir, MetricRequest(metrics=(case.metric,)), dialect="duckdb")
        (planned,) = conn.execute(plan.sql).fetchall()
    finally:
        conn.close()

    answer = expectation.outcome.answer
    assert answer is not None
    assert dict(zip([case.metric], planned, strict=True)) == case.results()[answer], (
        f"{case.name}/{expectation.name} is {expectation.outcome} and so must plan to the "
        f"{answer!r} result"
    )


def _decision_table(number: str) -> frozenset[str] | None:
    """The decision numbers RFC ``number`` declares, or ``None`` if its text
    cannot be reached.

    A live RFC is read from the tree. A retired one is not in the tree at all —
    ``RETIRED.md`` names a commit it is readable at, which is the whole reason
    that table exists — so it is read with ``git show``. ``None`` means the
    history is unavailable (a shallow clone), never that the RFC has no
    decisions: the caller reports what it could not check rather than passing.
    """
    live = REPO / "rfcs"
    for path in live.glob(f"{number}-*.md"):
        return _decisions(path.read_text(encoding="utf-8"))

    row = re.search(
        rf"^\| {number} \|[^|]*\| `([0-9a-f]{{7,}})`", (live / "RETIRED.md").read_text("utf-8"), re.M
    )
    if row is None:
        return frozenset()

    found = subprocess.run(
        ["git", "ls-tree", "--name-only", row.group(1), "rfcs/"],
        capture_output=True, text=True, cwd=REPO, check=False,
    )
    name = next((n for n in found.stdout.split() if f"/{number}-" in n), None)
    if found.returncode or name is None:
        return None

    shown = subprocess.run(
        ["git", "show", f"{row.group(1)}:{name}"],
        capture_output=True, text=True, cwd=REPO, check=False,
    )

    return _decisions(shown.stdout) if shown.returncode == 0 else None


def _decisions(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"^\| (\d+) \|", text, re.M))


def test_every_cited_rule_names_a_decision_that_exists() -> None:
    """RFC 0042 D3 asks for a **stable rule ID**, and the ID is the whole
    citation, not the number in front of it.

    Before this, `RFC 0010 D9999` passed: the RFC number was checked against
    the live and retired registers and the decision after it against nothing.
    A citation nobody can follow is prose wearing an identifier.

    Sections are refused as well as unchecked numbers. `§5.3` moves when a
    document is edited; a decision row is append-only and its number is never
    reused, which is what makes it stable enough to cite from outside.
    """
    unreachable = []

    for case in CASES:
        for expectation in case.expectations:
            cited = re.fullmatch(r"RFC (\d{4}) D(\d+)", expectation.rule)
            assert cited, (
                f"{case.name}/{expectation.name}: rule {expectation.rule!r} is not "
                "`RFC NNNN Dn`. A section number is not a stable ID — it moves when the "
                "document is edited, and a decision row's number never does"
            )
            number, decision = cited.groups()
            declared = _decision_table(number)
            if declared is None:
                unreachable.append(f"{expectation.rule} ({case.name}/{expectation.name})")
                continue
            assert decision in declared, (
                f"{case.name}/{expectation.name} cites {expectation.rule}, and RFC "
                f"{number} declares no decision {decision}"
            )

    # Reported, never silently skipped: a shallow clone cannot read a retired
    # RFC, and a check that passes quietly there is one nobody notices has
    # stopped running.
    assert not unreachable or _shallow(), (
        f"unreadable RFC text for {unreachable} in a repository with full history"
    )


def _shallow() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True, cwd=REPO, check=False,
    )

    return result.returncode != 0 or result.stdout.strip() != "false"


def test_a_retired_rfc_owns_no_unguarded_case() -> None:
    """RFC 0042 §8's design gate, in the one direction that holds.

    Retirement is the human act that declares an RFC complete. So a retired
    RFC still named by an ``unguarded`` case is a real defect: the document was
    finished without converting a case it owns, the fixture still plans to the
    wrong number, and nothing else notices — the assertion above stays green
    and says only that the number is still wrong, which is what an unguarded
    case is *supposed* to look like.

    **The converse does not hold, and asserting it was a defect of its own.**
    This test was first written as a biconditional — unguarded if and only if
    the cited RFC is live — which assumes an RFC ships all at once. RFC 0038
    ships in phases (§12): D1 and D2 refuse cases 002 and 005 today while the
    lowering of ``DistinctCount`` and ``Snapshot`` waits on RFC 0041, so the
    document is correctly still live and its rules are correctly built. The
    biconditional failed on a tree where nothing was wrong.

    Dropping that half costs nothing, because what makes a case ``refused`` is
    that bloomery refuses it with the named error class, which
    :func:`test_bloomery_does_what_the_case_says` asserts directly. The half
    kept here is the one no number can report.

    **It skips rather than passing when the corpus holds no unguarded case**,
    which is the state RFC 0038 left it in by converting the last two. A guard
    with nothing to guard reports green either way, and green is what a reader
    checks for — so the dormancy is said out loud instead. Cases 006-010 wake
    it, and so does any case added for a rule that has not shipped.
    """
    unguarded = [
        (case, expectation)
        for case in CASES
        for expectation in case.expectations
        if expectation.outcome is Outcome.UNGUARDED
    ]
    if not unguarded:
        pytest.skip(
            "no unguarded expectations in the corpus — every case names a rule that has "
            "shipped, so this gate has nothing to check until one is added that does not"
        )

    retired = set(
        re.findall(r"^\| (\d{4}) \|", (REPO / "rfcs" / "RETIRED.md").read_text("utf-8"), re.M)
    )

    # The citation's *shape* and the existence of the decision row it names are
    # `test_every_cited_rule_names_a_decision_that_exists`, over every
    # expectation rather than only these. This asks the one thing that test
    # cannot: whether the document has been declared finished.
    for case, expectation in unguarded:
        number = expectation.rule.split()[1]

        assert number not in retired, (
            f"{case.name}/{expectation.name} is unguarded and cites {expectation.rule}, "
            f"whose RFC {number} is retired — the document was declared complete without "
            "converting a case it owns. Either the rule did not do what the case says, or "
            "the case was not revisited when it landed (RFC 0042 §8)"
        )
