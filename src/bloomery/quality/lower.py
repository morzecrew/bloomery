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
- **``in_enum``'s admissible set** — read off the field's ``enum_map`` steps,
  both their targets and the spellings that reach them (D49), because the set
  *is* the chain's mapping and restating it would let the two drift;
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
from bloomery.spec.mapping import ALIAS_BOUND
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
from bloomery.transforms.registry import registry

if TYPE_CHECKING:
    from bloomery.spec.entity import Entity, EntityModel, Relationship
    from bloomery.spec.mapping import FieldMapping, Mapping
    from bloomery.spec.quality import FieldQualityRule

__all__ = [
    "field_sources",
    "generated_rule_names",
    "lower_dedupe",
    "lower_quality",
    "lower_quarantine",
    "lower_reconcile",
    "mapped_fields",
    "nullifying_steps",
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
    if isinstance(field_mapping, ALIAS_BOUND):
        paths = sorted(field_mapping.from_.values())
    else:
        paths = [field_mapping.from_]
    return tuple(canon(extraction(path)).sql for path in paths)


def _enum_chain(mapping: Mapping, field_name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The ``enum_map`` steps of a field's chain as (spellings, targets), each
    deduplicated and sorted — what defines ``in_enum``'s admissible set
    (RFC 0016 §5.2, D49).

    Both halves are needed, and neither is redundant. ``enum_map`` passes an
    *unmapped* value through untouched, so the raw values ``in_enum`` admits
    are the mapped spellings plus the targets themselves. A widening that
    points a new spelling at an existing target (``PAYED → paid``) changes no
    target, and a rule carrying only the targets could not see it — while it
    is exactly the edit §6's replay case is about. The pairing is deliberately
    *not* carried: re-pointing ``a → x`` to ``a → y`` when both are already
    targets changes the column's value, which the column diff reports, but
    changes nothing about which raw values this rule admits.
    """
    # Only a value field can carry ``in_enum`` (key fields have no
    # ``quality:`` surface), so the lookup is total.
    field_mapping = mapping.fields[field_name]
    if isinstance(field_mapping, ALIAS_BOUND):
        return ((), ())  # a recipe or macro binds aliases, not a chain — no enum_map
    spellings: set[str] = set()
    targets: set[str] = set()
    for step in field_mapping.transform:
        if step.name == "enum_map":
            spellings.update(str(value) for value in step.args[::2])
            targets.update(str(value) for value in step.args[1::2])
    return tuple(sorted(spellings)), tuple(sorted(targets))


def nullifying_steps(
    mapping: Mapping, column: str, field_mapping: FieldMapping | None
) -> tuple[str, ...]:
    """The names of transforms in this column's chain that declare
    ``nullifies`` — deduplicated, sorted, empty for a recipe field.

    ``field_mapping`` is ``None`` for a key column (:func:`mapped_fields`
    spells it that way because a key carries no ``quality:`` surface), but a
    ``KeyField`` does carry a ``transform`` chain, so the key is looked up
    rather than treated as chainless. Reading ``None`` as "no chain" left the
    key with the exact false positive this function exists to prevent — and
    the *worst* version of it, because with no ``quality:`` surface the author
    cannot declare the rule away and the guardrail cannot refuse it either.

    ``coercible`` reads "the output is NULL while a source was not" as *the
    cast failed* (§5.2). That inference is only sound when nothing in the
    chain nulls a value on purpose: ``{nullif: 'N/A'}`` says a sentinel means
    missing, and quarantining the row for obeying it withholds a good row for
    doing exactly what the author declared. So a chain naming any of these
    gets no implicit ``coercible``, and declaring one explicitly is refused.

    The set comes from the registry, not from a name list here — see
    :class:`~bloomery.transforms.registry.TransformSpec`. An unknown step name
    is not this function's error to raise: the chain typecheck already owns
    it, and reporting it twice would only crowd the batch.
    """
    if isinstance(field_mapping, ALIAS_BOUND):
        return ()  # a recipe or macro binds aliases, not a chain
    if field_mapping is None:
        key_field = mapping.key.get(column)
        if key_field is None:
            return ()
        chain = key_field.transform
    else:
        chain = field_mapping.transform
    specs = registry()
    return tuple(
        sorted(
            {
                step.name
                for step in chain
                if (spec := specs.get(step.name)) is not None and spec.nullifies
            }
        )
    )


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
        spellings, targets = _enum_chain(mapping, column)
        params.extend(_indexed("value", targets))
        params.extend(_indexed("spelling", spellings))
    elif isinstance(rule, InSetRule):
        params.extend(_indexed("value", tuple(str(value) for value in rule.values)))
        # The member's declared *type*, carried beside its text: the spec
        # surface admits `int` beside `str`, and the IR's params are strings,
        # so without this the two are indistinguishable downstream and every
        # member renders as a string literal — a comparison Trino refuses on an
        # integer column. Emitted only when the set actually holds an integer,
        # so an all-string set's IR bytes are unchanged.
        if any(isinstance(value, int) for value in rule.values):
            params.extend(
                _indexed(
                    "numeric",
                    tuple("true" if isinstance(value, int) else "false" for value in rule.values),
                )
            )
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


def _assign_names(rules: list[QualityRuleIR], taken: set[str]) -> list[QualityRuleIR]:
    """Give each rule the first free name in its ``name``, ``name_2``, … chain,
    walking :func:`~bloomery.ir.quality_sort_key` (RFC 0016 D50).

    The suffix counts *up until the candidate is actually free*, rather than
    trusting ``_{n}`` to be: an authored ``expression`` rule may legally be
    named ``a_range_min_2``, which is precisely what the second of two
    ``a_range_min`` rules used to be renamed to — two rules, one name, silently
    merged.

    The walk order is the sort key, which orders over the rule's whole value,
    ``on_fail`` included. Without that last component two rules differing only
    in disposition sorted equal, the stable sort fell through to authored
    order, and swapping two YAML lines swapped which rule owned the unsuffixed
    name (RFC 0003: same specs in, same bytes out).
    """
    named: list[QualityRuleIR] = []
    for rule in sorted(rules, key=quality_sort_key):
        name, index = rule.name, 1
        while name in taken:
            index += 1
            name = f"{rule.name}_{index}"
        taken.add(name)
        named.append(rule if name == rule.name else replace(rule, name=name))
    return named


def _deduplicate_names(
    generated: list[QualityRuleIR], authored: list[QualityRuleIR]
) -> tuple[QualityRuleIR, ...]:
    """Force rule names unique, deterministically — **generated names first**
    (RFC 0016 D50, completed by D71).

    Two identical-shaped rules on one column (the same bound declared twice
    with different dispositions) would otherwise share a name, and a shared
    name in ``failed_rules`` is an unreadable reject row — worse, one quality
    mart row whose counts are the union of two rules' failures.

    The two passes are what make a generated name **name-independent**, not
    only order-independent. Generated names are derived from a column and a
    rule kind; authored ones are whatever an ``expression`` rule declares. In
    one interleaved pass an authored ``amount_in_set`` sorted ahead of the
    field's own generated ``amount_in_set`` and took it, pushing the generated
    rule to ``amount_in_set_2`` — so an edit that has nothing to do with that
    field moved the key of a *time series* in the quality mart (§5.8), while
    ``plan()`` honestly reported a removal, an addition and a replay for a rule
    that never stopped firing on the same rows.

    Reserving the generated names first makes them a function of the mapping
    alone. The authored side is not silently renamed instead: a collision is
    refused at compile (:mod:`bloomery.guardrails.quality`), and this order is
    what keeps that refusal from being defeated by a future suffix landing
    somewhere unexpected.
    """
    taken: set[str] = set()
    named = _assign_names(generated, taken)
    named.extend(_assign_names(authored, taken))
    return tuple(sorted(named, key=quality_sort_key))


def _draft_rules(
    entity: Entity, mapping: Mapping, relationships: tuple[Relationship, ...]
) -> tuple[list[QualityRuleIR], list[QualityRuleIR]]:
    """``(generated, authored)`` — the entity's rules, still carrying the names
    each side proposes, before :func:`_deduplicate_names` arbitrates.

    The split is by **who names the rule**, which is the axis D71 turns on. A
    field rule's name is derived from its column and kind, a ``referential``
    rule's from its relationship, and the implicit ``coercible`` rule's from its
    column: all functions of the mapping. Only an ``expression`` rule carries a
    name a human wrote.
    """
    slice_columns = tuple(spec.column for spec in partition_specs(entity.partition_by))
    dedupe_fields = _dedupe_fields(entity)
    generated: list[QualityRuleIR] = []
    authored: list[QualityRuleIR] = []

    for column, field_mapping in mapped_fields(mapping):
        declared = _field_quality(field_mapping)
        generated.extend(
            _field_rule_ir(rule, column, mapping=mapping, slice_columns=slice_columns)
            for rule in declared
        )
        # The implicit rule (§5.2, D3) is skipped where the chain nulls a
        # value deliberately — see :func:`nullifying_steps` for why a marker
        # that cannot tell that from a failed cast must not fire at all —
        # **except** on a column the dedupe order reads. There the rule is not
        # a convenience: §5.4/D6 forces it to FAIL because an uncastable
        # recency value leaves the dedupe order undefined, and dropping it
        # would trade a false positive for a silently nondeterministic entity
        # (D80). A `nullif` on a sort column is the author's to see.
        skip = (
            bool(nullifying_steps(mapping, column, field_mapping)) and column not in dedupe_fields
        )
        if not any(isinstance(rule, CoercibleRule) for rule in declared) and not skip:
            on_fail = OnFail.FAIL if column in dedupe_fields else OnFail.QUARANTINE
            generated.append(
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
            authored.append(
                QualityRuleIR(
                    name=row_rule.name,
                    kind="expression",
                    column=None,
                    on_fail=OnFail(row_rule.on_fail),
                    params=(("expr", row_rule.expr),),
                )
            )
        else:
            # A ``via`` naming no declared relationship is a *guardrail*
            # refusal (§5.9) that the stage raises over this same draft — and
            # the stage runs after the lowering, so the lowering may not
            # assume the lookup is total. It skips instead: an unresolvable
            # rule lowers to nothing, the draft is well-formed, and the
            # guardrail reports the typo with the declared names beside it.
            # Compiling never reaches an IR missing the rule, because the
            # stage refuses before anything is emitted.
            relationship = by_name.get(row_rule.via)
            if relationship is not None:
                generated.append(_referential_ir(row_rule, relationship))
    return generated, authored


def generated_rule_names(
    entity: Entity, mapping: Mapping, relationships: tuple[Relationship, ...]
) -> frozenset[str]:
    """The names generation issues on its **own** account (RFC 0016 D71).

    A function of the mapping alone — no authored ``expression`` name reaches
    it, which is exactly what makes it usable as the set a guardrail refuses an
    authored name for landing in. Empty for an entity that never opted in.
    """
    if not opts_in(entity, mapping):
        return frozenset()
    generated, _authored = _draft_rules(entity, mapping, relationships)
    return frozenset(rule.name for rule in _assign_names(generated, set()))


def lower_quality(
    entity: Entity, mapping: Mapping, relationships: tuple[Relationship, ...]
) -> tuple[QualityRuleIR, ...]:
    """Every rule of one entity, field rules and row rules alike, canonically
    sorted (:func:`~bloomery.ir.quality_sort_key`)."""
    if not opts_in(entity, mapping):
        return ()
    generated, authored = _draft_rules(entity, mapping, relationships)
    return _deduplicate_names(generated, authored)


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
