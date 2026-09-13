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
from bloomery.errors import GuardrailError, InsufficientEvidence, SpecParseError
from bloomery.ir import project_fingerprint
from bloomery.guardrails import evidence as guard
from bloomery.semantic import (
    BASIS_PROVENANCE,
    DependencyBasis,
    MAX_DERIVATIONS,
    EvidenceGrade,
    Provenance,
)
from bloomery.spec.marts import Mart
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit


def _project(requirement: str | None, *, imported: bool = False):
    """The corpus fixture, optionally strict and optionally with its one
    relationship marked as read out of an artifact.

    ``imported`` is what makes the refusal reachable from a project rather
    than from a monkeypatched table: `item_of_order` is the `many_to_one` the
    `order_items` mart flattens through, so marking it moves every column that
    hop carries to `ASSUMED` (RFC 0070 P1).
    """

    sources = fixture_sources("ecom_basic")
    if requirement is not None:
        sources["marts"] = sources["marts"].replace(
            "    measures: [gross_revenue]",
            f"    measures: [gross_revenue]\n    requires_evidence: {requirement}",
            1,
        )
    if imported:
        sources["entity_model"] = sources["entity_model"].replace(
            "    cardinality: many_to_one",
            "    cardinality: many_to_one\n    imported_from: metricflow:semantic_manifest.json",
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

    declared = {("many_to_one", "order__customer")}
    derived = {("entity_key", None)}

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
    monkeypatch.setitem(guard.BASIS_PROVENANCE, "one_to_one", Provenance.DERIVED)

    assert guard.weak_bases([{("entity_key", None)}]) == ("entity_key",)
    # A route mixing a declared hop with a derived one is still weak: the
    # column was not reached without the derived step.
    assert guard.weak_bases([{("many_to_one", "r"), ("entity_key", None)}]) == ("entity_key",)
    # And one strong route still acquits.
    assert guard.weak_bases([{("many_to_one", "r")}, {("entity_key", None)}]) == ()


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
    monkeypatch.setitem(guard.BASIS_PROVENANCE, "one_to_one", Provenance.DERIVED)

    weak = [{("entity_key", None)}, {("one_to_one", "r")}][:MAX_DERIVATIONS]
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


def test_the_synthetic_bases_these_tests_use_are_real_ones() -> None:
    """`monkeypatch.setitem` adds a key that was not there, so a test naming a
    basis the vocabulary has dropped keeps passing while testing a fiction.

    That is not hypothetical: `transitive` left `DependencyBasis` in T-0041 and
    these tests named it. This asserts the two they now monkeypatch are members
    the compiler still knows.
    """

    assert {"entity_key", "one_to_one"} <= {basis.value for basis in DependencyBasis}


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


# ....................... #
# An imported relationship is not authored here (RFC 0070 D1, D7)


def test_an_imported_relationship_grades_assumed_and_a_locked_mart_refuses_it() -> None:
    """The first refusal in this suite reached from a project rather than from
    a monkeypatched table.

    `logs/T-0040.md` shipped `requires_evidence: locked` as a requirement no
    project could fail: after the `entity_key` regrade every basis the compile
    path mints grades `LOCKED`, so the only way to reach the refusal was to put
    the table back. `imported_from:` is the producer that closes that gap —
    the hop is still a `many_to_one`, and it was still not written here.
    """

    # The draft is built from the same project asking nothing, because the
    # guardrail stage runs inside `build_project_ir` and the strict one does
    # not get that far — the same staging the monkeypatched test above uses.
    relaxed, catalog = _project("assumed", imported=True)
    draft = build_project_ir(relaxed, catalog)
    strict, _ = _project("locked", imported=True)

    errors = guard.check_evidence(strict, draft)

    assert errors, "an imported relationship under a locked mart must refuse"
    assert all(isinstance(error, InsufficientEvidence) for error in errors)
    # The message names the relationship and the artifact, not the basis: one
    # is already declared, so "declare the relationship" is advice the author
    # cannot act on (RFC 0070 §1).
    message = str(errors[0])
    assert "'item_of_order'" in message
    assert "'metricflow:semantic_manifest.json'" in message
    assert "drop its 'imported_from:'" in message


def test_the_same_project_without_the_key_is_accepted() -> None:
    """The control the test above needs. Without `imported_from:` the identical
    project compiles, so the refusal is the key and not the fixture edit that
    carries it."""

    project, catalog = _project("locked")

    assert guard.check_evidence(project, build_project_ir(project, catalog)) == []
    # …and the refusal above really was this project plus one key: the same
    # compile with the key raises rather than returning, which is the guard
    # running inside `build_project_ir`.
    imported, _ = _project("locked", imported=True)
    with pytest.raises(GuardrailError, match=r"read out of 'metricflow:"):
        build_project_ir(imported, catalog)


def test_an_imported_relationship_costs_nothing_to_a_mart_that_asks_nothing() -> None:
    """`assumed` is the default and accepts every grade a compiling project
    produces, imported included — the annotation lowers a grade, it does not
    refuse on its own."""

    project, catalog = _project("assumed", imported=True)

    assert guard.check_evidence(project, build_project_ir(project, catalog)) == []
    # …and the whole project still compiles, not merely this one guard.
    assert build_project_ir(project, catalog).marts


def test_an_entity_key_hop_cannot_be_imported() -> None:
    """`via` is `None` for `entity_key`, which traverses no relationship — so
    the overlay cannot reach it whatever the imported set contains.

    Asked directly because no fixture can produce the case: a project cannot
    name a relationship that a key hop went through, since there is not one.

    What this pins is the *outcome*, not the `is not None` test that reads as
    its cause. That test is narrowing: `imported` is keyed by relationship
    name, so a `None` misses whether or not it is checked first, and removing
    it changes no answer. Said here because a sweep finds that and a reader
    should not have to.
    """

    assert guard.weak_bases([{("entity_key", None)}], {"item_of_order": "a.json"}) == ()


def test_a_single_imported_route_is_the_only_shape_that_refuses() -> None:
    """One route through an imported relationship is weak, and **any** column
    with two or more routes is not — including two weak ones.

    That second half is not the "strongest route acquits" rule. It is the cap
    abstention: `MAX_DERIVATIONS` is 2, and the cap branch returns
    unconditionally for a list that long, so it answers every multi-route
    column before the acquittal test above it is consulted. Two *weak* routes
    also returning `()` is what distinguishes the two, and it is asserted here
    so this test cannot be read as proving a rule it does not reach
    (`logs/T-0053.md`).
    """

    imported = {"from_artifact": "metricflow:semantic_manifest.json"}
    weak = {("many_to_one", "from_artifact")}
    strong = {("many_to_one", "authored")}

    assert guard.weak_bases([weak], imported) == ("many_to_one",)
    assert guard.weak_bases([strong], imported) == ()
    # Both of these are the cap, not the rule above it.
    assert guard.weak_bases([weak, strong], imported) == ()
    assert guard.weak_bases([weak, weak], imported) == ()


def test_importing_a_relationship_moves_no_fingerprint() -> None:
    """RFC 0070 D3, measured. `imported_from:` is a spec key and reaches no IR
    node, so a project that adds one fingerprints identically.

    The claim is not decorative: `_canon_bytes` writes every dataclass field's
    *name* and writes `None` as a byte, so a field on `RelationshipIR` would
    have moved every fingerprint in the corpus — RFC 0065 row 17's hazard,
    arriving from the same direction a second time. This is the assertion that
    would go red if the key were ever moved onto the IR for convenience.
    """

    plain, catalog = _project(None)
    imported, _ = _project(None, imported=True)

    assert project_fingerprint(build_project_ir(imported, catalog)) == project_fingerprint(
        build_project_ir(plain, catalog)
    )


def test_an_empty_imported_from_is_refused_at_parse() -> None:
    """Presence is the fact, and an empty string is present while naming
    nothing — it would lower the relationship's grade and then produce a
    refusal citing `''` as the artifact.

    Refused for the reason an empty `via:` is: shape is what parse is for, and
    the alternative is a message that helps nobody (PR #115 review).
    """

    sources = fixture_sources("ecom_basic")
    sources["entity_model"] = sources["entity_model"].replace(
        "    cardinality: many_to_one",
        '    cardinality: many_to_one\n    imported_from: ""',
        1,
    )
    with pytest.raises(SpecParseError):
        load_project(sources)
