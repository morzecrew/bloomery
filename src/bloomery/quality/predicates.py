"""Violation predicates: one dialect-neutral SQLGlot AST per rule kind
(RFC 0016 §5.4).

**The central invariant of this module (RFC 0016 D19 — three-valued logic).**
Every builder here returns a predicate that is definitively ``TRUE`` *only*
when the rule is violated. A comparison involving ``NULL`` evaluates to SQL
``UNKNOWN``, and ``UNKNOWN`` must **not** fire: it is neither a pass nor a
failure, and treating it as a failure would make every nullable column fail
every rule. Nulls are owned by exactly two rules — ``not_null`` and
``coercible`` — and an author who considers nulls invalid declares one of
them. This applies uniformly to ``range``, ``length``, ``pattern``,
``in_enum``, ``in_set``, ``unique``, ``expression``, and ``referential``: a
NULL fk is not an orphan, it is ``not_null``'s business.

Practically that means the builders never wrap a comparison in ``COALESCE`` or
``IS NOT TRUE``, and the two null-owning rules state their null handling
explicitly (``col IS NULL`` for ``not_null``; the coercion-failure marker —
"the projection is NULL although every source it reads was not" — for
``coercible``). Any rule added to the catalogue later must be reviewed against
this paragraph before it joins
:data:`~bloomery.quality.catalogue.ALL_RULES`.

Disposition precedence (RFC 0016 D18) lives here too: severity ``fail >
quarantine > flag``, deterministic for every combination — which is why no
rule/disposition pair needs compile-time rejection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.ir import OnFail, QualityRuleIR, SqlExpr
from bloomery.quality.catalogue import UNKNOWN_MEMBER

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "WINDOWED_KINDS",
    "conjunction",
    "disjunction",
    "disposition",
    "failed_rule_names",
    "grouped",
    "indexed_params",
    "params_of",
    "qualify_columns",
    "ref_alias",
    "source_alias",
    "unknown_member_case",
    "violation",
    "window_alias",
    "windowed",
    "worst",
]

# ....................... #
# Connectives. SQLGlot's generator emits no precedence parentheses of its own
# (``And(Or(a, b), c)`` renders ``a OR b AND c``), so every composite operand
# is parenthesised here — a mis-parenthesised quality predicate is a silently
# wrong disposition, the worst failure mode this package has.

_COMPOSITE = (exp.And, exp.Or, exp.Not)


def grouped(node: Expression) -> Expression:
    """``node`` parenthesised if it is a connective, unchanged otherwise."""
    return exp.Paren(this=node) if isinstance(node, _COMPOSITE) else node


def conjunction(parts: Sequence[Expression]) -> Expression:
    """Left-folded ``AND`` over ``parts`` — deterministic shape, explicit
    parentheses. Never called with an empty sequence."""
    node = grouped(parts[0])
    for part in parts[1:]:
        node = exp.And(this=node, expression=grouped(part))
    return node


def disjunction(parts: Sequence[Expression]) -> Expression:
    """Left-folded ``OR`` over ``parts`` — the ``AND`` sibling above."""
    node = grouped(parts[0])
    for part in parts[1:]:
        node = exp.Or(this=node, expression=grouped(part))
    return node


def _is_null(node: Expression) -> Expression:
    return exp.Is(this=node, expression=exp.null())


def _is_not_null(node: Expression) -> Expression:
    return exp.Not(this=_is_null(node))


# ....................... #
# Params


def params_of(rule: QualityRuleIR) -> dict[str, str]:
    """A rule's params as a mapping — the params tuple is sorted by name, so
    the dict is a view, never a re-ordering."""
    return dict(rule.params)


def indexed_params(rule: QualityRuleIR, prefix: str) -> tuple[str, ...]:
    """The values of ``<prefix>_0000``, ``<prefix>_0001`` … in index order.

    Ordered params exist because :attr:`QualityRuleIR.params` sorts by name
    (RFC 0003): zero-padded indices make the by-name sort *be* the authored
    order, the same device the ``assert: enum`` lowering uses (RFC 0006 D8).
    """
    marker = f"{prefix}_"
    return tuple(value for name, value in rule.params if name.startswith(marker))


def source_alias(rule: QualityRuleIR, index: int) -> str:
    """The projection name a ``coercible`` rule's *n*-th source hides behind.

    The marker compares the produced column against the raw source paths it
    reads, but those paths live one level down, in the extract SELECT — by the
    time the rules run they are behind a subquery. So the extract level
    projects each source under this deterministic name and the predicate
    references it. One convention, spelled once, used by the builder below and
    by the emitter that projects them.
    """
    return f"_src_{rule.name}_{index:04d}"


#: Rule kinds whose violation predicate contains a **window function**.
#:
#: SQL allows a window function in a projection and forbids it everywhere a
#: projection has not yet been computed — a ``WHERE`` clause, an aggregate's
#: argument, a ``QUALIFY`` other than the query's own. The lowering puts a
#: violation predicate in all three positions (the routing split, the audit
#: bodies, the conservation audit's ``SUM(CASE …)``), so a windowed rule has to
#: be *computed once, as a column*, and referenced by name from then on
#: (:func:`window_alias`). ``unique`` is the only such kind in the v1 catalogue
#: (D5); a rule added later that needs a window joins this set rather than
#: growing a special case at each position.
WINDOWED_KINDS = frozenset({"unique"})


def windowed(rule: QualityRuleIR) -> bool:
    """Whether this rule's predicate must be projected before it can be used."""
    return rule.kind in WINDOWED_KINDS


def window_alias(rule: QualityRuleIR) -> str:
    """The projection name a windowed rule's verdict is computed under.

    One convention, spelled once, used by the emitter that projects the column
    and by every position that reads it back. It carries the rule name, so two
    windowed rules on one entity never collide.
    """
    return f"_win_{rule.name}"


def ref_alias(relationship: str) -> str:
    """The join alias probing a ``referential`` rule's referenced entity.

    Derived from the relationship name, not the entity name: two relationships
    may point at the same entity, and each needs its own probe.
    """
    return f"_ref_{relationship}"


def qualify_columns(node: Expression, table: str | None) -> Expression:
    """Qualify every unqualified column reference in ``node`` with ``table``.

    Row rules carry authored SQL (``expression``) and the routing layer joins
    the referenced entities, so an unqualified ``stock_level`` would be
    ambiguous. Qualification happens on a copy; the input is never mutated.
    """
    if table is None:
        return node

    def qualified(child: Expression) -> Expression:
        if isinstance(child, exp.Column) and not child.table:
            return exp.column(child.name, table=table)
        return child

    return node.copy().transform(qualified)


# ....................... #
# The catalogue, one builder per kind. Read every one against this module's
# docstring: TRUE only when definitively violated.


def _coercible(rule: QualityRuleIR, table: str | None) -> Expression:
    """The coercion-failure marker (RFC 0016 §5.2, D3).

    Transform chains lower ``TRY_CAST``-shaped, so a failed coercion produces
    ``NULL`` rather than raising. A bare ``col IS NULL`` would then also fire
    for a genuinely null source — so the marker is "the projection is NULL
    *although every source path it reads was not*". Conservative by
    construction: a recipe over ``(total, qty)`` with a null ``total`` yields a
    legitimate null, not a coercion failure.
    """
    column = exp.column(rule.column or "", table=table)
    parts: list[Expression] = [_is_null(column)]
    parts.extend(
        _is_not_null(exp.column(source_alias(rule, index), table=table))
        for index, _source in enumerate(indexed_params(rule, "source"))
    )
    return conjunction(parts)


def _not_null(rule: QualityRuleIR, table: str | None) -> Expression:
    """One of the two null-owning rules: ``col IS NULL`` is two-valued by
    construction — it is never ``UNKNOWN``."""
    return _is_null(exp.column(rule.column or "", table=table))


def _bound_literal(value: str) -> Expression:
    """A range bound as a literal. Numeric text renders as a number literal;
    everything else as a string literal the engine compares in the column's
    own type. Floats never appear (RFC 0003 D5) — the bound arrives as text
    and leaves as text."""
    try:
        float(value)  # a shape probe only: ``value`` is never converted
    except ValueError:
        return exp.Literal.string(value)
    return exp.Literal.number(value)


def _range(rule: QualityRuleIR, table: str | None) -> Expression:
    """``col < min OR col > max``. A NULL ``col`` makes both comparisons
    ``UNKNOWN``, and ``UNKNOWN OR UNKNOWN`` is ``UNKNOWN`` — the rule stays
    silent, exactly as D19 requires."""
    column = exp.column(rule.column or "", table=table)
    params = params_of(rule)
    parts: list[Expression] = []
    if "min" in params:
        parts.append(exp.LT(this=column.copy(), expression=_bound_literal(params["min"])))
    if "max" in params:
        parts.append(exp.GT(this=column.copy(), expression=_bound_literal(params["max"])))
    return disjunction(parts)


def _length(rule: QualityRuleIR, table: str | None) -> Expression:
    """``LENGTH(col) < min OR LENGTH(col) > max`` — ``LENGTH(NULL)`` is NULL,
    so a null column keeps the predicate ``UNKNOWN`` (D19)."""
    length = exp.Length(this=exp.column(rule.column or "", table=table))
    params = params_of(rule)
    parts: list[Expression] = []
    if "min" in params:
        parts.append(exp.LT(this=length.copy(), expression=exp.Literal.number(params["min"])))
    if "max" in params:
        parts.append(exp.GT(this=length.copy(), expression=exp.Literal.number(params["max"])))
    return disjunction(parts)


def _pattern(rule: QualityRuleIR, table: str | None) -> Expression:
    """``NOT REGEXP_LIKE(col, regex)`` — ``NOT UNKNOWN`` is ``UNKNOWN``, so a
    null column does not fire (D19). The portable-subset and per-dialect
    validation happen at compile (:mod:`bloomery.quality.pattern`)."""
    matches = exp.RegexpLike(
        this=exp.column(rule.column or "", table=table),
        expression=exp.Literal.string(params_of(rule)["regex"]),
    )
    return exp.Not(this=matches)


def _not_in(rule: QualityRuleIR, table: str | None) -> Expression:
    members = [exp.Literal.string(value) for value in indexed_params(rule, "value")]
    return exp.Not(
        this=exp.In(this=exp.column(rule.column or "", table=table), expressions=members)
    )


def _in_enum(rule: QualityRuleIR, table: str | None) -> Expression:
    """The value survived its ``enum_map`` chain unmapped (RFC 0016 §5.2).

    The admissible set *is* the chain's mapping — resolved at lowering from
    the ``enum_map`` step's targets, never restated by the author, so the two
    cannot drift. ``col NOT IN (...)`` is ``UNKNOWN`` for a null column (D19).
    """
    return _not_in(rule, table)


def _in_set(rule: QualityRuleIR, table: str | None) -> Expression:
    """``col NOT IN (...)`` over the literal set — ``UNKNOWN`` for a null
    column (D19). The set is spec-declared and never contains NULL, so the
    classic ``NOT IN`` null trap cannot arise on the right-hand side."""
    return _not_in(rule, table)


def _unique(rule: QualityRuleIR, table: str | None) -> Expression:
    """``COUNT(*) OVER (PARTITION BY <slice>, col) > 1 AND col IS NOT NULL``.

    **The slice choice (RFC 0016 D5).** ``unique`` is evaluated per *partition
    slice* in both full and incremental runs — the partition is the scope unit
    either way, which is precisely why full/incremental equivalence holds. The
    slice columns are the entity's ``partition_by`` columns, resolved at
    lowering into the ``slice_0000`` … params; an unpartitioned FULL entity
    lowers to no slice columns at all, so the window covers the whole table —
    again in both modes. Cross-partition duplicates are out of scope in every
    mode: identity duplicates are key-based dedupe's job, and a late-arriving
    duplicate key lands on ``dedupe``, not here.

    The explicit ``col IS NOT NULL`` is the D19 conjunct: SQL windows group
    NULLs together, so without it two null rows would count as duplicates —
    a null verdict this rule does not own.
    """
    column = exp.column(rule.column or "", table=table)
    partition = [exp.column(name, table=table) for name in indexed_params(rule, "slice")]
    partition.append(column.copy())
    counted = exp.Window(this=exp.Count(this=exp.Star()), partition_by=partition)
    return conjunction(
        [
            exp.GT(this=counted, expression=exp.Literal.number(1)),
            _is_not_null(column.copy()),
        ]
    )


def _expression(rule: QualityRuleIR, table: str | None) -> Expression:
    """``NOT (<expr>)`` over the entity's own columns — a null operand leaves
    the authored predicate ``UNKNOWN``, and ``NOT UNKNOWN`` is ``UNKNOWN``
    (D19)."""
    body = qualify_columns(SqlExpr(params_of(rule)["expr"]).ast(), table)
    return exp.Not(this=exp.Paren(this=body))


def _referential(rule: QualityRuleIR, table: str | None) -> Expression:
    """``ref.<pk> IS NULL AND fk IS NOT NULL`` (RFC 0016 D19).

    Only a *non-null* fk with no referenced row is an orphan. This corrects
    Document 5's bare ``COALESCE(fk, '__unknown__')`` sketch, which mapped a
    NULL fk to the unknown member — the correction is recorded as D19.
    """
    alias = ref_alias(params_of(rule)["relationship"])
    pairs = [pair.split("=", 1) for pair in indexed_params(rule, "via")]
    parts: list[Expression] = [_is_null(exp.column(pairs[0][1], table=alias))]
    parts.extend(_is_not_null(exp.column(from_column, table=table)) for from_column, _to in pairs)
    return conjunction(parts)


_BUILDERS = {
    "coercible": _coercible,
    "expression": _expression,
    "in_enum": _in_enum,
    "in_set": _in_set,
    "length": _length,
    "not_null": _not_null,
    "pattern": _pattern,
    "range": _range,
    "referential": _referential,
    "unique": _unique,
}


def violation(rule: QualityRuleIR, *, table: str | None = None) -> Expression:
    """The dialect-neutral predicate that is ``TRUE`` exactly when ``rule`` is
    violated (see the module docstring's three-valued invariant).

    ``table`` qualifies the rule's own column references; the ``referential``
    probe always qualifies the referenced side with :func:`ref_alias`.
    """
    builder = _BUILDERS.get(rule.kind)
    if builder is None:  # pragma: no cover — the catalogue is closed (D5/D6)
        msg = f"no violation predicate for rule kind {rule.kind!r}"
        raise KeyError(msg)
    return builder(rule, table)


def unknown_member_case(rule: QualityRuleIR, *, table: str | None = None) -> Expression:
    """``CASE WHEN ref.<pk> IS NULL AND fk IS NOT NULL THEN '__unknown__' ELSE
    fk END`` — the ``on_missing: unknown_member`` lowering (RFC 0016 §5.4).

    The row passes with its fk rewritten to the reserved member, keeping
    aggregates *correct*: dropping orphans makes revenue quietly lower than
    the source system's, while a reserved member keeps the total right and
    makes the problem visible in the dashboard.
    """
    from_column = indexed_params(rule, "via")[0].split("=", 1)[0]
    return exp.Case(
        ifs=[exp.If(this=violation(rule, table=table), true=exp.Literal.string(UNKNOWN_MEMBER))],
        default=exp.column(from_column, table=table),
    )


# ....................... #
# Disposition precedence (RFC 0016 D18)

#: Severity, ascending — ``fail > quarantine > flag``.
_SEVERITY = {OnFail.FLAG: 0, OnFail.QUARANTINE: 1, OnFail.FAIL: 2}


def disposition(rule: QualityRuleIR) -> OnFail:
    """The effective disposition of one rule.

    ``referential`` carries ``on_missing`` rather than ``on_fail`` (its
    ``unknown_member`` value is not an :class:`OnFail` at all — the row passes
    with its fk rewritten). Its ``quarantine``/``flag`` values map onto the
    matching disposition; ``unknown_member`` maps to :attr:`OnFail.FLAG`,
    because the row is kept and the rule's firing is still recorded — never to
    ``QUARANTINE``, which would divert the very row the reserved member exists
    to keep.
    """
    if rule.on_fail is not None:
        return rule.on_fail
    if params_of(rule)["on_missing"] == "quarantine":
        return OnFail.QUARANTINE
    return OnFail.FLAG


def worst(rules: Iterable[QualityRuleIR]) -> OnFail | None:
    """The severest disposition among ``rules`` (D18), or ``None`` if empty."""
    dispositions = [disposition(rule) for rule in rules]
    if not dispositions:
        return None
    return max(dispositions, key=lambda value: _SEVERITY[value])


def failed_rule_names(rules: Iterable[QualityRuleIR]) -> tuple[str, ...]:
    """Every rule name a quarantined row records, lexicographically sorted.

    RFC 0016 D18: a quarantined row's ``failed_rules`` carries **all** its
    failures, flag-level ones included — the reject row is the full account of
    why a row is not in the entity, not merely the part that diverted it.
    """
    return tuple(sorted(rule.name for rule in rules))
