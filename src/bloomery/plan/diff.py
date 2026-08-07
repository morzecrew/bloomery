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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bloomery.errors import ContractViolation, PlanError, RenameTargetMissing
from bloomery.plan.model import BackfillScope, Change, ChangeClass, Plan
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
    from bloomery.ir import (
        ColumnIR,
        EntityIR,
        MartIR,
        MetricIR,
        ProjectIR,
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


def _entity_pair(old_e: EntityIR, new_e: EntityIR, acc: _Acc) -> None:
    _entity_level_changes(old_e, new_e, acc)
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
    empty backfill scope; ``plan(ir, ir)`` is the empty plan (D2). Raises
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
    )
