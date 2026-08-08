"""Lowering mutations for the chaos meta-test (RFC 0016 §6).

§6 asks for a **quarterly chaos meta-test**: "mutate the lowering (invert a
comparison, drop a stage, swap a disposition); at least one test must fail per
mutation, or the dirty corpus has a hole." The mutations live here, as data, so
the harness that applies them stays a loop and the *content* of each mutation is
reviewable beside the lowering it deforms.

Each mutation is a deliberate, plausible defect — the kind a refactor
introduces, not a random bit flip. A mutation that no test catches is a hole in
the corpus or in the suite, and the harness fails and names it; nothing here is
allowed to be "expected to survive".

Applied by monkeypatching the *importing* module, not only the defining one:
:mod:`bloomery.emit.lowering` binds ``violation``, ``disposition`` and
``with_dedupe_qualify`` by ``from … import``, so patching the definition alone
would silently do nothing — which would make every mutation "survive" for the
most boring possible reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.emit import lowering
from bloomery.ir import OnFail
from bloomery.marts import HAS_QUALITY_FLAGS
from bloomery.quality import predicates

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlglot.expressions.core import Expression

    from bloomery.ir import EntityIR, MartColumnIR, MartIR, QualityRuleIR

__all__ = [
    "MUTATIONS",
    "apply_mutation",
]


def _invert_route() -> None:
    """Swap the two sides of the two-way split (§5.4).

    The entity keeps what should have been quarantined and the reject table
    takes the survivors. Row conservation still holds — which is exactly why
    §6 insists a test read *both* sides.
    """
    original = lowering._route_predicate

    def mutated(entity: EntityIR, table: str, *, quarantined: bool) -> Expression | None:
        return original(entity, table, quarantined=not quarantined)

    lowering._route_predicate = mutated  # type: ignore[assignment]


def _drop_dedupe() -> None:
    """Drop stage 3 of the fixed pipeline order — the dedupe ``QUALIFY``.

    Losers survive into the entity, so a key that was deduplicated now carries
    several rows and ``rows_deduped`` reports nothing.
    """

    def mutated(select: exp.Select, dedupe: object, key: object) -> exp.Select:
        del dedupe, key
        return select

    lowering.with_dedupe_qualify = mutated  # type: ignore[assignment]


def _quarantine_becomes_flag() -> None:
    """Swap a disposition: every quarantining rule becomes a flag.

    Nothing is ever diverted, every reject table is empty, and every row that
    should have been held back reaches the entity — and the marts.
    """

    def mutated(rule: QualityRuleIR) -> OnFail:
        del rule
        return OnFail.FLAG

    lowering.disposition = mutated  # type: ignore[assignment]


def _range_bounds_swapped() -> None:
    """Invert the comparison inside the ``range`` predicate builder.

    ``col < min`` becomes ``col > min`` and ``col > max`` becomes ``col < max``
    — the single most plausible typo in the whole catalogue, and one that
    quarantines precisely the rows it should keep.
    """
    original = predicates._BUILDERS["range"]

    def mutated(rule: QualityRuleIR, table: str | None) -> Expression:
        def flipped(node: Expression) -> Expression:
            if isinstance(node, exp.LT):
                return exp.GT(this=node.this, expression=node.expression)
            if isinstance(node, exp.GT):
                return exp.LT(this=node.this, expression=node.expression)
            return node

        return original(rule, table).transform(flipped)

    predicates._BUILDERS["range"] = mutated


def _null_violations_fire() -> None:
    """Break three-valued logic (D19): make ``UNKNOWN`` fire.

    Every builder's predicate is wrapped in ``COALESCE(…, TRUE)``, so a
    NULL-involved comparison becomes a violation. This is the mutation that
    matters most: it is what a well-meaning "handle nulls properly" edit looks
    like, and it makes every nullable column fail every rule.
    """
    for kind, builder in list(predicates._BUILDERS.items()):
        predicates._BUILDERS[kind] = _coalescing(builder)


def _coalescing(
    builder: Callable[[QualityRuleIR, str | None], Expression],
) -> Callable[[QualityRuleIR, str | None], Expression]:
    def mutated(rule: QualityRuleIR, table: str | None) -> Expression:
        return exp.Coalesce(this=predicates.grouped(builder(rule, table)), expressions=[exp.true()])

    return mutated


def _quality_flags_polarity() -> None:
    """Invert the mart dimension: ``has_quality_flags`` becomes
    ``_quality_ok`` rather than its negation (§5.5).

    The mutation this battery was missing, and the reason it was missing is
    instructive: every other assertion in the M12 suite reads silver or the
    reject table, and the polarity of a *mart* dimension is observable in
    neither. Only a golden caught it — and §12 budgets golden regeneration by
    the wave, so an inverted quality dimension could ship inside churn a
    reviewer was told to expect. "Revenue excluding flagged rows" then returns
    exactly the flagged rows, which is the worst answer a BI product can give:
    confidently wrong, and wrong in the direction the caller was guarding
    against.
    """
    original = lowering._mart_projection

    def mutated(mart: MartIR, column: MartColumnIR) -> Expression:
        projection = original(mart, column)
        if column.name != HAS_QUALITY_FLAGS:
            return projection
        negated = projection.this
        return exp.alias_(negated.this, column.name)

    lowering._mart_projection = mutated  # type: ignore[assignment]


#: Every mutation, by the name the harness passes through the environment.
MUTATIONS: dict[str, Callable[[], None]] = {
    "invert_route": _invert_route,
    "drop_dedupe": _drop_dedupe,
    "quality_flags_polarity": _quality_flags_polarity,
    "quarantine_becomes_flag": _quarantine_becomes_flag,
    "range_bounds_swapped": _range_bounds_swapped,
    "null_violations_fire": _null_violations_fire,
}


def apply_mutation(name: str) -> None:
    """Deform the lowering in place. Irreversible for the process — which is
    why the harness runs each mutation in a subprocess of its own."""
    MUTATIONS[name]()
