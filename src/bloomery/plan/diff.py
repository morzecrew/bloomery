"""The spec differ: ``plan(old, new) -> Plan`` (RFC 0007).

A pure structural diff of two frozen :class:`~bloomery.ir.ProjectIR`s — no
external lineage, no I/O (D2). Subjects match by name; ``renamed_from``
bridges column identity across a rename (D3). Classification follows the
§5.2 precedence order: entity-level BREAKING first, then type (RFC 0004
lattice), then semantics (RESTATING, D4), then presence. Backfill scope and
downstream metric impact are computed from ``MetricIR.depends_on`` — the
same edges that drive the expand/contract refusal (D5), this stage's *only*
refusal: every other change, BREAKING included, is classified and returned.

Ambiguities RFC 0007 §10 leaves to the implementation, settled here:

- ``plan(ir, ir)`` is empty for *every* IR (D2, property-tested per
  RFC 0009), including one that still carries a ``renamed_from`` annotation:
  an annotation the old IR already carries on the same column is treated as
  applied, not stale. Staleness (``RenameTargetMissing``) fires whenever the
  annotation names a column absent from ``old`` that ``old`` does not already
  record — including ``old is None``.
- A changed metric definition (same name, different meaning) is RESTATING —
  nothing stored backfills, but every historical number the metric reported
  restates; a changed metric *grain* is BREAKING (it redefines the metric,
  mirroring D7 for entities).
- Entity ``partition_by``/audit changes and mart ``partition_by``/
  ``cost_hint`` changes are ADDITIVE metadata details: they change physical
  layout or checks, never what a stored number means.
- A changed source *relation* is RESTATING at the entity subject — every
  column's provenance changed while no shape did.
- ``required`` tightening (optional → required) is BREAKING per D7 but does
  not trigger the expand/contract refusal: it constrains writes, not the
  reads a metric performs; only type narrowing and drops do.

RFC 0016 §5.7 amends the stage with the data-quality surface. Its rules, and
the three questions §5.7 leaves open, settled here (each classification is
unit-tested per branch):

- **Rules and dedupe are RESTATING.** Adding, removing, or changing any
  quality rule, changing a disposition in **either** direction, and changing
  ``dedupe.keep``/``field``/``tie_break`` all change which rows the entity
  stores and what its history means — RESTATING, backfilling the entity.
- **Replay is narrower than backfill.** ``Plan.replay_scope`` names the
  entities whose ``<entity>__reject`` tables must be drained, and is populated
  only where a change can actually free rows — see :func:`_replay` for the
  three-line rule and why ``quarantine → fail`` and a narrowed bound are not
  among them. A scope naming entities with nothing to replay is a scope
  nobody can act on; worse, it feeds a replay runner rows the run will only
  quarantine (or now halt) on again.
- **A disposition is diffed as the author wrote it.** ``referential`` carries
  ``on_missing``, whose ``unknown_member`` value routes like ``flag`` but
  emits a different model, so the diff compares the authored label rather
  than the ``OnFail`` it collapses to (:func:`_disposition_label`).
- **``quarantine:`` retention is metadata; widening ``redact:`` is not.**
  Retention governs *deletion policy*, not any stored value → ADDITIVE.
  Narrowing ``redact:`` (redacting fewer paths) is ADDITIVE too — more payload
  is kept from now on, nothing stored changes. **Widening** it is RESTATING:
  it destroys payload going forward, so the reject table's ``raw`` means
  something different after the change than before. It carries **no** backfill
  and **no** replay, deliberately: neither can restore a payload the write
  path is now destroying, and pretending otherwise would send a caller to run
  jobs that cannot help. The two are **not** alternatives: a *swap* widens and
  narrows at once and reports as both, because the un-redaction — a path the
  reject table used to scrub and now stores — is a PII-governance fact of its
  own (§5.6, D59).
- **The reject table's own stored schema is diffed too** (D60):
  ``mapping_version:`` is a stored column of that schema and ``unmapped:``
  decides which bronze columns ``raw`` carries, so both change the emitted
  ``<entity>__reject`` model while changing no entity row. See
  :func:`_reject_schema_changes` for the classification and why it reports
  nothing on an entity with no ``quarantine:`` block.
- **``reconcile`` changes are RESTATING at the check, never at an entity.** A
  reconcile check materializes its own model over history (§5.3), so changing
  or removing one changes every historical row of that model — but it routes
  no row and invalidates no entity, so ``backfill_scope.entities`` stays
  empty. Adding one is ADDITIVE, not RESTATING: RFC 0007 D2's initial-deploy
  property (``plan(None, ir)`` is all-ADDITIVE) is normative, and an initial
  deploy adds every reconcile check there is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from bloomery.errors import ContractViolation, PlanError, RenameTargetMissing
from bloomery.ir import OnFail
from bloomery.plan.model import BackfillScope, Change, ChangeClass, Plan, ReplayScope
from bloomery.quality import disposition, payload_key
from bloomery.spec.quality import EXACT_DECIMAL
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
    assignable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bloomery.ir import (
        ColumnIR,
        DedupeIR,
        EntityIR,
        MartIR,
        MetricIR,
        ProjectIR,
        QualityRuleIR,
        QuarantineIR,
        ReconcileIR,
        TransformStepIR,
    )

__all__ = [
    "plan",
]

_SCALAR_NAMES: dict[type[LogicalType], str] = {
    StringType: "string",
    IntType: "int",
    BoolType: "bool",
    DateType: "date",
    TimestampType: "timestamp",
    VariantType: "variant",
}


def _render_type(logical: LogicalType) -> str:
    """The spec-layer spelling of a logical type — deterministic reprs for
    ``Change.old``/``Change.new``."""
    if isinstance(logical, DecimalType):
        return f"decimal({logical.precision},{logical.scale})"
    return _SCALAR_NAMES[type(logical)]


def _render_shape(column: ColumnIR) -> str:
    return f"{_render_type(column.type)}, {'required' if column.required else 'optional'}"


def _ref_names(column: ColumnIR) -> frozenset[str]:
    """Every name a metric may reference this column by: its own name and,
    when linked, its canonical name (``MetricIR.depends_on`` leaves are
    canonical names — RFC 0005 §5.3)."""
    names = {column.name}
    if column.canonical is not None:
        names.add(column.canonical)
    return frozenset(names)


@dataclass(slots=True)
class _Acc:
    """Mutable diff-walk accumulator; every set is consumed through
    ``sorted()`` or membership only, never iterated into output."""

    changes: list[Change] = field(default_factory=list[Change])
    backfill: set[str] = field(default_factory=set[str])
    #: Entities whose reject tables a relaxation frees rows from (RFC 0016 §5.7).
    replay: set[str] = field(default_factory=set[str])
    #: Names whose meaning/shape changed — the downstream-impact seeds.
    seeds: set[str] = field(default_factory=set[str])
    #: Dropped/narrowed fields: (display name, kind, reference names).
    contract_fields: list[tuple[str, str, frozenset[str]]] = field(
        default_factory=list[tuple[str, str, frozenset[str]]]
    )
    #: Measures removed from marts: (mart name, measure name).
    dropped_measures: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])


# ....................... #
# Entities and columns (§5.2 rules 1–4, §5.3)


def _entity_columns_refs(entity: EntityIR) -> frozenset[str]:
    names: set[str] = set()
    for column in entity.columns:
        names |= _ref_names(column)
    return frozenset(names)


def _added_entity(entity: EntityIR, acc: _Acc) -> None:
    for column in entity.columns:
        if column.renamed_from is not None:
            _raise_stale_rename(entity.name, column)
    acc.changes.append(
        Change(entity.name, f"entity:{entity.name}", ChangeClass.ADDITIVE, "entity added")
    )
    acc.changes.extend(
        Change(
            entity.name,
            f"field:{column.name}",
            ChangeClass.ADDITIVE,
            "field added",
            new=_render_shape(column),
        )
        for column in entity.columns
    )


def _dropped_entity(entity: EntityIR, acc: _Acc) -> None:
    acc.changes.append(
        Change(
            entity.name,
            f"entity:{entity.name}",
            ChangeClass.BREAKING,
            f"entity dropped ({len(entity.columns)} fields)",
        )
    )
    for column in entity.columns:
        acc.contract_fields.append((f"{entity.name}.{column.name}", "dropped", _ref_names(column)))
    acc.seeds |= _entity_columns_refs(entity)


def _entity_level_changes(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    """§5.2 rule 1: grain/key/scd/materialization redefine what a row *is* —
    BREAKING at the entity subject; column diffs are still reported."""
    subject = f"entity:{new_e.name}"
    breaking = (
        ("grain", old_e.grain, new_e.grain),
        ("key", ", ".join(old_e.key), ", ".join(new_e.key)),
        ("scd", str(old_e.scd), str(new_e.scd)),
        ("materialization", str(old_e.materialization), str(new_e.materialization)),
    )
    redefined = False
    for label, old_repr, new_repr in breaking:
        if old_repr != new_repr:
            redefined = True
            acc.changes.append(
                Change(
                    new_e.name,
                    subject,
                    ChangeClass.BREAKING,
                    f"{label} changed",
                    old=old_repr,
                    new=new_repr,
                )
            )
    if old_e.source.relation != new_e.source.relation:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.RESTATING,
                "source relation changed",
                old=old_e.source.relation,
                new=new_e.source.relation,
            )
        )
        acc.backfill.add(new_e.name)
        redefined = True
    if redefined:
        acc.seeds |= _entity_columns_refs(old_e) | _entity_columns_refs(new_e)
    if old_e.partition_by != new_e.partition_by:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.ADDITIVE,
                "partition_by changed (metadata only)",
            )
        )
    if old_e.audits != new_e.audits:
        acc.changes.append(
            Change(new_e.name, subject, ChangeClass.ADDITIVE, "audits changed (metadata only)")
        )


def _raise_stale_rename(entity_name: str, column: ColumnIR) -> None:
    msg = (
        f"field {column.name!r} declares renamed_from: {column.renamed_from!r}, but "
        f"{column.renamed_from!r} does not exist in the old spec — the annotation is "
        "stale (renamed_from is one-shot, RFC 0007 D3): drop it"
    )
    raise RenameTargetMissing(
        msg,
        source_path=f"entity_model: entities.{entity_name}.fields.{column.name}.renamed_from",
    )


def _rename_map(old_e: EntityIR, new_e: EntityIR) -> dict[str, str]:
    """Validated old-name → new-name bridges (§5.3). An annotation the old IR
    already carries on the same column is *applied*, not stale — this is what
    keeps ``plan(ir, ir)`` empty (D2) for an annotated IR."""
    old_cols = {column.name: column for column in old_e.columns}
    new_names = {column.name for column in new_e.columns}
    renames: dict[str, str] = {}
    for column in new_e.columns:
        source = column.renamed_from
        if source is None:
            continue
        source_path = f"entity_model: entities.{new_e.name}.fields.{column.name}.renamed_from"
        if source not in old_cols:
            prior = old_cols.get(column.name)
            if prior is not None and prior.renamed_from == source:
                continue  # already applied by a previous plan — identity, not a rename
            _raise_stale_rename(new_e.name, column)
        if source in new_names:
            msg = (
                f"field {column.name!r} declares renamed_from: {source!r} but both names "
                "are present in the new spec — a rename replaces the old name"
            )
            raise PlanError(msg, source_path=source_path)
        if column.name in old_cols:
            msg = (
                f"field {column.name!r} declares renamed_from: {source!r} but already "
                "existed in the old spec — the rename target is ambiguous"
            )
            raise PlanError(msg, source_path=source_path)
        renames[source] = column.name
    return renames


def _source_signature(
    entity: EntityIR, column: str
) -> tuple[tuple[str, tuple[TransformStepIR, ...]], ...]:
    """The column's lowering entries, name-independent: (source path, chain)."""
    return tuple(
        (entry.source_path, entry.transform)
        for entry in entity.source.fields
        if entry.target_field == column
    )


_SEMANTIC_FACETS = ("canonical", "recipe", "expression", "unit", "tax_basis", "source")


def _semantic_signature(
    entity: EntityIR, column: ColumnIR
) -> tuple[object, object, object, object, object, object]:
    """What the column *means* (D4), name and shape excluded: canonical link,
    recipe, lowered expression, catalog metadata, and source lowering."""
    return (
        column.canonical,
        column.recipe_id,
        column.expr.sql,
        column.unit,
        column.tax_basis,
        _source_signature(entity, column.name),
    )


def _added_column(entity_name: str, column: ColumnIR, acc: _Acc) -> None:
    if column.required:
        acc.changes.append(
            Change(
                entity_name,
                f"field:{column.name}",
                ChangeClass.BREAKING,
                "new field is required — historical rows cannot satisfy it; add it "
                "optional, backfill, then tighten (RFC 0007 D7)",
                new=_render_shape(column),
            )
        )
        return
    acc.changes.append(
        Change(
            entity_name,
            f"field:{column.name}",
            ChangeClass.ADDITIVE,
            "field added",
            new=_render_shape(column),
        )
    )


def _dropped_column(old_e: EntityIR, new_e: EntityIR, column: ColumnIR, acc: _Acc) -> None:
    old_names = {c.name for c in old_e.columns}
    same_typed = sorted(
        c.name for c in new_e.columns if c.name not in old_names and c.type == column.type
    )
    hint = ""
    if same_typed:
        hint = (
            f" (a same-typed field {same_typed[0]!r} was added — if this is a rename, "
            f"declare renamed_from: {column.name!r} instead)"
        )
    acc.changes.append(
        Change(
            new_e.name,
            f"field:{column.name}",
            ChangeClass.BREAKING,
            f"field dropped{hint}",
            old=_render_shape(column),
        )
    )
    acc.contract_fields.append((f"{new_e.name}.{column.name}", "dropped", _ref_names(column)))
    acc.seeds |= _ref_names(column)


def _column_pair(
    old_e: EntityIR,
    new_e: EntityIR,
    old_c: ColumnIR,
    new_c: ColumnIR,
    acc: _Acc,
    *,
    renamed_from: str | None,
) -> None:
    """Classify one matched column pair per the §5.2 precedence: type, then
    semantics, then metadata. A renamed pair additionally carries its RENAME
    record (identity preserved — no drop, no add, no backfill)."""
    subject = f"field:{new_c.name}"
    refs = _ref_names(old_c) | _ref_names(new_c)
    if renamed_from is not None:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.RENAME,
                f"renamed from {renamed_from!r}",
                old=renamed_from,
                new=new_c.name,
            )
        )
    if old_c.type != new_c.type or old_c.required != new_c.required:
        widened = assignable(old_c.type, new_c.type)
        tightened = new_c.required and not old_c.required
        if not widened or tightened:
            facets = [] if widened else ["type narrowed"]
            if tightened:
                facets.append("optional field became required")
            acc.changes.append(
                Change(
                    new_e.name,
                    subject,
                    ChangeClass.BREAKING,
                    " and ".join(facets),
                    old=_render_shape(old_c),
                    new=_render_shape(new_c),
                )
            )
            if not widened:
                acc.contract_fields.append((f"{new_e.name}.{new_c.name}", "narrowed", refs))
        else:
            detail = (
                "type widened" if old_c.type != new_c.type else "required field became optional"
            )
            acc.changes.append(
                Change(
                    new_e.name,
                    subject,
                    ChangeClass.WIDENING,
                    detail,
                    old=_render_shape(old_c),
                    new=_render_shape(new_c),
                )
            )
        acc.seeds |= refs
        return
    old_sig = _semantic_signature(old_e, old_c)
    new_sig = _semantic_signature(new_e, new_c)
    if old_sig != new_sig:
        facets = [
            facet
            for facet, old_part, new_part in zip(_SEMANTIC_FACETS, old_sig, new_sig, strict=True)
            if old_part != new_part
        ]
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.RESTATING,
                f"semantics changed ({', '.join(facets)})",
                old=old_c.recipe_id if old_c.recipe_id != new_c.recipe_id else None,
                new=new_c.recipe_id if old_c.recipe_id != new_c.recipe_id else None,
            )
        )
        acc.backfill.add(new_e.name)
        acc.seeds |= refs
        return
    if old_c.description != new_c.description:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.ADDITIVE,
                "description changed (metadata only)",
            )
        )


# ....................... #
# Data quality (RFC 0016 §5.7 — the RFC 0007 amendment). Read the module
# docstring's four bullets: this section implements exactly them.


def _rule_identity(rule: QualityRuleIR) -> tuple[str, str, str]:
    """What makes two rules *the same rule* across two IRs.

    Names are generated deterministically from the rule's kind, column and
    shape, so ``(kind, column, name)`` matches a rule to its successor across
    a settings change (``range min: 0`` → ``min: 5`` keeps its name) while a
    rule that changed shape (``min`` → ``max``) reads as one rule removed and
    another added — which is what it is.
    """
    return (rule.kind, rule.column or "", rule.name)


def _rule_settings(rule: QualityRuleIR) -> tuple[tuple[str, str], ...]:
    """The rule's params minus its disposition, which is reported separately.

    ``referential`` carries ``on_missing`` *as* a param, so leaving it in
    would report a disposition change twice, in two different vocabularies.
    """
    return tuple((name, value) for name, value in rule.params if name != "on_missing")


def _disposition_label(rule: QualityRuleIR) -> str:
    """What the author wrote, not what it collapses to (RFC 0016 D51).

    :func:`~bloomery.quality.disposition` answers a *routing* question — where
    does a failing row go — and correctly maps ``unknown_member`` onto
    ``FLAG``: the row is kept either way. But the diff asks a different
    question, and the collapse made ``unknown_member ⇄ flag`` invisible: zero
    changes, no backfill, ``has_changes`` False, while the emitted SQL gains or
    loses its ``'__unknown__'`` CASE and every stored fk restates. D11 wants
    disposition changes classified in **both** directions, so the label is the
    authored value.
    """
    if rule.on_fail is not None:
        return str(rule.on_fail)
    return dict(rule.params)["on_missing"]


#: Rule kinds whose params define an *ordered* admissible interval, so a
#: relaxation is readable from the params alone.
_BOUNDED_KINDS = frozenset({"length", "range"})
#: Rule kinds whose params define an admissible *set*, ditto by inclusion —
#: mapped to the param families that carry the **membership**.
#:
#: An allowlist, because the params carry more than membership: D62 gives an
#: ``in_set`` holding any int a ``numeric_NNNN`` marker per member, whose
#: *value* is the string ``"true"`` or ``"false"``. Flattening every param
#: value into one set therefore mixed those markers in with the literals, and
#: a set containing the literal ``"false"`` could be narrowed while the
#: surviving marker kept the flattened set identical — a tightening reported
#: as a relaxation, replaying rows that a narrowing cannot free. Naming the
#: families that mean membership is what keeps the next param family from
#: rejoining it silently; D62's claim that the markers are "read by the
#: ``in_set`` builder alone" was already false when it was written.
#:
#: ``in_enum``'s set is the chain's ``enum_map`` — spellings and targets both
#: reach the params (D49), and widening either one admits more raw values.
_MEMBERSHIP_FAMILIES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "in_enum": ("spelling", "value"),
        "in_set": ("value",),
    }
)
_SET_KINDS = frozenset(_MEMBERSHIP_FAMILIES)


def _members(kind: str, settings: tuple[tuple[str, str], ...]) -> frozenset[str]:
    """The values a set-kind rule admits, read off the membership families
    only — see :data:`_MEMBERSHIP_FAMILIES`. Param names are ``<family>_NNNN``
    (:func:`bloomery.quality.lower._indexed`), so the family is the name with
    its index suffix removed."""
    families = _MEMBERSHIP_FAMILIES[kind]
    return frozenset(value for name, value in settings if name.rsplit("_", 1)[0] in families)


def _admits_previously_rejected(old_rule: QualityRuleIR, new_rule: QualityRuleIR) -> bool | None:
    """Whether the settings change admits any value the old rule **rejected**:
    ``True`` some quarantined row can now come back, ``False`` none can,
    ``None`` undecidable.

    This is the question :func:`_replay` asks, and it is deliberately *not*
    "did the rule relax". The two agree on a pure widening and a pure
    narrowing and part company on a **swap**, which is both at once: `in_set`
    ``["a"] → ["b"]`` is not a superset of its old membership, so a
    relaxation test answers "no" — while every row quarantined on ``b`` is now
    admissible and, with no replay scope naming it, stays in the reject table
    until someone finds it by hand. Rows the change *newly* rejects are not
    this function's concern: they are in the entity, and the RESTATING
    classification already backfills them out.

    ``None`` is an honest answer, not a placeholder. A ``pattern``'s regex and
    an ``expression``'s SQL are not orderable — ``^A+$`` → ``^B+$`` admits an
    unknown set — and a ``coercible`` rule's params are the source expressions
    it reads, which say nothing about castability. The caller decides what to
    do with the three-valued answer; it is not this function's business to
    pretend.
    """
    old_settings, new_settings = _rule_settings(old_rule), _rule_settings(new_rule)
    if old_settings == new_settings:
        return False
    if old_rule.kind in _SET_KINDS:
        # The param *names* are positions in a sorted list, so a set that grew
        # or shrank changes them; only the membership families carry values.
        # Set difference, not a superset test: what matters is whether the new
        # membership contains anything the old one did not.
        gained = _members(new_rule.kind, new_settings) - _members(old_rule.kind, old_settings)
        return bool(gained)
    old_params, new_params = dict(old_settings), dict(new_settings)
    if old_rule.kind in _BOUNDED_KINDS and set(old_params) == set(new_params):
        return _admits_outside_bounds(old_params, new_params)
    return None


def _bound_value(text: str) -> Decimal | datetime | None:
    """One bound as a sortable value, or ``None`` if it is not one this module
    can order.

    A ``range`` bound is an exact decimal **or** an ISO date/timestamp (RFC
    0016 D57) — the string carrier exists for exactly that. Parsing every
    bound as ``Decimal`` therefore raised on every temporal one, which the
    caller read as "undecidable"; see :func:`_admits_outside_bounds` for what
    that cost. The numeric/temporal split is :data:`EXACT_DECIMAL`, the same
    grammar the spec layer validated the bound against, so the two cannot
    disagree about which carrier a bound is written in.

    Parsing only; no clock is read (RFC 0003).
    """
    if EXACT_DECIMAL.match(text):
        return Decimal(text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _compare_bounds(lhs_text: str, rhs_text: str) -> int | None:
    """The sign of ``lhs - rhs``, or ``None`` when the two are incomparable.

    Comparable means *like-typed*: two decimals, or two datetimes that are
    both aware or both naive. ISO text is not lexicographically ordered —
    ``2020-01-01T05:00:00+06:00`` sorts after ``2020-01-01T00:00:00Z`` as text
    and is the earlier instant — so the values are parsed rather than
    compared as strings; and Python refuses to compare an aware datetime with
    a naive one at all, which is a genuine ambiguity (the naive one has no
    instant until someone supplies a zone) and is reported rather than
    guessed.
    """
    lhs, rhs = _bound_value(lhs_text), _bound_value(rhs_text)
    if isinstance(lhs, Decimal) and isinstance(rhs, Decimal):
        return (lhs > rhs) - (lhs < rhs)
    if (
        isinstance(lhs, datetime)
        and isinstance(rhs, datetime)
        and (lhs.tzinfo is None) == (rhs.tzinfo is None)
    ):
        return (lhs > rhs) - (lhs < rhs)
    return None


def _admits_outside_bounds(old_params: dict[str, str], new_params: dict[str, str]) -> bool | None:
    """Whether a ``range``/``length`` interval now admits a value outside the
    old one — its floor dropped **or** its ceiling rose.

    ``or``, not ``and``. Requiring both meant a shifted interval reported
    nothing: ``0..10 → 5..20`` neither drops its floor nor keeps its ceiling
    fixed, so the conjunction was false and a row quarantined at 15 — squarely
    inside the new interval — was left stranded in the reject table. Both
    bound sets have the same keys here (the caller checks), so a missing bound
    on one side is a missing bound on the other and simply cannot move.

    A bound pair :func:`_compare_bounds` cannot order makes the whole answer
    ``None``, undecidable, rather than a guess about the end it could read.
    """
    moved: dict[str, int] = {}
    for bound, old_text in old_params.items():
        order = _compare_bounds(new_params[bound], old_text)
        if order is None:
            return None
        moved[bound] = order
    return moved.get("min", 0) < 0 or moved.get("max", 0) > 0


def _restates(acc: _Acc, entity: EntityIR, subject: str, detail: str, **reprs: str | None) -> None:
    """One RESTATING quality change: recompute the entity, and seed the
    downstream impact — every metric reading these columns reports different
    numbers after it."""
    acc.changes.append(
        Change(
            entity.name,
            subject,
            ChangeClass.RESTATING,
            detail,
            old=reprs.get("old"),
            new=reprs.get("new"),
        )
    )
    acc.backfill.add(entity.name)
    acc.seeds |= _entity_columns_refs(entity)


def _quality_changes(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    """Rule add / remove / change, and the replay scope a relaxation opens."""
    old_rules = {_rule_identity(rule): rule for rule in old_e.quality}
    new_rules = {_rule_identity(rule): rule for rule in new_e.quality}
    for identity in sorted(old_rules.keys() | new_rules.keys()):
        kind, _column, name = identity
        subject = f"quality:{name}"
        old_rule = old_rules.get(identity)
        new_rule = new_rules.get(identity)
        if old_rule is None and new_rule is not None:
            _restates(
                acc,
                new_e,
                subject,
                f"quality rule added ({kind})",
                new=_disposition_label(new_rule),
            )
            continue
        if old_rule is not None and new_rule is None:
            _restates(
                acc,
                new_e,
                subject,
                f"quality rule removed ({kind})",
                old=_disposition_label(old_rule),
            )
            _replay(old_rule, None, new_e, acc)
            continue
        if old_rule is None or new_rule is None:  # pragma: no cover — one map held it
            continue
        old_label, new_label = _disposition_label(old_rule), _disposition_label(new_rule)
        facets: list[str] = []
        if old_label != new_label:
            facets.append("disposition")
        if _rule_settings(old_rule) != _rule_settings(new_rule):
            facets.append("settings")
        if not facets:
            continue
        _restates(
            acc,
            new_e,
            subject,
            f"quality rule changed ({', '.join(facets)})",
            old=old_label,
            new=new_label,
        )
        _replay(old_rule, new_rule, new_e, acc)


def _replay(
    old_rule: QualityRuleIR, new_rule: QualityRuleIR | None, entity: EntityIR, acc: _Acc
) -> None:
    """Name the entity's reject table only when this change can let rows that
    are **sitting in it** back into the entity (RFC 0016 D52).

    Two facts bound the question. Rows are in the reject table on this rule's
    account only if it *used to* quarantine — so a rule that flagged, failed,
    or kept its rows via ``unknown_member`` opens no replay whatever happens to
    it. And a replay is worth running only if some quarantined row now comes
    out the other side:

    - the rule is **gone** — every row it diverted returns;
    - its disposition is now ``flag`` (``unknown_member`` included, D19: the
      row is kept with its fk rewritten) — §5.7's named case;
    - its parameters now **admit something the old ones rejected** — those
      rows return, whatever happens to the ones that still fail.

    That third clause is :func:`_admits_previously_rejected`, and the question
    it asks is narrower than "did the rule relax" on purpose (D81). A **swap**
    — ``in_set ["a"] → ["b"]``, or ``range 0..10 → 5..20`` — relaxes nothing
    by the superset/interval-widening reading, yet every row quarantined on
    ``b`` or at 15 is admissible under the new rule. Asking the relaxation
    question left exactly those rows in the reject table with no scope naming
    them, which is §5.6's "drop plus recoverability" failing in the one
    direction it must not.

    What is deliberately *not* a replay: ``quarantine → fail`` at unchanged
    parameters, and a **tightening**. Both leave every quarantined row still
    violating the rule, so a replay drains nothing — and under ``fail`` it is
    actively harmful, feeding a replay runner rows that trip the new blocking
    audit and halt the pipeline. Naming them was the shipped behaviour and it
    contradicted this module's own docstring.

    Where the answer is undecidable (an unorderable ``pattern`` or
    ``expression``), the replay **is** reported. That is the conservative
    direction on purpose: a scope with nothing to drain costs a no-op MERGE,
    while a missing one strands rows in quarantine until someone notices by
    hand — and §5.6's whole point is that quarantine is drop *plus*
    recoverability.
    """
    if disposition(old_rule) is not OnFail.QUARANTINE:
        return
    if new_rule is None or disposition(new_rule) is OnFail.FLAG:
        acc.replay.add(entity.name)
        return
    if _admits_previously_rejected(old_rule, new_rule) is not False:
        acc.replay.add(entity.name)


def _dedupe_repr(dedupe: DedupeIR | None) -> tuple[str, str, str]:
    if dedupe is None:
        return ("", "", "")
    return (dedupe.keep, dedupe.field, ", ".join(dedupe.tie_break))


def _dedupe_changes(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    """``keep``/``field``/``tie_break`` decide *which row wins* per key, so a
    change to any of them changes stored history (§5.7). Adding or removing
    the block is the same statement in the limit."""
    old_repr, new_repr = _dedupe_repr(old_e.dedupe), _dedupe_repr(new_e.dedupe)
    if old_repr == new_repr:
        return
    facets = [
        label
        for label, old_part, new_part in zip(
            ("keep", "field", "tie_break"), old_repr, new_repr, strict=True
        )
        if old_part != new_part
    ]
    _restates(
        acc,
        new_e,
        f"dedupe:{new_e.name}",
        f"dedupe changed ({', '.join(facets)})",
        old=" / ".join(old_repr) or None,
        new=" / ".join(new_repr) or None,
    )


def _quarantine_repr(quarantine: QuarantineIR | None) -> tuple[str, frozenset[str]]:
    if quarantine is None:
        return ("", frozenset())
    return (quarantine.retention, frozenset(quarantine.redact))


def _quarantine_changes(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    """Retention is deletion *policy* → ADDITIVE; a widened ``redact:``
    destroys payload going forward → RESTATING with no backfill and no replay
    (neither can restore what the write path now removes).

    Removing the block entirely is neither: it is BREAKING. Reading it as a
    retention edit to ``""`` called a deletion "policy only" — but the
    ``<entity>__reject`` model stops being emitted, and every unresolved row
    still sitting in it goes with it. RFC 0016 D2 buys quarantine over drop
    precisely for recoverability, and §5.6 names retention as the *only*
    deleter; a migration that deletes reject rows by removing the table is
    both of those undone, and the plan has to say so.
    """
    subject = f"quarantine:{new_e.name}"
    old_retention, old_redact = _quarantine_repr(old_e.quarantine)
    new_retention, new_redact = _quarantine_repr(new_e.quarantine)
    if old_e.quarantine is not None and new_e.quarantine is None:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.BREAKING,
                f"quarantine block removed — {new_e.name}__reject is no longer emitted and "
                "its unresolved rows are discarded by something that is not retention "
                "(RFC 0016 §5.6, D2). Drain the reject table via replay before applying",
                old=old_retention or None,
                new=None,
            )
        )
    elif old_retention != new_retention:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.ADDITIVE,
                "quarantine retention changed (policy only)",
                old=old_retention or None,
                new=new_retention or None,
            )
        )
    # Not mutually exclusive: a **swap** is a widening and a narrowing at once,
    # and an ``elif`` here dropped the un-redaction — the caller was told payload
    # is being destroyed but never that a previously-scrubbed path is now being
    # written into ``raw``, which is a PII-governance fact (§5.6, D59).
    widened = sorted(new_redact - old_redact)
    narrowed = sorted(old_redact - new_redact)
    if widened:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.RESTATING,
                f"quarantine redact widened ({', '.join(widened)}) — reject payloads written "
                "from now on carry less than the stored ones; no backfill or replay can "
                "restore a redacted path",
            )
        )
    if narrowed:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.ADDITIVE,
                f"quarantine redact narrowed ({', '.join(narrowed)}) — reject payloads written "
                "from now on carry a path the stored ones scrubbed",
            )
        )


def _raw_payload_columns(entity: EntityIR) -> frozenset[str]:
    """The bronze **columns** the reject table's ``raw`` carries, redaction
    aside — mapped and acknowledged-``unmapped:`` paths alike, keyed by
    top-level column exactly as ``_payload_columns`` keys them
    (:mod:`bloomery.emit.lowering`, §5.6).

    Keying by column rather than by path is what makes the comparison honest in
    both directions: ``$.a.b`` → ``$.a.c`` emits the identical model, and a path
    moving between ``fields:`` and ``unmapped:`` leaves ``raw`` untouched.
    Redaction is diffed by :func:`_quarantine_changes` and deliberately left out
    here, so a ``redact:`` edit is never reported twice.
    """
    paths = {field.source_path for field in entity.source.fields} | set(entity.source.unmapped)
    return frozenset(payload_key(path) for path in paths)


def _reject_schema_changes(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    """``mapping_version:`` and the ``raw`` payload's column set are stored
    facts of ``<entity>__reject`` (§5.6) that no other subject reports (D60).

    Both are gated on a reject table existing on **both** sides: without a
    ``quarantine:`` block no reject model is emitted, so neither field reaches
    an artifact and reporting it would be a change nobody can act on (the D52
    discipline). Adding or removing the block is already reported as its own
    retention change.

    ``mapping_version`` is ADDITIVE: it is a provenance stamp, and a stored
    reject row still correctly records the version that rejected it (the merge
    re-stamps only rows it re-observes, alongside ``last_seen`` — D36).

    The payload set mirrors ``redact:``: **widened** is ADDITIVE (more is kept
    from now on, nothing stored changes), **narrowed** is RESTATING with no
    backfill and no replay — reject rows written from now on carry less than the
    stored ones, and neither job can restore a column the write path no longer
    projects.
    """
    if old_e.quarantine is None or new_e.quarantine is None:
        return
    subject = f"quarantine:{new_e.name}"
    if old_e.source.mapping_version != new_e.source.mapping_version:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.ADDITIVE,
                "mapping_version changed (reject provenance stamp)",
                old=str(old_e.source.mapping_version),
                new=str(new_e.source.mapping_version),
            )
        )
    old_raw, new_raw = _raw_payload_columns(old_e), _raw_payload_columns(new_e)
    gained = sorted(new_raw - old_raw)
    lost = sorted(old_raw - new_raw)
    if gained:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.ADDITIVE,
                f"reject payload widened ({', '.join(gained)}) — raw carries bronze columns "
                "the stored reject rows do not",
            )
        )
    if lost:
        acc.changes.append(
            Change(
                new_e.name,
                subject,
                ChangeClass.RESTATING,
                f"reject payload narrowed ({', '.join(lost)}) — raw stops carrying bronze "
                "columns the stored reject rows have; no backfill or replay can restore a "
                "column the write path no longer projects",
            )
        )


def _reconcile_definition(check: ReconcileIR) -> tuple[str, str, str, str]:
    return (check.left, check.right, str(check.tolerance), str(check.on_fail))


def _diff_reconcile(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    """Reconcile checks are project-level: they relate two entities and belong
    to neither, so they never enter ``backfill_scope`` (§5.7)."""
    old_map = {check.name: check for check in old.reconcile} if old is not None else {}
    new_map = {check.name: check for check in new.reconcile}
    for name in sorted(old_map.keys() | new_map.keys()):
        subject = f"reconcile:{name}"
        if name not in old_map:
            acc.changes.append(Change(None, subject, ChangeClass.ADDITIVE, "reconcile check added"))
        elif name not in new_map:
            acc.changes.append(
                Change(None, subject, ChangeClass.RESTATING, "reconcile check removed")
            )
        elif _reconcile_definition(old_map[name]) != _reconcile_definition(new_map[name]):
            acc.changes.append(
                Change(
                    None,
                    subject,
                    ChangeClass.RESTATING,
                    "reconcile check changed — every row it recorded restates",
                )
            )


def _entity_pair(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    _entity_level_changes(old_e, new_e, acc)
    _quality_changes(old_e, new_e, acc)
    _dedupe_changes(old_e, new_e, acc)
    _quarantine_changes(old_e, new_e, acc)
    _reject_schema_changes(old_e, new_e, acc)
    renames = _rename_map(old_e, new_e)
    renamed_targets = set(renames.values())
    old_cols = {column.name: column for column in old_e.columns}
    new_cols = {column.name: column for column in new_e.columns}
    for name in sorted(old_cols.keys() | new_cols.keys()):
        if name in renames:
            _column_pair(
                old_e, new_e, old_cols[name], new_cols[renames[name]], acc, renamed_from=name
            )
        elif name in renamed_targets:
            continue  # handled alongside its rename source
        elif name not in new_cols:
            _dropped_column(old_e, new_e, old_cols[name], acc)
        elif name not in old_cols:
            _added_column(new_e.name, new_cols[name], acc)
        else:
            _column_pair(old_e, new_e, old_cols[name], new_cols[name], acc, renamed_from=None)


def _diff_entities(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    old_map = {entity.name: entity for entity in old.entities} if old is not None else {}
    new_map = {entity.name: entity for entity in new.entities}
    for name in sorted(old_map.keys() | new_map.keys()):
        if name not in old_map:
            _added_entity(new_map[name], acc)
        elif name not in new_map:
            _dropped_entity(old_map[name], acc)
        else:
            _entity_pair(old_map[name], new_map[name], acc)


# ....................... #
# Metrics


def _metric_definition(metric: MetricIR) -> tuple[object, ...]:
    return (
        metric.additivity,
        metric.agg,
        metric.expr.sql if metric.expr is not None else None,
        metric.ratio,
        metric.semi_additive,
        metric.depends_on,
    )


def _metric_pair(old_m: MetricIR, new_m: MetricIR, acc: _Acc) -> None:
    subject = f"metric:{new_m.name}"
    if old_m.grain != new_m.grain:
        acc.changes.append(
            Change(
                None,
                subject,
                ChangeClass.BREAKING,
                "grain changed",
                old=old_m.grain,
                new=new_m.grain,
            )
        )
        acc.seeds.add(new_m.name)
        return
    if _metric_definition(old_m) != _metric_definition(new_m):
        acc.changes.append(
            Change(
                None,
                subject,
                ChangeClass.RESTATING,
                "definition changed — every number this metric reported restates",
            )
        )
        acc.seeds.add(new_m.name)
        return
    if old_m.description != new_m.description:
        acc.changes.append(
            Change(None, subject, ChangeClass.ADDITIVE, "description changed (metadata only)")
        )


def _diff_metrics(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    old_map = {metric.name: metric for metric in old.metrics} if old is not None else {}
    new_map = {metric.name: metric for metric in new.metrics}
    unreachable = {entry.name: entry for entry in new.unreachable}
    for name in sorted(old_map.keys() | new_map.keys()):
        subject = f"metric:{name}"
        if name not in old_map:
            acc.changes.append(Change(None, subject, ChangeClass.ADDITIVE, "metric added"))
        elif name not in new_map:
            gone = unreachable.get(name)
            detail = (
                "metric removed"
                if gone is None
                else f"metric became unreachable (missing: {', '.join(gone.missing)})"
            )
            acc.changes.append(Change(None, subject, ChangeClass.BREAKING, detail))
            acc.seeds.add(name)
        else:
            _metric_pair(old_map[name], new_map[name], acc)


# ....................... #
# Marts (RFC 0007 §12 amended phasing; RFC 0010)


def _mart_pair(old_m: MartIR, new_m: MartIR, acc: _Acc) -> None:
    subject = f"mart:{new_m.name}"
    for label, old_repr, new_repr in (
        ("grain", old_m.grain, new_m.grain),
        ("base", old_m.base, new_m.base),
        ("materialization", str(old_m.materialization), str(new_m.materialization)),
    ):
        if old_repr != new_repr:
            acc.changes.append(
                Change(
                    None,
                    subject,
                    ChangeClass.BREAKING,
                    f"{label} changed",
                    old=old_repr,
                    new=new_repr,
                )
            )
    old_cols = {column.name: column for column in old_m.columns}
    new_cols = {column.name: column for column in new_m.columns}
    for name in sorted(old_cols.keys() | new_cols.keys()):
        if name not in old_cols:
            acc.changes.append(
                Change(None, subject, ChangeClass.ADDITIVE, f"flattened column {name!r} added")
            )
        elif name not in new_cols:
            acc.changes.append(
                Change(None, subject, ChangeClass.BREAKING, f"flattened column {name!r} dropped")
            )
        elif old_cols[name] != new_cols[name]:
            acc.changes.append(
                Change(None, subject, ChangeClass.BREAKING, f"flattened column {name!r} changed")
            )
    old_measures, new_measures = set(old_m.measures), set(new_m.measures)
    acc.changes.extend(
        Change(None, subject, ChangeClass.ADDITIVE, f"measure {name!r} added")
        for name in sorted(new_measures - old_measures)
    )
    for name in sorted(old_measures - new_measures):
        acc.changes.append(Change(None, subject, ChangeClass.BREAKING, f"measure {name!r} removed"))
        acc.dropped_measures.append((new_m.name, name))
    if old_m.dimensions != new_m.dimensions:
        acc.changes.append(Change(None, subject, ChangeClass.BREAKING, "dimensions changed"))
    if old_m.joins != new_m.joins:
        acc.changes.append(Change(None, subject, ChangeClass.BREAKING, "joins changed"))
    if old_m.partition_by != new_m.partition_by:
        acc.changes.append(
            Change(None, subject, ChangeClass.ADDITIVE, "partition_by changed (metadata only)")
        )
    if old_m.cost_hint != new_m.cost_hint:
        acc.changes.append(
            Change(
                None,
                subject,
                ChangeClass.ADDITIVE,
                "cost_hint changed (metadata only)",
                old=str(old_m.cost_hint),
                new=str(new_m.cost_hint),
            )
        )


def _diff_marts(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    old_map = {mart.name: mart for mart in old.marts} if old is not None else {}
    new_map = {mart.name: mart for mart in new.marts}
    for name in sorted(old_map.keys() | new_map.keys()):
        subject = f"mart:{name}"
        if name not in old_map:
            acc.changes.append(Change(None, subject, ChangeClass.ADDITIVE, "mart added"))
        elif name not in new_map:
            acc.changes.append(Change(None, subject, ChangeClass.BREAKING, "mart dropped"))
            acc.dropped_measures.extend((name, measure) for measure in old_map[name].measures)
        else:
            _mart_pair(old_map[name], new_map[name], acc)


# ....................... #
# Relationships and the date dimension


def _diff_relationships(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    old_map = {rel.name: rel for rel in old.relationships} if old is not None else {}
    new_map = {rel.name: rel for rel in new.relationships}
    for name in sorted(old_map.keys() | new_map.keys()):
        subject = f"relationship:{name}"
        if name not in old_map:
            acc.changes.append(Change(None, subject, ChangeClass.ADDITIVE, "relationship added"))
        elif name not in new_map:
            acc.changes.append(Change(None, subject, ChangeClass.BREAKING, "relationship dropped"))
        elif old_map[name] != new_map[name]:
            acc.changes.append(
                Change(
                    None,
                    subject,
                    ChangeClass.BREAKING,
                    "relationship redefined — join semantics changed",
                )
            )


def _diff_date_dimension(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    old_d = old.date_dimension if old is not None else None
    new_d = new.date_dimension
    if new_d is None:
        if old_d is not None:
            acc.changes.append(
                Change(
                    None,
                    f"date_dimension:{old_d.name}",
                    ChangeClass.BREAKING,
                    "date dimension removed",
                )
            )
        return
    if old_d is None:
        acc.changes.append(
            Change(
                None, f"date_dimension:{new_d.name}", ChangeClass.ADDITIVE, "date dimension added"
            )
        )
        return
    if old_d == new_d:
        return
    bounds_only = (
        old_d.name == new_d.name
        and old_d.grain == new_d.grain
        and new_d.start_year <= old_d.start_year
        and new_d.end_year >= old_d.end_year
    )
    change_class = ChangeClass.ADDITIVE if bounds_only else ChangeClass.BREAKING
    detail = "date dimension bounds extended" if bounds_only else "date dimension redefined"
    acc.changes.append(
        Change(
            None,
            f"date_dimension:{new_d.name}",
            change_class,
            detail,
            old=f"{old_d.start_year}-{old_d.end_year}",
            new=f"{new_d.start_year}-{new_d.end_year}",
        )
    )


# ....................... #
# Dependency edges: downstream impact and expand/contract (D5, D6)


def _dependency_closure(
    name: str, by_name: dict[str, MetricIR], memo: dict[str, frozenset[str]]
) -> frozenset[str]:
    """Every name reachable from a metric through ``depends_on``, itself
    included — leaves are canonical field names, inner nodes metric names."""
    cached = memo.get(name)
    if cached is not None:
        return cached
    memo[name] = frozenset((name,))  # cycle guard; resolution guarantees a DAG
    names = {name}
    metric = by_name.get(name)
    if metric is not None:
        for dependency in metric.depends_on:
            names |= _dependency_closure(dependency, by_name, memo)
    closure = frozenset(names)
    memo[name] = closure
    return closure


def _downstream_impact(new: ProjectIR, seeds: set[str]) -> tuple[str, ...]:
    if not seeds:
        return ()
    by_name = {metric.name: metric for metric in new.metrics}
    memo: dict[str, frozenset[str]] = {}
    return tuple(
        metric.name
        for metric in new.metrics  # already sorted by name (RFC 0003 §5.3)
        if _dependency_closure(metric.name, by_name, memo) & seeds
    )


def _enforce_contract(old: ProjectIR | None, new: ProjectIR, acc: _Acc) -> None:
    """RFC 0007 D5 — the stage's only refusal: a dropped or narrowed field
    still referenced by a metric reachable in ``new``, or by an old-reachable
    metric that vanished in the same plan (deprecation must land first)."""
    problems: list[str] = []
    if acc.contract_fields and old is not None:
        old_by_name = {metric.name: metric for metric in old.metrics}
        new_by_name = {metric.name: metric for metric in new.metrics}
        vanished = tuple(m for m in old.metrics if m.name not in new_by_name)
        old_memo: dict[str, frozenset[str]] = {}
        new_memo: dict[str, frozenset[str]] = {}
        for display, kind, refs in sorted(acc.contract_fields):
            live = {
                m.name
                for m in new.metrics
                if _dependency_closure(m.name, new_by_name, new_memo) & refs
            }
            gone = {
                m.name
                for m in vanished
                if _dependency_closure(m.name, old_by_name, old_memo) & refs
            }
            referencing = sorted(live | gone)
            if referencing:
                problems.append(
                    f"field {display!r} is {kind} but still referenced by metric(s) "
                    f"{', '.join(referencing)} — expand/contract: land the metric's removal "
                    "(deprecation) in a prior version, then drop or narrow the field"
                )
    if acc.dropped_measures:
        new_metric_names = {metric.name for metric in new.metrics}
        served = {measure for mart in new.marts for measure in mart.measures}
        for mart_name, measure in sorted(set(acc.dropped_measures)):
            if measure in new_metric_names and measure not in served:
                problems.append(
                    f"mart {mart_name!r} drops measure {measure!r} while the metric is still "
                    "reachable and no other mart serves it — remove or deprecate the metric "
                    "in a prior version"
                )
    if problems:
        raise ContractViolation(
            "expand/contract violation (RFC 0007 D5):\n  - " + "\n  - ".join(problems)
        )


# ....................... #
# The public diff


def _sort_key(change: Change) -> tuple[str, str, str, str, str, str]:
    return (
        change.entity or "",
        change.subject,
        change.change_class,
        change.detail,
        change.old or "",
        change.new or "",
    )


def plan(old: ProjectIR | None, new: ProjectIR) -> Plan:
    """Diff two project IRs into a classified :class:`Plan` (RFC 0007).

    ``plan(None, new)`` is the initial deploy — everything ADDITIVE with an
    empty backfill *and* replay scope; ``plan(ir, ir)`` is the empty plan
    (D2). Data-quality changes classify per RFC 0016 §5.7 and populate
    :attr:`Plan.replay_scope` where a relaxation frees quarantined rows a
    backfill cannot reach (see the module docstring). Raises
    :class:`RenameTargetMissing` on a stale ``renamed_from`` annotation (D3)
    and :class:`ContractViolation` on an expand/contract breach (D5) — every
    other change, BREAKING included, is classified and returned.
    """
    if old is not None and old.bloomery_ir_version != new.bloomery_ir_version:
        msg = (
            f"cannot diff IR version {old.bloomery_ir_version} against "
            f"{new.bloomery_ir_version} — recompile both sides with one compiler"
        )
        raise PlanError(msg)
    acc = _Acc()
    _diff_entities(old, new, acc)
    _diff_metrics(old, new, acc)
    _diff_marts(old, new, acc)
    _diff_relationships(old, new, acc)
    _diff_date_dimension(old, new, acc)
    _diff_reconcile(old, new, acc)
    _enforce_contract(old, new, acc)
    changes = tuple(sorted(acc.changes, key=_sort_key))
    return Plan(
        changes=changes,
        backfill_scope=BackfillScope(
            entities=tuple(sorted(acc.backfill)),
            restates_history=any(
                change.change_class is ChangeClass.RESTATING for change in changes
            ),
        ),
        downstream_impact=_downstream_impact(new, acc.seeds),
        replay_scope=ReplayScope(entities=tuple(sorted(acc.replay))),
    )
