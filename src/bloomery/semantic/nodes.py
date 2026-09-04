"""The grain vocabulary: structural grain identity, functional dependencies
with their basis, and the two answers a rollup question can have
(RFC 0037 §5.1, §5.6, §5.7, §9).

Every node here is **derived from** :class:`~bloomery.ir.ProjectIR`, never
stored in it. That is deliberate and it is what makes RFC 0037 §7's "preserve
observable behaviour" mechanical rather than argued: a grain computed on
demand from ``EntityIR.key`` moves no ``bloomery_ir_version``, no project
fingerprint and no golden. The IR keeps its authored key order because the
emitted SQL's key order is authored; grain *identity* is order-independent
(§5.7), which is why :class:`GrainRef` canonicalizes and ``EntityIR.key`` does
not.

Determinism, on RFC 0003's terms and RFC 0037 D7's: every collection here is a
sorted tuple, and nothing iterates a set where the order can reach a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from bloomery.errors import InvariantViolated
from bloomery.semantic.historical import AsOfState

if TYPE_CHECKING:
    from collections.abc import Iterable

# ----------------------- #

__all__ = [
    "BlockedEdge",
    "ColumnRef",
    "DependencyBasis",
    "DependencySet",
    "Derivation",
    "Determined",
    "FunctionalDependency",
    "GrainRef",
    "grain_of",
    "NO_CONTEXT",
    "RefusalReason",
    "RollupContext",
    "RollupProof",
    "RollupRefusal",
]


@dataclass(frozen=True, slots=True, order=True)
class ColumnRef:
    """One column of one entity — a determinant when it sits in a
    :class:`GrainRef`, a dependent when a :class:`FunctionalDependency`
    determines it.

    RFC 0037 §5.6 sketches these as two types, ``EntityKeyRef`` and
    ``SemanticRef``; the section says its shape is illustrative. Two dataclasses
    of identical fields would need converting between at every closure step,
    and the conversion is where the two readings would drift apart.
    """

    entity: str
    column: str

    # ....................... #

    def __str__(self) -> str:
        return f"{self.entity}.{self.column}"


# ....................... #


@dataclass(frozen=True, slots=True, order=True)
class GrainRef:
    """A grain as the set of columns that identify one row of it — never a
    display string (RFC 0037 D1, `LOCKED`).

    Determinants are canonicalized on construction: sorted and deduplicated,
    so ``{order_id, line_id}`` and ``{line_id, order_id}`` are one value and
    compare equal (§5.7, test 6). Canonicalizing rather than refusing a
    non-canonical tuple is what makes that unconditional — there is no way to
    hold an instance whose equality is wrong.

    Composite is the general case, not a special one: a single-column grain is
    a one-member tuple. Nothing here concatenates.
    """

    determinants: tuple[ColumnRef, ...]

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(set(self.determinants)))
        if canonical != self.determinants:
            object.__setattr__(self, "determinants", canonical)

    # ....................... #

    @property
    def label(self) -> str:
        """The grain for a diagnostic — names stay available for reading, they
        are simply not the identity (§5.1)."""

        return "{" + ", ".join(str(d) for d in self.determinants) + "}"


# ....................... #


class DependencyBasis(StrEnum):
    """Why the compiler believes a dependency (RFC 0037 §5.6).

    The list is closed and D3 (`LOCKED`) is what closes it: no heuristic ever
    contributes a member, because the value of every proof built on this is
    exactly the weakest fact admitted here.
    """

    #: An entity's own key determines every column of that entity.
    ENTITY_KEY = "entity_key"
    #: A declared ``many_to_one`` read in its declared direction, or a declared
    #: ``one_to_many`` read inversely — which *is* a ``many_to_one`` and is not
    #: the preserving direction D3 excludes (§6 test 3 asks for exactly this
    #: asymmetry, and :mod:`bloomery.guardrails.grain` already reads a
    #: relationship inversely this way).
    MANY_TO_ONE = "many_to_one"
    #: A declared ``one_to_one``, which is symmetric.
    ONE_TO_ONE = "one_to_one"
    #: A historical relationship whose ``as_of`` anchor qualified it (§5.3).
    #: Its own member rather than a ``many_to_one`` carrying an anchor,
    #: because it determines strictly more: the anchor picks one version, so
    #: the whole of the target row is determined, not only the joined key.
    AS_OF = "as_of"
    #: Composition of the above. Never a step of its own — the derivation
    #: carries the steps it composed.
    TRANSITIVE = "transitive"


# ....................... #


@dataclass(frozen=True, slots=True)
class FunctionalDependency:
    """``determinant`` determines ``dependent``, and ``basis`` says why.

    ``via`` names the declared relationship for a relationship basis and is
    ``None`` for :attr:`DependencyBasis.ENTITY_KEY`. ``as_of`` is the anchor
    that qualified a historical hop (§5.3) — ``None`` on every other edge,
    including a hop onto a non-historical entity, where there is nothing to
    qualify.

    ``join`` is the hop this dependency crossed, as ``(determinant-side,
    dependent-side)`` column pairs, sorted; empty for
    :attr:`DependencyBasis.ENTITY_KEY`, which crosses nothing. It is what makes
    two hops onto one entity distinguishable: a billing address and a shipping
    address are both ``address.address_id`` as a *dependent* and differ only in
    the column that reached it. Without it the two routes look identical and
    the ambiguity §9 exists to catch is invisible — while two declarations of
    one relationship in opposite directions, which mean the same thing, look
    like two meanings.

    The whole hop rather than one column of it, because a composite join is
    one reading: two relationships joining ``(a, b)`` and ``(a, c)`` differ,
    and a single column would report them as the same wherever ``a`` is the
    one it happened to carry.
    """

    determinant: GrainRef
    dependent: ColumnRef
    basis: DependencyBasis
    via: str | None = None
    as_of: str | None = None
    join: tuple[tuple[ColumnRef, ColumnRef], ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class Derivation:
    """How a member of a closure was reached: the dependencies composed, in
    order, from the origin grain.

    A derivation, not a boolean (RFC 0037 D6) — RFC 0039 builds a proof tree
    out of these and RFC 0042 pins a case to the rule that decided it, and
    both would otherwise have to re-derive the reason from the answer.

    Empty ``steps`` means the member is a determinant of the origin grain
    itself, which is determined by nothing and needs no argument.
    """

    steps: tuple[FunctionalDependency, ...] = ()

    # ....................... #

    @property
    def relationships(self) -> tuple[str, ...]:
        """The declared relationships this derivation traverses, in order.
        For diagnostics — a reader asking *how* wants the names."""

        return tuple(step.via for step in self.steps if step.via is not None)

    # ....................... #

    @property
    def signature(self) -> tuple[tuple[tuple[tuple[ColumnRef, ColumnRef], ...], str | None], ...]:
        """What this derivation *means*: each hop it crossed, and the instant
        it read that hop as of.

        Two derivations are the same route when their signatures match, even
        when they traverse differently-named relationships — one relationship
        declared in both directions is one meaning, not two. And two routes
        that join identical columns are different meanings when they read them
        at different instants: a tier as of the order date and a tier as of the
        ship date are two numbers, and collapsing them would report one of them
        as proven.

        Entity-key steps cross no hop and contribute nothing: they add no
        reading, they only unfold an identity already established.
        """

        return tuple((step.join, step.as_of) for step in self.steps if step.join)


# ....................... #


@dataclass(frozen=True, slots=True)
class Determined:
    """One member of a closure, with every derivation that reaches it.

    More than one derivation is the ambiguity §9 requires be distinguishable:
    two relationships landing on one entity mean the same column name has two
    meanings (a billing and a shipping address are both ``address.city``), and
    a rollup that picks one silently is the wrong-answer class this compiler
    exists to refuse.
    """

    ref: ColumnRef
    derivations: tuple[Derivation, ...]

    # ....................... #

    @property
    def ambiguous(self) -> bool:
        return len(self.derivations) > 1


# ....................... #


class RefusalReason(StrEnum):
    """What a rollup was refused for (RFC 0037 §9). Kept apart rather than
    collapsed into "unsafe", because each names a different repair."""

    #: A grain names an entity this project has no mapping for, or a column
    #: that is not part of that entity's key.
    UNKNOWN_GRAIN = "unknown_grain"
    #: No chain of admitted dependencies reaches the target's determinants,
    #: and none would even ignoring direction.
    NO_FUNCTIONAL_PATH = "no_functional_path"
    #: A path exists but every route crosses a relationship in the direction
    #: that multiplies rows.
    CARDINALITY_EXPANDING = "cardinality_expanding"
    #: A path exists but crosses an ``scd: type2`` entity that the anchor did
    #: not qualify — none was given, or the one given names no column of the
    #: reading entity, or names one that does not order against an interval
    #: (§5.3). The :class:`BlockedEdge` carries which.
    UNQUALIFIED_HISTORICAL = "unqualified_historical"
    #: An anchor was supplied for a relation that keeps no versions. Kept apart
    #: from the above because there is no history here to be unqualified
    #: about: the repair is to drop the anchor, not to fix it.
    ANCHOR_WITHOUT_HISTORY = "anchor_without_history"
    #: The **source** grain names an ``scd: type2`` entity. Its declared key
    #: selects a set of versions rather than a row, so values do not originate
    #: at that grain in the sense a rollup needs — there is no one row to
    #: aggregate from. Reaching *into* history is a different question, and an
    #: anchored hop is its answer.
    HISTORICAL_GRAIN = "historical_grain"
    #: More than one route reaches a determinant, and the routes mean
    #: different things.
    AMBIGUOUS_PATH = "ambiguous_path"
    #: The target grain is *finer* than the source. Not a rollup at all: no
    #: implicit operation may duplicate a measure because SQL can perform the
    #: join (D2, `LOCKED`).
    REFINEMENT = "refinement"


# ....................... #


@dataclass(frozen=True, slots=True)
class BlockedEdge:
    """A relationship that contributed no dependency, and why — kept so a
    refusal can name the hop that stopped it rather than reporting the absence
    of a path and leaving the author to find the reason."""

    relationship: str
    reason: RefusalReason
    #: The precise as-of pairing, for an edge blocked by one — a missing
    #: anchor, an anchor on a relation that keeps no versions, one naming no
    #: column, one naming a column that does not order against an interval.
    #: ``None`` on every other reason.
    state: AsOfState | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class DependencySet:
    """Every dependency this project justifies, and every edge it refused.

    Both sorted. The refused half is not diagnostics decoration: without it
    ``no path`` and ``a path an unanchored historical hop broke`` are the same
    answer, and they are opposite repairs.
    """

    dependencies: tuple[FunctionalDependency, ...] = ()
    blocked: tuple[BlockedEdge, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class RollupContext:
    """The semantic facts a caller supplies that the IR does not carry.

    ``anchors`` pairs a relationship name with the ``as_of`` column on the
    entity the join reads from — the same anchor a mart's ``via:`` step
    declares, supplied here per relationship because a grain question is asked
    without a mart. Sorted, like every other collection in this module.

    **One anchor per relationship**, refused rather than resolved. Two anchors
    for one hop are two readings of it — a tier as of the order date and a tier
    as of the ship date are different numbers — and picking either would answer
    a question the caller did not ask. Repeating the *same* anchor is not a
    conflict and deduplicates.
    """

    anchors: tuple[tuple[str, str], ...] = ()

    # ....................... #

    def __post_init__(self) -> None:
        canonical = tuple(sorted(set(self.anchors)))
        conflicting = sorted(
            {name for name, _ in canonical if sum(n == name for n, _ in canonical) > 1}
        )
        if conflicting:
            listed = ", ".join(
                f"{name!r}: {sorted(a for n, a in canonical if n == name)}" for name in conflicting
            )
            msg = (
                f"relationship anchored more than once — {listed}. An as-of anchor is the "
                "instant a hop is read at, so two of them are two different readings of one "
                "join, and there is no rule for choosing between them. Fix: build one context "
                "per reading"
            )
            raise InvariantViolated(msg)

        if canonical != self.anchors:
            object.__setattr__(self, "anchors", canonical)

    # ....................... #

    def anchor(self, relationship: str) -> str | None:
        return next((a for r, a in self.anchors if r == relationship), None)


# ....................... #

#: The default: no anchors declared, so every historical hop is unanchored.
#: A module-level singleton rather than a call in an argument default — it is
#: frozen, and sharing one instance is what makes that safe.
NO_CONTEXT: Final = RollupContext()


# ....................... #


@dataclass(frozen=True, slots=True)
class RollupProof:
    """A rollup that is safe, and the argument for it: one derivation per
    determinant of the target grain."""

    source: GrainRef
    target: GrainRef
    determinants: tuple[Determined, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class RollupRefusal:
    """A rollup that is not safe.

    Returned rather than raised — RFC 0037 §5.4 types the answer as
    ``Proof | Refusal``, and a caller asking *whether* a rollup is possible is
    not in an exceptional state when the answer is no. The planner RFC 0040
    builds on this decides which refusals become
    :class:`~bloomery.errors.BloomeryError` leaves and where.
    """

    source: GrainRef
    target: GrainRef
    reason: RefusalReason
    #: The determinants of the target that were not reached, sorted. Empty
    #: when the refusal is about the whole question rather than a member —
    #: an unknown grain, or a refinement.
    unreached: tuple[ColumnRef, ...] = ()
    #: The edges that would have completed the path, sorted.
    blocked: tuple[BlockedEdge, ...] = ()


# ....................... #


def grain_of(entity_name: str, key: Iterable[str]) -> GrainRef:
    """The grain of an entity, from its declared key."""

    return GrainRef(tuple(ColumnRef(entity_name, column) for column in key))
