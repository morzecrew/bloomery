"""R018, the zone obligation (S-0076/r018-and-where-it-fires).

The prover is asked one question — *can every source of this column say which
clock it read?* — and the three answers that discharge it are three different
facts about the world. What is asserted here is that they stay three: a proof
that collapsed them into "declared" would still be true and would lose the only
record of which one applied, on a rule whose whole content is provenance.
"""

from __future__ import annotations

import pytest

from bloomery.semantic import RULES, Proof, Provenance, Refutation
from bloomery.semantic.zone import UNDECLARED_SOURCE_ZONE, WallClock, prove_zone

pytestmark = pytest.mark.unit

SITE = "a mart buckets it as a date role"


def answer(*readings: WallClock) -> Proof | Refutation:
    return prove_zone(readings, entity="order", column="placed_at", site=SITE)


# ....................... #


def test_r018_is_in_the_registry() -> None:
    """D8: a rule id is a public contract, and `Proof` refuses one the registry
    does not carry — so this fails here rather than at whichever proof cited it
    first."""

    assert "R018" in RULES
    assert RULES["R018"].summary.strip()


def test_a_converted_chain_proves_it() -> None:
    proof = answer(WallClock("shop__orders", parsed=True, converted=True, declared=None))

    assert isinstance(proof, Proof)
    assert proof.rule == "R018"
    (fact,) = proof.facts
    assert fact.provenance is Provenance.DECLARED
    assert "to_utc" in fact.statement


def test_a_declared_zone_proves_it() -> None:
    proof = answer(WallClock("shop__orders", parsed=True, converted=False, declared="UTC"))

    assert isinstance(proof, Proof)
    (fact,) = proof.facts
    assert fact.provenance is Provenance.DECLARED
    assert "UTC clock" in fact.statement


def test_a_value_that_was_never_a_wall_clock_proves_it_as_derived() -> None:
    """The third provenance is `DERIVED`, not `DECLARED`, and the difference is
    the point: nobody asserted anything about this column's clock — the
    question never arose, because nothing here read a wall clock."""

    proof = answer(WallClock("shop__orders", parsed=False, converted=False, declared=None))

    assert isinstance(proof, Proof)
    (fact,) = proof.facts
    assert fact.provenance is Provenance.DERIVED
    assert "never a wall clock" in fact.statement


def test_an_undeclared_wall_clock_is_refuted() -> None:
    refutation = answer(WallClock("shop__orders", parsed=True, converted=False, declared=None))

    assert isinstance(refutation, Refutation)
    assert refutation.reason == UNDECLARED_SOURCE_ZONE
    (obligation,) = refutation.obligations
    assert SITE in obligation.required
    assert "shop__orders" in obligation.found
    assert "zone_in" in refutation.remediation and "to_utc" in refutation.remediation


def test_the_rejected_fact_is_unknown_rather_than_declared() -> None:
    """D1, `LOCKED`: unknown is not safe. The column *has* a zone — every wall
    clock was written on some clock — and what bloomery holds about it is
    nothing, so reporting it as `DECLARED` would say an author wrote something
    they did not, and send them to correct it."""

    refutation = answer(WallClock("shop__orders", parsed=True, converted=False, declared=None))

    assert isinstance(refutation, Refutation)
    (rejected,) = refutation.rejected
    assert rejected.provenance is Provenance.UNKNOWN
    assert not rejected.provenance.closes


def test_one_undeclared_source_refutes_a_column_every_other_source_declared() -> None:
    """A merged entity is as good as its worst mapping: the rows from the
    undeclared source sit in the same column, and an aggregate over the column
    reads all of them."""

    refutation = answer(
        WallClock("shop__orders", parsed=True, converted=True, declared=None),
        WallClock("legacy__orders", parsed=True, converted=False, declared=None),
    )

    assert isinstance(refutation, Refutation)
    (obligation,) = refutation.obligations
    assert "legacy__orders" in obligation.found
    assert "shop__orders" not in obligation.found


def test_every_undeclared_source_is_named_at_once() -> None:
    """Not the first one: a boundary is usually got wrong the same way in each
    mapping that feeds it, and one refusal per round-trip would make an author
    fix the same thing twice."""

    refutation = answer(
        WallClock("a__orders", parsed=True, converted=False, declared=None),
        WallClock("b__orders", parsed=True, converted=False, declared=None),
    )

    assert isinstance(refutation, Refutation)
    assert len(refutation.rejected) == 2


def test_a_column_no_source_carries_proves_vacuously() -> None:
    """No readings is not a refusal. A column absent from every source is a
    different defect with its own refusal upstream, and answering it here would
    mean two guards claiming one bug — which is how an author gets sent to
    declare a zone on a column that does not exist.
    """

    proof = answer()

    assert isinstance(proof, Proof)
    assert proof.facts == ()
