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

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
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
    VALIDITY_COLUMNS,
    Additivity,
    Cardinality,
    ColumnIR,
    CumulativeIR,
    DateDimensionIR,
    DerivedIR,
    DimensionRef,
    EntityIR,
    FxRatesIR,
    Materialization,
    MetricFilterIR,
    MetricInputIR,
    MetricIR,
    ProjectIR,
    QualityRuleIR,
    Ratio,
    RelationshipIR,
    SCDKind,
    SemiAdditivePolicy,
    SemiAdditiveRule,
    SourceColumnIR,
    SourceFieldIR,
    SourceIR,
    TaxBasis,
    TimeWindow,
    TransformStepIR,
    Unit,
    canon,
    extraction,
    partition_specs,
    quality_sort_key,
)
from bloomery.marts import lower_marts
from bloomery.quality import (
    attach_quality_mart,
    enum_chain,
    field_sources,
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
from bloomery.spec.mapping import (
    ALIAS_BOUND,
    KeyField,
    MacroFieldMapping,
    RecipeFieldMapping,
    SimpleFieldMapping,
)
from bloomery.spec.metrics import parse_time_window
from bloomery.spec.project import Project
from bloomery.steps import EMPTY_REGISTRY, StepRegistry
from bloomery.steps.splice import parameter_literal, placeholders, splice
from bloomery.transforms import (
    CONVERT_ANCHOR,
    CONVERT_ARITY,
    CONVERT_FROM,
    CONVERT_MARKER,
    CONVERT_TO,
    neutral_type,
    registry,
)
from bloomery.typing import (
    ChainCheck,
    DateType,
    LogicalType,
    StringType,
    TimestampType,
    parse_type,
    render_type,
    typecheck_chain,
    typecheck_chains,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from bloomery.spec.entity import Entity, Field, Relationship
    from bloomery.spec.mapping import FieldMapping, Mapping, TransformStep
    from bloomery.spec.metrics import DerivedSpec, MetricFilter
    from bloomery.steps import StepManifest
    from bloomery.transforms import Registry

# ----------------------- #

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


# ....................... #


@dataclass(frozen=True, slots=True)
class StageProgress:
    """What analysis had produced *before* the stage it is yielded with ran.

    Both fields widen to non-``None`` as the pipeline advances and never
    narrow, so a consumer that stops early keeps the prefix rather than losing
    it — which is the whole of RFC 0022 D3.
    """

    resolution: Resolution | None = None
    ir: ProjectIR | None = None


# ....................... #


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


# ....................... #


def _field_type(entity_name: str, field_name: str, field: Field) -> LogicalType:
    path = f"entity_model: entities.{entity_name}.fields.{field_name}.type"
    return parse_type(field.type, source_path=path)


# ....................... #


def _identity_shape(node: Expression) -> Expression:
    """The shipped produce-or-raise lowering: no marker, nothing rewritten."""

    return node


# ....................... #


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


# ....................... #


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
        return exp.cast(node, neutral_type(declared))

    # The running logical type, threaded so a builder that declares `types` can
    # construct against the same fact its `output_type` declares (RFC 0029 D1).
    # Bronze lands as text, which is where `chain_segments` starts too; after a
    # Tier 1 link it is whatever the macro's manifest says it produces.
    #
    # `output_type` cannot raise here: Stage.TYPECHECK runs the batched check
    # over every chain before Stage.LOWER, so a chain reaching this loop has
    # already been proven, with the per-step source paths that stage attaches.
    current: LogicalType = StringType()

    for step in steps:
        if step.step is not None:
            node, current = _splice_link(step.step, node, macros, source_path=source_path)
            continue
        spec = reg[step.name]
        node = (
            spec.builder(node, *step.args, input_type=current)
            if spec.types
            else spec.builder(node, *step.args)
        )
        current = spec.output_type(current, step.args)

    terminal = _chain_terminal(steps, declared, reg, macros, source_path=source_path)

    if terminal != declared:
        node = exp.cast(node, neutral_type(declared))

    return node


# ....................... #


def _splice_link(
    use: str, running: Expression, macros: StepRegistry, *, source_path: str
) -> tuple[Expression, LogicalType]:
    """One Tier 1 link in a chain: the running value fills the macro's single
    accepted column. Returns the spliced node and the type it produces.

    Which name that column has does not matter and is deliberately not a
    convention — the manifest declares it, and :func:`_refuse_unchainable`
    has already established there is exactly one.

    The produced type is returned rather than recomputed by the caller because
    a macro body is opaque SQL: its manifest is the only thing that knows what
    comes out, and :func:`chain_segments` reads the same declaration for the
    typecheck (D51). A chain that continues past a macro needs it to keep
    threading the running type.
    """
    manifest, body = _macro_parts(use, macros, source_path=source_path)
    _refuse_unchainable(use, manifest, source_path=source_path)
    (column,) = manifest.accepts
    arguments: dict[str, Expression] = {column: running}
    arguments.update(_macro_parameters(manifest, {}))
    (output,) = manifest.outputs.values()
    (produced,) = output.produces.values()
    return splice(body, arguments), parse_type(produced.type, source_path=source_path)


# ....................... #


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


# ....................... #


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


# ....................... #


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


# ....................... #


def _catalog_metadata(
    field: Field, catalog: Catalog | None
) -> tuple[Unit | None, TaxBasis | None, str | None]:
    if field.canonical is None or catalog is None:
        return None, None, None

    canonical_field = catalog.canonical_fields[field.canonical]
    unit = Unit(canonical_field.unit) if canonical_field.unit is not None else None
    tax = TaxBasis(canonical_field.tax_basis) if canonical_field.tax_basis is not None else None
    return unit, tax, canonical_field.description


# ....................... #


@dataclass(frozen=True, slots=True)
class _BranchFacts:
    """One mapping's inputs to the rules evaluated over the merged relation
    (RFC 0024 D32).

    Empty for an entity outside the quality system, and empty for a column the
    mapping does not produce — the second case is load-bearing rather than
    incidental: a branch that does not map a column projects a typed NULL for
    it (§5.2 rule 3), and an empty ``sources`` is what makes the ``coercible``
    marker read that NULL as "no evidence" instead of as a failed cast.
    """

    sources: tuple[str, ...] = ()
    enum_values: tuple[str, ...] = ()
    enum_spellings: tuple[str, ...] = ()


# ....................... #


def _branch_facts(entity: Entity, mapping: Mapping, column: str) -> _BranchFacts:
    """The facts one branch contributes for one column.

    Read from the mapping because that is where they are true. A key column
    carries no ``quality:`` surface and so no ``enum_map`` set to admit —
    :func:`~bloomery.quality.enum_chain` is only defined over ``fields``.
    """

    if not opts_in(entity, mapping):
        return _BranchFacts()

    sources = field_sources(mapping, column)

    if column in mapping.key:
        return _BranchFacts(sources=sources)

    spellings, targets = enum_chain(mapping, column)
    return _BranchFacts(sources=sources, enum_values=targets, enum_spellings=spellings)


# ....................... #


def _column_pair(
    name: str,
    field: Field,
    declared: LogicalType,
    expr: Expression,
    catalog: Catalog | None,
    facts: _BranchFacts,
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
    come from the entity model — while ``expr``, ``recipe_id`` and ``facts``
    come from the mapping and are the only things a second source would spell
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
        SourceColumnIR(
            name=name,
            expr=canon(expr),
            recipe_id=recipe_id,
            sources=facts.sources,
            enum_values=facts.enum_values,
            enum_spellings=facts.enum_spellings,
        ),
    )


# ....................... #


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

    return exp.cast(body, neutral_type(declared)), recipe.id


# ....................... #


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


# ....................... #


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


# ....................... #


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


# ....................... #


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

    return exp.cast(splice(body, arguments), neutral_type(declared))


# ....................... #


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


# ....................... #


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


# ....................... #


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
            bodies[column] = canon(exp.cast(splice(body, arguments), neutral_type(declared))).sql

    return bodies


# ....................... #


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


# ....................... #


def _materialization(entity: Entity) -> Materialization:
    """RFC 0002 D7: declared wins; the derived default is only the default."""

    if entity.materialization is not None:
        return Materialization(entity.materialization)

    if entity.partition_by:
        return Materialization.INCREMENTAL_BY_PARTITION

    return Materialization.FULL


# ....................... #


def _build_source(
    entity_name: str,
    entity: Entity,
    mapping: Mapping,
    project: Project,
    catalog: Catalog | None,
    reg: Registry,
    steps: StepRegistry,
) -> tuple[tuple[ColumnIR, ...], SourceIR]:
    """One mapping's contribution: the entity columns it declares, and its own
    :class:`SourceIR` projection of them (RFC 0024 D26).

    The schema half is returned rather than kept because a merged entity's
    columns are the *union* over its mappings — one system may map a loyalty
    tier the other has never heard of (§5.2 rule 3) — and the caller is what
    can see all of them. Every mapping targeting one entity produces byte-equal
    ``ColumnIR`` values for a shared column, since :func:`_column_pair` derives
    that half from the entity model and the catalog alone.
    """
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
        column, projection = _column_pair(
            name,
            field,
            declared,
            expr,
            catalog,
            _branch_facts(entity, mapping, name),
            recipe_id=recipe_id,
        )
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
        # Both loops, so no marker can reach emit with its anchor unbound: a
        # key is a strange place to convert, but `convert` types decimal ->
        # decimal and a decimal key is legal, and an unvisited path here would
        # surface at emit as the "no rates declared" refusal on a project that
        # declares them.
        expr = _resolve_conversions(
            expr,
            entity_name,
            entity,
            mapping,
            catalog,
            reg,
            steps,
            column=field_name,
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
            expr = _resolve_conversions(
                expr,
                entity_name,
                entity,
                mapping,
                catalog,
                reg,
                steps,
                column=field_name,
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

    return (
        tuple(sorted(columns, key=lambda c: c.name)),
        SourceIR(
            relation=mapping.source,
            fields=tuple(sorted(source_fields, key=lambda f: (f.target_field, f.source_path))),
            columns=tuple(sorted(projections, key=lambda c: c.name)),
            mapping_version=mapping.mapping_version,
            unmapped=tuple(sorted(mapping.unmapped)),
        ),
    )


# ....................... #


def _filled(source: SourceIR, columns: tuple[ColumnIR, ...]) -> SourceIR:
    """``source`` with a typed ``NULL`` projection for every entity column it
    does not map (RFC 0024 §5.2 rule 3).

    A field one mapping produces and another does not is legitimate — one
    system has no loyalty tier — and it is `NULL` for the other's rows. That
    has to be a *projection* rather than an absence: the branches of a
    ``UNION ALL`` must agree on column count and order, so a branch missing a
    column is not a narrower branch, it is invalid SQL.

    Cast, not a bare ``NULL``: an untyped null makes the union's column type
    depend on which branch the engine reads first, and the whole point of a
    fixed branch order is that nothing downstream depends on it.

    The identity on a single-source entity, where the schema is exactly what
    the one mapping produced.
    """
    projected = {column.name for column in source.columns}
    missing = [column for column in columns if column.name not in projected]

    if not missing:
        return source

    return replace(
        source,
        columns=tuple(
            sorted(
                [
                    *source.columns,
                    *(
                        SourceColumnIR(
                            name=column.name,
                            expr=canon(exp.cast(exp.null(), neutral_type(column.type))),
                        )
                        for column in missing
                    ),
                ],
                key=lambda column: column.name,
            )
        ),
    )


# ....................... #


def _build_entity(
    entity_name: str,
    entity: Entity,
    mappings: tuple[Mapping, ...],
    project: Project,
    catalog: Catalog | None,
    reg: Registry,
    steps: StepRegistry,
) -> EntityIR:
    """One entity from one *or more* mappings, merged by ``UNION ALL``
    (RFC 0024 D1).

    ``mappings`` arrives sorted by source relation and stays that way on
    ``EntityIR.sources``: branch order is lexicographic so the emitted SQL is
    byte-identical across processes (D3). Row order is not claimed and nothing
    downstream may depend on it — ``UNION ALL`` is a bag.
    """
    built = [
        _build_source(entity_name, entity, mapping, project, catalog, reg, steps)
        for mapping in mappings
    ]
    # By name, because every mapping spells a shared column identically (see
    # :func:`_build_source`) and the entity's schema is the union over its
    # sources — not the intersection, which would silently drop a field only
    # one system carries.
    schema = {column.name: column for columns, _source in built for column in columns}
    columns = tuple(sorted(schema.values(), key=lambda column: column.name))
    return EntityIR(
        name=entity_name,
        grain=entity.grain,
        key=entity.key,
        scd=SCDKind(entity.scd),
        materialization=_materialization(entity),
        partition_by=partition_specs(entity.partition_by),
        columns=columns,
        sources=tuple(_filled(source, columns) for _columns, source in built),
        audits=(),  # populated by the guardrail stage: assert: lowering + reconcile (RFC 0006)
        # Stages 3–6 (RFC 0016 §5.4): dedupe, field rules, row rules, route.
        # The rules are one sorted tuple — the fixed pipeline order, not the
        # node type, is what separates a field rule from a row rule, and
        # emission renders the stages in that order.
        #
        # Lowered over **every** mapping and unioned, on a merged entity as on
        # any other (RFC 0024 D32/D33). Two things make that honest rather than
        # a silent choice among N: :func:`_rule_agreement_refusals` has already
        # refused every entity whose mappings disagree about a shared column,
        # and the per-mapping facts a rule used to carry — the ``coercible``
        # source paths, the ``in_enum`` admissible set — now live on each
        # :class:`SourceColumnIR` instead. What is left is one rule set the
        # merged relation is judged by.
        quality=_merged_rules(
            entity_name, entity, mappings, project.entity_model.relationships, steps
        ),
        dedupe=lower_dedupe(entity),
        quarantine=lower_quarantine(entity),
    )


# ....................... #


def _merge_refusals(
    entity_name: str,
    entity: Entity,
    mappings: tuple[Mapping, ...],
    relationships: tuple[Relationship, ...],
    steps: StepRegistry,
) -> list[ResolutionError]:
    """Everything a union merge refuses at compile time (RFC 0024 §5.2, §5.6).

    Batched rather than raised one at a time, so an author sees every
    disagreement in one round-trip (RFC 0002 D6) — and returned rather than
    raised so the caller can batch these across *entities* too.

    Two of §5.2's four checks are absent because they already hold. **The full
    declared key** is enforced per mapping by ``resolve.refs`` ("entity key
    column %r is not lowered by the mapping's key:"), which runs over every
    mapping and therefore over every branch of a merge. **Type agreement** is
    the existing per-mapping typecheck seen from the other side: each mapping's
    chain is checked against the entity's *declaration*, so two mappings cannot
    disagree about a column's type without both failing first (§5.7).
    """
    errors: list[ResolutionError] = []

    if len(mappings) < 2:
        return errors

    count = len(mappings)

    by_source: dict[str, list[Mapping]] = {}

    for mapping in mappings:
        by_source.setdefault(mapping.source, []).append(mapping)

    for relation in sorted(by_source):
        tied = by_source[relation]
        if len(tied) < 2:
            continue
        msg = (
            f"entity {entity_name!r} is built from {len(tied)} mappings that all read "
            f"{relation!r}. A union merge orders its branches lexicographically by source "
            "relation, and two branches on one relation have no order — which leaves "
            "'_source' ambiguous between them and the collision audit unable to name which "
            "branch it means (RFC 0024 D12). Fix: express two disjoint row sets of one "
            "relation as one mapping with a filter"
        )
        errors.extend(
            ResolutionError(msg, source_path=f"{mapping_doc(mapping)}: source")
            for mapping in tied[1:]
        )

    for mapping in mappings:
        doc = mapping_doc(mapping)
        produced = set(mapping.key) | set(mapping.fields)
        for field_name in sorted(entity.fields):
            if not entity.fields[field_name].required or field_name in produced:
                continue
            msg = (
                f"entity {entity_name!r} is built from {count} mappings and declares "
                f"{field_name!r} required, but the mapping of {mapping.source!r} does not "
                "produce it — the merge would NULL-fill a required column for that source's "
                "rows alone, so the entity looks internally inconsistent rather than "
                "externally broken (RFC 0024 D4). Fix: map the field in every mapping, or "
                "drop 'required: true'"
            )
            errors.append(ResolutionError(msg, source_path=f"{doc}: fields"))

    errors.extend(_rule_agreement_refusals(entity_name, entity, mappings, relationships, steps))

    if entity.scd == "type2":
        msg = (
            f"entity {entity_name!r} declares 'scd: type2' and is built from {count} "
            "mappings. The collision audit a merge generates would fire on every key "
            "holding versions from two sources, and telling a version from a collision "
            "needs the audit to read the validity interval — which the union's own "
            "lowering does not, even now that the interval is modelled (RFC 0023 §5.3). "
            "So the combination stays refused rather than shipping an audit that blocks "
            "correct data (RFC 0024 D23). Fix: keep one mapping per historical entity"
        )
        errors.append(ResolutionError(msg, source_path=f"entity_model: entities.{entity_name}.scd"))

    errors.extend(_direct_agreement_refusals(entity_name, mappings))

    return errors


# ....................... #


def _direct_path(mapping: Mapping, field_name: str) -> str | None:
    """The ``direct:`` path this mapping records for ``field_name``, if any.

    ``None`` covers three cases, and they are the same answer to D36's
    question — this branch contributes no shadow: the mapping recorded no
    path, it lowered the column with a plain ``from:``, or it lowered the
    column under ``key:``. Only :class:`RecipeFieldMapping` carries ``direct``
    at all, which is why the last two cannot record one.
    """
    field_mapping = mapping.fields.get(field_name)

    if not isinstance(field_mapping, RecipeFieldMapping):
        return None

    return field_mapping.direct


# ....................... #


def _reachable_direct(mapping: Mapping, field_name: str) -> bool:
    """Whether this mapping *could* record a ``direct:`` path for the column.

    Only where it already lowers it as a recipe. A plain ``from:`` mapping
    would have to gain a ``recipe:`` first — ``direct:`` is the path-conflict
    state and there is no conflict without a derivation (RFC 0006 §5.5) — and
    a column lowered under ``key:`` cannot carry one at all, since
    :class:`~bloomery.spec.mapping.KeyFieldMapping` has no such key. The
    refusal below reads this so that it offers each mapping a fix it can
    actually perform.
    """

    return isinstance(mapping.fields.get(field_name), RecipeFieldMapping)


# ....................... #


def _direct_agreement_refusals(
    entity_name: str, mappings: tuple[Mapping, ...]
) -> list[ResolutionError]:
    """Every mapping that produces the column records a ``direct:`` path, or
    none does (RFC 0024 D36).

    D28 refused the combination outright. What it argued from was real and is
    what this preserves: a shadow NULL for one branch's rows is
    indistinguishable from a genuinely NULL direct value, so the reconcile
    audit either reports a false disagreement or quietly stops checking — the
    failure mode this project ranks worst, a check that stops checking. Under
    agreement no branch's shadow is NULL for want of a path, so the audit keeps
    the meaning it has on one source: the recipe-derived value against the
    direct value *that row's own mapping* extracted (D32's principle, applied
    to a second reader).

    **Scoped to the mappings that produce the column**, like
    :func:`_rule_agreement_refusals` and for the same reason: §5.2 rule 3 lets
    a source omit an optional field and fills it with a typed NULL. A branch
    that maps nothing for the field derives nothing, so there is nothing for a
    shadow to disagree with, and requiring a path there would be unfixable —
    ``direct:`` is a key of a *field mapping*, and that mapping does not exist.

    No ``len(mappings) < 2`` guard, unlike :func:`_rule_agreement_refusals`
    beside it: the caller returns before reaching either, so that guard is
    unreachable in both — and here it would also be redundant, since one
    mapping cannot be in ``recording`` and ``silent`` at once and the loop
    finds nothing to report.
    """
    errors: list[ResolutionError] = []
    fields = sorted({name for mapping in mappings for name in _produced(mapping)})

    for field_name in fields:
        # ``_produced``, not ``mapping.fields``: ``resolve.refs`` lets a mapping
        # lower a *declared non-key* entity field under ``key:`` (it refuses
        # only an undeclared name, and the same field under both blocks), so a
        # column can be produced by one branch's ``fields:`` and another's
        # ``key:``. Scoped to ``fields`` alone, that second branch is invisible
        # here, ``_fill`` gives it a typed NULL shadow, and the blocking
        # reconcile audit reports every one of its rows as a disagreement —
        # a false refusal on correct data. The sibling ``_produced`` has
        # always meant key ∪ fields; reading it here is what keeps the two
        # agreement checks scoped the same way.
        producing = [mapping for mapping in mappings if field_name in _produced(mapping)]
        recording = [m for m in producing if _direct_path(m, field_name) is not None]
        silent = [m for m in producing if _direct_path(m, field_name) is None]

        if not recording or not silent:
            continue

        named = ", ".join(sorted(mapping_doc(mapping) for mapping in silent))
        witness = min(recording, key=lambda mapping: mapping.source)
        # The fix each silent mapping can perform, which is not the same one.
        # Only a recipe mapping can record a ``direct:`` path — it is the
        # path-conflict state and there is no conflict without a derivation
        # (RFC 0006 §5.5) — so a column lowered under ``key:`` or by a plain
        # ``from:`` names a key that block does not have.
        #
        # Where *any* silent mapping is of that kind, adding paths to the
        # others is not a fix: the refusal fires while a single silent
        # producer remains, so dropping the witness's path is the only thing
        # that resolves it. The message says which mappings could take one
        # anyway — omitting them made the "lower it without a recipe" clause
        # false about mappings that do have one.
        addable = sorted(mapping_doc(m) for m in silent if _reachable_direct(m, field_name))
        blocked = sorted(mapping_doc(m) for m in silent if not _reachable_direct(m, field_name))
        if not blocked:
            remedy = (
                f"record a direct: path for {field_name!r} in {', '.join(addable)} too, or "
                f"drop it from {mapping_doc(witness)}"
            )
        else:
            remedy = (
                f"drop 'direct:' from {mapping_doc(witness)}. {', '.join(blocked)} "
                f"lower{'' if len(blocked) > 1 else 's'} {field_name!r} without a recipe "
                "(under 'key:', or as a plain 'from:') and only a recipe mapping can record "
                "a direct: path, so this stays refused while that path is there"
            )
            if addable:
                remedy += f" — giving {', '.join(addable)} one as well would not lift it"
        msg = (
            f"entity {entity_name!r} is built from {len(mappings)} mappings and only "
            f"{len(recording)} of the {len(producing)} that produce {field_name!r} record a "
            f"direct: path for it. 'direct:' is per mapping, so this leaves the "
            f"'{field_name}__direct' shadow NULL for the rows of {named}, indistinguishable "
            "from a genuinely NULL direct value, and the reconcile audit either reports a "
            "false disagreement or silently stops checking (RFC 0024 D36, answering D28). "
            f"Fix: {remedy}"
        )
        errors.append(
            ResolutionError(msg, source_path=f"{mapping_doc(witness)}: fields.{field_name}.direct")
        )

    return errors


# ....................... #


def _validity_collisions(entity_name: str, entity: Entity) -> list[ResolutionError]:
    """A ``type2`` entity may not declare a field named like its own validity
    interval (RFC 0023 §5.3).

    The target's snapshot machinery writes ``valid_from``/``valid_to`` onto the
    historical relation, so an authored column of that name is two columns with
    one name: an as-of join would compare the anchor against whichever the
    engine resolved, and neither answer is the one the author meant. On a
    ``type1`` entity the names are ordinary and stay legal — which is why this
    is a refusal here rather than a reserved name everywhere (a business
    ``valid_from`` on a current-view dimension is a perfectly good column).

    ``fields`` alone is the whole declared surface by the time this runs, which
    is why the message can name that one path. ``resolve.refs`` has already
    refused a mapping whose ``key:`` lowers a name the entity does not declare
    ("key lowers unknown field") and an entity key column no mapping lowers
    ("entity key column %r is not lowered by the mapping's key:"), and those two
    compose into ``entity.key`` ⊆ ``entity.fields``. Reading ``key`` here as
    well would be a union that can never differ —
    ``test_a_validity_column_in_the_key_is_refused_before_this_check_sees_it``
    is what fails if that stops being true, rather than this refusal quietly
    narrowing.
    """
    if entity.scd != "type2":
        return []

    collisions = sorted(name for name in entity.fields if name in VALIDITY_COLUMNS)

    if not collisions:
        return []

    listed = ", ".join(repr(name) for name in collisions)
    msg = (
        f"entity {entity_name!r} declares 'scd: type2' and carries {listed}, which is "
        "what the target's snapshot writes for the version's own validity interval "
        "(RFC 0023 §5.3) — the relation would hold two columns of that name and an "
        "as-of join could not tell them apart. Fix: rename the field, or declare the "
        "entity scd: type1"
    )
    return [ResolutionError(msg, source_path=f"entity_model: entities.{entity_name}.fields")]


# ....................... #


#: What the path-conflict guardrail appends to a field's name for its shadow
#: (RFC 0006 §5.5, D7). Declared here rather than imported from
#: ``guardrails.conflict`` because the refusal below runs one stage earlier —
#: ``guardrails`` sits under ``resolve``, and the shadow does not exist yet
#: when the collision has to be refused. Both spellings are pinned together by
#: ``test_the_shadow_suffix_is_the_one_the_guardrail_appends``.
DIRECT_SUFFIX = "__direct"


def _shadow_collisions(
    entity_name: str, entity: Entity, mappings: tuple[Mapping, ...]
) -> list[ResolutionError]:
    """No authored field may occupy the name a ``direct:`` path's shadow takes.

    The guardrail stage adds ``<field>__direct`` beside a field that records
    both a recipe and a direct path, and it adds it only when the entity does
    not already carry a column of that name — an ordinary guard against
    amending the same entity twice (the stage is idempotent by contract). With
    an *authored* column of that name the two coincide: the shadow is dropped
    as already present, the reconcile audit is emitted anyway, and it compares
    the derived value against a column the author mapped from somewhere else
    entirely. That audit is blocking, so the result is a run stopped by a
    comparison nobody asked for, with nothing anywhere naming the collision.

    Conditional rather than a name reserved everywhere, for
    :func:`_validity_collisions`' reason: ``price__direct`` is a perfectly good
    business column on an entity where ``price`` records no ``direct:`` path,
    and refusing it there would cost a real name to prevent nothing.
    """
    recording = {
        field_name
        for mapping in mappings
        for field_name in mapping.fields
        if _direct_path(mapping, field_name) is not None
    }
    collisions = sorted(
        (field_name, f"{field_name}{DIRECT_SUFFIX}")
        for field_name in recording
        if f"{field_name}{DIRECT_SUFFIX}" in entity.fields
    )

    return [
        ResolutionError(
            f"entity {entity_name!r} declares a field {shadow!r} and records a direct: path "
            f"for {field_name!r}, whose shadow column takes that same name (RFC 0006 §5.5). "
            "The generated shadow would be dropped as already present while the reconcile "
            f"audit still reads {shadow!r}, so the audit would compare {field_name!r} against "
            "the authored column — and it is blocking, so it stops the run on a comparison "
            f"nobody declared. Fix: rename the {shadow!r} field, or drop 'direct:' from "
            f"{field_name!r}",
            source_path=f"entity_model: entities.{entity_name}.fields.{shadow}",
        )
        for field_name, shadow in collisions
    ]


# ....................... #


def _lowered_rules(
    entity_name: str,
    entity: Entity,
    mapping: Mapping,
    relationships: tuple[Relationship, ...],
    steps: StepRegistry,
) -> tuple[QualityRuleIR, ...]:
    """One mapping's rules, lowered the way :func:`_build_entity` lowers them."""

    return lower_quality(
        entity, mapping, relationships, _repair_bodies(entity_name, entity, mapping, steps)
    )


# ....................... #


def _produced(mapping: Mapping) -> frozenset[str]:
    """The entity columns this mapping lowers — its key and its fields."""

    return frozenset(mapping.key) | frozenset(mapping.fields)


# ....................... #


def _rules_over(
    rules: tuple[QualityRuleIR, ...], columns: frozenset[str]
) -> tuple[QualityRuleIR, ...]:
    """``rules`` restricted to ``columns``, keeping the column-less ones.

    A row rule — ``expression``, ``referential`` — is lowered from the entity
    model and the relationships, never from a mapping, so it is the same for
    every branch by construction and belongs in every comparison.
    """

    return tuple(rule for rule in rules if rule.column is None or rule.column in columns)


# ....................... #


def _merged_rules(
    entity_name: str,
    entity: Entity,
    mappings: tuple[Mapping, ...],
    relationships: tuple[Relationship, ...],
    steps: StepRegistry,
) -> tuple[QualityRuleIR, ...]:
    """Every rule of an entity, over every mapping that builds it.

    A **union** rather than the first mapping's set, and the difference is one
    case: a column only some mappings produce (§5.2 rule 3). Its rules are real
    and belong to the entity, so taking ``mappings[0]``'s set alone would drop
    the rules of every column the first mapping happens not to map — silently,
    and depending on nothing but which source relation sorts first.

    Rules on a column every mapping produces are identical across them
    (:func:`_rule_agreement_refusals` has refused the entity otherwise), so
    the union deduplicates them by name to the same one tuple that mapping
    would have produced alone.
    """
    by_name: dict[str, QualityRuleIR] = {}

    for mapping in mappings:
        for rule in _lowered_rules(entity_name, entity, mapping, relationships, steps):
            existing = by_name.setdefault(rule.name, rule)
            if existing == rule:
                continue
            # Two *different* rules under one generated name. For a column
            # every mapping produces this cannot happen — the agreement
            # refusal ran first — so what is left is two distinct columns
            # whose names fold to one rule name (`_rule_name` lowercases and
            # replaces non-identifier characters, so `Order-Id` and `Order_Id`
            # both give `order_id_coercible`). Keeping the first would leave
            # the other column with no check at all, silently.
            msg = (
                f"entity {entity_name!r} is built from {len(mappings)} mappings that "
                f"generate two different rules named {rule.name!r} — one on column "
                f"{existing.column!r}, one on {rule.column!r}. Generated names are folded "
                "to the [a-z0-9_]+ shape a flag list can carry unescaped (RFC 0016 D23), so "
                "two columns can fold to one name; merging them would drop one column's "
                "check without saying so. Fix: rename one of the two fields"
            )
            raise ResolutionError(msg, source_path=f"entity_model: entities.{entity_name}.fields")

    return tuple(sorted(by_name.values(), key=quality_sort_key))


# ....................... #


def _rule_agreement_refusals(
    entity_name: str,
    entity: Entity,
    mappings: tuple[Mapping, ...],
    relationships: tuple[Relationship, ...],
    steps: StepRegistry,
) -> list[ResolutionError]:
    """Every mapping of a merged entity lowers the **same rules**, or the
    entity is refused (RFC 0024 D33).

    D33 states the requirement as agreement over ``opts_in`` and names a second
    coupling — two mappings naming different ``repair`` recipes for one column —
    as "the same refusal rather than a fifth case". The check is written
    against the *lowered rule set* rather than against either of those, because
    the rule set is the thing D33's consequence is about: ``lower_quality`` may
    go on taking one ``Mapping`` exactly when every mapping would have produced
    the same tuple from it. Comparing the output rather than enumerating the
    inputs is also what makes this total — ``opts_in`` is a **disjunction** over
    one mapping's fields, so two mappings can agree that the entity joined the
    quality system and still declare disjoint rules (A a ``coercible`` on
    ``amount``, B an ``in_set`` on ``status``), and a set lowered from either
    would be missing half of what the author wrote.

    What is deliberately *not* compared is the per-branch facts D32 moved onto
    :class:`~bloomery.ir.SourceColumnIR`. Source paths and ``enum_map``
    spellings are what a second source is *for*; requiring them to agree would
    refuse every real merge. The rules are invariant because the compiler makes
    them so, and the facts they read are per branch — those are the two halves
    of D32 and D33, and this function is only the second one.

    **Nor is a column only one mapping produces.** §5.2 rule 3 lets a source
    omit an optional field and fills it with a typed NULL, so requiring the
    other mapping to declare the same rules there would refuse the shape the
    RFC exists to allow — and it would be unfixable, because a rule is declared
    on a mapping's *field* and the mapping that omits the field has nothing to
    hang one on. Those rules join the entity's set instead
    (:func:`_merged_rules`), where a branched one is inert on the branch that
    maps nothing (:func:`~bloomery.quality.branch_violation` reads no sources
    as FALSE) and an authored one judges the NULLs that branch supplies, which
    is the true statement about the merged relation.
    """
    if len(mappings) < 2:
        return []

    lowered = {
        mapping.source: _lowered_rules(entity_name, entity, mapping, relationships, steps)
        for mapping in mappings
    }
    errors: list[ResolutionError] = []

    # **Every pair**, not every mapping against the first. A column only some
    # mappings produce is excluded from any comparison the others are in, so
    # against `mappings[0]` alone two *other* mappings could disagree about it
    # and never meet: with A, B and C and an optional column that B and C both
    # map, `A ∩ B` and `A ∩ C` exclude it and B is never compared with C. Both
    # rules then land in the union and one silently wins by name.
    for index, reference in enumerate(mappings):
        for mapping in mappings[index + 1 :]:
            shared = _produced(reference) & _produced(mapping)
            left = _rules_over(lowered[reference.source], shared)
            right = _rules_over(lowered[mapping.source], shared)

            if left == right:
                continue

            msg = (
                f"entity {entity_name!r} is built from {len(mappings)} mappings whose "
                f"'quality:' declarations disagree: {_rule_disagreement(left, right)}. The "
                "rules are evaluated once over the merged relation, so a set lowered from one "
                "mapping would silently drop what the others declared (RFC 0024 D33). Fix: "
                "declare the same rules — and the same transform chains where they generate "
                f"one — in {mapping_doc(reference)} and {mapping_doc(mapping)}, or keep one "
                "mapping per entity"
            )
            errors.append(
                ResolutionError(msg, source_path=f"{mapping_doc(mapping)}: fields"),
            )

    return errors


# ....................... #


def _disposition(rule: QualityRuleIR) -> str:
    """A rule's authored disposition, or ``on_missing`` for the one kind that
    carries no ``on_fail`` at all (``referential``, RFC 0016 D6)."""

    if rule.on_fail is not None:
        return rule.on_fail.value

    return dict(rule.params).get("on_missing", "-")


# ....................... #


def _rule_disagreement(
    baseline: tuple[QualityRuleIR, ...], candidate: tuple[QualityRuleIR, ...]
) -> str:
    """The first difference between two lowered rule sets, in name order.

    One difference rather than all of them: the message routes to a pair of
    documents the author then reads side by side, and a rule set that differs
    at all usually differs everywhere — listing the tail buries the head.
    """
    left = {rule.name: rule for rule in baseline}
    right = {rule.name: rule for rule in candidate}

    for name in sorted(set(left) | set(right)):
        if name not in right:
            return f"{name!r} is declared by the first mapping and not by the second"
        if name not in left:
            return f"{name!r} is declared by the second mapping and not by the first"
        if left[name] != right[name]:
            return (
                f"{name!r} is declared by both and differs — "
                f"{_disposition(left[name])} vs {_disposition(right[name])}, "
                f"params {left[name].params} vs {right[name].params}"
            )

    # Unreachable while the tuples are canonically sorted by name and compared
    # for equality by the caller: two sets with the same names and equal rules
    # *are* equal.
    msg = "rule sets differ but no differing rule was found"
    raise InvariantViolated(msg)


# ....................... #


def _build_entities(
    project: Project, catalog: Catalog | None, reg: Registry, steps: StepRegistry
) -> tuple[EntityIR, ...]:
    """Every mapped entity, each from the mappings that target it (RFC 0024 D1).

    More than one mapping is a **union merge**, which replaces the refusal that
    stood here and kept the promise its message made. The grouping was already
    by-target-then-sorted, so the structure the merge needs is the one the
    refusal was sitting on.
    """
    by_target: dict[str, list[Mapping]] = {}

    for mapping in project.mappings:
        by_target.setdefault(mapping.target, []).append(mapping)

    # Sorted by source relation: this is D3's branch order, established once
    # here so that everything downstream — `EntityIR.sources`, the UNION ALL,
    # the `_source` literals — inherits it rather than re-deriving it.
    grouped = {
        entity_name: tuple(sorted(mappings, key=lambda mapping: mapping.source))
        for entity_name, mappings in by_target.items()
    }
    refusals = [
        error
        for entity_name in sorted(grouped)
        for error in (
            *_merge_refusals(
                entity_name,
                project.entity_model.entities[entity_name],
                grouped[entity_name],
                project.entity_model.relationships,
                steps,
            ),
            *_validity_collisions(entity_name, project.entity_model.entities[entity_name]),
            *_shadow_collisions(
                entity_name,
                project.entity_model.entities[entity_name],
                grouped[entity_name],
            ),
        )
    ]

    if refusals:
        ordered = tuple(sorted(refusals, key=lambda error: (error.source_path or "", str(error))))
        if len(ordered) == 1:
            raise ordered[0]
        raise ResolutionError.from_collected(ordered)

    entities = [
        _build_entity(
            entity_name,
            project.entity_model.entities[entity_name],
            grouped[entity_name],
            project,
            catalog,
            reg,
            steps,
        )
        for entity_name in sorted(grouped)
    ]
    return tuple(entities)  # sorted: `grouped` iterated in sorted order


# ....................... #


def _time_window(window: str | None) -> TimeWindow | None:
    """``"3 months"`` → ``TimeWindow(3, "month")``. The spec pattern has already
    established the shape; :func:`parse_time_window` is the one place the plural
    is dropped, so the IR carries a single spelling of each grain."""

    if window is None:
        return None

    count, grain = parse_time_window(window)
    return TimeWindow(count=count, grain=grain)


# ....................... #


def _derived(derived: DerivedSpec | None) -> DerivedIR | None:
    """The ``derived:`` block as IR — inputs sorted by alias (RFC 0034 D1).

    The alias is the mapping key rather than a field, so it cannot be missing
    and cannot repeat; sorting it here is what makes the tuple deterministic
    without a set ever reaching output (RFC 0003).
    """

    if derived is None:
        return None

    return DerivedIR(
        # ``parse_one`` is annotated with the ``Expr`` base, but every node it
        # returns is an ``Expression`` (cf. ir.nodes).
        expr=canon(cast("Expression", parse_one(derived.expr))),
        inputs=tuple(
            MetricInputIR(
                alias=alias,
                metric=spec.metric,
                offset_window=_time_window(spec.offset.window if spec.offset else None),
                offset_to_grain=spec.offset.to_grain if spec.offset else None,
            )
            for alias, spec in sorted(derived.inputs.items())
        ),
    )


# ....................... #


def _metric_filters(filters: tuple[MetricFilter, ...]) -> tuple[MetricFilterIR, ...]:
    """The ``filter:`` list as IR, in authored order — the clauses are ANDed,
    so the order is cosmetic in SQL and load-bearing in the artifact bytes.

    A ``date``/``datetime`` value becomes its ISO text, the carrier
    :class:`~bloomery.ir.AuditIR` params already use: a temporal literal
    reaches SQL as a quoted string compared in the column's own type, and the
    canonical encoder has no tag for a ``date`` (RFC 0003 §5.4).
    """

    return tuple(
        MetricFilterIR(
            dimension=clause.dimension,
            op=clause.op,
            values=tuple(
                value.isoformat() if isinstance(value, (date, datetime)) else value
                for value in clause.values
            ),
        )
        for clause in filters
    )


# ....................... #


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
                cumulative=(
                    CumulativeIR(
                        period_agg=metric.cumulative.period_agg,
                        window=_time_window(metric.cumulative.window),
                        grain_to_date=metric.cumulative.grain_to_date,
                    )
                    if metric.cumulative is not None
                    else None
                ),
                derived=_derived(metric.derived),
                filter=_metric_filters(metric.filter),
                description=metric.description,
                depends_on=tuple(sorted({*metric.requires, *metric.requires_metrics})),
            )
        )

    return tuple(built)


# ....................... #


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


# ....................... #


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


# ....................... #


def _build_fx_rates(catalog: Catalog | None) -> FxRatesIR | None:
    """Lower the catalog's exchange-rate relation (RFC 0023 §5.4).

    ``None`` for every vertical that never converts, which is what the
    ``convert`` refusal at emit reads: the transform stays legal and
    typechecked, and is refused until a rate relation is declared here."""

    if catalog is None or catalog.fx_rates is None:
        return None

    fx = catalog.fx_rates
    return FxRatesIR(
        relation=fx.relation,
        from_currency=fx.from_,
        to_currency=fx.to,
        rate=fx.rate,
        valid_from=fx.valid_from,
        valid_to=fx.valid_to,
    )


# ....................... #


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


# ....................... #


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
        fx_rates=_build_fx_rates(catalog),
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


# ....................... #
# Currency conversion (RFC 0023 §5.4)

#: The shape :data:`~bloomery.spec.common.CurrencyCode` enforces on a *declared*
#: currency. A transform argument is an ``ArgKind.STR`` and never passed through
#: that annotation, so the same rule is applied here — an unchecked code is not
#: a parse error downstream, it is a predicate that matches no rate row.
_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


def _anchor_expression(
    anchor: str,
    entity_name: str,
    entity: Entity,
    mapping: Mapping,
    reg: Registry,
    steps: StepRegistry,
    *,
    source_path: str,
) -> Expression:
    """The lowered expression for a ``convert`` anchor, or a refusal.

    The anchor names a sibling column — a ``fields:`` entry or a ``key:`` one,
    both of which are direct paths — and what the conversion needs is that
    column's **value**, which in a branch SELECT is its own lowering, not a
    reference to its output name. The silver name does not exist yet where the
    conversion is projected: both are projections of one SELECT, and a lateral
    column alias is a DuckDB extension that Postgres and Trino reject. So the
    chain is lowered a second time, here, into the conversion.
    """
    field = entity.fields.get(anchor)

    if field is None:
        known = sorted(entity.fields)
        msg = (
            f"convert names anchor {anchor!r}, which entity {entity_name!r} does not "
            f"declare; declared fields: {known}. The anchor dates the rate, so it has to "
            "be a column of the row being converted (RFC 0023 §5.4)"
        )
        raise ResolutionError(msg, source_path=source_path)

    declared = _field_type(entity_name, anchor, field)

    if not isinstance(declared, DateType | TimestampType):
        msg = (
            f"convert names anchor {anchor!r}, which is {render_type(declared)} — an as-of "
            "anchor is compared against the rate's validity interval, so it must be a "
            "date or a timestamp (RFC 0023 §5.4). Fix: name the field that dates the "
            "amount, or parse this one into a date first"
        )
        raise ResolutionError(msg, source_path=source_path)

    lowering: KeyField | FieldMapping | None = mapping.fields.get(anchor) or mapping.key.get(anchor)

    if lowering is None:
        msg = (
            f"convert names anchor {anchor!r}, which entity {entity_name!r} declares but "
            f"mapping {mapping.source!r} does not lower. A merged entity's branches map "
            "different columns (RFC 0024 §5.2 rule 3), and the branch that converts is "
            "the one that has to supply the date"
        )
        raise ResolutionError(msg, source_path=source_path)

    # Both direct-path shapes, and they are different classes: `key:` entries
    # are `KeyField`, `fields:` entries are `SimpleFieldMapping`. Testing only
    # the second refused a perfectly ordinary key anchor — and said it was
    # "lowered by a step", which it was not.
    if not isinstance(lowering, SimpleFieldMapping | KeyField):
        kind = "recipe" if isinstance(lowering, RecipeFieldMapping) else "step"
        msg = (
            f"convert names anchor {anchor!r}, which is lowered by a {kind} rather than a "
            "direct from: path. Only a direct path is re-lowered into the conversion "
            "today, because a derived anchor would splice its whole derivation into every "
            "converted column. Fix: map the anchor directly, or convert against a field "
            "that is"
        )
        raise ResolutionError(msg, source_path=source_path)

    return _lower_chain(
        lowering.from_, lowering.transform, declared, reg, steps, source_path=source_path
    )


# ....................... #


def _resolve_conversions(
    expr: Expression,
    entity_name: str,
    entity: Entity,
    mapping: Mapping,
    catalog: Catalog | None,
    reg: Registry,
    steps: StepRegistry,
    *,
    column: str,
    source_path: str,
) -> Expression:
    """Validate every ``convert`` in one lowered column and bind its anchor.

    What comes out is still a :data:`CONVERT_MARKER` call — with the anchor's
    *expression* in place of the field name it was written with. The rate
    relation is named by the catalog and resolved through the naming policy,
    which is an emit concern, so emit finishes the rewrite (RFC 0023 D4 keeps
    the refusal there too, for the project that converts with no rates
    declared).

    The checks live here because here is where the entity, the mapping and the
    catalog are all in scope, and where a refusal can name the document that
    has to change.
    """
    markers = [
        node
        for node in expr.find_all(exp.Anonymous)
        if str(node.this).upper() == CONVERT_MARKER and len(node.expressions) == CONVERT_ARITY
    ]

    if not markers:
        return expr

    declared_currency = _declared_currency(entity, catalog, column)

    for marker in markers:
        from_ccy = marker.expressions[CONVERT_FROM].this
        to_ccy = marker.expressions[CONVERT_TO].this
        anchor = marker.expressions[CONVERT_ANCHOR].this

        for role, code in (("from", from_ccy), ("to", to_ccy)):
            if not _CURRENCY_CODE.fullmatch(code):
                msg = (
                    f"convert names {code!r} as its {role} currency, which is not an "
                    "ISO-4217 code (three uppercase letters). The code is compared "
                    "against the rate relation as written, so this one would match no "
                    "rate and convert every amount to NULL rather than failing"
                )
                raise ResolutionError(msg, source_path=source_path)

        if from_ccy == to_ccy:
            msg = (
                f"convert asks for {from_ccy!r} to {to_ccy!r}, which converts nothing but "
                "still joins the rate relation — a missing self-rate would turn the "
                "amount into NULL. Fix: drop the convert step"
            )
            raise ResolutionError(msg, source_path=source_path)

        if declared_currency is not None and declared_currency != to_ccy:
            msg = (
                f"convert produces {to_ccy!r} but column {column!r} is declared "
                f"{declared_currency!r} in the catalog — the currency guardrail would then "
                "reason about this column in a currency it is not in, which is how a "
                "wrong number passes every check (RFC 0006 D4). Fix: convert to "
                f"{declared_currency!r}, or declare the canonical field as {to_ccy!r}"
            )
            raise ResolutionError(msg, source_path=source_path)

        marker.expressions[CONVERT_ANCHOR] = _anchor_expression(
            anchor, entity_name, entity, mapping, reg, steps, source_path=source_path
        )

    return expr


# ....................... #


def _declared_currency(entity: Entity, catalog: Catalog | None, column: str) -> str | None:
    """The catalog currency of the column being written, or ``None``.

    ``None`` covers both "no catalog" and "no currency declared", which are the
    same fact here: nothing to disagree with, so the conversion is unconstrained.
    """
    field = entity.fields.get(column)

    if field is None or field.canonical is None or catalog is None:
        return None

    canonical = catalog.canonical_fields.get(field.canonical)

    return None if canonical is None else canonical.currency
