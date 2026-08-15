"""Step lowering: manifest × wiring → :class:`StepIR` (RFC 0017 §5.6).

This is where the platform's declaration and the authored spec's wiring meet,
and where every compile-time refusal about a step is decided. It lives in
``resolve`` rather than in ``bloomery.steps`` for a layering reason worth
stating: ``bloomery.steps`` sits *below* the IR so that
:mod:`bloomery.steps.contract` can be imported by generated code without
dragging the compile pipeline behind it, and a module that builds
:class:`StepIR` cannot sit below the IR it builds.

**Refusals are batched** (RFC 0006 D2): every step is validated, then the
whole crop is raised as one aggregate. An author fixing a wiring should see
all of it in one round-trip, not discover the next problem on the next run.

They are :class:`StepError` leaves rather than :class:`GuardrailError` ones,
and that is not an oversight. A guardrail says *the model is wrong* — an
arithmetic, grain or additivity claim about specs that all parsed. These say
the step *reference* does not resolve, or that the step itself is disqualified
from a pipeline that must be able to restate. Different question, different
stage, different aggregate.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from bloomery.errors import BloomeryError, StepDeterminismError, StepError, UnknownStep
from bloomery.ir import (
    ColumnIR,
    Determinism,
    EntityIR,
    Lineage,
    Materialization,
    OnFail,
    QualityRuleIR,
    SCDKind,
    SourceColumnIR,
    SourceIR,
    StepColumnIR,
    StepIR,
    StepKind,
    StepOutputIR,
    StepParameterIR,
    canon,
    step_sort_key,
)
from bloomery.steps import EMPTY_REGISTRY
from bloomery.typing import parse_type

if TYPE_CHECKING:
    from sqlglot.expressions.core import Expression

    from bloomery.spec.project import Project
    from bloomery.spec.steps import StepWiring
    from bloomery.steps import StepManifest, StepRegistry

__all__ = [
    "lower_steps",
    "output_canonicals",
    "step_entities",
]


def _path(wiring: StepWiring) -> str:
    return f"steps: steps.{wiring.use}"


def _check_determinism(wiring: StepWiring, manifest: StepManifest) -> list[BloomeryError]:
    """§5.5, D5 — both arms.

    ``nondeterministic`` is refused outright: a step that reads a clock, the
    network or unseeded randomness makes a backfill disagree with the original
    run, which destroys the ability to restate. That is the capability the
    whole architecture is organized around, so this refusal is load-bearing
    rather than cautious.

    ``seeded`` without a seed is the same failure wearing a different hat —
    the step *can* be deterministic and this wiring has not made it so. A seed
    on a ``pure`` step is refused too: it is either a lie about the step or a
    misunderstanding of the tier, and silently ignoring the value would leave
    an author believing something is pinned that is not.
    """
    errors: list[BloomeryError] = []
    if manifest.determinism == "nondeterministic":
        msg = (
            f"step {wiring.use!r} declares determinism: nondeterministic (RFC 0017 §5.5). "
            "A backfill of a nondeterministic step disagrees with the original run, which "
            "destroys restatement — the capability this architecture exists to provide. "
            "Fix: make the step deterministic and declare pure, or seed it and declare "
            "seeded"
        )
        errors.append(StepDeterminismError(msg, source_path=_path(wiring)))
    elif manifest.determinism == "seeded" and wiring.seed is None:
        msg = (
            f"step {wiring.use!r} declares determinism: seeded but the wiring sets no "
            "seed, so two runs may disagree and a backfill cannot be trusted "
            "(RFC 0017 §5.5). Fix: add seed: <int>"
        )
        errors.append(StepDeterminismError(msg, source_path=_path(wiring)))
    elif manifest.determinism == "pure" and wiring.seed is not None:
        msg = (
            f"step {wiring.use!r} sets a seed, but the step declares determinism: pure — "
            "a pure step reads no randomness, so nothing would consume it. Fix: drop the "
            "seed, or have the step declare seeded if it does draw from a generator"
        )
        errors.append(StepDeterminismError(msg, source_path=_path(wiring)))
    return errors


def _check_bindings(wiring: StepWiring, manifest: StepManifest) -> list[BloomeryError]:
    """Inputs and outputs must name what the manifest declares, and every
    declared output must be bound.

    An unbound output is refused rather than defaulted: each output gets its
    own generated wrapper model (D16), so an unbound one is a relation nobody
    named and nothing would write to — the compiler would have to invent a
    name, which is exactly the guessing this project refuses.
    """
    errors: list[BloomeryError] = []
    for label, bound, declared in (
        ("input", set(wiring.inputs), set(manifest.inputs)),
        ("output", set(wiring.outputs), set(manifest.outputs)),
    ):
        unknown = sorted(bound - declared)
        if unknown:
            msg = (
                f"step {wiring.use!r} binds {label}(s) {', '.join(unknown)}, which the "
                f"manifest does not declare; declared {label}s: "
                f"{', '.join(sorted(declared)) or '(none)'}"
            )
            errors.append(StepError(msg, source_path=_path(wiring)))
    unbound = sorted(set(manifest.outputs) - set(wiring.outputs))
    if unbound:
        msg = (
            f"step {wiring.use!r} leaves output(s) {', '.join(unbound)} unbound; every "
            "declared output becomes its own model (RFC 0017 D16), so each needs a "
            "relation to write to. Fix: bind them under outputs:"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    missing_inputs = sorted(set(manifest.inputs) - set(wiring.inputs))
    if missing_inputs:
        msg = (
            f"step {wiring.use!r} does not bind input(s) {', '.join(missing_inputs)} the "
            "manifest declares; the step reads them, so there is nothing to read from"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    return errors


def _check_parameters(wiring: StepWiring, manifest: StepManifest) -> list[BloomeryError]:
    """Parameters must be declared and within their declared bounds (§5.2).

    This is the enforcement half of "parameterize, never fork" (§5.7): bounds
    are only a contract if setting a value outside them is an error, and a
    parameter checked at compile is one that cannot surprise somebody's Python
    halfway through a run.
    """
    errors: list[BloomeryError] = []
    unknown = sorted(set(wiring.parameters) - set(manifest.parameters))
    if unknown:
        msg = (
            f"step {wiring.use!r} sets parameter(s) {', '.join(unknown)} the manifest does "
            f"not declare; declared: {', '.join(sorted(manifest.parameters)) or '(none)'}"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    for name in sorted(set(wiring.parameters) & set(manifest.parameters)):
        spec, value = manifest.parameters[name], wiring.parameters[name]
        if spec.min is None and spec.max is None:
            continue
        try:
            numeric = Decimal(str(value))
            # Inside the guard on purpose: Decimal("NaN") *constructs* fine and
            # raises on comparison, so a guard around construction alone let
            # InvalidOperation escape compile_project — a non-BloomeryError
            # crossing the boundary, which RFC 0002's contract forbids.
            out_of_range = (spec.min is not None and numeric < spec.min) or (
                spec.max is not None and numeric > spec.max
            )
        except InvalidOperation:
            msg = (
                f"step {wiring.use!r} sets parameter {name!r} to {value!r}, which is not "
                f"numeric, but the manifest bounds it (min {spec.min}, max {spec.max})"
            )
            errors.append(StepError(msg, source_path=_path(wiring)))
            continue
        if out_of_range:
            msg = (
                f"step {wiring.use!r} sets parameter {name!r} to {value}, outside the "
                f"declared bounds (min {spec.min}, max {spec.max})"
            )
            errors.append(StepError(msg, source_path=_path(wiring)))
    return errors


def _claims(wiring: StepWiring) -> list[tuple[str, str]]:
    """What a step would write, for the collision check to see even when the
    step itself failed validation — otherwise the author fixes one error,
    re-runs, and only then learns two steps claim one relation."""
    return [
        (relation.rsplit(".", 1)[-1], f"{wiring.ref}@{wiring.version}.{name}")
        for name, relation in sorted(wiring.outputs.items())
    ]


def _check_parameter_types(
    wiring: StepWiring, manifest: StepManifest, resolved: dict[str, str]
) -> list[BloomeryError]:
    """Every resolved value must parse as its declared type.

    The emitter rebuilds a real ``int``/``Decimal``/``date`` from this text
    (§5.8), so a value that will not parse used to surface as a bare
    ``ValueError`` out of ``int()`` — a non-``BloomeryError`` crossing the
    compile boundary, which RFC 0002 forbids — or, for the temporal and
    decimal constructors, as an exception at *model import* in somebody's
    warehouse. Checked here, where it is a spec error with the step's name on
    it. Manifest **defaults** are checked too: they resolve into the IR
    exactly like an authored value and were the path that crashed.
    """
    errors: list[BloomeryError] = []
    for name in sorted(resolved):
        declared = manifest.parameters[name].type.split("(", 1)[0].strip()
        value = resolved[name]
        problem: str | None = None
        if declared == "int":
            try:
                int(value)
            except ValueError:
                problem = "an integer"
        elif declared == "decimal":
            try:
                if not Decimal(value).is_finite():
                    problem = "a finite decimal"
            except InvalidOperation:
                problem = "a decimal"
        elif declared == "date":
            # `date`, not `datetime`: the emitter renders
            # `_blm_date.fromisoformat(...)`, which rejects a time component.
            # Checking with the wider constructor let `2024-01-01T10:00:00`
            # pass compile and fail at model import — the failure this whole
            # function exists to move to compile time (D34).
            try:
                date.fromisoformat(value)
            except ValueError:
                problem = "an ISO date"
        elif declared == "timestamp":
            try:
                datetime.fromisoformat(value)
            except ValueError:
                problem = "an ISO timestamp"
        if problem is not None:
            msg = (
                f"step {wiring.use!r} resolves parameter {name!r} to {value!r}, which is "
                f"not {problem} as the manifest declares (RFC 0017 §5.2). The generated "
                "wrapper builds the real value from this text, so an unparseable one "
                "fails at model import rather than here"
            )
            errors.append(StepError(msg, source_path=_path(wiring)))
    return errors


def _resolved_parameters(wiring: StepWiring, manifest: StepManifest) -> tuple[StepParameterIR, ...]:
    """Every parameter the step will run with — the wiring's values over the
    manifest's defaults — sorted by name.

    Defaults are *resolved* rather than left implicit because the IR is what
    the fingerprint covers (D15): a step whose behaviour depends on a default
    must restate when that default changes, and it can only do that if the
    value is recorded. Values are stringified so the canonical encoding never
    meets a float (RFC 0003 D5); the declared type travels beside each one so
    the generated wrapper can rebuild the real value (§5.8).
    """
    return tuple(
        StepParameterIR(name=name, value=value, type=manifest.parameters[name].type)
        for name, value in sorted(_resolved_values(wiring, manifest).items())
    )


def _resolved_values(wiring: StepWiring, manifest: StepManifest) -> dict[str, str]:
    """The wiring's values over the manifest's defaults, as text. Only the
    parameters the manifest declares — an undeclared one is
    :func:`_check_parameters`' refusal, and including it here would make this
    function crash on the lookup before that refusal could be reported."""
    resolved: dict[str, str] = {
        name: str(spec.default)
        for name, spec in manifest.parameters.items()
        if spec.default is not None
    }
    resolved.update(
        {
            name: str(value)
            for name, value in wiring.parameters.items()
            if name in manifest.parameters
        }
    )
    return resolved


def _outputs(wiring: StepWiring, manifest: StepManifest) -> tuple[StepOutputIR, ...]:
    path = _path(wiring)
    outputs: list[StepOutputIR] = []
    for name in sorted(set(wiring.outputs) & set(manifest.outputs)):
        declared = manifest.outputs[name]
        outputs.append(
            StepOutputIR(
                name=name,
                relation=wiring.outputs[name],
                grain=declared.grain,
                key=declared.key,
                references=tuple(sorted(declared.references.items())),
                columns=tuple(
                    StepColumnIR(
                        name=column,
                        type=parse_type(produces.type, source_path=path),
                        required=produces.required,
                    )
                    for column, produces in sorted(declared.produces.items())
                ),
            )
        )
    return tuple(outputs)


def _emitted_name(relation: str) -> str:
    """The bare relation an output actually emits to.

    Compared instead of the authored binding because the naming policy owns
    the namespace: ``a.customer`` and ``b.customer`` are different strings and
    the *same* emitted model. Comparing the bindings let both through and
    produced two files at one path, the last of which won.
    """
    return relation.rsplit(".", 1)[-1]


def _check_duplicate_relations(
    steps: tuple[StepIR, ...],
    entity_names: frozenset[str],
    also_claimed: tuple[tuple[str, str], ...] = (),
) -> list[BloomeryError]:
    """Two writers for one emitted relation is a compile error (§5.8, D8 —
    settling Document 5 §11.5 explicitly rather than assuming it away).

    Refused rather than merged or ordered: each output is its own model, so
    two claims on one relation is two models at one path, and whichever ran
    last would silently win. Caught three ways — between two steps, within one
    step's ``outputs:`` block, and against an **entity** of the same name,
    which collides just as hard and was the case nothing checked at all.
    """
    seen: dict[str, str] = {name: f"entity {name!r}" for name in entity_names}
    errors: list[BloomeryError] = []
    claims: list[tuple[str, str]] = [
        (_emitted_name(output.relation), f"{step.ref}@{step.version}.{output.name}")
        for step in steps
        for output in step.outputs
    ]
    claims.extend(also_claimed)
    for emitted, claimant in sorted(claims):
        if emitted in seen and seen[emitted] != f"step output {claimant}":
            msg = (
                f"relation {emitted!r} is written by two things: {seen[emitted]} and "
                f"step output {claimant} (RFC 0017 §5.8, D8). Each becomes its own "
                "model, so one relation with two writers is two models at one path "
                "and the last run wins. Fix: bind one of them to a different relation"
            )
            errors.append(StepError(msg, source_path=f"steps: steps.{claimant}"))
            continue
        seen[emitted] = f"step output {claimant}"
    return errors


def _check_scope(wiring: StepWiring, manifest: StepManifest) -> list[BloomeryError]:
    """Refuse what M13 does not implement, rather than accepting it silently.

    Two gaps, both of which used to compile clean and produce nothing:

    **Tier 1.** ``macro_expression`` exists and is tested, but there is no
    spec surface by which a mapping *references* a macro step, so a wired
    ``sql_macro`` bound an output relation and then emitted nothing at all.
    Documenting a splice that does not happen is worse than not shipping the
    tier, so it is refused until the reference surface exists.

    **Quality rules on outputs.** §5.2 permits them and §1 makes them the
    reason RFC 0016 and 0017 ship as a pair. They parse, and nothing consumes
    them: an author would write a rule, get no rule, and get no error either.
    A silently ignored quality rule is the worst possible failure for a
    feature whose entire job is to catch bad data.
    """
    errors: list[BloomeryError] = []
    if manifest.kind == "sql_macro":
        msg = (
            f"step {wiring.use!r} is a sql_macro, which is not wired here: Tier 1 splices "
            "into the consuming model's query (RFC 0017 §5.1), so it writes no relation "
            "and has no output to bind. A macro is referenced from the mapping that uses "
            "it, as a field's step:/from: pair (D50) — which is also what lets one macro "
            "serve several call sites with different arguments"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    routed = sorted(rule.name for rule in wiring.quality if rule.on_fail != "fail")
    if routed:
        msg = (
            f"step {wiring.use!r} declares quality rule(s) {', '.join(routed)} on its "
            "outputs with a disposition other than on_fail: fail (RFC 0017 D39). flag and "
            "quarantine compile into the silver SELECT — the _quality_flags projection and "
            "the routing WHERE — and a step-produced relation has no SELECT: its wrapper "
            "writes the rows. Only on_fail: fail lowers, as an audit over the relation. "
            "Fix: use on_fail: fail, or move the rule to a downstream mapped entity"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    return errors


def _check_canonical(wiring: StepWiring, manifest: StepManifest) -> list[BloomeryError]:
    """Each ``canonical:`` link names a column the bound output actually
    produces (D49).

    The output name is the spec layer's business and already checked there;
    the *column* is not, because only the manifest says what an output
    produces and the spec layer has never seen one. A link naming a column
    that does not exist would draw a DAG edge from a field nothing writes, so
    a metric would read as reachable and its mart would then fail to build —
    the kind of late failure this stage exists to pull forward.
    """
    errors: list[BloomeryError] = []
    for output, links in sorted(wiring.canonical.items()):
        declared = manifest.outputs.get(output)
        if declared is None:  # pragma: no cover — _check_bindings refuses this first
            continue
        missing = sorted(set(links) - set(declared.produces))
        if missing:
            msg = (
                f"step {wiring.use!r} links canonical field(s) to column(s) "
                f"{', '.join(missing)} of output {output!r}, which it does not produce; "
                f"produced: {', '.join(sorted(declared.produces))}"
            )
            errors.append(StepError(msg, source_path=_path(wiring)))
    return errors


def _check_body(
    wiring: StepWiring, manifest: StepManifest, body: str | None
) -> list[BloomeryError]:
    """A Tier 2 step needs a body in the registry.

    Without one the emitter rendered a MODEL with an empty SELECT — a
    syntactically fine artifact that no engine can run. D19's whole point is
    that a bad body is a compile error naming the step, not something an
    engine discovers later, and a *missing* body is the same statement.
    """
    if manifest.kind in {"sql_macro", "sql_model"} and body is None:
        msg = (
            f"step {wiring.use!r} is a {manifest.kind} but the registry carries no body "
            "for it (RFC 0017 §5.3). bloomery parses Tier 1 and Tier 2 bodies at compile; "
            "with none there it would emit a model with no query at all. Fix: add the "
            "body to the registry's macro_bodies/sql_bodies"
        )
        return [StepError(msg, source_path=_path(wiring))]
    return []


def _check_placeholders(
    wiring: StepWiring,
    manifest: StepManifest,
    node: Expression,
    resolved: dict[str, str],
) -> list[BloomeryError]:
    """A Tier 2 body's ``:name`` placeholders and its *resolved* parameters
    name exactly the same set (§10, settled).

    Resolved, not declared: a manifest parameter with no default that the
    wiring never sets is declared and has no value, so checking against
    ``manifest.parameters`` let it through to emit as an unsubstituted
    ``$p`` — the same hole this check exists to close, one path over.

    Both directions are refusals, and each closes a silent hole:

    - a placeholder nothing declares emitted **unsubstituted**, so the engine
      met an unknown macro variable — the author wrote a parameter, got no
      parameter, and got no error;
    - a declared parameter the body never mentions changes the step's
      fingerprint and no SQL, so bumping it restates the outputs and
      reproduces byte-identical data. That is the same "believing something is
      pinned that is not" D18(c) refused for a seed on a ``pure`` step.

    Tier 1 is deliberately excluded: a ``sql_macro``'s placeholders are the
    *columns* its call site supplies, which is why :func:`macro_expression`
    ignores an unused argument rather than refusing it.
    """
    if manifest.kind != "sql_model":
        return []
    used = {
        placeholder.this
        for placeholder in node.find_all(exp.Placeholder)
        if isinstance(placeholder.this, str)
    }
    declared = set(manifest.parameters)
    available = set(resolved)
    errors: list[BloomeryError] = []
    # Split so the message names the actual fault: a typo in the body, versus
    # a parameter that is declared but was never given a value.
    if undeclared := sorted(used - declared):
        msg = (
            f"step {wiring.use!r} has a body referencing :{', :'.join(undeclared)}, which "
            f"the manifest does not declare as a parameter (declared: "
            f"{', '.join(sorted(declared)) or 'none'}). An unsubstituted placeholder "
            "reaches the engine as an unknown variable"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    if unresolved := sorted((used & declared) - available):
        msg = (
            f"step {wiring.use!r} has a body referencing :{', :'.join(unresolved)}, which "
            "the manifest declares with no value: it has no default and the wiring does "
            "not set it, so the placeholder would be emitted unsubstituted. Fix: set it "
            "in the step's parameters:, or give the manifest a default"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    variants = sorted(
        name
        for name in used & available
        if manifest.parameters[name].type.split("(", 1)[0].strip() == "variant"
    )
    if variants:
        msg = (
            f"step {wiring.use!r} substitutes parameter(s) {', '.join(variants)} of type "
            "variant into its body, which bloomery cannot spell portably: DuckDB, "
            "Postgres and Trino do not write a semi-structured literal the same way, and "
            "emitting one of the three would compile everywhere and compare correctly in "
            "one. Fix: pass the value as a string/int/decimal parameter and cast in the "
            "body, or keep the structure in a relation the body joins"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    if unused := sorted(available - used):
        msg = (
            f"step {wiring.use!r} resolves parameter(s) {', '.join(unused)} that its body "
            "never uses (RFC 0017 §5.8). The value is part of the step's identity, so "
            "changing it would restate the outputs and recompute the same rows. Fix: "
            f"reference :{unused[0]} in the body, or drop it from the manifest"
        )
        errors.append(StepError(msg, source_path=_path(wiring)))
    return errors


def _parse_body(wiring: StepWiring, body: str) -> tuple[object | None, list[BloomeryError]]:
    """A Tier 1/2 body, parsed at compile (§5.8).

    Parsing is the whole of what bloomery does with step SQL — text in, AST
    out, never execution — and doing it here rather than at emit means an
    unparseable body is a compile error naming the step, not a broken artifact
    discovered by an engine. It is also what makes a ``sql_macro`` splice
    possible at all: an expression has to be an AST before it can be
    substituted into a SELECT.
    """
    try:
        return sqlglot.parse_one(body), []
    # The base class, not `ParseError`: `TokenError` is its *sibling* under
    # `SqlglotError`, so an unterminated string (`SELECT 'abc`) bypassed a
    # `ParseError`-only handler and crossed the compile boundary as a
    # non-`BloomeryError` — which RFC 0002 forbids.
    except SqlglotError as exc:
        msg = (
            f"step {wiring.use!r} has a body that does not parse as SQL: {exc}. Bloomery "
            "parses Tier 1 and Tier 2 bodies at compile (RFC 0017 §5.8), so this is a "
            "registry error rather than something an engine discovers later"
        )
        return None, [StepError(msg, source_path=_path(wiring))]


def step_entities(
    steps: tuple[StepIR, ...], project: Project | None = None
) -> tuple[EntityIR, ...]:
    """One :class:`EntityIR` per step output (RFC 0017 §5.8).

    This is what §5.8 means by "step outputs are entities in the DAG:
    downstream mappings, marts, and metrics reference them like any silver
    entity". Without it a step's outputs existed only inside ``StepIR``, so a
    mart over one was refused with "no mapping lowers it" and §5.4's promise
    that downstream models typecheck against ``produces`` was not true.

    Three fields have no natural value and are chosen rather than derived, so
    they are stated here instead of being discovered later:

    - ``source`` is mandatory on an entity and a step has no bronze relation.
      It names the relation the step itself writes — the honest reading, since
      that *is* where the rows come from as far as anything downstream can
      tell.
    - ``materialization`` is ``FULL`` and ``scd`` is ``TYPE1``, matching what
      the generated wrapper already declares (``kind="FULL"``). Deriving
      something else would put the IR and the artifact into disagreement.
    - ``produced_by`` marks it so the emitter's entity loop skips it; the
      wrapper owns emission.
    - each column's ``expr`` is the column referring to itself. A step column
      has no lowering — the wrapper wrote it — and an identity is what a
      downstream model selecting from the relation would emit anyway.

    ``quality`` carries the wiring's ``on_fail: fail`` rules, routed by
    ``applies_to`` (D39). They live on the *entity* rather than on a new
    ``StepOutputIR`` field for a reason worth stating: ``EntityIR.quality``
    already exists, so nothing about the IR's shape changes and no fingerprint
    moves for a project that declares no rule — where a new IR field would
    move every fingerprint in the corpus, the type-driven encoder covering
    field names and count rather than values (RFC 0003).

    ``flag`` and ``quarantine`` stay refused in :func:`_check_scope`: both
    compile into a silver *SELECT* — the ``_quality_flags`` projection and the
    routing ``WHERE`` — and a step-produced relation has none, because its
    wrapper writes the rows.
    """
    rules = _output_rules(project)
    links = output_canonicals(project)
    entities: list[EntityIR] = []
    for step in steps:
        for output in step.outputs:
            entities.append(
                EntityIR(
                    name=output.relation.rsplit(".", 1)[-1],
                    grain=output.grain,
                    key=output.key,
                    scd=SCDKind.TYPE1,
                    materialization=Materialization.FULL,
                    partition_by=(),
                    columns=tuple(
                        ColumnIR(
                            name=column.name,
                            type=column.type,
                            canonical=links.get((step.ref, step.version, output.name), {}).get(
                                column.name
                            ),
                            unit=None,
                            tax_basis=None,
                            renamed_from=None,
                            required=column.required,
                        )
                        for column in output.columns
                    ),
                    source=SourceIR(
                        relation=output.relation,
                        # A step column has no lowering: the wrapper wrote it.
                        # The expression is the column referring to itself,
                        # which is exactly what a downstream model selecting
                        # from this relation would emit — an honest identity
                        # rather than a fabricated derivation. It lives here
                        # with every other per-source projection (RFC 0024
                        # D26) even though a step output has exactly one
                        # source and always will.
                        columns=tuple(
                            SourceColumnIR(name=column.name, expr=canon(exp.column(column.name)))
                            for column in sorted(output.columns, key=lambda c: c.name)
                        ),
                    ),
                    quality=rules.get((step.ref, step.version, output.name), ()),
                    produced_by=f"{step.ref}@{step.version}",
                )
            )
    return tuple(sorted(entities, key=lambda entity: entity.name))


def output_canonicals(
    project: Project | None,
) -> dict[tuple[str, int, str], dict[str, str]]:
    """Authored ``canonical:`` links, keyed by ``(ref, version, output)``.

    Shared by :func:`step_entities` and the DAG builder on purpose: the IR's
    ``ColumnIR.canonical`` and the graph's ``canonical`` edge are two readings
    of one declaration, and deriving them separately is how they drift — a
    column claiming a link the graph never drew reads as reachable and then
    has no derivation path.
    """
    if project is None or project.steps is None:
        return {}
    return {
        (wiring.ref, wiring.version, output): dict(links)
        for wiring in project.steps.steps
        for output, links in wiring.canonical.items()
    }


def _output_rules(
    project: Project | None,
) -> dict[tuple[str, int, str], tuple[QualityRuleIR, ...]]:
    """Authored ``on_fail: fail`` rules, keyed by ``(ref, version, output)``.

    ``applies_to`` is what makes this addressable: an entity's ``quality:`` has
    one relation to mean, a step has several, so a rule names the output it
    judges (§5.2). Rules of one output are sorted by name so the entity's
    ``quality`` tuple is canonical whatever order they were authored in.
    """
    if project is None or project.steps is None:
        return {}
    rules: dict[tuple[str, int, str], list[QualityRuleIR]] = {}
    for wiring in project.steps.steps:
        for rule in wiring.quality:
            output = wiring.applies_to.get(rule.name)
            if output is None:  # pragma: no cover — the spec model requires it
                continue
            rules.setdefault((wiring.ref, wiring.version, output), []).append(
                QualityRuleIR(
                    name=rule.name,
                    kind="expression",
                    column=None,
                    on_fail=OnFail(rule.on_fail),
                    params=(("expr", rule.expr),),
                )
            )
    return {key: tuple(sorted(value, key=lambda rule: rule.name)) for key, value in rules.items()}


def lower_steps(project: Project, registry: StepRegistry = EMPTY_REGISTRY) -> tuple[StepIR, ...]:
    """Every wired step as a :class:`StepIR`, sorted by ``(ref, version)``.

    Raises a batched :class:`~bloomery.errors.StepError` if any step fails to
    resolve or is disqualified; returns ``()`` for a project that wires none,
    which is every project that has never heard of steps.
    """
    if project.steps is None or not project.steps.steps:
        return ()

    errors: list[BloomeryError] = []
    steps: list[StepIR] = []
    claimed: list[tuple[str, str]] = []
    for wiring in project.steps.steps:
        try:
            manifest = registry.resolve(wiring.ref, wiring.version, source_path=_path(wiring))
        except UnknownStep as exc:
            errors.append(exc)
            continue
        body = registry.macro_body(wiring.ref, wiring.version) or registry.sql_body(
            wiring.ref, wiring.version
        )
        step_errors = [
            *_check_scope(wiring, manifest),
            *_check_determinism(wiring, manifest),
            *_check_bindings(wiring, manifest),
            *_check_parameters(wiring, manifest),
            *_check_body(wiring, manifest, body),
            *_check_canonical(wiring, manifest),
        ]
        resolved = _resolved_values(wiring, manifest)
        step_errors.extend(_check_parameter_types(wiring, manifest, resolved))
        errors.extend(step_errors)
        if step_errors:
            # Its relations still enter the collision check below: skipping a
            # failing step there meant an author fixed a determinism error,
            # re-ran, and only then learned two steps claim one relation —
            # the second round-trip this module exists to prevent.
            claimed.extend(_claims(wiring))
            continue
        parsed = None
        if body is not None:
            node, body_errors = _parse_body(wiring, body)
            errors.extend(body_errors)
            if body_errors:
                claimed.extend(_claims(wiring))
                continue
            tree = cast("Expression", node)
            placeholder_errors = _check_placeholders(wiring, manifest, tree, resolved)
            errors.extend(placeholder_errors)
            if placeholder_errors:
                claimed.extend(_claims(wiring))
                continue
            parsed = canon(tree)
        steps.append(
            StepIR(
                ref=manifest.ref,
                version=manifest.version,
                kind=StepKind(manifest.kind),
                determinism=Determinism(manifest.determinism),
                runtime_lock=manifest.runtime_lock,
                lineage=Lineage(manifest.lineage),
                outputs=_outputs(wiring, manifest),
                inputs=tuple(sorted(wiring.inputs.items())),
                parameters=_resolved_parameters(wiring, manifest),
                seed=wiring.seed,
                entrypoint=manifest.entrypoint,
                body=parsed,
            )
        )

    ordered = tuple(sorted(steps, key=step_sort_key))
    errors.extend(
        _check_duplicate_relations(
            ordered, frozenset(project.entity_model.entities), tuple(claimed)
        )
    )
    if errors:
        batched = tuple(sorted(errors, key=lambda e: (e.source_path or "", str(e))))
        if len(batched) == 1:
            raise batched[0]
        raise StepError.from_collected(batched)
    return ordered
