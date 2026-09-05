"""The proof vocabulary (RFC 0039 §10).

Five kinds of test, one per line of §10, plus the registry discipline D8 asks
for. The corpus is `support.grain_model`'s — the same one the closure tests and
the determinism guard read, so a shape that stops being exercised there stops
being exercised here too rather than quietly diverging.
"""

from __future__ import annotations

import dataclasses

import pytest
from bloomery.semantic import (
    RULES,
    SUPERSEDED,
    Obligation,
    Proof,
    Provenance,
    Refutation,
    SemanticFact,
    SemanticJudgement,
    can_roll_up,
    prove_rollup,
)
from bloomery.semantic.nodes import DependencyBasis, RollupProof
from bloomery.semantic.proof import BASIS_PROVENANCE, BASIS_RULES
from support.grain_model import ANCHORED, CORPUS, QUESTIONS, grain

pytestmark = pytest.mark.unit


def _fact(provenance: Provenance) -> SemanticFact:
    return SemanticFact(source="entity:order.shipping", provenance=provenance, statement="s")


# ----------------------- #
# §10 — negative: an unknown fact cannot close an obligation


@pytest.mark.parametrize(
    ("provenance", "closes"),
    [
        (Provenance.DECLARED, True),
        (Provenance.DERIVED, True),
        (Provenance.IMPORTED_VERIFIED, True),
        (Provenance.INFERRED_HEURISTIC, False),
        (Provenance.UNKNOWN, False),
    ],
)
def test_only_declared_derived_and_imported_close_an_obligation(
    provenance: Provenance, closes: bool
) -> None:
    """D1, `LOCKED`, stated once as a table. Parametrized over every member so
    the test enumerates the enum rather than sampling it — a sixth member added
    without a decision fails the membership canary below, not this."""
    assert provenance.closes is closes
    assert _fact(provenance).closes is closes


def test_the_provenance_vocabulary_is_closed() -> None:
    """The canary D1 needs, and it is not a restatement of the enum: a new
    member would otherwise inherit whichever side of `closes` it fell on, and
    the parametrized table above would still pass because it names the five it
    was written for."""
    assert set(Provenance) == {
        Provenance.DECLARED,
        Provenance.DERIVED,
        Provenance.IMPORTED_VERIFIED,
        Provenance.INFERRED_HEURISTIC,
        Provenance.UNKNOWN,
    }


def test_one_heuristic_leaf_makes_the_whole_proof_unclosed() -> None:
    """A proof is exactly as good as the worst fact under it, however deep.

    The heuristic is buried two levels down and under a sibling that is fine,
    because a check that only looked at its own `facts` would pass this and
    report a guess as a proof.
    """
    deep = Proof(
        rule="R001",
        conclusion=SemanticJudgement("Determines", (("to", "order.region"),)),
        facts=(_fact(Provenance.INFERRED_HEURISTIC),),
    )
    sound = Proof(
        rule="R002",
        conclusion=SemanticJudgement("Determines", (("to", "order.customer_id"),)),
        facts=(_fact(Provenance.DECLARED),),
    )
    root = Proof(
        rule="R006",
        conclusion=SemanticJudgement("SafeRollup"),
        premises=(sound, Proof(rule="R005", conclusion=SemanticJudgement("Reaches"), premises=(deep,))),
    )

    assert sound.closed
    assert not root.closed
    assert Provenance.INFERRED_HEURISTIC in {fact.provenance for fact in root.leaves}


# ----------------------- #
# §10 — property: deterministic derivations (D6, `LOCKED`)


def test_premise_order_is_canonical_not_construction_order() -> None:
    """Two proofs built with their premises in opposite orders are one value.

    This is the failure mode RFC 0003 keeps meeting: the walk that produces
    premises is a graph traversal, and its order is the thing least likely to
    be stable across processes.
    """
    a = Proof(rule="R001", conclusion=SemanticJudgement("Reaches", (("column", "a"),)))
    b = Proof(rule="R002", conclusion=SemanticJudgement("Reaches", (("column", "b"),)))

    forward = Proof(rule="R006", conclusion=SemanticJudgement("SafeRollup"), premises=(a, b))
    reverse = Proof(rule="R006", conclusion=SemanticJudgement("SafeRollup"), premises=(b, a))

    assert forward == reverse
    assert forward.serialize() == reverse.serialize()


def test_a_judgements_operands_are_canonical() -> None:
    left = SemanticJudgement("SafeRollup", (("from", "x"), ("to", "y")))
    right = SemanticJudgement("SafeRollup", (("to", "y"), ("from", "x")))

    assert left == right
    assert left.render() == "SafeRollup(from=x, to=y)"


def test_the_sort_key_is_total_over_the_node() -> None:
    """Two premises of one rule differ only in their conclusion, so a key
    stopping at `rule` leaves them tied — and a tie is resolved by whatever
    order the walk produced, which is the bug this key exists to prevent."""
    first = Proof(rule="R001", conclusion=SemanticJudgement("Reaches", (("column", "a"),)))
    second = Proof(rule="R001", conclusion=SemanticJudgement("Reaches", (("column", "b"),)))

    assert first.sort_key != second.sort_key
    assert Proof(
        rule="R006", conclusion=SemanticJudgement("S"), premises=(second, first)
    ).premises == (first, second)


def test_serialization_carries_nothing_that_varies_between_processes() -> None:
    """§9's list, asserted rather than promised: no addresses, no timestamps."""
    source, target = QUESTIONS[0]
    answer = prove_rollup(source, target, CORPUS)
    assert isinstance(answer, Proof)

    encoded = answer.serialize()

    assert "0x" not in encoded
    assert "object at" not in encoded
    assert encoded == prove_rollup(source, target, CORPUS).serialize()


# ----------------------- #
# §10 — snapshot: the proof trees themselves


@pytest.mark.parametrize(
    ("source", "target"), QUESTIONS, ids=[f"{s.label}->{t.label}" for s, t in QUESTIONS]
)
def test_every_corpus_question_renders(source: object, target: object) -> None:
    """Not a golden file: what is pinned is that every answer shape *has* a
    rendering and a serialization, since a proof nobody can print is evidence
    nobody can read. The bytes are pinned by the determinism guard, which
    compares them across processes rather than against a checked-in string."""
    answer = prove_rollup(source, target, CORPUS)  # type: ignore[arg-type]

    assert answer.render()
    assert answer.document()
    # Both halves, not just the proven one: `Proven | Refused` is one
    # vocabulary and a caller holding the union should not have to ask which
    # half it has before writing the answer down. The determinism guard found
    # this — `Refutation` had no `serialize` at all.
    assert answer.serialize()

    if isinstance(answer, Proof):
        assert answer.closed
        assert answer.rule in RULES


def test_a_proof_names_every_rule_that_admitted_it() -> None:
    """RFC 0042 §10 asks which rule admitted a case, and a tree whose nodes
    cite ids is what answers it."""
    answer = prove_rollup(
        grain("order_item", "order_id", "line_id"), grain("customer", "customer_id"), CORPUS
    )
    assert isinstance(answer, Proof)

    rendered = answer.render()

    assert "R006" in rendered
    assert "R002" in rendered  # the many_to_one hops that reached the customer


def test_an_axiom_is_emitted_rather_than_dropped() -> None:
    """A determinant of the origin grain is determined by nothing, and a proof
    that omits its own starting points reads as though it proved more than it
    did. Found by a rollup of a grain to itself, which is every determinant an
    axiom and was an `IndexError` before R007 existed."""
    order = grain("order", "order_id")
    answer = prove_rollup(order, order, CORPUS)

    assert isinstance(answer, Proof)
    assert "R007" in answer.render()
    assert answer.closed


def test_a_single_hop_is_not_wrapped_in_a_composition() -> None:
    """R005 composes two or more dependencies. Wrapping one hop in it would
    repeat the hop's own rule a line higher and claim a composition that
    composed nothing."""
    answer = prove_rollup(
        grain("order_item", "order_id", "line_id"), grain("order", "order_id"), CORPUS
    )
    assert isinstance(answer, Proof)

    (only,) = answer.premises

    assert only.rule == "R002"
    assert only.premises == ()


# ----------------------- #
# §10 — adversarial: remove a premise, require refusal


def test_removing_the_relationship_turns_the_proof_into_a_refutation() -> None:
    """The premise that carried it, taken away. Without this the proof above
    demonstrates only that *something* produced a tree — not that the tree
    rests on the relationship it names."""
    source = grain("order_item", "order_id", "line_id")
    target = grain("customer", "customer_id")

    assert isinstance(prove_rollup(source, target, CORPUS), Proof)

    without = dataclasses.replace(
        CORPUS,
        relationships=tuple(r for r in CORPUS.relationships if r.name != "order_customer"),
    )
    answer = prove_rollup(source, target, without)

    assert isinstance(answer, Refutation)
    assert answer.obligations
    assert answer.remediation


def test_a_refutation_states_the_smallest_failed_obligation() -> None:
    """§6: what was required, and what was found instead."""
    answer = prove_rollup(
        grain("order", "order_id"), grain("order_item", "order_id", "line_id"), CORPUS
    )

    assert isinstance(answer, Refutation)
    assert answer.reason == "refinement"
    assert any("order_item" in obligation.required for obligation in answer.obligations)
    assert "finer" in answer.remediation


def test_a_refutation_never_claims_impossibility() -> None:
    """§6 says a refutation is not a proof that no derivation could exist, and
    the wording must not claim more. The rule set grows; a request refused
    today may be provable in the next release with the data unchanged."""
    for source, target in QUESTIONS:
        answer = prove_rollup(source, target, CORPUS)
        if not isinstance(answer, Refutation):
            continue

        rendered = answer.render().lower()

        assert rendered.startswith("cannot prove")
        for overclaim in ("impossible", "never possible", "cannot be done", "no such"):
            assert overclaim not in rendered, f"{answer.reason}: refutation claims {overclaim!r}"


# ----------------------- #
# §10 — parity: the existing boundary is unchanged (D3, `LOCKED`)


@pytest.mark.parametrize(
    ("source", "target"), QUESTIONS, ids=[f"{s.label}->{t.label}" for s, t in QUESTIONS]
)
@pytest.mark.parametrize("context", [None, ANCHORED], ids=["unanchored", "anchored"])
def test_the_proof_agrees_with_the_answer_it_expresses(
    source: object, target: object, context: object
) -> None:
    """D3 in one assertion. `prove_rollup` is a second *reading* of
    `can_roll_up`, not a second decision — so the two can never disagree about
    whether a rollup is safe, and the narrow answer stays the authority until
    something has compared them. This is that something.
    """
    arguments = (source, target, CORPUS) if context is None else (source, target, CORPUS, context)
    narrow = can_roll_up(*arguments)  # type: ignore[arg-type]
    expressed = prove_rollup(*arguments)  # type: ignore[arg-type]

    assert isinstance(narrow, RollupProof) == isinstance(expressed, Proof)

    if isinstance(narrow, RollupProof):
        assert isinstance(expressed, Proof)
        # Every determinant the narrow answer reached is accounted for, matched
        # by *which* rather than by how many: a proof that dropped one would
        # claim the rollup on less than it stands on and still be a proof, and a
        # count is blind to that wherever the target has a single determinant —
        # which was every proven question in the corpus until one was added.
        #
        # Read off the conclusion's operands rather than rebuilt from the
        # derivation: reconstructing what `_determined_proof` would have made
        # compares that function against itself and passes however wrong its
        # notion of "reached" becomes. A premise names its column under `to`
        # when it is a single hop and under `column` when it is an axiom or a
        # composition, and that is the whole of what this needs to know.
        reached = {
            value
            for premise in expressed.premises
            for name, value in premise.conclusion.operands
            if name in ("to", "column")
        }

        assert reached == {str(member.ref) for member in narrow.determinants}
        assert len(expressed.premises) == len(narrow.determinants)

    else:
        assert isinstance(expressed, Refutation)
        assert expressed.reason == narrow.reason.value


# ----------------------- #
# D8 — the rule registry is a public contract


def test_every_rule_is_documented_and_uniquely_identified() -> None:
    """D5: named, individually documented, independently testable. A summary
    is what makes a rendered proof readable, so an empty one is a rule nobody
    can cite in prose."""
    assert RULES

    for identifier, rule in RULES.items():
        assert rule.id == identifier
        assert rule.summary.strip()


def test_every_rule_a_basis_maps_to_exists() -> None:
    """The translation table cannot cite an id the registry does not carry,
    and `Proof` refuses one at construction — this fails at the table rather
    than at whichever proof happened to use it first."""
    assert set(BASIS_RULES) == {basis.value for basis in DependencyBasis}
    assert set(BASIS_PROVENANCE) == {basis.value for basis in DependencyBasis}

    for identifier in BASIS_RULES.values():
        assert identifier in RULES


def test_no_basis_is_admitted_on_a_fact_that_cannot_close() -> None:
    """RFC 0037 D3 closed the basis vocabulary so that no heuristic contributes
    a member. This asserts the two documents agree: every way of believing a
    dependency rests on a fact that may close an obligation."""
    for basis, provenance in BASIS_PROVENANCE.items():
        assert provenance.closes, f"basis {basis!r} rests on {provenance}, which cannot close"


def test_a_rule_id_is_never_minted_at_a_call_site() -> None:
    """D8: the ids are a public contract from the moment CI asserts on them,
    so one invented in passing would ship a contract nobody registered."""
    with pytest.raises(ValueError, match="not in the registry"):
        Proof(rule="R999", conclusion=SemanticJudgement("SafeRollup"))


def test_a_superseded_rule_keeps_its_entry() -> None:
    """Append-only, by the discipline the decision tables use (logs/T-0020.md
    D-112). A citation written against a split rule still resolves, and the
    entry says what replaced it.

    `SUPERSEDED` is empty today and the assertion is not vacuous: it pins that
    every listed id is *still in* the registry, which is the half that breaks
    when someone deletes a rule instead of superseding it.
    """
    for identifier in SUPERSEDED:
        assert identifier in RULES, f"{identifier} was removed rather than superseded"
        assert RULES[identifier].superseded_by
        assert not RULES[identifier].live

    assert all(rule.live for rule in RULES.values() if rule.id not in SUPERSEDED)


# ----------------------- #
# Shapes the vocabulary has to hold


def test_both_halves_carry_the_same_surface() -> None:
    """D2 types the answer as `Proven | Refused`, so the two halves owe the
    same methods. An asymmetric surface makes the refusal second-class, which
    is backwards — it is the answer this compiler gives most often."""
    for name in ("render", "document", "serialize"):
        assert callable(getattr(Proof, name)), name
        assert callable(getattr(Refutation, name)), name


def test_a_refutation_orders_its_obligations() -> None:
    unordered = Refutation(
        reason="refinement",
        judgement=SemanticJudgement("SafeRollup"),
        obligations=(Obligation(required="b"), Obligation(required="a")),
    )

    assert [obligation.required for obligation in unordered.obligations] == ["a", "b"]


def test_facts_are_deduplicated_on_a_proof() -> None:
    """One fact read twice is one fact. Left in, it would appear twice in the
    serialization and make two proofs of the same thing compare unequal."""
    fact = _fact(Provenance.DECLARED)
    proof = Proof(rule="R001", conclusion=SemanticJudgement("Reaches"), facts=(fact, fact))

    assert proof.facts == (fact,)
