"""R009 on its own, apart from the resolution that calls it (RFC 0061 §5.4).

The rule decides — `resolve.build` refuses on the refutation and accepts on the
proof — so these are the tests of the decision itself, and
`tests/unit/test_resolve/test_currency_convert.py` tests that resolution asks
the question and reports the answer.
"""

from __future__ import annotations

import pytest

from bloomery.semantic import Conversion, DenominationRefusal, prove_conversion
from bloomery.semantic.proof import Proof, Provenance, Refutation

# ----------------------- #

EUR_USD = Conversion(from_ccy="EUR", to_ccy="USD", anchor="paid_at")
EUR_CHF = Conversion(from_ccy="EUR", to_ccy="CHF", anchor="paid_at")
CHF_USD = Conversion(from_ccy="CHF", to_ccy="USD", anchor="paid_at")


def _prove(
    *conversions: Conversion, declared_in: str | None = "EUR", per_row: bool = False
) -> Proof | Refutation:
    return prove_conversion(
        conversions,
        column="amount_usd",
        declared_in=declared_in,
        per_row=per_row,
        document="payments.yaml",
    )


# ....................... #
# What closes


def test_a_declared_input_closes_a_single_conversion() -> None:
    answer = _prove(EUR_USD)

    assert isinstance(answer, Proof)
    assert answer.rule == "R009"
    assert answer.conclusion.render() == "Denominated(column=amount_usd, currency=USD)"


def test_a_chain_is_opened_once_and_carried_by_its_own_steps() -> None:
    """The two-hop case, which is the reason the input is walked rather than
    compared at the ends: `EUR -> CHF -> USD` is three agreements, and only the
    first of them is a declaration."""
    answer = _prove(EUR_CHF, CHF_USD)

    assert isinstance(answer, Proof)
    assert answer.conclusion.render() == "Denominated(column=amount_usd, currency=USD)"
    # One leaf for the declaration, one per rate the chain reads.
    assert len(answer.facts) == 3
    assert all(fact.provenance.closes for fact in answer.facts)


def test_every_leaf_is_a_provenance_that_may_close() -> None:
    """RFC 0039 §4's rule, asserted rather than assumed: a proof is only as
    strong as its weakest leaf, and a leaf that cannot close an obligation
    makes the whole derivation decoration."""
    answer = _prove(EUR_CHF, CHF_USD)

    assert isinstance(answer, Proof)
    assert {fact.provenance for fact in answer.facts} == {Provenance.DECLARED}


def test_the_same_pair_read_on_two_dates_is_two_facts() -> None:
    """`Proof` deduplicates by `source`, which it calls the identity — so a
    rate reading whose source did not carry its anchor was dropped, silently,
    and the surviving fact still looked right.

    Four conversions in, three facts out before this (logs/T-0025.md, D-163).
    The chain is pathological on purpose: converting back and forth is legal
    and nothing refuses it, which is what makes it the case that reaches the
    collision.
    """
    answer = _prove(
        EUR_USD,
        Conversion(from_ccy="USD", to_ccy="EUR", anchor="paid_at"),
        Conversion(from_ccy="EUR", to_ccy="USD", anchor="settled_at"),
    )

    assert isinstance(answer, Proof)
    # One declaration plus one per rate read, none collapsed into another.
    assert len(answer.facts) == 4
    assert len({fact.source for fact in answer.facts}) == 4


def test_a_refutation_is_about_the_chain_the_proof_would_have_concluded() -> None:
    """Both halves of one question name one judgement. A three-hop chain that
    breaks in the middle used to document the middle step's output, so a
    refusal and the proof it stands against serialized under different
    conclusions."""
    answer = _prove(
        EUR_CHF,
        Conversion(from_ccy="JPY", to_ccy="GBP", anchor="paid_at"),
        Conversion(from_ccy="GBP", to_ccy="USD", anchor="paid_at"),
    )

    assert isinstance(answer, Refutation)
    # The chain's destination, not 'GBP' where it broke.
    assert answer.judgement.render() == "Denominated(column=amount_usd, currency=USD)"


# ....................... #
# What refuses


def test_an_undeclared_input_is_refused_and_says_nothing_declares_it() -> None:
    """The bug this rule exists for. `convert` asserts the input currency and
    the assertion is its own evidence, which is the thing RFC 0061 D1 refuses.
    """
    answer = _prove(EUR_USD, declared_in=None)

    assert isinstance(answer, Refutation)
    assert answer.reason == DenominationRefusal.UNDECLARED_INPUT.value
    assert "nothing declares it" in answer.obligations[0].found
    assert "currency_in:" in answer.remediation
    # The fact it *did* find, at the provenance it actually has — reporting it
    # as anything that closes would be the waiver this whole document is about.
    (rejected,) = answer.rejected
    assert rejected.provenance is Provenance.UNKNOWN
    assert not rejected.provenance.closes


def test_a_from_that_disagrees_with_the_declaration_is_refused() -> None:
    """`{convert: [JPY, USD, paid_at]}` on euros: every cast succeeds, the rate
    relation has the row asked for, and the answer is wrong by whatever the two
    rates differ by."""
    answer = _prove(Conversion(from_ccy="JPY", to_ccy="USD", anchor="paid_at"))

    assert isinstance(answer, Refutation)
    assert answer.reason == DenominationRefusal.INPUT_DISAGREES.value
    assert "'EUR'" in answer.obligations[0].required
    assert "'JPY'" in answer.obligations[0].found


def test_a_chain_whose_middle_disagrees_is_refused_at_the_step_that_breaks() -> None:
    """The obligation names what was being held *at that point*, not the
    field's declaration — otherwise a three-hop chain reports its first
    currency for a break in its third step."""
    answer = _prove(EUR_CHF, Conversion(from_ccy="JPY", to_ccy="USD", anchor="paid_at"))

    assert isinstance(answer, Refutation)
    assert answer.reason == DenominationRefusal.INPUT_DISAGREES.value
    assert "'CHF'" in answer.obligations[0].required  # not 'EUR'


def test_a_per_row_input_is_refused_as_unbuilt_not_as_invalid() -> None:
    """RFC 0061 D5: the vocabulary admits it and P1 does not lower it. The
    remediation has to say which, because "invalid" sends an author to rewrite
    a declaration that is correct."""
    answer = _prove(EUR_USD, declared_in=None, per_row=True)

    assert isinstance(answer, Refutation)
    assert answer.reason == DenominationRefusal.PER_ROW_UNBUILT.value
    assert "not yet lowered" in answer.remediation


# ....................... #


@pytest.mark.parametrize("reason", list(DenominationRefusal))
def test_every_refusal_reason_carries_a_remediation(reason: DenominationRefusal) -> None:
    """A member added without one reaches an author as an empty `Fix:`, which
    is worse than a missing refusal: it says something is wrong and nothing
    about what to do."""
    from bloomery.semantic.denomination import _REMEDIES

    assert _REMEDIES[reason].strip()
