"""The consumer-evidence guard (RFC 0065 §5.2, §5.3, D3/D4).

A mart declares the weakest premise it accepts under its measures, and a
violation is a compile-time refusal. Every fact reachable today grades
``LOCKED`` — an entity key is entailed by an authored key (RFC 0037's
`entity_key`, regraded in `logs/T-0040.md`), and every other basis is a
relationship somebody declared — so the corpus satisfies ``locked`` and the
refusal is exercised against the mapping rather than against a fixture. That
is stated here rather than left for a reader to infer from a test that never
goes red.
"""

from __future__ import annotations

import dataclasses

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import GuardrailError, InsufficientEvidence
from bloomery.guardrails import evidence as guard
from bloomery.semantic import (
    BASIS_PROVENANCE,
    MAX_DERIVATIONS,
    EvidenceGrade,
    Provenance,
)
from bloomery.spec.marts import Mart
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit


def _project(requirement: str | None):
    sources = fixture_sources("ecom_basic")
    if requirement is not None:
        sources["marts"] = sources["marts"].replace(
            "    measures: [gross_revenue]",
            f"    measures: [gross_revenue]\n    requires_evidence: {requirement}",
            1,
        )
    _, catalog = load_fixture("ecom_basic")
    return load_project(sources), catalog


# ....................... #
# The default is invisible (D3)


def test_absence_is_the_default_and_the_default_asks_nothing() -> None:
    """§6's first test. A project with no key compiles, and it compiles for the
    same reason one writing `assumed` does — not because the guard skipped it."""

    project, _catalog = _project(None)
    assert project.marts is not None
    assert project.marts.marts["order_items"].requires_evidence == "assumed"


def test_a_mart_that_asks_nothing_is_never_walked(monkeypatch: pytest.MonkeyPatch) -> None:
    """`assumed` accepts every grade a compiling project can produce, so the
    guard returns before reading a single fact.

    Asserted **in the pre-regrade world**, which is the only one where the
    difference is observable: with every basis grading `LOCKED`, a guard that
    ignored the requirement and walked every mart would find nothing and look
    identical to one that respected it.
    """

    project, catalog = _project("assumed")
    draft = build_project_ir(project, catalog)
    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)

    assert guard.check_evidence(project, draft) == []
    # …and the same project asking for `locked` does find something, so the
    # emptiness above is the requirement being honoured and not a dead walk.
    strict, _ = _project("locked")
    assert guard.check_evidence(strict, draft) != []


@pytest.mark.parametrize("requirement", ["assumed", "locked"])
def test_either_requirement_compiles_on_this_corpus(requirement: str) -> None:
    """Both settings compile today. `locked` does so because every basis under
    a mart's columns grades `LOCKED`, which is the state the regrade produced
    and the reason this phase ships a requirement no current project fails."""

    project, catalog = _project(requirement)
    assert build_project_ir(project, catalog).marts


# ....................... #
# The refusal (D4)


def test_a_weaker_basis_is_refused_and_the_message_names_the_way_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The predicate, exercised against the mapping it reads.

    Nothing in the corpus grades below `LOCKED`, so the only honest way to
    reach the refusal is to put the table back the way it was before
    `logs/T-0040.md` regraded it — which is exactly the world the measurement
    there describes: all 15 marts refusing on `entity_key`. It doubles as the
    regression test for the regrade, since it fails if `entity_key` is ever
    quietly moved back.
    """

    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)
    project, catalog = _project("locked")

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(project, catalog)

    leaves = [e for e in caught.value.collected if isinstance(e, InsufficientEvidence)]
    assert leaves, "the evidence guard contributed no leaf"
    message = str(leaves[0])
    # D4's four parts: the consumer, the measure, the fact, and how it was got.
    assert "mart 'order_items' requires 'locked'" in message
    assert "'gross_revenue'" in message
    assert "rest on column" in message
    assert "'entity_key'" in message
    # …and the clause without which a team deletes the requirement instead.
    assert "Fix: declare the relationship" in message
    assert "requires_evidence: assumed" in message
    assert leaves[0].source_path == "marts: marts.order_items.requires_evidence"


def test_every_violation_is_collected(monkeypatch: pytest.MonkeyPatch) -> None:
    """§6's aggregate test: a strict mart resting on several weak columns
    reports all of them, so a team sees what the requirement costs in one run
    rather than one refusal per compile."""

    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)
    project, catalog = _project("locked")

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(project, catalog)

    leaves = [e for e in caught.value.collected if isinstance(e, InsufficientEvidence)]
    assert len(leaves) > 1
    columns = [str(e).split("rest on column ")[1].split(",")[0] for e in leaves]
    assert len(set(columns)) == len(leaves), "one leaf per column, not one per (measure, column)"
    assert columns == sorted(columns), "the batch is ordered, so two runs read the same"


def test_a_declared_relationship_is_never_the_weak_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the refusal: what it does *not* name.

    `many_to_one` is a relationship an author wrote, so even in the pre-regrade
    world it grades `LOCKED` and never appears in a message. Without this the
    test above would pass just as well on a guard that refused every column.
    """

    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)
    project, catalog = _project("locked")

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(project, catalog)

    assert not [e for e in caught.value.collected if "'many_to_one'" in str(e)]


def test_a_mart_that_failed_to_flatten_gets_no_second_leaf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mart absent from the draft failed its own check, and that violation is
    already in this batch. Reporting its evidence too would name a mart the
    author is being told about anyway — and would do it from a draft that never
    resolved the mart's columns.

    Exercised against a draft the mart is genuinely missing from, rather than
    trusting the `is None` branch by reading it.
    """

    lenient, catalog = _project("assumed")
    draft = build_project_ir(lenient, catalog)
    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)

    strict, _ = _project("locked")
    assert guard.check_evidence(strict, draft) != [], "the control: this draft does refuse"

    without = dataclasses.replace(draft, marts=())
    assert guard.check_evidence(strict, without) == []


def test_a_column_outside_the_closure_is_passed_over() -> None:
    """A mart may carry a column the closure does not reach.

    `scd2_as_of` flattens a historical entity through an `as_of` anchor, and
    its three `customer_*` columns are not members of the base grain's closure
    — the anchor qualifies the hop at flatten time, not as a functional
    dependency of `order`. There is no derivation to grade, so the guard steps
    over them rather than treating an absent member as a missing premise.

    Both halves matter. Reporting them would refuse a mart for columns it
    carries legitimately; asserting only the pass would not distinguish this
    branch from one that never ran, so the columns are named.
    """

    sources = fixture_sources("scd2_as_of")
    sources["marts"] = sources["marts"].replace(
        "    measures: [revenue]",
        "    measures: [revenue]\n    requires_evidence: locked",
        1,
    )
    _, catalog = load_fixture("scd2_as_of")
    project = load_project(sources)
    draft = build_project_ir(project, catalog)

    carried = {column.name for mart in draft.marts for column in mart.columns}
    assert {"customer_segment", "customer_signed_up_at"} <= carried

    assert guard.check_evidence(project, draft) == []


# ....................... #
# The rule itself, asked directly


def test_a_column_is_as_strong_as_its_strongest_route() -> None:
    """The acquittal no fixture can exercise.

    No column in any fixture is reached two ways, so the corpus cannot tell
    "as strong as its strongest route" from "every route must be strong" —
    and the second is a different rule, not a stricter reading of the first.
    An author who declared a relationship must not be refused because the
    compiler could also have got there through a key.
    """

    declared = {"many_to_one"}
    derived = {"entity_key"}

    # One strong route acquits, whichever order the routes arrive in.
    assert guard.weak_bases([declared, derived]) == ()
    assert guard.weak_bases([derived, declared]) == ()
    # …and with no strong route it reports the weak bases of all of them.
    assert guard.weak_bases([derived]) == ()  # entity_key grades LOCKED today


def test_the_rule_reports_every_weak_basis_when_no_route_is_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of the same rule, in the pre-regrade world where a weak
    basis exists at all."""

    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)
    monkeypatch.setitem(guard.BASIS_PROVENANCE, "transitive", Provenance.DERIVED)

    assert guard.weak_bases([{"entity_key"}]) == ("entity_key",)
    # A route mixing a declared hop with a derived one is still weak: the
    # column was not reached without the derived step.
    assert guard.weak_bases([{"many_to_one", "entity_key"}]) == ("entity_key",)
    # And one strong route still acquits.
    assert guard.weak_bases([{"many_to_one"}, {"entity_key"}]) == ()


def test_a_route_list_at_the_cap_is_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """`closure` keeps at most `MAX_DERIVATIONS` routes per member and drops
    the rest by signature order, so a member holding that many may have had a
    stronger route discarded.

    Refusing there would be a refusal the author cannot act on: the route they
    declared might be the one that was dropped, and telling them to declare a
    relationship they already declared is the remedy-free refusal this design
    was regraded to avoid. Abstaining costs a refusal that is not certain;
    refusing costs one that is wrong.

    Asserted against the constant rather than the literal 2, so raising the cap
    moves this test with it instead of silently changing what it means.
    """

    monkeypatch.setitem(guard.BASIS_PROVENANCE, "entity_key", Provenance.DERIVED)
    monkeypatch.setitem(guard.BASIS_PROVENANCE, "transitive", Provenance.DERIVED)

    weak = [{"entity_key"}, {"transitive"}][:MAX_DERIVATIONS]
    assert len(weak) == MAX_DERIVATIONS
    assert guard.weak_bases(weak) == ()
    # One route below the cap still reports, so the abstention above is the
    # cap and not a guard that stopped refusing anything.
    assert guard.weak_bases(weak[: MAX_DERIVATIONS - 1]) != ()


def test_a_column_reached_by_nothing_is_not_weak() -> None:
    """A determinant of the origin grain is the grain, and a grain is argued
    for by nothing — so an empty route list is not a missing premise."""

    assert guard.weak_bases([]) == ()
    assert guard.weak_bases([set()]) == ()


# ....................... #
# The vocabulary is one vocabulary


def test_the_spec_literal_and_the_grades_agree() -> None:
    """The spec layer spells the requirement as a literal because it sits below
    ``semantic`` in the import contract, which makes it a second copy of a
    closed vocabulary. This is the pin that keeps the two together.

    ``open`` is deliberately absent from the spec side and present in the enum:
    a requirement of "accept anything" is the absence of the annotation, not a
    third setting (§5.2).
    """

    field = Mart.model_fields["requires_evidence"]
    spelled = set(field.annotation.__args__)  # type: ignore[union-attr]

    assert spelled == {grade.value for grade in EvidenceGrade} - {EvidenceGrade.OPEN.value}
    assert field.default == EvidenceGrade.ASSUMED.value


def test_open_is_not_a_requirement() -> None:
    """The absent third setting, refused as the document is read rather than
    honoured and ignored."""

    sources = fixture_sources("ecom_basic")
    sources["marts"] = sources["marts"].replace(
        "    measures: [gross_revenue]",
        "    measures: [gross_revenue]\n    requires_evidence: open",
        1,
    )
    with pytest.raises(Exception, match="Input should be 'locked' or 'assumed'"):
        load_project(sources)


def test_every_basis_grades_and_the_guard_reads_that_grade() -> None:
    """§6's "every `Provenance` member has a grade", pointed at this guard.

    The guard compares against :class:`EvidenceGrade` rather than testing
    provenance members by name, so a basis added to ``BASIS_PROVENANCE``
    without a decision is graded by the same rule as the rest instead of
    falling through it.
    """

    for basis, provenance in BASIS_PROVENANCE.items():
        assert isinstance(provenance.grade, EvidenceGrade), basis
        # Every basis still closes: this guard sits above RFC 0039's floor and
        # never below it (D2), so nothing it admits is unsound.
        assert provenance.closes, basis
