"""Whether a measure may be *summed* once its values are allowed to travel
(RFC 0039 §3 — the additive-rollup and derived-ratio rules).

Two questions look like one and are not. :func:`~bloomery.semantic.can_roll_up`
answers whether values originating at one grain may reach another; it says
nothing about what to do with them when they arrive. A measure whose grain
proof is perfect can still be wrong to add up — an average, a distinct count, a
ratio — and one rule conflating the two could not refuse the second while
granting the first, which is corpus case 002's whole shape.

So the additive obligation composes *with* the grain proof rather than inside
it: :func:`prove_additive_rollup` takes ``prove_rollup``'s answer as a premise
and adds the one fact that answer never reads. Nothing in this package read
additivity before (logs/T-0029.md), which is why this is a second obligation
rather than a refinement of an existing one.

**Expressed, not substituted** (RFC 0039 D3, `LOCKED`). `guardrails/additivity`
still refuses a false additivity claim when a project compiles, and this does
not replace it. What this adds is the ability to *state* the reasoning, which a
guardrail that answers by staying silent cannot do.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from sqlglot import exp

from bloomery.ir import Additivity, OnFail
from bloomery.semantic.closure import prove_rollup
from bloomery.semantic.nodes import NO_CONTEXT
from bloomery.semantic.proof import (
    Obligation,
    Proof,
    Provenance,
    Refutation,
    SemanticFact,
    SemanticJudgement,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bloomery.ir import MetricIR, ProjectIR
    from bloomery.semantic.nodes import GrainRef, RollupContext

# ----------------------- #

__all__ = [
    "RatioRowsRefusal",
    "prove_additive_rollup",
    "prove_ratio_reconstruction",
    "prove_ratio_rows",
]


def _judgement(kind: str, metric: str, source: GrainRef, target: GrainRef) -> SemanticJudgement:
    return SemanticJudgement(
        kind, (("measure", metric), ("from", source.label), ("to", target.label))
    )


# ....................... #


def _metric(project: ProjectIR, name: str) -> MetricIR | None:
    return next((candidate for candidate in project.metrics if candidate.name == name), None)


# ....................... #


def prove_additive_rollup(
    metric: MetricIR,
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
) -> Proof | Refutation:
    """Whether ``metric`` may be summed from ``source`` to ``target``.

    Two obligations, in the order that makes the refusal useful. The grain
    question first, because its refutation is the more specific one: "these
    values may not travel this way" tells an author about a relationship, and
    reporting "this measure is not additive" over a route that does not exist
    would send them to fix the wrong thing. Where the grain proof refuses, that
    refutation is returned unchanged — it *is* the smallest failed obligation
    (§6), and its judgement says which of the two questions failed.

    The additivity fact is `DECLARED`: an author wrote `additivity: additive`
    and owns it. RFC 0038 closed that word at six members and made the claim
    checked rather than trusted, so what closes this obligation is a
    declaration the compiler has already refused to take on faith.
    """

    judgement = _judgement("AdditiveRollup", metric.name, source, target)
    origins = {column.entity for column in source.determinants}

    # The caller names the grain to sum *from*, and a measure that does not
    # originate there is the fan-out case 001 is about — summed once per row of
    # a finer grain it was copied onto. Checked rather than trusted: a proof is
    # evidence, and one built from a source the caller got wrong would certify
    # exactly the duplication this sequence exists to refuse
    # (logs/T-0029.md, finding 1).
    if origins != {metric.grain}:
        return Refutation(
            reason="not_the_origin_grain",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"sum {metric.name} from {source.label}",
                    found=f"{metric.name} originates at {metric.grain}",
                ),
            ),
            remediation=(
                "ask from the grain the measure originates at — a measure summed from a "
                "finer grain it was copied onto is counted once per copy"
            ),
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"originates at {metric.grain}",
                ),
            ),
        )

    grain = prove_rollup(source, target, project, context)

    if isinstance(grain, Refutation):
        return grain

    if metric.additivity is not Additivity.ADDITIVE:
        return Refutation(
            reason="not_additive",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"sum {metric.name} from {source.label} to {target.label}",
                    found=f"{metric.name} is declared {metric.additivity.value}",
                ),
            ),
            remediation=(
                "a non-additive measure is recomputed at the requested grain rather than "
                "summed from a coarser one — declare its decomposition, or request it at "
                "the grain it originates"
            ),
            # `DECLARED` rather than `UNKNOWN`: the additivity is written down
            # and is the wrong one. Reporting it as absent would send an author
            # to declare a word that is already there.
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=f"additivity is {metric.additivity.value}",
                ),
            ),
        )

    return Proof(
        rule="R011",
        conclusion=judgement,
        premises=(grain,),
        facts=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=f"{metric.name} is declared additive",
            ),
        ),
    )


# ....................... #


def prove_ratio_reconstruction(
    metric: MetricIR,
    source: GrainRef,
    target: GrainRef,
    project: ProjectIR,
    context: RollupContext = NO_CONTEXT,
) -> Proof | Refutation:
    """Whether ``metric``'s ratio may be *recomputed* at ``target``.

    A ratio is never rolled up; it is rebuilt. `SUM(num) / SUM(den)` at the
    requested grain and a stored quotient aggregated afterwards are different
    numbers, and the second is the one a warehouse hands you for free. So the
    obligation is not "may this quotient be summed" — it never may — but "may
    each operand be summed to here", and the ratio follows from the two.

    That is why the premises are :func:`prove_additive_rollup` answers rather
    than a rule of this one's own: the reconstruction is sound exactly when the
    reconstruction's *inputs* are, and stating it any other way would let a
    ratio over a non-additive operand prove itself.
    """

    judgement = _judgement("RatioReconstruction", metric.name, source, target)

    if metric.ratio is None:
        return Refutation(
            reason="not_a_ratio",
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"reconstruct {metric.name} at {target.label}",
                    found=f"{metric.name} declares no ratio to reconstruct from",
                ),
            ),
            remediation=(
                "a metric recomputed at the requested grain declares its operands — "
                "additivity: ratio with ratio: {numerator, denominator}"
            ),
        )

    operands = (metric.ratio.numerator, metric.ratio.denominator)
    premises: list[Proof] = []

    for name in operands:
        operand = _metric(project, name)

        if operand is None:
            return Refutation(
                reason="operand_unreachable",
                judgement=judgement,
                obligations=(
                    Obligation(
                        required=f"read {name} as an operand of {metric.name}",
                        found=f"{name} is not a metric of this project",
                    ),
                ),
                # `UNKNOWN` and not `DECLARED`: unlike a wrong additivity, there
                # is no fact here at all — the name reaches nothing.
                rejected=(
                    SemanticFact(
                        source=f"metric:{name}",
                        provenance=Provenance.UNKNOWN,
                        statement="no such metric",
                    ),
                ),
            )

        answer = prove_additive_rollup(operand, source, target, project, context)

        if isinstance(answer, Refutation):
            return answer

        premises.append(answer)

    return Proof(
        rule="R012",
        conclusion=judgement,
        premises=tuple(premises),
        facts=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=(
                    f"{metric.name} is {metric.ratio.numerator} / {metric.ratio.denominator}"
                ),
            ),
        ),
    )


# ....................... #
# R019 — which rows the ratio is about (RFC 0075)


class RatioRowsRefusal(StrEnum):
    """What a ratio's row set was refused for. Two, kept apart rather than
    collapsed into one code, because each names a different repair — R009's
    reasoning, one rule over: the first sends an author to say *which rows*,
    the second to make two restrictions agree, and one class would hand the
    first message to the second author.
    """

    #: A row can contribute to the numerator and nothing to the denominator,
    #: and nothing says whether it belongs in the ratio.
    UNDECLARED_ROWS = "undeclared_rows"
    #: The operands are restricted to different row sets, which makes the
    #: quotient a ratio of two quantities about different things.
    OPERANDS_DISAGREE = "operands_disagree"


# ....................... #

#: The dispositions that make a range rule a *premise* rather than a note
#: (RFC 0075 D3). Both remove the row from the relation the ratio sums;
#: ``flag`` leaves it there, and ``repair`` rewrites the value to a fallback
#: this rule cannot bound — it is the member D3 did not name, and it is
#: excluded for D3's own reason rather than by omission (logs/T-0063.md).
_REMOVING: Final[frozenset[OnFail]] = frozenset({OnFail.QUARANTINE, OnFail.FAIL})

#: The filter operators that can exclude a zero, and what each needs to be
#: true of its values to do it. A restriction the compiler cannot read as
#: zero-excluding is not a restriction it may treat as one: the whole rule is
#: that an unstated reading is refused, so a guess here would be the defect
#: wearing a proof.
_EXCLUDES_ZERO: Final[dict[str, Callable[[tuple[object, ...]], bool]]] = {
    # `> b` excludes zero for any bound at or above it; `>= b` needs the bound
    # itself to be above zero.
    "gt": lambda values: _at_least(values[0], 0),
    "gte": lambda values: _above(values[0], 0),
    "ne": lambda values: _is_zero(values[0]),
    "not_in": lambda values: any(_is_zero(value) for value in values),
    "in": lambda values: values != () and not any(_is_zero(value) for value in values),
}


def _never(_values: tuple[object, ...]) -> bool:
    """The operator this rule cannot read as zero-excluding. Named rather than
    a lambda at the call site so the table above is the whole of what the rule
    admits, read in one place."""

    return False


def _is_zero(value: object) -> bool:
    number = _numeric(value)

    return number is not None and number == 0


def _at_least(value: object, bound: int) -> bool:
    number = _numeric(value)

    return number is not None and number >= bound


def _above(value: object, bound: int) -> bool:
    number = _numeric(value)

    return number is not None and number > bound


def _numeric(value: object) -> Decimal | None:
    """``value`` as a number, or ``None`` where it is not one.

    Filter values arrive as text, int or bool (RFC 0034 D8), and a bool is
    excluded on purpose: ``True == 1`` in Python, so a ``ne: [true]`` filter
    would otherwise read as "not one" and discharge nothing it claims to.
    """

    if isinstance(value, bool):
        return None

    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


# ....................... #


def _dimension_source(metric: MetricIR, project: ProjectIR) -> dict[str, str]:
    """Each dimension this metric can be filtered on, as the entity column it
    resolves to.

    A mart's dimension name is not canonical: the flattener prefixes a joined
    column, so one order-level `region` is `region` on the orders mart and
    `order_region` on the order-items mart. Two operands on two marts restricted
    to the same rows therefore carry two spellings, and comparing the spellings
    refuses a correct ratio (logs/T-0063.md).

    Read from every mart carrying the metric, because that is the set of marts
    whose filters were checked against it (RFC 0034 D9) — and they agree by
    construction, since each name resolves to the column it was flattened from.
    """

    return {
        column.name: f"{column.source_entity}.{column.source_column}"
        for mart in project.marts
        if metric.name in mart.measures
        for column in mart.columns
    }


# ....................... #


def _restriction(
    metric: MetricIR, project: ProjectIR
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """One metric's restriction, canonically.

    Sorted, with each clause's values sorted inside it, because the IR keeps
    ``filter:`` in **authored order** on purpose — the clauses are ANDed, so
    the order is cosmetic in SQL and load-bearing in the artifact bytes
    (`resolve/build.py`). Two projects that wrote the same clauses in different
    orders are different bytes and must stay so; they are not different
    restrictions, and this is where that distinction is made rather than in the
    IR (RFC 0075 §5.2, see logs/T-0063.md).

    Each dimension is named by the entity column it resolves to, for the same
    reason one step further out: a name is how a mart addresses a column, and
    two marts address one column two ways.
    """

    source = _dimension_source(metric, project)

    return tuple(
        sorted(
            (
                source.get(clause.dimension, clause.dimension),
                clause.op,
                tuple(sorted(str(value) for value in clause.values)),
            )
            for clause in metric.filter
        )
    )


# ....................... #


def _excludes_zero_of(metric: MetricIR, column: str) -> bool:
    """Whether ``metric``'s own restriction removes the rows where ``column``
    is zero."""

    return any(
        clause.dimension == column and _EXCLUDES_ZERO.get(clause.op, _never)(clause.values)
        for clause in metric.filter
    )


# ....................... #


def _origin_column(metric: MetricIR, project: ProjectIR) -> tuple[str, str] | None:
    """The ``(entity, column)`` a measure aggregates, where it aggregates one.

    ``None`` for an expression that is not a bare column — ``parcels * crates``
    has no single field to carry a range rule, so the positivity discharge is
    unavailable rather than guessed at.
    """

    if metric.expr is None:
        return None

    tree = metric.expr.ast()

    if not isinstance(tree, exp.Column):
        return None

    entity = next((one for one in project.entities if one.name == metric.grain), None)

    if entity is None or all(column.name != tree.name for column in entity.columns):
        return None

    return entity.name, tree.name


# ....................... #


#: The aggregations whose value is at least one over any non-empty row set,
#: given a column that cannot be null. Everything else — a sum, an average, a
#: minimum — takes its value from the rows themselves and can be zero while the
#: numerator is not, which is the whole of what R019 asks about.
_COUNTING: Final[frozenset[str]] = frozenset({"count", "count_distinct"})


def _counts_every_row(metric: MetricIR, project: ProjectIR) -> str | None:
    """Whether this measure is a count no row of its own row set can miss.

    ``COUNT(expr)`` counts the rows where ``expr`` is not null, so a count over
    a column that cannot be null counts *every* row — and a row that
    contributes to the numerator contributes 1 to the denominator by
    construction. There is nothing for an author to declare here, which is why
    this discharge exists: without it the rule refuses ``revenue /
    order_count``, the most common correct ratio there is (logs/T-0063.md).

    ``count_distinct`` counts too. It was excluded once, on the grounds that a
    distinct count is about the group rather than the row — true, and not the
    premise: what R019 refuses is a denominator whose *per-row* contribution
    can be zero while the numerator's is not, which is a property of a sum over
    a numeric column. A distinct count of a non-null column is at least one for
    any non-empty row set, and "discount per distinct customer" has no
    zero-denominator row to declare anything about. Excluding it produced a
    refusal telling an author to filter a *string* column to values above zero
    (logs/T-0063.md, attempt 2).
    """

    if metric.agg not in _COUNTING:
        return None

    origin = _origin_column(metric, project)

    if origin is None:
        return None

    entity_name, column = origin
    entity = next((one for one in project.entities if one.name == entity_name), None)

    if entity is None:  # pragma: no cover — `_origin_column` resolved it already
        return None

    if any(one.name == column and one.required for one in entity.columns):
        return f"{column!r} is declared required"

    removes_nulls = any(
        rule.kind == "not_null" and rule.column == column and rule.on_fail in _REMOVING
        for rule in entity.quality
    )

    return f"{column!r} carries a not_null rule that removes the row" if removes_nulls else None


# ....................... #


def _positive_by_construction(metric: MetricIR, project: ProjectIR) -> str | None:
    """The rule that makes this measure's column positive, or ``None``.

    Returns the disposition it is declared at, for the proof's fact to name:
    *which* rule discharged the premise is the whole content of it, and a fact
    saying only "declared positive" would be true of a `flag` rule too.
    """

    origin = _origin_column(metric, project)

    if origin is None:
        return None

    entity_name, column = origin
    entity = next((one for one in project.entities if one.name == entity_name), None)

    for rule in entity.quality if entity is not None else ():
        if rule.kind != "range" or rule.column != column or rule.on_fail not in _REMOVING:
            continue

        minimum = next((value for name, value in rule.params if name == "min"), None)

        if minimum is not None and _above(minimum, 0):
            return f"{rule.name} (range min {minimum}, on_fail {rule.on_fail.value})"

    return None


# ....................... #


def _rows_judgement(metric: str) -> SemanticJudgement:
    return SemanticJudgement("RatioRowSet", (("measure", metric),))


# ....................... #


def prove_ratio_rows(metric: MetricIR, project: ProjectIR) -> Proof | Refutation:
    """Whether this ratio is about one row set, and a stated one (R019).

    Two legs, in the order that reports the cheaper defect first:

    * **the operands are restricted identically.** A numerator over one row set
      and a denominator over another is a quotient of two quantities about
      different things, and it is wrong whether or not a zero is involved.
    * **every row contributing to the numerator contributes a non-zero amount
      to the denominator** — or the author has said the ratio is about the
      other row set. A shipment cancelled after the carrier charged for it
      contributes cost and no parcels, and sum-over-sum charges that cost to
      the parcels somebody else moved.

    The second leg discharges three ways and every one of them is the author
    having stated a reading: both operands restricted to exclude the zeros, the
    denominator's own field declared positive at a disposition that removes the
    row, or ``includes_zero_denominator: true`` — the inclusive reading, said
    out loud rather than arrived at by default (D1, D2).

    Nothing here chooses. A refutation is the rule working; a proof names which
    of the three the author wrote, because "declared" without which declaration
    is a fact a reader cannot check.
    """

    judgement = _rows_judgement(metric.name)

    if metric.ratio is None:  # pragma: no cover — the caller filters on `ratio`
        raise ValueError("prove_ratio_rows needs a ratio metric")

    numerator = _metric(project, metric.ratio.numerator)
    denominator = _metric(project, metric.ratio.denominator)

    if numerator is None or denominator is None:
        # R012's territory: an operand that names nothing is refused there,
        # with the message written for it. Answering it here too would mean two
        # rules claiming one defect.
        return Proof(
            rule="R019",
            conclusion=judgement,
            facts=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DERIVED,
                    statement=(
                        f"{metric.name} names an operand this project does not declare; "
                        "which rows it is about is R012's refusal to make, not this one's"
                    ),
                ),
            ),
        )

    if _restriction(numerator, project) != _restriction(denominator, project):
        return Refutation(
            reason=RatioRowsRefusal.OPERANDS_DISAGREE.value,
            judgement=judgement,
            obligations=(
                Obligation(
                    required=f"{numerator.name} and {denominator.name} restricted to one row set",
                    found=(
                        f"{numerator.name} is restricted by {_rendered(numerator)} and "
                        f"{denominator.name} by {_rendered(denominator)}"
                    ),
                ),
            ),
            remediation=(
                "restrict both operands the same way, or neither — a quotient of two "
                "quantities about different row sets is not a rate of anything"
            ),
            rejected=(
                SemanticFact(
                    source=f"metric:{metric.name}",
                    provenance=Provenance.DECLARED,
                    statement=(
                        f"{metric.name} divides {numerator.name} by {denominator.name}, "
                        "which are about different rows"
                    ),
                ),
            ),
        )

    if metric.ratio.includes_zero_denominator:
        return _rows_proof(
            metric,
            f"{metric.name} is declared to include rows whose {denominator.name} is zero",
        )

    origin = _origin_column(denominator, project)
    column = origin[1] if origin is not None else denominator.name

    if _excludes_zero_of(denominator, column) and _excludes_zero_of(numerator, column):
        return _rows_proof(
            metric,
            f"both operands are restricted to rows whose {column!r} is not zero",
        )

    counted = _counts_every_row(denominator, project)

    if counted is not None:
        return _rows_proof(
            metric,
            f"{denominator.name} counts every row of the set it is over: {counted}",
        )

    positive = _positive_by_construction(denominator, project)

    if positive is not None:
        return _rows_proof(
            metric,
            f"{denominator.name} reads {column!r}, which every row declares positive: {positive}",
        )

    # A counting denominator misses a row when its column is *null*, not when
    # it is zero, and telling an author to filter a string column to values
    # above zero is a refusal they cannot act on (logs/T-0063.md, attempt 2).
    counting = denominator.agg in _COUNTING
    empty = "is null" if counting else "is zero"
    present = "is not null" if counting else "is not zero"
    declare = (
        f"declare {column!r} required on the entity, or give it "
        "quality: [{rule: not_null, on_fail: quarantine}]"
        if counting
        else f"declare {column!r} positive on the entity — "
        "quality: [{rule: range, min: 1, on_fail: quarantine}]"
    )
    restrict = (
        f"filter: [{{dimension: {column}, op: is_null, values: [false]}}]"
        if counting
        else f"filter: [{{dimension: {column}, op: gt, values: [0]}}]"
    )

    return Refutation(
        reason=RatioRowsRefusal.UNDECLARED_ROWS.value,
        judgement=judgement,
        obligations=(
            Obligation(
                required=f"which rows {metric.name} is about, where {column!r} {empty} on some",
                found=(
                    f"nothing restricts {numerator.name} and {denominator.name} to rows where "
                    f"{column!r} {present}, nothing on the entity removes those rows, and the "
                    "ratio does not declare that it includes them"
                ),
            ),
        ),
        remediation=(
            f"restrict both operands — {restrict} — or {declare} — or, for the "
            "total-over-units reading, ratio: {..., includes_zero_denominator: true}"
        ),
        rejected=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.UNKNOWN,
                statement=(
                    f"a row whose {column!r} {empty} contributes to {numerator.name} and "
                    f"nothing to {denominator.name}; nothing says whether it belongs here"
                ),
            ),
        ),
    )


# ....................... #


def _rendered(metric: MetricIR) -> str:
    """One metric's restriction, for a refusal to name it by."""

    if not metric.filter:
        return "nothing"

    return ", ".join(
        f"{clause.dimension} {clause.op} {list(clause.values)}" for clause in metric.filter
    )


# ....................... #


def _rows_proof(metric: MetricIR, statement: str) -> Proof:
    """R019 discharged, naming *which* declaration discharged it."""

    return Proof(
        rule="R019",
        conclusion=_rows_judgement(metric.name),
        facts=(
            SemanticFact(
                source=f"metric:{metric.name}",
                provenance=Provenance.DECLARED,
                statement=statement,
            ),
        ),
    )
