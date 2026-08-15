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

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.errors import (
    InvariantViolated,
    ResolutionError,
    StepDeterminismError,
    StepError,
    guaranteed,
)
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
    SourceColumnIR,
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
    lower_coverage,
    lower_dedupe,
    lower_quality,
    lower_quarantine,
    lower_reconcile,
    mapped_fields,
    opts_in,
)
from bloomery.resolve.metrics import effective_metrics
from bloomery.resolve.recipes import resolve_recipe
from bloomery.resolve.refs import mapping_doc
from bloomery.resolve.resolution import Resolution, resolve
from bloomery.resolve.steps import lower_steps, step_entities
from bloomery.spec.catalog import Catalog
from bloomery.spec.mapping import ALIAS_BOUND, MacroFieldMapping, RecipeFieldMapping
from bloomery.spec.project import Project
from bloomery.steps import EMPTY_REGISTRY, StepRegistry
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
    from collections.abc import Iterator

    from bloomery.spec.entity import Entity, Field
    from bloomery.spec.mapping import Mapping, TransformStep
    from bloomery.steps import StepManifest
    from bloomery.transforms import Registry

__all__ = [
    "Stage",
    "StageProgress",
    "build_project_ir",
    "pipeline",
]


class Stage(StrEnum):
    """A stage of spec analysis, in the order :func:`pipeline` runs them.

    Public because :attr:`~bloomery.SpecEvidence.stage_reached` is the field a
    caller has to read before any other (RFC 0022 D5): an empty ``unreachable``
    means "nothing is unreachable" only at :attr:`COMPLETE`, and means "never
    computed" at :attr:`RESOLVE`. Without the stage that tuple is ambiguous in
    exactly the way that produces a wrong conclusion.

    Treat it as an **open** enum: compare against :attr:`COMPLETE` and read
    everything else as "analysis stopped early". Stages are an account of how
    the pipeline is built, and one may be added or split without the meaning of
    that comparison changing.

    Every member is a stage that can genuinely refuse, and each is tested on a
    spec that refuses there. RFC 0022's draft listed two that cannot be
    reported: ``PARSE``, because :func:`~bloomery.load_project` has already run
    by the time anything here holds a :class:`~bloomery.Project` — a document
    that does not parse never reaches this pipeline — and ``MARTS``, because
    the flattener is total and its violations are re-derived by the guardrail
    stage (RFC 0010 D6), so it refuses nothing of its own. A stage that can
    never be reported is a value a consumer would write a branch for and never
    execute, which is worse than its absence. :attr:`LOWER` is the stage the
    draft named ``MARTS``, renamed for what it does: mart flattening is one
    part of lowering the spec into a draft IR, and step lowering — which does
    refuse — is another.
    """

    #: Reachability and reference validation (RFC 0005).
    RESOLVE = "resolve"
    #: The batched transform-chain typecheck (RFC 0004).
    TYPECHECK = "typecheck"
    #: Spec to draft IR: steps, entities, metrics, relationships, marts.
    LOWER = "lower"
    #: The batched guardrail stage over the finished draft (RFC 0006).
    GUARDRAILS = "guardrails"
    #: Every stage ran. Only here does an empty result mean "nothing found".
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class StageProgress:
    """What analysis had produced *before* the stage it is yielded with ran.

    Both fields widen to non-``None`` as the pipeline advances and never
    narrow, so a consumer that stops early keeps the prefix rather than losing
    it — which is the whole of RFC 0022 D3.
    """

    resolution: Resolution | None = None
    ir: ProjectIR | None = None


def pipeline(
    project: Project,
    catalog: Catalog | None = None,
    *,
    steps: StepRegistry = EMPTY_REGISTRY,
) -> Iterator[tuple[Stage, StageProgress]]:
    """The compile pipeline, one yield per stage, in order.

    **Each yield hands back the stage that is about to run**, together with
    everything the stages before it produced. So a consumer that catches a
    refusal knows both which stage refused — the stage from the last yield,
    because the exception surfaced while that stage was running — and what
    survived it. A consumer that runs to exhaustion ends on
    :attr:`Stage.COMPLETE`, whose progress carries the finished IR.

    This exists so that :func:`build_project_ir` and
    :func:`~bloomery.evaluate` cannot disagree about what the pipeline *is*.
    Writing the sequence twice — once to compile and once to assess — is the
    failure mode RFC 0022 §9 names as the one it could plausibly introduce, and
    a shared generator is what makes it not a matter of discipline.
    """
    yield Stage.RESOLVE, StageProgress()
    resolution = resolve(project, catalog)

    yield Stage.TYPECHECK, StageProgress(resolution=resolution)
    reg = registry()
    _typecheck_project(project, reg, steps)

    yield Stage.LOWER, StageProgress(resolution=resolution)
    draft = _lower_draft(project, catalog, reg, steps, resolution)

    yield Stage.GUARDRAILS, StageProgress(resolution=resolution, ir=draft)
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
    finished = attach_quality_mart(checked)

    yield Stage.COMPLETE, StageProgress(resolution=resolution, ir=finished)


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
    macros: StepRegistry,
    *,
    source_path: str,
) -> Expression:
    node = extraction(path)
    if not steps:
        return exp.cast(node, generic_type(declared))
    for step in steps:
        if step.step is not None:
            node = _splice_link(step.step, node, macros, source_path=source_path)
            continue
        node = reg[step.name].builder(node, *step.args)
    terminal = _chain_terminal(steps, declared, reg, macros, source_path=source_path)
    if terminal != declared:
        node = exp.cast(node, generic_type(declared))
    return node


def _splice_link(
    use: str, running: Expression, macros: StepRegistry, *, source_path: str
) -> Expression:
    """One Tier 1 link in a chain: the running value fills the macro's single
    accepted column.

    Which name that column has does not matter and is deliberately not a
    convention — the manifest declares it, and :func:`_refuse_unchainable`
    has already established there is exactly one.
    """
    manifest, body = _macro_parts(use, macros, source_path=source_path)
    _refuse_unchainable(use, manifest, source_path=source_path)
    (column,) = manifest.accepts
    arguments: dict[str, Expression] = {column: running}
    arguments.update(_macro_parameters(manifest, {}))
    return splice(body, arguments)


def chain_segments(
    steps: tuple[TransformStep, ...],
    declared: LogicalType,
    macros: StepRegistry,
    *,
    source_path: str,
) -> tuple[tuple[LogicalType, tuple[TransformStep, ...], LogicalType], ...]:
    """A chain split *around* each Tier 1 link, as ``(input, run, declared)``.

    A macro is where the transform whitelist stops being able to reason: its
    body is opaque SQL. So the run of transforms before it is checked against
    the type the macro **declares** it accepts, and the run after it starts
    from the type its ``produces`` declares — which is exactly what makes
    Tier 1 no weaker than Tier 0, whose ``TransformSpec`` declares
    ``input_domain`` and ``output_type`` for the same reason (D51).

    Returned as segments rather than checked here so both callers can use
    one implementation: the batch stage queues them as ordinary
    ``ChainCheck``s — keeping RFC 0006 D2's one-aggregate property for chains
    containing a macro — and lowering walks them for the terminal type.
    """
    segments: list[tuple[LogicalType, tuple[TransformStep, ...], LogicalType]] = []
    current: LogicalType = StringType()
    run: list[TransformStep] = []
    for step in steps:
        if step.step is None:
            run.append(step)
            continue
        manifest, _body = _macro_parts(step.step, macros, source_path=source_path)
        _refuse_unchainable(step.step, manifest, source_path=source_path)
        (accepted,) = manifest.accepts.values()
        segments.append((current, tuple(run), parse_type(accepted, source_path=source_path)))
        run = []
        (output,) = manifest.outputs.values()
        (produced,) = output.produces.values()
        current = parse_type(produced.type, source_path=source_path)
    segments.append((current, tuple(run), declared))
    return tuple(segments)


def _chain_terminal(
    steps: tuple[TransformStep, ...],
    declared: LogicalType,
    reg: Registry,
    macros: StepRegistry,
    *,
    source_path: str,
) -> LogicalType:
    terminal = declared
    for input_type, run, expected in chain_segments(
        steps, declared, macros, source_path=source_path
    ):
        terminal = typecheck_chain(input_type, run, expected, registry=reg, source_path=source_path)
    return terminal


def _typecheck_project(project: Project, reg: Registry, macros: StepRegistry) -> None:
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
                path = f"{doc}: key.{field_name}"
                checks.extend(
                    ChainCheck(input_type, run, expected, path)
                    for input_type, run, expected in chain_segments(
                        steps, declared, macros, source_path=path
                    )
                )
        for field_name in sorted(mapping.fields):
            field_mapping = mapping.fields[field_name]
            if isinstance(field_mapping, ALIAS_BOUND) or not field_mapping.transform:
                continue
            declared = _field_type(mapping.target, field_name, entity.fields[field_name])
            path = f"{doc}: fields.{field_name}"
            checks.extend(
                ChainCheck(input_type, run, expected, path)
                for input_type, run, expected in chain_segments(
                    field_mapping.transform, declared, macros, source_path=path
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


def _column_pair(
    name: str,
    field: Field,
    declared: LogicalType,
    expr: Expression,
    catalog: Catalog | None,
    *,
    recipe_id: str | None = None,
) -> tuple[ColumnIR, SourceColumnIR]:
    """The entity's column and this mapping's projection of it (RFC 0024 D26).

    One function rather than two because the two halves are decided together
    and must not drift: every ``ColumnIR`` an entity carries needs exactly one
    projection per source, and building them apart is how a column comes to
    exist with nothing to select for it.

    The split is the parameter list's own: ``field`` and ``catalog`` decide
    the schema — identical for every mapping targeting this entity, since both
    come from the entity model — while ``expr`` and ``recipe_id`` come from
    the mapping and are the only things a second source would spell
    differently.
    """
    unit, tax_basis, description = _catalog_metadata(field, catalog)
    return (
        ColumnIR(
            name=name,
            type=declared,
            canonical=field.canonical,
            unit=unit,
            tax_basis=tax_basis,
            renamed_from=field.renamed_from,
            required=field.required,
            description=description,
        ),
        SourceColumnIR(name=name, expr=canon(expr), recipe_id=recipe_id),
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


def _macro_parts(
    use: str, macros: StepRegistry, *, source_path: str
) -> tuple[StepManifest, Expression]:
    """The manifest and parsed body behind a ``ref@version``, with every
    refusal about *which steps may be spliced at all* applied once."""
    ref, version = use.split("@", 1)
    manifest = macros.resolve(ref, int(version), source_path=source_path)
    if manifest.kind != "sql_macro":
        msg = (
            f"field references step {use!r}, which is a {manifest.kind} and cannot be "
            "spliced into a column: only a sql_macro is an expression (RFC 0017 §5.1). "
            "Fix: wire it in the steps: document, which is where a step that writes a "
            "relation belongs"
        )
        raise StepError(msg, source_path=source_path)
    if manifest.determinism != "pure":
        msg = (
            f"field references step {use!r}, which declares determinism: "
            f"{manifest.determinism} (RFC 0017 §5.5). A macro is spliced into the "
            "entity's query and re-evaluated on every backfill, so anything but pure "
            "makes a restatement disagree with the run it replaces"
        )
        raise StepDeterminismError(msg, source_path=source_path)
    body = macros.macro_body(ref, int(version))
    if body is None:
        msg = (
            f"field references step {use!r} but the registry carries no macro body for it "
            "(RFC 0017 §5.3); with none there the column would lower to nothing at all"
        )
        raise StepError(msg, source_path=source_path)
    parsed = cast("Expression", parse_one(body))
    _refuse_body_disagreement(use, manifest, parsed, source_path=source_path)
    return manifest, parsed


def _refuse_unchainable(use: str, manifest: StepManifest, *, source_path: str) -> None:
    """A chain carries exactly one running value, so a link must accept
    exactly one column — checked rather than assumed, because a two-column
    macro reached this way would silently drop an argument."""
    if len(manifest.accepts) != 1:
        expected = ", ".join(sorted(manifest.accepts)) or "(nothing)"
        msg = (
            f"step {use!r} accepts {len(manifest.accepts)} column(s) ({expected}), so it "
            "cannot be a link in a transform chain — a chain carries exactly one running "
            "value. Fix: use it as a field's step:/from: pair, where each accepted column "
            "is bound to its own source path"
        )
        raise StepError(msg, source_path=source_path)
    undefaulted = sorted(name for name, spec in manifest.parameters.items() if spec.default is None)
    if undefaulted:
        # A chain link has nowhere to put parameter values — the `{step: ref@v}`
        # form is a bare reference, unlike the `step:`/`from:` field shape which
        # carries a `parameters:` map. So a parameter with no default is never
        # resolved, and `splice` leaves its `:name` alone: the emitted SQL
        # carried a live `$factor` placeholder into the model (RFC 0017 D54).
        msg = (
            f"step {use!r} declares parameter(s) {', '.join(undefaulted)} with no default, so "
            "it cannot be a link in a transform chain — a chain link is a bare reference with "
            "nowhere to pass a value, and an unresolved parameter would reach the emitted SQL "
            "as a placeholder. Fix: give the parameter a default in the manifest, or use the "
            "step as a field's step:/from: pair, which carries a parameters: map"
        )
        raise StepError(msg, source_path=source_path)


def _macro_parameters(
    manifest: StepManifest, overrides: dict[str, object]
) -> dict[str, Expression]:
    """Declared defaults under the call site's values, as typed literals."""
    resolved = {
        name: str(spec.default)
        for name, spec in manifest.parameters.items()
        if spec.default is not None
    }
    resolved.update({name: str(value) for name, value in overrides.items()})
    return {
        name: parameter_literal(value, manifest.parameters[name].type)
        for name, value in resolved.items()
    }


def _macro_expr(
    field_mapping: MacroFieldMapping,
    declared: LogicalType,
    steps: StepRegistry,
    *,
    source_path: str,
) -> Expression:
    """A Tier 1 macro spliced into the consuming column (RFC 0017 D50/D51).

    Two populations fill the body's placeholders, disjoint by declaration:
    ``from`` binds the columns the manifest ``accepts`` (substituted as
    extraction expressions) and ``parameters`` binds the scalars it declares
    (substituted as typed literals, so a value is data wherever it lands).
    """
    manifest, body = _macro_parts(field_mapping.step, steps, source_path=source_path)
    _refuse_macro_disagreement(field_mapping, manifest, source_path=source_path)
    arguments: dict[str, Expression] = {
        alias: extraction(path) for alias, path in field_mapping.from_.items()
    }
    arguments.update(_macro_parameters(manifest, dict(field_mapping.parameters)))
    return exp.cast(splice(body, arguments), generic_type(declared))


def _refuse_body_disagreement(
    use: str, manifest: StepManifest, parsed: Expression, *, source_path: str
) -> None:
    """The macro's *body* and its *declared signature* name one set (D51).

    Checked once, against the manifest rather than against any call site: the
    registry is where a macro's body and its declaration meet, and a
    disagreement there is the platform's bug, not the spec author's. Without
    it the signature would be decoration — a body could refer to a
    placeholder nothing declares, and the call site would have no way to know
    it was supposed to supply one.
    """
    declared = set(manifest.accepts) | set(manifest.parameters)
    used = placeholders(parsed)
    if undeclared := sorted(used - declared):
        msg = (
            f"step {use!r} has a body referring to :{', :'.join(undeclared)}, which its "
            "manifest declares neither in accepts: nor in parameters:. A macro's signature "
            "is declared, never read off its body (RFC 0017 D51)"
        )
        raise StepError(msg, source_path=source_path)
    if unused := sorted(declared - used):
        msg = (
            f"step {use!r} declares {', '.join(unused)}, which its body never refers to. "
            f"A call site would be required to supply :{unused[0]} for nothing"
        )
        raise StepError(msg, source_path=source_path)


def _refuse_macro_disagreement(
    field_mapping: MacroFieldMapping,
    manifest: StepManifest,
    *,
    source_path: str,
) -> None:
    """The call site supplies exactly the signature the macro declares.

    Against the declaration, not against the body: that is the difference D51
    makes. The message can now name what the macro *expects*, and a body
    change that adds a placeholder is the platform's error rather than a
    puzzle handed to whoever wired it.
    """
    supplied = set(field_mapping.from_)
    if missing := sorted(set(manifest.accepts) - supplied):
        msg = (
            f"field does not bind {', '.join(missing)}, which step {field_mapping.step!r} "
            f"accepts; bind it under from:, as a source path. Expected: "
            f"{', '.join(f'{n}: {t}' for n, t in sorted(manifest.accepts.items()))}"
        )
        raise StepError(msg, source_path=source_path)
    if spare := sorted(supplied - set(manifest.accepts)):
        msg = (
            f"field binds {', '.join(spare)}, which step {field_mapping.step!r} does not "
            f"accept; it accepts {', '.join(sorted(manifest.accepts)) or '(nothing)'}. "
            "The path would be read for nothing — and a typo here is otherwise silent"
        )
        raise StepError(msg, source_path=source_path)
    if unknown := sorted(set(field_mapping.parameters) - set(manifest.parameters)):
        msg = (
            f"field sets parameter(s) {', '.join(unknown)} that step "
            f"{field_mapping.step!r} does not declare; declared: "
            f"{', '.join(sorted(manifest.parameters)) or '(none)'}"
        )
        raise StepError(msg, source_path=source_path)


def _repair_bodies(
    entity_name: str,
    entity: Entity,
    mapping: Mapping,
    steps: StepRegistry,
) -> dict[str, str]:
    """``{column: spliced recipe SQL}`` for every ``on_fail: repair`` rule
    (RFC 0016 D87).

    Resolved here, not in ``quality/``, because splicing needs three things
    that live at this stage: the step registry, the field's declared type, and
    the extraction machinery. The result travels as SQL in the rule's params —
    the arrangement an ``expression`` rule already uses — so emission needs no
    registry, and a version or ``runtime_lock`` bump lands in the IR where the
    fingerprint and ``plan()`` can see it.

    The recipe reads the column *after* extraction and transforms, so its
    argument is a column reference rather than a source path: repair is a
    disposition on a rule, and a rule sees the produced value. Fixing a value
    on its way in is a different job with its own shape — a Tier 1 macro in the
    mapping (RFC 0017 D50).
    """
    dedupe_columns: frozenset[str] = (
        frozenset[str]()
        if entity.dedupe is None
        else frozenset({entity.dedupe.field, *entity.dedupe.tie_break})
    )
    bodies: dict[str, str] = {}
    for column, field_mapping in mapped_fields(mapping):
        if field_mapping is None:
            continue
        for rule in field_mapping.quality:
            if rule.repair is None:
                continue
            where = f"{mapping_doc(mapping)}: fields.{column}.quality"
            if column in bodies:
                msg = (
                    f"field {column!r} carries two repair rules. Each rewrites the column in "
                    "the same projection, so which value survives would depend on the order "
                    "they happened to be written in (RFC 0016 D87) — and the second recipe "
                    "would judge a value the first had already changed"
                )
                raise StepError(msg, source_path=where)
            if column in dedupe_columns:
                msg = (
                    f"field {column!r} is read by the dedupe order, so it cannot carry a "
                    "repair rule (RFC 0016 D87). Dedupe runs *before* the field rules (D7), "
                    "so the winner would be chosen on the value as delivered and then have "
                    "that value rewritten underneath it — the same reason D6 forces "
                    "coercible to fail here"
                )
                raise StepError(msg, source_path=where)
            manifest, body = _macro_parts(rule.repair.via, steps, source_path=where)
            _refuse_unrepairing(rule.repair.via, manifest, column, where=where)
            declared = _field_type(entity_name, column, entity.fields[column])
            arguments: dict[str, Expression] = {
                guaranteed(
                    iter(manifest.accepts),
                    expected=f"the single column {rule.repair.via!r} accepts",
                    by="_refuse_unrepairing, which requires exactly one (RFC 0016 D87)",
                ): exp.column(column),
                **_macro_parameters(manifest, dict(rule.repair.parameters)),
            }
            bodies[column] = canon(exp.cast(splice(body, arguments), generic_type(declared))).sql
    return bodies


def _refuse_unrepairing(use: str, manifest: StepManifest, column: str, *, where: str) -> None:
    """A repair recipe takes the column it repairs, and nothing else.

    Exactly one accepted column, because the recipe is bound to *this* rule's
    value and there is no second path for it to read — the ``from:`` map a
    Tier 1 field shape uses has no counterpart on a quality rule, and inventing
    one would make a rule a second mapping surface.
    """
    if len(manifest.accepts) != 1:
        accepted = ", ".join(sorted(manifest.accepts)) or "(nothing)"
        msg = (
            f"repair recipe {use!r} accepts {len(manifest.accepts)} column(s) ({accepted}), "
            f"but a repair rule hands it exactly one — {column}, the value the rule fired "
            "on (RFC 0016 D87). A recipe needing more than the value it repairs is a "
            "mapping, not a repair"
        )
        raise StepError(msg, source_path=where)


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
    projections: list[SourceColumnIR] = []
    source_fields: list[SourceFieldIR] = []

    def add_column(
        name: str,
        field: Field,
        declared: LogicalType,
        expr: Expression,
        *,
        recipe_id: str | None = None,
    ) -> None:
        """Append both halves of one column, so neither can be added alone."""
        column, projection = _column_pair(name, field, declared, expr, catalog, recipe_id=recipe_id)
        columns.append(column)
        projections.append(projection)

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
            steps,
            source_path=f"{doc}: key.{field_name}",
        )
        add_column(field_name, field, declared, shape(expr))
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
            add_column(field_name, field, declared, shape(expr))
            source_fields.extend(
                SourceFieldIR(target_field=field_name, source_path=path)
                for _alias, path in sorted(field_mapping.from_.items())
            )
        elif isinstance(field_mapping, RecipeFieldMapping):
            expr, recipe_id = _recipe_expr(
                field_mapping, declared, mapping, field_name, project, catalog
            )
            add_column(field_name, field, declared, shape(expr), recipe_id=recipe_id)
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
                steps,
                source_path=f"{doc}: fields.{field_name}",
            )
            add_column(field_name, field, declared, shape(expr))
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
            columns=tuple(sorted(projections, key=lambda c: c.name)),
            mapping_version=mapping.mapping_version,
            unmapped=tuple(sorted(mapping.unmapped)),
        ),
        audits=(),  # populated by the guardrail stage: assert: lowering + reconcile (RFC 0006)
        # Stages 3–6 (RFC 0016 §5.4): dedupe, field rules, row rules, route.
        # The rules are one sorted tuple — the fixed pipeline order, not the
        # node type, is what separates a field rule from a row rule, and
        # emission renders the stages in that order.
        quality=lower_quality(
            entity,
            mapping,
            project.entity_model.relationships,
            _repair_bodies(entity_name, entity, mapping, steps),
        ),
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

    Written as :func:`pipeline` run to exhaustion rather than as the sequence
    itself, so that this and :func:`~bloomery.evaluate` read one definition of
    what the pipeline is. Every refusal propagates, unchanged: this function is
    all-or-nothing by design, and it is ``evaluate`` that keeps the prefix.
    """
    progress = StageProgress()
    for _stage, reached in pipeline(project, catalog, steps=steps):
        progress = reached
    if progress.ir is None:  # pragma: no cover — COMPLETE always carries the IR
        msg = "the pipeline reached COMPLETE without an IR"
        raise InvariantViolated(msg)
    return progress.ir


def _lower_draft(
    project: Project,
    catalog: Catalog | None,
    reg: Registry,
    steps: StepRegistry,
    resolution: Resolution,
) -> ProjectIR:
    """Spec plus resolution to the draft IR the guardrail stage judges.

    ``bloomery_ir_version`` is left to :class:`~bloomery.ProjectIR`'s default
    rather than repeated here. It was written in both places, and the two could
    disagree in either direction with nothing to say so: bump only the default
    and the compiler keeps emitting the old number, bump only this call site and
    every artifact claims a version no hand-built IR carries — which shows up as
    a golden fingerprint diff, exactly the diff a ``just snapshot-update`` walks
    straight past. The dataclass is the one declaration now, and
    ``test_the_compiler_emits_the_declared_ir_version`` pins that it is.
    """
    steps_ir = lower_steps(project, steps)
    draft = ProjectIR(
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
        coverage=lower_coverage(project.entity_model),
        # Steps lower before the mart flattener and the guardrail stage, because
        # step outputs are relations both of them must be able to see
        # (RFC 0017 §5.8).
        steps=steps_ir,
    )
    # Mart flattening (RFC 0010 D6): pure, total — violations are re-derived
    # and raised by the guardrail stage below; only clean marts attach here.
    return replace(draft, marts=lower_marts(project.marts, draft).marts)
