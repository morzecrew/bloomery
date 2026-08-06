"""The IR builder: ``build_project_ir(project, catalog) -> ProjectIR``.

Runs resolution (RFC 0005), then the batched typecheck (RFC 0004), then
lowers mappings and recipes into :class:`~bloomery.ir.ColumnIR` expressions —
transform chains applied via the registry builders, recipe exprs parsed via
SQLGlot with aliases substituted by their source-column extractions, all held
as canonical dialect-neutral :class:`~bloomery.ir.SqlExpr` text (RFC 0003 D2).

Lowering rules pinned here:

- A JSONPath-lite ``$.a.b`` lowers to column ``a`` of the bronze relation,
  with deeper segments extracted via ``JSON_EXTRACT_SCALAR`` — extraction
  yields text, so non-empty chains start at ``string`` (RFC 0004 §5.4).
- A chain-less mapping asserts the declared type at extraction: it lowers to
  a cast of the raw extraction to the declared logical type.
- A chain whose terminal type is assignable but not equal to the declared
  type gains a final cast, so the emitted column always has the declared type.
- Materialization defaults (RFC 0002 D7): explicit wins; else
  ``incremental_by_partition`` when ``partition_by`` is present, else ``full``.

Marts are not lowered here — mart flattening is the M5 milestone (RFC 0010);
``ProjectIR.marts`` stays empty. Audits stay empty too: M4 wires ``assert:``
clauses into real audits. The guardrail stage (RFC 0006, M4) slots in at the
marked seam below, between typecheck and lowering.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one

from bloomery.errors import ResolutionError
from bloomery.ir import (
    Additivity,
    Cardinality,
    ColumnIR,
    DimensionRef,
    EntityIR,
    Materialization,
    MetricIR,
    PartitionSpec,
    ProjectIR,
    Ratio,
    RelationshipIR,
    SCDKind,
    SemiAdditivePolicy,
    SemiAdditiveRule,
    SourceFieldIR,
    SourceIR,
    SqlExpr,
    TaxBasis,
    TransformStepIR,
    Unit,
)
from bloomery.resolve.metrics import effective_metrics
from bloomery.resolve.recipes import resolve_recipe
from bloomery.resolve.refs import mapping_doc
from bloomery.resolve.resolution import resolve
from bloomery.spec.common import PARTITION_SPEC_PATTERN
from bloomery.spec.mapping import RecipeFieldMapping
from bloomery.transforms import registry
from bloomery.typing import (
    BoolType,
    ChainCheck,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
    parse_type,
    typecheck_chain,
    typecheck_chains,
)

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.entity import Entity, Field
    from bloomery.spec.mapping import Mapping, TransformStep
    from bloomery.spec.project import Project
    from bloomery.transforms import Registry

__all__ = [
    "build_project_ir",
]

_PARTITION_RE = re.compile(PARTITION_SPEC_PATTERN)

_GENERIC_TYPES: dict[type[LogicalType], str] = {
    StringType: "TEXT",
    IntType: "BIGINT",
    BoolType: "BOOLEAN",
    DateType: "DATE",
    TimestampType: "TIMESTAMP",
    VariantType: "JSON",
}


def _generic_type(t: LogicalType) -> exp.DataType:
    """The dialect-neutral SQLGlot type for a logical type. Physical DDL
    types are the dialect port's job (RFC 0008); this cast is rendered per
    dialect at emit from the neutral AST."""
    if isinstance(t, DecimalType):
        return exp.DataType.build(f"DECIMAL({t.precision}, {t.scale})")
    return exp.DataType.build(_GENERIC_TYPES[type(t)])


def _canon(node: exp.Expression) -> SqlExpr:
    """Canonical dialect-neutral text (RFC 0003 §5.2)."""
    return SqlExpr(node.sql(pretty=False))


def _extraction(path: str) -> exp.Expression:
    """Lower a JSONPath-lite ``$.a.b`` against the bronze relation: the first
    segment is the physical column, deeper segments are JSON extraction."""
    segments = path.removeprefix("$.").split(".")
    column = exp.column(segments[0])
    if len(segments) == 1:
        return column
    remainder = "$." + ".".join(segments[1:])
    return exp.JSONExtractScalar(this=column, expression=exp.Literal.string(remainder))


def _field_type(entity_name: str, field_name: str, field: Field) -> LogicalType:
    path = f"entity_model: entities.{entity_name}.fields.{field_name}.type"
    return parse_type(field.type, source_path=path)


def _lower_chain(
    path: str,
    steps: tuple[TransformStep, ...],
    declared: LogicalType,
    reg: Registry,
    *,
    source_path: str,
) -> exp.Expression:
    node = _extraction(path)
    if not steps:
        return exp.cast(node, _generic_type(declared))
    for step in steps:
        node = reg[step.name].builder(node, *step.args)
    terminal = typecheck_chain(StringType(), steps, declared, registry=reg, source_path=source_path)
    if terminal != declared:
        node = exp.cast(node, _generic_type(declared))
    return node


def _typecheck_project(project: Project, reg: Registry) -> None:
    """Batch-check every non-empty transform chain (RFC 0004 §5.4). Empty
    chains are declared-type casts at extraction and carry no chain to check."""
    checks: list[ChainCheck] = []
    for mapping in project.mappings:
        doc = mapping_doc(mapping)
        entity = project.entity_model.entities[mapping.target]
        for field_name in sorted(mapping.key):
            steps = mapping.key[field_name].transform
            if steps:
                declared = _field_type(mapping.target, field_name, entity.fields[field_name])
                checks.append(ChainCheck(StringType(), steps, declared, f"{doc}: key.{field_name}"))
        for field_name in sorted(mapping.fields):
            field_mapping = mapping.fields[field_name]
            if isinstance(field_mapping, RecipeFieldMapping) or not field_mapping.transform:
                continue
            declared = _field_type(mapping.target, field_name, entity.fields[field_name])
            checks.append(
                ChainCheck(
                    StringType(),
                    field_mapping.transform,
                    declared,
                    f"{doc}: fields.{field_name}",
                )
            )
    typecheck_chains(checks, registry=reg)


def _catalog_metadata(field: Field, catalog: Catalog | None) -> tuple[Unit | None, TaxBasis | None]:
    if field.canonical is None or catalog is None:
        return None, None
    canonical_field = catalog.canonical_fields[field.canonical]
    unit = Unit(canonical_field.unit) if canonical_field.unit is not None else None
    tax = TaxBasis(canonical_field.tax_basis) if canonical_field.tax_basis is not None else None
    return unit, tax


def _column_ir(
    name: str,
    field: Field,
    declared: LogicalType,
    expr: exp.Expression,
    catalog: Catalog | None,
    *,
    recipe_id: str | None = None,
) -> ColumnIR:
    unit, tax_basis = _catalog_metadata(field, catalog)
    return ColumnIR(
        name=name,
        type=declared,
        canonical=field.canonical,
        unit=unit,
        tax_basis=tax_basis,
        expr=_canon(expr),
        recipe_id=recipe_id,
        renamed_from=field.renamed_from,
        required=field.required,
    )


def _recipe_expr(
    field_mapping: RecipeFieldMapping,
    declared: LogicalType,
    mapping: Mapping,
    field_name: str,
    project: Project,
    catalog: Catalog | None,
) -> tuple[exp.Expression, str]:
    recipe = resolve_recipe(mapping, field_name, field_mapping, project, catalog)
    if recipe.expr is None:
        # Identity recipe: the single required alias, cast to the declared type.
        body = _extraction(field_mapping.from_[recipe.requires[0]])
    else:
        parsed = parse_one(recipe.expr)

        def substitute(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Column) and not node.table and node.name in field_mapping.from_:
                return _extraction(field_mapping.from_[node.name])
            return node

        body = parsed.transform(substitute)
    return exp.cast(body, _generic_type(declared)), recipe.id


def _partition_specs(entries: tuple[str, ...]) -> tuple[PartitionSpec, ...]:
    specs: list[PartitionSpec] = []
    for entry in entries:
        match = _PARTITION_RE.match(entry)
        if match is None or match.group(2) is None:  # bare column form
            specs.append(PartitionSpec(transform=None, column=entry))
        else:
            specs.append(PartitionSpec(transform=match.group(1), column=match.group(2)))
    return tuple(specs)


def _materialization(entity: Entity) -> Materialization:
    """RFC 0002 D7: declared wins; the derived default is only the default."""
    if entity.materialization is not None:
        return Materialization(entity.materialization)
    if entity.partition_by:
        return Materialization.INCREMENTAL_BY_PARTITION
    return Materialization.FULL


def _build_entity(
    entity_name: str,
    entity: Entity,
    mapping: Mapping,
    project: Project,
    catalog: Catalog | None,
    reg: Registry,
) -> EntityIR:
    doc = mapping_doc(mapping)
    columns: list[ColumnIR] = []
    source_fields: list[SourceFieldIR] = []

    for field_name in sorted(mapping.key):
        key_field = mapping.key[field_name]
        field = entity.fields[field_name]
        declared = _field_type(entity_name, field_name, field)
        expr = _lower_chain(
            key_field.from_,
            key_field.transform,
            declared,
            reg,
            source_path=f"{doc}: key.{field_name}",
        )
        columns.append(_column_ir(field_name, field, declared, expr, catalog))
        source_fields.append(
            SourceFieldIR(
                target_field=field_name,
                source_path=key_field.from_,
                transform=tuple(
                    TransformStepIR(name=s.name, args=s.args) for s in key_field.transform
                ),
            )
        )

    for field_name in sorted(mapping.fields):
        field_mapping = mapping.fields[field_name]
        field = entity.fields[field_name]
        declared = _field_type(entity_name, field_name, field)
        if isinstance(field_mapping, RecipeFieldMapping):
            expr, recipe_id = _recipe_expr(
                field_mapping, declared, mapping, field_name, project, catalog
            )
            columns.append(
                _column_ir(field_name, field, declared, expr, catalog, recipe_id=recipe_id)
            )
            source_fields.extend(
                SourceFieldIR(target_field=field_name, source_path=path)
                for _alias, path in sorted(field_mapping.from_.items())
            )
        else:
            expr = _lower_chain(
                field_mapping.from_,
                field_mapping.transform,
                declared,
                reg,
                source_path=f"{doc}: fields.{field_name}",
            )
            columns.append(_column_ir(field_name, field, declared, expr, catalog))
            source_fields.append(
                SourceFieldIR(
                    target_field=field_name,
                    source_path=field_mapping.from_,
                    transform=tuple(
                        TransformStepIR(name=s.name, args=s.args) for s in field_mapping.transform
                    ),
                )
            )

    return EntityIR(
        name=entity_name,
        grain=entity.grain,
        key=entity.key,
        scd=SCDKind(entity.scd),
        materialization=_materialization(entity),
        partition_by=_partition_specs(entity.partition_by),
        columns=tuple(sorted(columns, key=lambda c: c.name)),
        source=SourceIR(
            relation=mapping.source,
            fields=tuple(sorted(source_fields, key=lambda f: (f.target_field, f.source_path))),
        ),
        audits=(),  # M4 wires assert: clauses into real audits (RFC 0006 D8)
    )


def _build_entities(
    project: Project, catalog: Catalog | None, reg: Registry
) -> tuple[EntityIR, ...]:
    by_target: dict[str, list[Mapping]] = {}
    for mapping in project.mappings:
        by_target.setdefault(mapping.target, []).append(mapping)
    entities: list[EntityIR] = []
    for entity_name in sorted(by_target):
        mappings = by_target[entity_name]
        if len(mappings) > 1:
            msg = (
                f"{len(mappings)} mappings target entity {entity_name!r}; deterministic "
                "union merge lands with the multi_source milestone (RFC 0009 D4)"
            )
            raise ResolutionError(msg, source_path=f"{mapping_doc(mappings[1])}: target")
        entity = project.entity_model.entities[entity_name]
        entities.append(_build_entity(entity_name, entity, mappings[0], project, catalog, reg))
    return tuple(entities)  # sorted: by_target iterated in sorted order


def _build_metrics(
    project: Project, catalog: Catalog | None, reachable: tuple[str, ...]
) -> tuple[MetricIR, ...]:
    reachable_set = set(reachable)
    built: list[MetricIR] = []
    for metric in effective_metrics(project, catalog):  # sorted by name
        if metric.name not in reachable_set:
            continue
        semi_additive = None
        if metric.semi_additive is not None:
            semi_additive = SemiAdditivePolicy(
                over=DimensionRef(dimension=metric.semi_additive.over),
                rule=SemiAdditiveRule(metric.semi_additive.rule),
            )
        built.append(
            MetricIR(
                name=metric.name,
                grain=metric.grain or "",
                additivity=Additivity(metric.additivity),
                agg=metric.agg,
                expr=(
                    # ``parse_one`` is annotated with the ``Expr`` base, but
                    # every node it returns is an ``Expression`` (cf. ir.nodes).
                    _canon(cast("exp.Expression", parse_one(metric.expr)))
                    if metric.expr is not None
                    else None
                ),
                ratio=(
                    Ratio(numerator=metric.ratio.numerator, denominator=metric.ratio.denominator)
                    if metric.ratio is not None
                    else None
                ),
                semi_additive=semi_additive,
                depends_on=tuple(sorted({*metric.requires, *metric.requires_metrics})),
            )
        )
    return tuple(built)


def _build_relationships(project: Project) -> tuple[RelationshipIR, ...]:
    return tuple(
        sorted(
            (
                RelationshipIR(
                    name=rel.name,
                    from_entity=rel.from_,
                    to_entity=rel.to,
                    via=tuple(sorted(rel.via.items())),
                    cardinality=Cardinality(rel.cardinality),
                )
                for rel in project.entity_model.relationships
            ),
            key=lambda r: r.name,
        )
    )


def build_project_ir(project: Project, catalog: Catalog | None = None) -> ProjectIR:
    """Compile parsed specs into the frozen, fingerprintable IR (RFC 0003).

    Pure function: resolution (RFC 0005) and the batched typecheck (RFC 0004)
    run first, so lowering only ever sees a reference-clean, well-typed
    project. Marts are not lowered until M5 (RFC 0010); audits until M4.
    """
    resolution = resolve(project, catalog)
    reg = registry()
    _typecheck_project(project, reg)

    # ── M4 guardrail seam ──────────────────────────────────────────────
    # The guardrail stage (RFC 0006) runs here, over (project, catalog,
    # resolution), refusing before any artifact-bound lowering happens.

    return ProjectIR(
        bloomery_ir_version=1,
        entities=_build_entities(project, catalog, reg),
        metrics=_build_metrics(project, catalog, resolution.reachable_metrics),
        unreachable=resolution.unreachable_metrics,
        relationships=_build_relationships(project),
        marts=(),  # mart flattening is M5 (RFC 0010)
    )
