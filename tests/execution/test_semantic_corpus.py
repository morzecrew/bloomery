"""The semantic bug corpus, executed (S-0056/engine-execution).

Three assertions per case, and the first two are what make the third worth
anything:

1. **The naive query runs.** If it errored, the case would be an ordinary SQL
   bug and belong somewhere else — S-0056/D-1's whole distinction from
   ``tests/fixtures/dirty/`` is that here every value is valid and every cast
   succeeds.
2. **It returns the wrong number**, and the corrected query returns the right
   one. Both asserted against the case's own ``expected/result.json``, so the
   arithmetic a reviewer checked by hand is the arithmetic the suite checks.
3. **bloomery does what the case says it does** — refuse with a named error,
   accept, or (S-0056/corpus-as-design-gate) not guard it at all.

The third one alone would be a test of bloomery. All three together are a test
that the *problem is real*, which is what a corpus is for: a refusal nobody can
demonstrate a wrong answer behind is a refusal nobody will keep.
"""

from __future__ import annotations

import pathlib
import re
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
from bloomery.semantic import RULES
from support.execution import materialize, warehouse
from support.planning import make_planner
from support.semantic_corpus import (
    DECISION_CITATION,
    Case,
    Expectation,
    Outcome,
    cases,
    unregistered_rule,
)

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
        plan = PLANNER.plan(ir, MetricRequest(metrics=case.metrics), dialect="duckdb")
        (planned,) = conn.execute(plan.sql).fetchall()
    finally:
        conn.close()

    # The arm's own answer where it has one, and the outcome's otherwise. An
    # arm declares one when it is right and returns the *other* number — a case
    # with two readings has two right answers, and only one of them is the
    # question the naive query asked (S-0077/tests).
    answer = expectation.answer or expectation.outcome.answer
    assert answer is not None
    assert dict(zip(case.metrics, planned, strict=True)) == case.results()[answer], (
        f"{case.name}/{expectation.name} is {expectation.outcome} and so must plan to the "
        f"{answer!r} result"
    )


SPECS = REPO / ".torve" / "specs"


def _decision_table(number: str) -> frozenset[str] | None:
    """The decision ids document ``S-number`` declares, or ``None`` when no
    such document is in the corpus. Every document — live or landed — is in
    `.torve/specs/`, so nothing here reads history."""
    path = SPECS / f"S-{number}" / "decisions.yaml"
    if not path.is_file():
        return None
    return frozenset(re.findall(r"^  - id: (D-\d+)$", path.read_text(encoding="utf-8"), re.M))


def _landed() -> set[str]:
    """The document numbers whose implementation is complete: the corpus's
    word for what retirement used to say."""
    return {
        path.parent.name[2:]
        for path in SPECS.glob("S-*/document.yaml")
        if re.search(r"^implementation: complete$", path.read_text(encoding="utf-8"), re.M)
    }


def test_every_cited_rule_names_a_decision_that_exists() -> None:
    """S-0056/D-3 asks for a **stable rule ID**, and the ID is the whole
    citation, not the number in front of it.

    Before this, `S-0027/D-9999` passed: the document number was checked
    against the register and the decision after it against nothing.
    A citation nobody can follow is prose wearing an identifier.

    Sections are refused as well as unchecked numbers. `§5.3` moves when a
    document is edited; a decision row is append-only and its number is never
    reused, which is what makes it stable enough to cite from outside.

    **Two registers, both accepted, each checked against itself.** A proof rule
    id resolves against `bloomery.semantic.RULES`, which S-0005/D-8 governs as
    append-only and which this process can read; an `S-NNNN/D-n` resolves
    against that document's `decisions.yaml`. The R-id is the stronger citation on
    D3's own terms — machine-readable, never reused, and verifiable without
    opening a document that may since have been retired — and the older form
    stays because every case written before R009 uses it (logs/T-0025.md,
    D-159).
    """
    missing = []

    for case in CASES:
        for expectation in case.expectations:
            unusable = unregistered_rule(expectation.rule, RULES)
            assert not unusable, f"{case.name}/{expectation.name}: {unusable}"

            cited = DECISION_CITATION.fullmatch(expectation.rule)
            if cited is None:  # a proof-rule id, resolved against RULES above
                continue

            number, decision = cited.groups()
            declared = _decision_table(number)
            if declared is None:
                missing.append(f"{expectation.rule} ({case.name}/{expectation.name})")
                continue
            assert f"D-{decision}" in declared, (
                f"{case.name}/{expectation.name} cites {expectation.rule}, and S-"
                f"{number} declares no decision D-{decision}"
            )

    assert not missing, f"no document in the corpus for {missing}"


def test_a_retired_rfc_owns_no_unguarded_case() -> None:
    """S-0056/corpus-as-design-gate's design gate, in the one direction that holds.

    Retirement is the human act that declares an RFC complete. So a retired
    RFC still named by an ``unguarded`` case is a real defect: the document was
    finished without converting a case it owns, the fixture still plans to the
    wrong number, and nothing else notices — the assertion above stays green
    and says only that the number is still wrong, which is what an unguarded
    case is *supposed* to look like.

    **The converse does not hold, and asserting it was a defect of its own.**
    This test was first written as a biconditional — unguarded if and only if
    the cited RFC is live — which assumes an RFC ships all at once. S-0053
    ships in phases (§12): D1 and D2 refuse cases 002 and 005 today while the
    lowering of ``DistinctCount`` and ``Snapshot`` waits on S-0055, so the
    document is correctly still live and its rules are correctly built. The
    biconditional failed on a tree where nothing was wrong.

    Dropping that half costs nothing, because what makes a case ``refused`` is
    that bloomery refuses it with the named error class, which
    :func:`test_bloomery_does_what_the_case_says` asserts directly. The half
    kept here is the one no number can report.

    **It skips rather than passing when the corpus holds no unguarded case**,
    which is the state S-0053 left it in by converting the last two. A guard
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

    retired = _landed()

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
            "the case was not revisited when it landed (S-0056/corpus-as-design-gate)"
        )
