"""Spec → IR lowering for the data-quality surface (RFC 0016 §5.3–§5.6).

Pure, total, and I/O-free like every other lowering: authored ``quality:`` /
``dedupe:`` / ``quarantine:`` / ``reconcile:`` blocks become
:class:`~bloomery.ir.QualityRuleIR` / :class:`~bloomery.ir.DedupeIR` /
:class:`~bloomery.ir.QuarantineIR` / :class:`~bloomery.ir.ReconcileIR` values,
with every rule's kind-specific settings flattened into the string-valued
``params`` tuple so the canonical encoding never sees anything but text.

Three things are *resolved* here rather than restated by the author:

- **the implicit ``coercible`` rule** (§5.2, D3) — one per mapped field of a
  quality-carrying entity, carrying the source expressions its marker needs;
- **``in_enum``'s admissible set** — read off the field's ``enum_map`` step's
  targets, because the set *is* the chain's mapping and restating it would let
  the two drift;
- **``referential``'s join** — the named relationship's ``via`` pairs and
  target entity, so emission never needs a relationship lookup.

**Opt-in (an RFC ambiguity resolved).** §5.2 calls ``coercible`` "implicit,
always-present", and §5.6 makes ``retention:`` mandatory wherever a
``quarantine`` disposition exists. Read together and applied to *every*
entity, those two make every project that has never heard of data quality fail
to compile with ``QuarantineRetentionMissing`` — a break §12's phasing does not
anticipate (it budgets for golden churn from ``_quality_flags``, nothing more).
So the implicit rule materializes on the entities that **opt in**: those
declaring entity-level ``quality:``, a ``quarantine:`` block, or any field-level
``quality:``. ``dedupe:`` alone does not opt in — deduplicating is not a
statement about coercibility, and dragging a reject table in behind it would
surprise. Everything else keeps the shipped produce-or-raise lowering.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from bloomery.ir import (
    DedupeIR,
    OnFail,
    QualityRuleIR,
    QuarantineIR,
    ReconcileIR,
    canon,
    extraction,
    partition_specs,
    quality_sort_key,
)
from bloomery.spec.mapping import RecipeFieldMapping
from bloomery.spec.quality import (
    CoercibleRule,
    ExpressionRule,
    InEnumRule,
    InSetRule,
    LengthRule,
    PatternRule,
    RangeRule,
    ReferentialRule,
)

if TYPE_CHECKING:
    from bloomery.spec.entity import Entity, EntityModel, Relationship
    from bloomery.spec.mapping import FieldMapping, Mapping
    from bloomery.spec.quality import FieldQualityRule

__all__ = [
    "field_sources",
    "lower_dedupe",
    "lower_quality",
    "lower_quarantine",
    "lower_reconcile",
    "mapped_fields",
    "opts_in",
]

_NON_NAME = re.compile(r"[^a-z0-9_]")


def _rule_name(stem: str) -> str:
    """A generated rule name, forced into the D23 identifier constraint.

    Rule names reach ``_quality_flags`` and ``failed_rules``, where the whole
    point of ``[a-z0-9_]+`` is that neither shape ever needs escaping. Authored
    names are already constrained at parse; generated ones are folded here, so
    a column spelled ``Order-Id`` cannot smuggle a delimiter into the
    comma-delimited fallback.
    """
    return _NON_NAME.sub("_", stem.lower())


# ....................... #
# Mapping introspection


def mapped_fields(mapping: Mapping) -> tuple[tuple[str, FieldMapping | None], ...]:
    """Every field the mapping lowers, sorted: key fields first (they carry no
    ``quality:`` surface of their own, hence ``None``), then value fields."""
    keys: list[tuple[str, FieldMapping | None]] = [(name, None) for name in sorted(mapping.key)]
    values: list[tuple[str, FieldMapping | None]] = [
        (name, mapping.fields[name]) for name in sorted(mapping.fields)
    ]
    return (*keys, *values)


def field_sources(mapping: Mapping, field_name: str) -> tuple[str, ...]:
    """The canonical SQL of every raw extraction one mapped field reads.

    The coercion-failure marker needs them: "the projection is NULL although
    every source it reads was not" (see
    :func:`bloomery.quality.predicates.violation`).
    """
    if field_name in mapping.key:
        return (canon(extraction(mapping.key[field_name].from_)).sql,)
    field_mapping = mapping.fields[field_name]
    if isinstance(field_mapping, RecipeFieldMapping):
        paths = sorted(field_mapping.from_.values())
    else:
        paths = [field_mapping.from_]
    return tuple(canon(extraction(path)).sql for path in paths)


def _enum_targets(mapping: Mapping, field_name: str) -> tuple[str, ...]:
    """The ``enum_map`` targets on a field's chain, deduplicated and sorted —
    ``in_enum``'s admissible set (RFC 0016 §5.2)."""
    # Only a value field can carry ``in_enum`` (key fields have no
    # ``quality:`` surface), so the lookup is total.
    field_mapping = mapping.fields[field_name]
    if isinstance(field_mapping, RecipeFieldMapping):
        return ()  # a recipe binds aliases, not a chain — no enum_map to read
    targets: set[str] = set()
    for step in field_mapping.transform:
        if step.name == "enum_map":
            targets.update(str(value) for value in step.args[1::2])
    return tuple(sorted(targets))


def _field_quality(field_mapping: FieldMapping | None) -> tuple[FieldQualityRule, ...]:
    return () if field_mapping is None else field_mapping.quality


def opts_in(entity: Entity, mapping: Mapping) -> bool:
    """Whether this entity joins the quality system (see the module docstring
    for why ``dedupe:`` alone does not)."""
    return bool(
        entity.quality
        or entity.quarantine is not None
        or any(_field_quality(fm) for _name, fm in mapped_fields(mapping))
    )


# ....................... #
# Rule lowering


def _indexed(prefix: str, values: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(f"{prefix}_{index:04d}", value) for index, value in enumerate(values)]


def _field_rule_ir(
    rule: FieldQualityRule,
    column: str,
    *,
    mapping: Mapping,
    slice_columns: tuple[str, ...],
) -> QualityRuleIR:
    params: list[tuple[str, str]] = []
    stem = f"{column}_{rule.rule}"
    if isinstance(rule, CoercibleRule):
        params.extend(_indexed("source", field_sources(mapping, column)))
    elif isinstance(rule, (RangeRule, LengthRule)):
        if rule.min is not None:
            params.append(("min", str(rule.min)))
        if rule.max is not None:
            params.append(("max", str(rule.max)))
        if rule.min is None or rule.max is None:
            stem = f"{stem}_{'min' if rule.min is not None else 'max'}"
    elif isinstance(rule, PatternRule):
        params.append(("regex", rule.regex))
    elif isinstance(rule, InEnumRule):
        params.extend(_indexed("value", _enum_targets(mapping, column)))
    elif isinstance(rule, InSetRule):
        params.extend(_indexed("value", tuple(str(value) for value in rule.values)))
    else:  # UniqueRule — the slice is the entity's partition, or the table
        params.extend(_indexed("slice", slice_columns))
    return QualityRuleIR(
        name=_rule_name(stem),
        kind=rule.rule,
        column=column,
        on_fail=OnFail(rule.on_fail),
        params=tuple(sorted(params)),
    )


def _referential_ir(rule: ReferentialRule, relationship: Relationship) -> QualityRuleIR:
    """``via`` pairs are carried as ``<from>=<to>`` strings, sorted by
    from-column — the same order :class:`~bloomery.ir.RelationshipIR` keeps.
    ``=`` is an unambiguous separator: both sides are SQL identifiers."""
    via = tuple(
        f"{from_column}={to_column}" for from_column, to_column in sorted(relationship.via.items())
    )
    params = [
        ("on_missing", rule.on_missing),
        ("relationship", relationship.name),
        ("to_entity", relationship.to),
        *_indexed("via", via),
    ]
    return QualityRuleIR(
        name=_rule_name(f"{relationship.name}_referential"),
        kind="referential",
        column=None,
        on_fail=None,  # referential carries on_missing; unknown_member is not an OnFail
        params=tuple(sorted(params)),
    )


def _dedupe_fields(entity: Entity) -> frozenset[str]:
    if entity.dedupe is None:
        return frozenset()
    return frozenset({entity.dedupe.field, *entity.dedupe.tie_break})


def _deduplicate_names(rules: list[QualityRuleIR]) -> tuple[QualityRuleIR, ...]:
    """Force rule names unique, deterministically.

    Two identical-shaped rules on one column (the same bound declared twice
    with different dispositions) would otherwise share a name, and a shared
    name in ``failed_rules`` is an unreadable reject row. Suffixes are assigned
    in the IR's own canonical order, so the assignment is a pure function of
    the value — never of authored order.
    """
    seen: dict[str, int] = {}
    named: list[QualityRuleIR] = []
    for rule in sorted(rules, key=quality_sort_key):
        count = seen.get(rule.name, 0)
        seen[rule.name] = count + 1
        name = rule.name if count == 0 else f"{rule.name}_{count + 1}"
        named.append(rule if name == rule.name else replace(rule, name=name))
    return tuple(sorted(named, key=quality_sort_key))


def lower_quality(
    entity: Entity, mapping: Mapping, relationships: tuple[Relationship, ...]
) -> tuple[QualityRuleIR, ...]:
    """Every rule of one entity, field rules and row rules alike, canonically
    sorted (:func:`~bloomery.ir.quality_sort_key`)."""
    if not opts_in(entity, mapping):
        return ()
    slice_columns = tuple(spec.column for spec in partition_specs(entity.partition_by))
    dedupe_fields = _dedupe_fields(entity)
    rules: list[QualityRuleIR] = []

    for column, field_mapping in mapped_fields(mapping):
        declared = _field_quality(field_mapping)
        for rule in declared:
            rules.append(_field_rule_ir(rule, column, mapping=mapping, slice_columns=slice_columns))
        if not any(isinstance(rule, CoercibleRule) for rule in declared):
            # The implicit rule (§5.2, D3). Forced to FAIL on a field the
            # dedupe order reads (§5.4): an uncastable recency field leaves
            # dedupe ordering undefined, so quarantining it is not an option.
            on_fail = OnFail.FAIL if column in dedupe_fields else OnFail.QUARANTINE
            rules.append(
                QualityRuleIR(
                    name=_rule_name(f"{column}_coercible"),
                    kind="coercible",
                    column=column,
                    on_fail=on_fail,
                    params=tuple(sorted(_indexed("source", field_sources(mapping, column)))),
                )
            )

    by_name = {relationship.name: relationship for relationship in relationships}
    for row_rule in entity.quality:
        if isinstance(row_rule, ExpressionRule):
            rules.append(
                QualityRuleIR(
                    name=row_rule.name,
                    kind="expression",
                    column=None,
                    on_fail=OnFail(row_rule.on_fail),
                    params=(("expr", row_rule.expr),),
                )
            )
        else:
            # Resolution (RFC 0005) has already refused a ``via`` naming no
            # relationship, so the lookup is total by the time lowering runs.
            rules.append(_referential_ir(row_rule, by_name[row_rule.via]))
    return _deduplicate_names(rules)


# ....................... #
# The entity-level blocks


def lower_dedupe(entity: Entity) -> DedupeIR | None:
    """``dedupe:`` → :class:`DedupeIR`, authored ``tie_break`` order kept (it
    is a sort order, therefore semantic — RFC 0003 D4)."""
    if entity.dedupe is None:
        return None
    return DedupeIR(
        keep=entity.dedupe.keep, field=entity.dedupe.field, tie_break=entity.dedupe.tie_break
    )


def lower_quarantine(entity: Entity) -> QuarantineIR | None:
    """``quarantine:`` → :class:`QuarantineIR`, ``redact`` sorted (it is a set
    of paths; authored order carries nothing)."""
    if entity.quarantine is None:
        return None
    return QuarantineIR(
        retention=entity.quarantine.retention, redact=tuple(sorted(entity.quarantine.redact))
    )


def lower_reconcile(entity_model: EntityModel) -> tuple[ReconcileIR, ...]:
    """The document-level ``reconcile:`` list → :class:`ReconcileIR`, sorted by
    name."""
    return tuple(
        sorted(
            (
                ReconcileIR(
                    name=check.name,
                    left=check.left,
                    right=check.right,
                    tolerance=check.tolerance,
                    on_fail=OnFail(check.on_fail),
                )
                for check in entity_model.reconcile
            ),
            key=lambda check: check.name,
        )
    )
