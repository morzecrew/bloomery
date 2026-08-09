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

Marts lower here through the pure flattener (``bloomery/marts/``, RFC 0010
D6): the wide schemas land on ``ProjectIR.marts`` sorted by name, and the
catalog's date dimension — when declared — lowers to
``ProjectIR.date_dimension`` (RFC 0008 D13). The guardrail stage (RFC 0006)
runs over the draft IR at the seam below — after typecheck and lowering,
before the IR leaves the builder — refusing before any artifact is emitted
(mart-level violations included) and amending the draft with path-conflict
shadows and lowered ``assert:`` audits.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.errors import ResolutionError, StepDeterminismError, StepError
from bloomery.guardrails import check_guardrails
from bloomery.ir import (
    Additivity,
    Cardinality,
    ColumnIR,
    DateDimensionIR,
    DimensionRef,
    EntityIR,
    Materialization,
    MetricIR,
    ProjectIR,
    Ratio,
    RelationshipIR,
    SCDKind,
    SemiAdditivePolicy,
    SemiAdditiveRule,
    SourceFieldIR,
    SourceIR,
    TaxBasis,
    TransformStepIR,
    Unit,
    canon,
    extraction,
    generic_type,
    partition_specs,
)
from bloomery.marts import lower_marts
from bloomery.quality import (
    attach_quality_mart,
    lower_dedupe,
    lower_quality,
    lower_quarantine,
    lower_reconcile,
    opts_in,
)
from bloomery.resolve.metrics import effective_metrics
from bloomery.resolve.recipes import resolve_recipe
from bloomery.resolve.refs import mapping_doc
from bloomery.resolve.resolution import resolve
from bloomery.resolve.steps import lower_steps, step_entities
from bloomery.spec.mapping import ALIAS_BOUND, MacroFieldMapping, RecipeFieldMapping
from bloomery.steps import EMPTY_REGISTRY
from bloomery.steps.splice import parameter_literal, placeholders, splice
from bloomery.transforms import registry
from bloomery.typing import (
    ChainCheck,
    LogicalType,
    StringType,
    parse_type,
    typecheck_chain,
    typecheck_chains,
)

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.entity import Entity, Field
    from bloomery.spec.mapping import Mapping, TransformStep
    from bloomery.spec.project import Project
    from bloomery.steps import StepRegistry
    from bloomery.transforms import Registry

__all__ = [
    "build_project_ir",
]


def _field_type(entity_name: str, field_name: str, field: Field) -> LogicalType:
    path = f"entity_model: entities.{entity_name}.fields.{field_name}.type"
    return parse_type(field.type, source_path=path)


def _identity_shape(node: Expression) -> Expression:
    """The shipped produce-or-raise lowering: no marker, nothing rewritten."""
    return node


def _try_cast_shape(node: Expression) -> Expression:
    """Rewrite every ``CAST`` in a lowered chain as ``TRY_CAST`` (RFC 0016
    §5.2, D3).

    Stage 2 of the fixed pipeline order changes from produce-or-raise to
    "produce a value **or** a coercion-failure marker", and the marker is the
    NULL a failed ``TRY_CAST`` yields. It is applied to the whole chain, not
    only its terminal cast: an inner ``to_int`` that raises would abort the
    run before the outer cast could mark anything, which is precisely the
    behaviour the implicit ``coercible`` rule replaces.

    Only entities that opt into the quality system are shaped this way (see
    :func:`bloomery.quality.opts_in`); everything else keeps the shipped
    produce-or-raise lowering.
    """

    def shaped(child: Expression) -> Expression:
        if type(child) is exp.Cast:
            return exp.TryCast(this=child.this, to=child.to)
        return child

    return node.transform(shaped)


def _lower_chain(
    path: str,
    steps: tuple[TransformStep, ...],
    declared: LogicalType,
    reg: Registry,
    *,
    source_path: str,
) -> Expression:
    node = extraction(path)
    if not steps:
        return exp.cast(node, generic_type(declared))
    for step in steps:
        node = reg[step.name].builder(node, *step.args)
    terminal = typecheck_chain(StringType(), steps, declared, registry=reg, source_path=source_path)
    if terminal != declared:
        node = exp.cast(node, generic_type(declared))
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
            if isinstance(field_mapping, ALIAS_BOUND) or not field_mapping.transform:
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


def _catalog_metadata(
    field: Field, catalog: Catalog | None
) -> tuple[Unit | None, TaxBasis | None, str | None]:
    if field.canonical is None or catalog is None:
        return None, None, None
    canonical_field = catalog.canonical_fields[field.canonical]
    unit = Unit(canonical_field.unit) if canonical_field.unit is not None else None
    tax = TaxBasis(canonical_field.tax_basis) if canonical_field.tax_basis is not None else None
    return unit, tax, canonical_field.description


def _column_ir(
    name: str,
    field: Field,
    declared: LogicalType,
    expr: Expression,
    catalog: Catalog | None,
    *,
    recipe_id: str | None = None,
) -> ColumnIR:
    unit, tax_basis, description = _catalog_metadata(field, catalog)
    return ColumnIR(
        name=name,
        type=declared,
        canonical=field.canonical,
        unit=unit,
        tax_basis=tax_basis,
        expr=canon(expr),
        recipe_id=recipe_id,
        renamed_from=field.renamed_from,
        required=field.required,
        description=description,
    )


def _recipe_expr(
    field_mapping: RecipeFieldMapping,
    declared: LogicalType,
    mapping: Mapping,
    field_name: str,
    project: Project,
    catalog: Catalog | None,
) -> tuple[Expression, str]:
    recipe = resolve_recipe(mapping, field_name, field_mapping, project, catalog)
    if recipe.expr is None:
        # Identity recipe: the single required alias, cast to the declared type.
        body = extraction(field_mapping.from_[recipe.requires[0]])
    else:
        parsed = parse_one(recipe.expr)

        def substitute(node: Expression) -> Expression:
            if isinstance(node, exp.Column) and not node.table and node.name in field_mapping.from_:
                return extraction(field_mapping.from_[node.name])
            return node

        body = parsed.transform(substitute)
    return exp.cast(body, generic_type(declared)), recipe.id


def _macro_expr(
    field_mapping: MacroFieldMapping,
    declared: LogicalType,
    steps: StepRegistry,
    *,
    source_path: str,
) -> Expression:
    """A Tier 1 macro spliced into the consuming column (RFC 0017 D50).

    Every refusal here is the same shape D47 settled for Tier 2, and for the
    same reason: the body's placeholders and what the call site supplies must
    name **one** set. A placeholder nothing fills reaches the engine as an
    unknown variable; an argument the body never mentions is a column read for
    nothing, or a typo silently doing nothing.

    Two populations fill placeholders, and they are disjoint by construction:
    ``from`` binds *columns* (substituted as extraction expressions) and
    ``parameters`` binds *scalars* (substituted as typed literals, so a value
    is data wherever it lands). A name in both is refused rather than resolved
    by precedence — a rule nobody can predict is worse than an error.
    """
    ref, version = field_mapping.step.split("@", 1)
    manifest = steps.resolve(ref, int(version), source_path=source_path)
    if manifest.kind != "sql_macro":
        msg = (
            f"field references step {field_mapping.step!r}, which is a {manifest.kind} "
            "and cannot be spliced into a column: only a sql_macro is an expression "
            "(RFC 0017 §5.1). Fix: wire it in the steps: document, which is where a "
            "step that writes a relation belongs"
        )
        raise StepError(msg, source_path=source_path)
    if manifest.determinism != "pure":
        msg = (
            f"field references step {field_mapping.step!r}, which declares determinism: "
            f"{manifest.determinism} (RFC 0017 §5.5). A macro is spliced into the "
            "entity's SELECT and re-evaluated on every backfill, so anything but pure "
            "makes a restatement disagree with the run it replaces"
        )
        raise StepDeterminismError(msg, source_path=source_path)
    body = steps.macro_body(ref, int(version))
    if body is None:
        msg = (
            f"field references step {field_mapping.step!r} but the registry carries no "
            "macro body for it (RFC 0017 §5.3); with none there the column would lower "
            "to nothing at all"
        )
        raise StepError(msg, source_path=source_path)
    # `parse_one` is typed against `sqlglot.expressions`; the codebase reads
    # the same class through `.core` (the spelling pyright resolves).
    parsed = cast("Expression", parse_one(body))
    used = placeholders(parsed)
    columns = set(field_mapping.from_)
    scalars = set(field_mapping.parameters) | {
        name for name, spec in manifest.parameters.items() if spec.default is not None
    }
    overlap = sorted(columns & scalars)
    if overlap:
        msg = (
            f"field binds {', '.join(overlap)} as both a column (from:) and a parameter "
            f"of step {field_mapping.step!r}. One placeholder cannot be two things, and "
            "picking one silently is a rule nobody can predict"
        )
        raise StepError(msg, source_path=source_path)
    _refuse_macro_disagreement(field_mapping, used, columns, scalars, source_path=source_path)
    arguments: dict[str, Expression] = {
        alias: extraction(path) for alias, path in field_mapping.from_.items()
    }
    resolved = {
        name: str(spec.default)
        for name, spec in manifest.parameters.items()
        if spec.default is not None
    }
    resolved.update({name: str(value) for name, value in field_mapping.parameters.items()})
    arguments.update(
        {
            name: parameter_literal(value, manifest.parameters[name].type)
            for name, value in resolved.items()
        }
    )
    return exp.cast(splice(parsed, arguments), generic_type(declared))


def _refuse_macro_disagreement(
    field_mapping: MacroFieldMapping,
    used: frozenset[str],
    columns: set[str],
    scalars: set[str],
    *,
    source_path: str,
) -> None:
    """The body and the call site name one set, or it is a compile error."""
    supplied = columns | scalars
    if unfilled := sorted(used - supplied):
        msg = (
            f"step {field_mapping.step!r} has a body referring to :{', :'.join(unfilled)}, "
            "which this field supplies neither as a column (from:) nor as a parameter. "
            "An unfilled placeholder reaches the engine as an unknown variable"
        )
        raise StepError(msg, source_path=source_path)
    if unused := sorted(supplied - used):
        msg = (
            f"field supplies {', '.join(unused)} to step {field_mapping.step!r}, whose body "
            f"never refers to :{unused[0]}. It would be read for nothing — and a typo here "
            "is otherwise silent"
        )
        raise StepError(msg, source_path=source_path)


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
    steps: StepRegistry,
) -> EntityIR:
    doc = mapping_doc(mapping)
    columns: list[ColumnIR] = []
    source_fields: list[SourceFieldIR] = []
    # Stages 1–2 of the fixed pipeline order (RFC 0016 §5.4): extract, then
    # transform. A quality-carrying entity's transforms lower to the
    # coercion-failure-marker form, feeding the implicit ``coercible`` rule.
    shape = _try_cast_shape if opts_in(entity, mapping) else _identity_shape

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
        columns.append(_column_ir(field_name, field, declared, shape(expr), catalog))
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
        if isinstance(field_mapping, MacroFieldMapping):
            expr = _macro_expr(
                field_mapping, declared, steps, source_path=f"{doc}: fields.{field_name}"
            )
            columns.append(_column_ir(field_name, field, declared, shape(expr), catalog))
            source_fields.extend(
                SourceFieldIR(target_field=field_name, source_path=path)
                for _alias, path in sorted(field_mapping.from_.items())
            )
        elif isinstance(field_mapping, RecipeFieldMapping):
            expr, recipe_id = _recipe_expr(
                field_mapping, declared, mapping, field_name, project, catalog
            )
            columns.append(
                _column_ir(field_name, field, declared, shape(expr), catalog, recipe_id=recipe_id)
            )
            source_fields.extend(
                SourceFieldIR(target_field=field_name, source_path=path)
                for _alias, path in sorted(field_mapping.from_.items())
            )
            if field_mapping.direct is not None:
                # The path-conflict shadow (RFC 0006 D7) is a path the mapping
                # genuinely reads: the guardrail stage lowers it to a
                # ``<field>__direct`` column, and replay re-runs that same
                # lowering against ``raw`` (RFC 0016 D10). Left off the source
                # fields, it was absent from the bronze payload the reject
                # table stores, so every replayed row rebuilt the shadow from
                # a key that is not there — ``__direct`` NULL for all of them,
                # feeding the reconcile audit that exists to compare it.
                source_fields.append(
                    SourceFieldIR(
                        target_field=f"{field_name}__direct", source_path=field_mapping.direct
                    )
                )
        else:
            expr = _lower_chain(
                field_mapping.from_,
                field_mapping.transform,
                declared,
                reg,
                source_path=f"{doc}: fields.{field_name}",
            )
            columns.append(_column_ir(field_name, field, declared, shape(expr), catalog))
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
        partition_by=partition_specs(entity.partition_by),
        columns=tuple(sorted(columns, key=lambda c: c.name)),
        source=SourceIR(
            relation=mapping.source,
            fields=tuple(sorted(source_fields, key=lambda f: (f.target_field, f.source_path))),
            mapping_version=mapping.mapping_version,
            unmapped=tuple(sorted(mapping.unmapped)),
        ),
        audits=(),  # populated by the guardrail stage: assert: lowering + reconcile (RFC 0006)
        # Stages 3–6 (RFC 0016 §5.4): dedupe, field rules, row rules, route.
        # The rules are one sorted tuple — the fixed pipeline order, not the
        # node type, is what separates a field rule from a row rule, and
        # emission renders the stages in that order.
        quality=lower_quality(entity, mapping, project.entity_model.relationships),
        dedupe=lower_dedupe(entity),
        quarantine=lower_quarantine(entity),
    )


def _build_entities(
    project: Project, catalog: Catalog | None, reg: Registry, steps: StepRegistry
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
        entities.append(
            _build_entity(entity_name, entity, mappings[0], project, catalog, reg, steps)
        )
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
                    canon(cast("Expression", parse_one(metric.expr)))
                    if metric.expr is not None
                    else None
                ),
                ratio=(
                    Ratio(numerator=metric.ratio.numerator, denominator=metric.ratio.denominator)
                    if metric.ratio is not None
                    else None
                ),
                semi_additive=semi_additive,
                description=metric.description,
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


def _build_date_dimension(catalog: Catalog | None) -> DateDimensionIR | None:
    """Lower the catalog's date dimension (RFC 0008 D13): one definition
    drives the gold ``dim_date`` model and, at M6, the MetricFlow time spine."""
    if catalog is None or catalog.date_dimension is None:
        return None
    dim = catalog.date_dimension
    return DateDimensionIR(
        name=dim.name,
        grain=dim.grain,
        start_year=dim.start_year,
        end_year=dim.end_year,
    )


def build_project_ir(
    project: Project,
    catalog: Catalog | None = None,
    *,
    steps: StepRegistry = EMPTY_REGISTRY,
) -> ProjectIR:
    """Compile parsed specs into the frozen, fingerprintable IR (RFC 0003).

    Pure function: resolution (RFC 0005) and the batched typecheck (RFC 0004)
    run first, so lowering only ever sees a reference-clean, well-typed
    project; marts flatten over the entity draft (RFC 0010 D6); the guardrail
    stage (RFC 0006) refuses last, over the finished draft — mart-level
    violations batched with the rest.
    """
    resolution = resolve(project, catalog)
    reg = registry()
    _typecheck_project(project, reg)

    steps_ir = lower_steps(project, steps)
    draft = ProjectIR(
        bloomery_ir_version=3,
        # Mapped entities plus one per step output: §5.8 makes a step output an
        # entity so marts, metrics and downstream mappings can reference it
        # like any other. Sorted together, because the IR's ordering rule is
        # about the collection, not about how a member got there.
        entities=tuple(
            sorted(
                (*_build_entities(project, catalog, reg, steps), *step_entities(steps_ir, project)),
                key=lambda entity: entity.name,
            )
        ),
        metrics=_build_metrics(project, catalog, resolution.reachable_metrics),
        unreachable=resolution.unreachable_metrics,
        relationships=_build_relationships(project),
        marts=(),  # attached below, once the flattener has the entity draft
        date_dimension=_build_date_dimension(catalog),
        # Document-level reconcile checks (RFC 0016 §5.3): they relate two
        # entities, so they belong to neither — they live on the root.
        reconcile=lower_reconcile(project.entity_model),
        # Steps lower before the mart flattener and the guardrail stage, because
        # step outputs are relations both of them must be able to see
        # (RFC 0017 §5.8).
        steps=steps_ir,
    )
    # Mart flattening (RFC 0010 D6): pure, total — violations are re-derived
    # and raised by the guardrail stage below; only clean marts attach here.
    draft = replace(draft, marts=lower_marts(project.marts, draft).marts)

    # ── Guardrail seam (RFC 0006 §5.1) ─────────────────────────────────
    # Stage four: pure over the draft — refuses with one batched
    # GuardrailError (mart-level leaves included, RFC 0006 D10) before any
    # artifact is emitted, and amends only via path-conflict shadows and
    # lowered assert: audits (RFC 0006 D9).
    checked = check_guardrails(draft, project=project, catalog=catalog)
    # The quality mart (RFC 0016 §5.8) is bloomery-owned, like the dim_date
    # calendar: synthesized from the finished IR rather than authored, so it
    # attaches *after* the refusals — there is nothing about it for a
    # guardrail to refuse. What the stage does check, from the spec alone, is
    # that no authored metric claimed one of its reserved names.
    return attach_quality_mart(checked)
