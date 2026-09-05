"""The proof vocabulary (RFC 0039): a positive derivation, not the absence of
a complaint.

Every guardrail in this compiler answers by raising or staying silent, so the
whole of the evidence that a project is safe is *that nothing objected*. That
is enough to refuse wrongly-shaped specs and not enough to say why a plan is
correct, which is the gap this closes: an accepted semantic operation carries a
finite derivation from facts that were declared or mechanically implied.

**Unknown is not safe** (D1, `LOCKED`). A proof obligation closes on a
:class:`Provenance` of ``DECLARED``, ``DERIVED`` or ``IMPORTED_VERIFIED`` and
never on ``INFERRED_HEURISTIC`` or ``UNKNOWN``. Those two exist so a diagnostic
can say "there is a fact here, and it is not one I may use" — a distinction
worth more than their absence, and worth nothing at all if either can close an
obligation. :meth:`Provenance.closes` is the single place that decision is
made; nothing else compares provenance values.

Nothing here is stored on :class:`~bloomery.ir.ProjectIR`. A proof is the
answer to a question — :func:`~bloomery.semantic.can_roll_up` builds one when
asked — so a compile that asks nothing pays nothing (D7, see logs/T-0020.md
D-111).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

# ----------------------- #

__all__ = [
    "BASIS_PROVENANCE",
    "BASIS_RULES",
    "RULES",
    "SUPERSEDED",
    "Obligation",
    "Proof",
    "Provenance",
    "Refutation",
    "Rule",
    "SemanticFact",
    "SemanticJudgement",
]


class Provenance(StrEnum):
    """Where a fact came from, and therefore whether it may close an
    obligation (RFC 0039 §4, D1 `LOCKED`).

    The ordering of the members is the ordering of trust, and
    :meth:`closes` is the line drawn through it. It is drawn once here rather
    than at each call site, because a proof is only ever as strong as the
    weakest fact any of its leaves admitted, and a second copy of this test
    that drifted would not look like a safety change in review.
    """

    #: Authored directly in a bloomery spec. The strongest thing there is: a
    #: human wrote it down and owns it.
    DECLARED = "declared"
    #: Mechanically implied by declared facts — an entity's key determining
    #: its own columns, a `many_to_one` read in its declared direction.
    DERIVED = "derived"
    #: Read from a machine-readable external artifact under a documented exact
    #: rule (RFC 0044). Admitted because the rule is exact, not because the
    #: artifact is trusted.
    IMPORTED_VERIFIED = "imported_verified"
    #: A guess, however good. Never closes an obligation, and is carried so a
    #: refutation can say what it found rather than only what it lacked.
    INFERRED_HEURISTIC = "inferred_heuristic"
    #: No fact at all. Never closes an obligation.
    UNKNOWN = "unknown"

    # ....................... #

    @property
    def closes(self) -> bool:
        """Whether a fact of this provenance may close a proof obligation."""

        return self in _CLOSING


#: The three that close, named positively. An allowlist rather than a test
#: against the two that do not: a member added to this enum without a decision
#: would otherwise default to closing obligations, which is the failure this
#: whole document exists to prevent.
_CLOSING: Final = frozenset({Provenance.DECLARED, Provenance.DERIVED, Provenance.IMPORTED_VERIFIED})


# ....................... #


@dataclass(frozen=True, slots=True, order=True)
class SemanticFact:
    """One leaf of a proof: a statement, and where it came from.

    ``statement`` is rendered text and is *not* the identity of anything —
    ``source`` is. Two facts saying the same thing about different columns are
    two facts, and a renderer changing its wording must not change what a proof
    serializes to.
    """

    #: A stable machine identity, e.g. ``"entity:order.shipping"`` or
    #: ``"relationship:order_customer"``. Sorted on, so it decides canonical
    #: order (D6).
    source: str
    provenance: Provenance
    statement: str

    # ....................... #

    @property
    def closes(self) -> bool:
        return self.provenance.closes


# ....................... #


@dataclass(frozen=True, slots=True, order=True)
class SemanticJudgement:
    """What a proof concludes, as a value rather than a sentence.

    ``AdditiveRollup(measure=shipping, from=Order, to=CustomerCountry)`` in
    RFC 0039 §3's example is this: a ``kind`` and its named operands. Operands
    are sorted pairs so that two judgements about the same thing compare equal
    however they were built (D6).
    """

    kind: str
    operands: tuple[tuple[str, str], ...] = ()

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.operands))
        if canonical != self.operands:
            object.__setattr__(self, "operands", canonical)

    # ....................... #

    def render(self) -> str:
        inner = ", ".join(f"{name}={value}" for name, value in self.operands)

        return f"{self.kind}({inner})" if inner else self.kind


# ....................... #


@dataclass(frozen=True, slots=True)
class Rule:
    """One named proof rule (D5).

    Documented individually and testable on its own, because the question
    RFC 0042 asks of every corpus case — *which rule admitted this?* — has no
    answer from a monolithic checker that returns a tree.
    """

    #: Stable, public the moment CI asserts on it. Append-only: never reused,
    #: never repointed (D8, see logs/T-0020.md D-112).
    id: str
    summary: str
    #: The ids that replaced this one, for a rule that was split or subsumed.
    #: Empty for a live rule. A superseded rule keeps its entry in
    #: :data:`RULES` so a citation written against it still resolves.
    superseded_by: tuple[str, ...] = ()

    # ....................... #

    @property
    def live(self) -> bool:
        return not self.superseded_by


# ....................... #

#: Every rule this compiler can cite, by id. The registry is the public
#: contract D8 governs, and it is a module constant rather than a docstring so
#: that a test can assert an id never leaves it — the half of "append-only" a
#: convention cannot enforce on its own.
#:
#: R001-R005 are the five bases RFC 0037 already closed — nothing here invents
#: a way to believe a dependency, it names the ones that existed. R006 is the
#: rollup those compose into, and R007 the axiom they start from.
RULES: Final[dict[str, Rule]] = {
    rule.id: rule
    for rule in (
        Rule("R001", "an entity's own key determines every column of that entity"),
        Rule("R002", "a declared many_to_one, read in the preserving direction"),
        Rule("R003", "a declared one_to_one, which is symmetric"),
        Rule("R004", "a qualified as-of join against a historical entity"),
        Rule("R005", "a functional dependency composed from two or more others"),
        Rule("R006", "every determinant of the target grain is determined by the source"),
        Rule("R007", "a determinant of the origin grain, which is determined by nothing"),
    )
}

#: Ids that have been superseded, kept so a citation against one still
#: resolves. Empty until the first rule is split; present from the first commit
#: so that splitting one is an edit to a structure that exists rather than an
#: invention under time pressure.
SUPERSEDED: Final[tuple[str, ...]] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class Proof:
    """A finite derivation of one judgement (RFC 0039 §3).

    Recursive: ``premises`` are the proofs this one rests on, ``facts`` the
    leaves it reads directly. A proof with neither is an axiom, which here
    means a determinant of the origin grain — determined by nothing, and
    needing no argument.

    Canonical by construction (D6, `LOCKED`). Premises and facts are sorted on
    construction rather than trusted to arrive in order, because the graph walk
    that produces them is where every determinism failure in this codebase has
    entered.
    """

    rule: str
    conclusion: SemanticJudgement
    premises: tuple[Proof, ...] = ()
    facts: tuple[SemanticFact, ...] = ()

    # ....................... #

    def __post_init__(self) -> None:
        if self.rule not in RULES:
            msg = (
                f"proof cites rule {self.rule!r}, which is not in the registry — a rule id "
                "is a public contract and is never minted at a call site (RFC 0039 D8)"
            )
            raise ValueError(msg)

        premises = tuple(sorted(self.premises, key=lambda proof: proof.sort_key))
        if premises != self.premises:
            object.__setattr__(self, "premises", premises)

        # By `source`, which the docstring calls the identity — deduplicating
        # on the whole value instead would keep two facts about one source
        # whenever their wording differed, so a renderer changing a sentence
        # would change what a proof serializes to. Two facts that disagree
        # about a source's provenance are not a duplicate to be dropped: one of
        # them is wrong, and picking silently is how the weaker one closes an
        # obligation.
        by_source: dict[str, SemanticFact] = {}
        for fact in self.facts:
            held = by_source.setdefault(fact.source, fact)
            if held.provenance is not fact.provenance:
                msg = (
                    f"fact {fact.source!r} is claimed both {held.provenance.value} and "
                    f"{fact.provenance.value} in one proof — a source has one provenance, "
                    "and the weaker of two would decide whether this closes (RFC 0039 D1)"
                )
                raise ValueError(msg)

        facts = tuple(sorted(by_source.values()))
        if facts != self.facts:
            object.__setattr__(self, "facts", facts)

    # ....................... #

    @property
    def sort_key(self) -> tuple[str, ...]:
        """Total over the node's **whole** value, including what hangs below it.

        A key stopping at ``rule`` leaves two premises of one rule tied, and a
        tie among equal keys is resolved by whatever order the walk happened to
        produce — `sorted` is stable, so the traversal wins. The first version
        of this stopped at ``(rule, conclusion)``, which two proofs differing
        only in their facts share: they sorted by construction order and the
        parent serialized differently for the same set of premises.

        So the key descends. ``serialize`` is the canonical form of everything
        a proof is, which makes it the one value that cannot tie for two proofs
        that differ — and premises are already canonical by the time a parent
        sorts them, since each was built before it.
        """

        return (self.rule, self.conclusion.render(), self.serialize())

    # ....................... #

    @property
    def leaves(self) -> tuple[SemanticFact, ...]:
        """Every fact this proof rests on, its premises' included, sorted."""

        gathered = set(self.facts)
        for premise in self.premises:
            gathered.update(premise.leaves)

        return tuple(sorted(gathered))

    # ....................... #

    @property
    def closed(self) -> bool:
        """Whether every leaf may close an obligation (D1, `LOCKED`).

        A proof standing on one heuristic is not a weaker proof, it is not a
        proof: the conclusion is exactly as good as the worst fact underneath
        it. Read rather than checked on construction so a caller may build a
        candidate derivation and ask.

        **A proof resting on nothing is not closed.** ``all(())`` is ``True``,
        so the empty case has to be decided rather than inherited from the
        reduction: a node with no facts and no premises asserts its conclusion
        out of thin air, which is the one thing a closed-world checker may
        never report as proven. Nothing in :func:`prove_rollup` can build one —
        an empty grain is refused as ``unknown_grain`` — and the predicate is
        the public expression of D1, so it answers for itself rather than for
        its current callers.
        """

        return bool(self.leaves) and all(fact.closes for fact in self.leaves)

    # ....................... #

    def document(self) -> dict[str, object]:
        """The serializable form — deterministic, and free of anything that
        varies between processes (§9). No addresses, no timestamps, no
        traversal order."""

        return {
            "rule": self.rule,
            "conclusion": self.conclusion.render(),
            "facts": [
                {
                    "source": fact.source,
                    "provenance": fact.provenance.value,
                    "statement": fact.statement,
                }
                for fact in self.facts
            ],
            "premises": [premise.document() for premise in self.premises],
        }

    # ....................... #

    def serialize(self) -> str:
        """The canonical JSON encoding, for a golden test or a CI assertion."""

        return _encode(self.document())

    # ....................... #

    def render(self, *, indent: int = 0) -> str:
        """The numbered prose form RFC 0039 §7 shows, deepest premise first.

        Premises before their conclusion, because that is the order the
        argument is read in — a reader meets ``revenue originates at Order``
        before ``therefore Order -> CustomerCountry is a safe rollup``.
        """

        lines = [
            line for premise in self.premises for line in premise.render(indent=indent).split("\n")
        ]
        pad = " " * indent
        lines.append(f"{pad}{self.conclusion.render()}  [{self.rule}: {RULES[self.rule].summary}]")

        return "\n".join(lines)


def _encode(document: dict[str, object]) -> str:
    """One encoder for both halves, so their bytes cannot drift apart.

    ``sort_keys=False`` on purpose: every mapping here is built in a fixed
    literal order, and sorting would silently repair a future one that was not
    — hiding exactly the nondeterminism §9 forbids instead of failing on it.
    """

    return json.dumps(document, sort_keys=False, separators=(",", ":"), ensure_ascii=False)


# ....................... #


@dataclass(frozen=True, slots=True, order=True)
class Obligation:
    """One thing that had to be shown and was not (RFC 0039 §6).

    ``required`` is what the caller asked for; ``found`` is what the compiler
    has instead. Both are rendered text: a refutation is read, and the
    machine-readable half of a refusal is its reason code, not this.
    """

    required: str
    found: str = ""


# ....................... #


@dataclass(frozen=True, slots=True)
class Refutation:
    """No permitted derivation exists under the current rule set — which is
    **not** a proof that none could (RFC 0039 §6).

    The distinction is the whole of this docstring's reason for existing.
    "bloomery cannot prove this" and "this is impossible" differ, the second is
    what a reader hears if the wording is careless, and only the first is true:
    the rule set grows, and a request refused today may be provable in the next
    release without anything about the data having changed. Wording that claims
    more than the first is a defect, not a style preference.
    """

    #: The reason code, which is the stable half. Text moves; this does not.
    reason: str
    judgement: SemanticJudgement
    #: The smallest failed obligations available, sorted.
    obligations: tuple[Obligation, ...] = ()
    #: What to do about it, where the compiler knows. Empty rather than
    #: guessed: a wrong remediation costs more than a missing one, because an
    #: author acts on it.
    remediation: str = ""
    #: Facts the compiler holds that did not close this obligation, with the
    #: provenance they actually have. A declared relationship that is blocked
    #: belongs here as ``DECLARED``: it exists and the author wrote it, and
    #: what is missing is a *qualification* of it, not the fact. Reporting one
    #: as ``UNKNOWN`` would say no such relationship exists, sending an author
    #: to declare a second copy of the one already there.
    rejected: tuple[SemanticFact, ...] = field(default=())

    # ....................... #

    def __post_init__(self) -> None:
        for name in ("obligations", "rejected"):
            value = tuple(sorted(getattr(self, name)))
            if value != getattr(self, name):
                object.__setattr__(self, name, value)

    # ....................... #

    def document(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "judgement": self.judgement.render(),
            "obligations": [
                {"required": obligation.required, "found": obligation.found}
                for obligation in self.obligations
            ],
            "remediation": self.remediation,
            "rejected": [
                {"source": fact.source, "provenance": fact.provenance.value}
                for fact in self.rejected
            ],
        }

    # ....................... #

    def serialize(self) -> str:
        """The canonical JSON encoding.

        Present because ``Proven | Refused`` is one vocabulary with two halves
        (D2), and a caller holding the union should not have to ask which half
        it has before it can write the answer down. An asymmetric surface makes
        the refusal the second-class one, which is backwards: a refusal is the
        answer this compiler gives most often and the one an author reads.
        """

        return _encode(self.document())

    # ....................... #

    def render(self) -> str:
        lines = [f"Cannot prove {self.judgement.render()}."]

        for obligation in self.obligations:
            lines.append(f"  required: {obligation.required}")
            if obligation.found:
                lines.append(f"  found:    {obligation.found}")

        lines.append(f"  reason:   {self.reason}")

        if self.remediation:
            lines.append(f"  fix:      {self.remediation}")

        return "\n".join(lines)


# ----------------------- #
# Expressing the rollup answer as a proof (RFC 0039 §8)


#: The rule that admits each way of believing a dependency. The mapping is the
#: whole of the translation: RFC 0037 already closed the vocabulary of *why*
#: the compiler believes an edge, so nothing here invents a way to believe one.
#:
#: Keyed by the ``DependencyBasis`` value rather than the member, so this
#: module stays free of the node types it describes — the proof vocabulary is
#: read by consumers that never touch a `GrainRef`.
BASIS_RULES: Final[dict[str, str]] = {
    "entity_key": "R001",
    "many_to_one": "R002",
    "one_to_one": "R003",
    "as_of": "R004",
    "transitive": "R005",
}

#: What a dependency of each basis *rests on*. An entity key and a transitive
#: composition are `DERIVED` — nobody wrote them down, they follow from what
#: was written. A relationship and an as-of anchor are `DECLARED`, because an
#: author put them in a spec and owns them.
BASIS_PROVENANCE: Final[dict[str, Provenance]] = {
    "entity_key": Provenance.DERIVED,
    "many_to_one": Provenance.DECLARED,
    "one_to_one": Provenance.DECLARED,
    "as_of": Provenance.DECLARED,
    "transitive": Provenance.DERIVED,
}
