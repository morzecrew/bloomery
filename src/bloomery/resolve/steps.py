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

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, cast

import sqlglot
from sqlglot.errors import ParseError

from bloomery.errors import BloomeryError, StepDeterminismError, StepError, UnknownStep
from bloomery.ir import (
    Determinism,
    Lineage,
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
            errors.append(UnknownStep(msg, source_path=_path(wiring)))
    unbound = sorted(set(manifest.outputs) - set(wiring.outputs))
    if unbound:
        msg = (
            f"step {wiring.use!r} leaves output(s) {', '.join(unbound)} unbound; every "
            "declared output becomes its own model (RFC 0017 D16), so each needs a "
            "relation to write to. Fix: bind them under outputs:"
        )
        errors.append(UnknownStep(msg, source_path=_path(wiring)))
    missing_inputs = sorted(set(manifest.inputs) - set(wiring.inputs))
    if missing_inputs:
        msg = (
            f"step {wiring.use!r} does not bind input(s) {', '.join(missing_inputs)} the "
            "manifest declares; the step reads them, so there is nothing to read from"
        )
        errors.append(UnknownStep(msg, source_path=_path(wiring)))
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
        errors.append(UnknownStep(msg, source_path=_path(wiring)))
    for name in sorted(set(wiring.parameters) & set(manifest.parameters)):
        spec, value = manifest.parameters[name], wiring.parameters[name]
        if spec.min is None and spec.max is None:
            continue
        try:
            numeric = Decimal(str(value))
        except InvalidOperation:
            msg = (
                f"step {wiring.use!r} sets parameter {name!r} to {value!r}, which is not "
                f"numeric, but the manifest bounds it (min {spec.min}, max {spec.max})"
            )
            errors.append(UnknownStep(msg, source_path=_path(wiring)))
            continue
        if (spec.min is not None and numeric < spec.min) or (
            spec.max is not None and numeric > spec.max
        ):
            msg = (
                f"step {wiring.use!r} sets parameter {name!r} to {value}, outside the "
                f"declared bounds (min {spec.min}, max {spec.max})"
            )
            errors.append(UnknownStep(msg, source_path=_path(wiring)))
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
    resolved: dict[str, str] = {
        name: str(spec.default)
        for name, spec in manifest.parameters.items()
        if spec.default is not None
    }
    resolved.update({name: str(value) for name, value in wiring.parameters.items()})
    return tuple(
        StepParameterIR(name=name, value=value, type=manifest.parameters[name].type)
        for name, value in sorted(resolved.items())
    )


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


def _check_duplicate_relations(steps: tuple[StepIR, ...]) -> list[BloomeryError]:
    """Two steps writing one relation is a compile error (§5.8, D8 — settling
    Document 5 §11.5 explicitly rather than assuming it away).

    Refused rather than merged or ordered: each output is its own model, so
    two claims on one relation is two models at one path, and whichever ran
    last would silently win. Also caught within a single step, where the same
    mistake is a copy-paste in the ``outputs:`` block.
    """
    seen: dict[str, str] = {}
    errors: list[BloomeryError] = []
    for step in steps:
        for output in step.outputs:
            claimant = f"{step.ref}@{step.version}.{output.name}"
            if output.relation in seen:
                msg = (
                    f"relation {output.relation!r} is written by two step outputs: "
                    f"{seen[output.relation]} and {claimant} (RFC 0017 §5.8, D8). Each "
                    "output becomes its own model, so one relation with two writers is "
                    "two models at one path and the last run wins. Fix: bind one of them "
                    "to a different relation"
                )
                errors.append(
                    UnknownStep(msg, source_path=f"steps: steps.{step.ref}@{step.version}")
                )
                continue
            seen[output.relation] = claimant
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
    except ParseError as exc:
        msg = (
            f"step {wiring.use!r} has a body that does not parse as SQL: {exc}. Bloomery "
            "parses Tier 1 and Tier 2 bodies at compile (RFC 0017 §5.8), so this is a "
            "registry error rather than something an engine discovers later"
        )
        return None, [UnknownStep(msg, source_path=_path(wiring))]


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
    for wiring in project.steps.steps:
        try:
            manifest = registry.resolve(wiring.ref, wiring.version, source_path=_path(wiring))
        except UnknownStep as exc:
            errors.append(exc)
            continue
        step_errors = [
            *_check_determinism(wiring, manifest),
            *_check_bindings(wiring, manifest),
            *_check_parameters(wiring, manifest),
        ]
        errors.extend(step_errors)
        if step_errors:
            continue
        body = registry.macro_body(wiring.ref, wiring.version) or registry.sql_body(
            wiring.ref, wiring.version
        )
        parsed = None
        if body is not None:
            node, body_errors = _parse_body(wiring, body)
            errors.extend(body_errors)
            if body_errors:
                continue
            parsed = canon(cast("Expression", node))
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
    errors.extend(_check_duplicate_relations(ordered))
    if errors:
        batched = tuple(sorted(errors, key=lambda e: (e.source_path or "", str(e))))
        if len(batched) == 1:
            raise batched[0]
        raise StepError.from_collected(batched)
    return ordered
