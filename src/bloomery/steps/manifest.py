"""The step manifest: what a platform step declares about itself (RFC 0017
§5.2, D2).

A manifest is **not** an authored spec. It is written by the platform team beside
the step body, in the platform repo, and reaches bloomery only as an already
parsed value inside a :class:`~bloomery.steps.registry.StepRegistry` (§5.3).
Bloomery never reads it from disk and never imports the code it describes —
at compile time it consumes this declaration and SQL text, nothing else.

Every model here is frozen and strict, and that is load-bearing rather than
stylistic: :class:`~bloomery.steps.registry.StepRegistry` snapshots its
mappings at construction, and a shallow snapshot only makes compilation
independent of the caller if the values it holds cannot be mutated either
(D14 — the two together, or neither).

The declaration is *trusted* at compile and *verified* at run time (§5.4,
D4). Nothing here checks that a step body does what it says; that is
:func:`~bloomery.steps.contract.assert_step_contract`'s job, inside the
generated wrapper, on every run.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from bloomery.spec.common import SpecModel, TypeString

__all__ = [
    "ENTRYPOINT_PATTERN",
    "PARAMETER_TYPE_PATTERN",
    "ParameterTypeString",
    "REF_PATTERN",
    "DeterminismName",
    "LineageName",
    "StepEntrypoint",
    "StepInput",
    "StepKindName",
    "StepManifest",
    "StepOutput",
    "StepParameter",
    "StepProduces",
    "StepRef",
]

#: A step ref is an identifier, not a path: the absence of any path-like
#: spelling is part of why an authored spec can never name code to load (§5.3).
REF_PATTERN = r"^[a-z][a-z0-9_]*$"

#: ``package.module:function`` — the platform function a ``python_model``
#: wrapper imports **at run time** (D13). Bloomery never resolves it; registry
#: build does, caller-side, before the registry is handed over.
ENTRYPOINT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"

#: A parameter's declared type. The column grammar plus a bare ``decimal``,
#: because §5.2's own worked manifest writes ``{type: decimal, default: 0.85}``
#: and the implementation rejected it — the RFC is the authority, and a
#: parameter is a scalar knob rather than a stored column, so precision and
#: scale say nothing useful about it. A ``produces`` column still needs the
#: full ``decimal(p,s)``: that one *is* a stored column, and downstream models
#: are typechecked against it.
PARAMETER_TYPE_PATTERN = (
    r"^(?:string|int|bool|date|timestamp|variant|decimal(?:\((\d{1,3}), ?(\d{1,3})\))?)$"
)

ParameterTypeString = Annotated[str, StringConstraints(pattern=PARAMETER_TYPE_PATTERN)]

StepRef = Annotated[str, StringConstraints(pattern=REF_PATTERN)]
StepEntrypoint = Annotated[str, StringConstraints(pattern=ENTRYPOINT_PATTERN)]

#: The ladder above Tier 0 (§5.1, D1). Tier 0 is the transform whitelist (RFC
#: 0004) and is not a step at all — a step kind names a tier that needs a body.
StepKindName = Literal["sql_macro", "sql_model", "python_model"]

#: §5.5, D5. ``nondeterministic`` is declarable so that a step can say so and
#: be **refused**: the alternative — no way to spell it — would only mean the
#: same steps arrive mislabelled as ``pure``.
DeterminismName = Literal["pure", "seeded", "nondeterministic"]

#: §5.1: Tier 3 loses column-level lineage, and the manifest says so rather
#: than letting the consumer infer it from ``kind``.
LineageName = Literal["coarse", "column"]


class StepProduces(SpecModel):
    """One column a step output declares (§5.2).

    ``required`` is what the runtime contract null-checks; the type is what
    downstream models are typechecked against at compile, on trust.
    """

    type: TypeString
    required: bool = False


class StepInput(SpecModel):
    """One input a step reads: the grain it expects and the columns it needs.

    ``requires`` is a *lower* bound — the step may be handed a relation with
    more columns, and asking for fewer than it reads is the manifest's bug,
    not the wiring's. Bloomery checks the bound is met, never that it is tight.
    """

    grain: str
    requires: tuple[str, ...] = ()


class StepOutput(SpecModel):
    """One relation a step produces (§5.2).

    ``grain`` is prose, for humans and for the IR node's grain; ``key`` is the
    machine-readable half — the concrete columns over which that grain is
    unique, and exactly what :func:`assert_step_contract` enforces. The two
    are separate because a grain sentence cannot be checked and a key can.
    """

    grain: str
    key: tuple[str, ...] = Field(min_length=1)
    produces: dict[str, StepProduces] = Field(min_length=1)
    #: Columns of *this* output that reference a sibling output's key, as
    #: ``{column: sibling_output}`` (RFC 0017 §5.8, D16).
    #:
    #: **Declared, never inferred.** The obvious shortcut is to notice that one
    #: output happens to carry another's key columns and assume a reference —
    #: which fabricates a relationship from a coincidence. Two outputs both
    #: keyed ``id`` would get a mutual pair of blocking audits asserting their
    #: id sets are *identical*, failing every run on correct data. Guessing a
    #: relationship nobody declared is precisely what RFC 0006 exists to
    #: refuse, and it does not become acceptable because the guess is cheap.
    references: dict[str, str] = Field(default_factory=dict[str, str])

    @model_validator(mode="after")
    def _references_name_produced_columns(self) -> Self:
        """A referencing column must be one this output produces; the sibling
        it points at is checked one level up, where the other outputs are in
        scope."""
        missing = sorted(set(self.references) - set(self.produces))
        if missing:
            msg = (
                f"references names column(s) {', '.join(missing)}, which this output does "
                f"not produce; produced: {', '.join(sorted(self.produces))}"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _key_columns_are_produced(self) -> Self:
        """A key naming a column the step does not produce is unenforceable —
        the runtime assertion would have nothing to group by."""
        missing = sorted(set(self.key) - set(self.produces))
        if missing:
            msg = (
                f"key names {', '.join(missing)}, which this output does not produce; "
                f"produced columns: {', '.join(sorted(self.produces))}"
            )
            raise ValueError(msg)
        return self


class StepParameter(SpecModel):
    """A tunable an authored spec may set, with the bounds it must set it
    within (§5.2) — the machinery behind "parameterize, never fork" (§5.7, D7).

    Bounds are declared here and enforced at compile against the authored
    wiring, so a parameter out of range is a spec error rather than a run-time
    surprise inside somebody's Python. ``min``/``max`` apply to numeric
    parameters only; they are ``Decimal``, never ``float`` (RFC 0003 D5).
    """

    type: ParameterTypeString
    default: str | int | bool | Decimal | None = None
    min: Decimal | None = None
    max: Decimal | None = None

    @model_validator(mode="after")
    def _bounds_are_ordered(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            msg = f"parameter bounds are inverted: min {self.min} > max {self.max}"
            raise ValueError(msg)
        return self


class StepManifest(SpecModel):
    """One versioned step, as its platform team declares it (§5.2, D2).

    Identity is ``(ref, version)``. Everything else that can change behaviour
    is *inside* the manifest on purpose, ``runtime_lock`` most of all (§5.6,
    D6): the manifest is lowered into the IR, so any field moving here shifts
    ``project_fingerprint`` and `plan()` classifies it RESTATING with no
    special-casing anywhere.
    """

    ref: StepRef
    version: int = Field(ge=1)
    kind: StepKindName
    determinism: DeterminismName
    #: A hash of the pinned dependency set, computed at registry build time.
    #: Opaque to bloomery — it is compared, never interpreted — which is why
    #: it is a plain string rather than a parsed digest.
    runtime_lock: str = Field(min_length=1)
    outputs: dict[str, StepOutput] = Field(min_length=1)
    inputs: dict[str, StepInput] = Field(default_factory=dict[str, StepInput])
    parameters: dict[str, StepParameter] = Field(default_factory=dict[str, StepParameter])
    lineage: LineageName = "column"
    #: ``python_model`` only: the function the generated wrapper imports at
    #: run time. Required there and refused elsewhere — a SQL step has no
    #: Python to call, and a manifest naming one is describing something the
    #: emitter would silently ignore.
    entrypoint: StepEntrypoint | None = None

    @model_validator(mode="after")
    def _entrypoint_matches_kind(self) -> Self:
        if self.kind == "python_model" and self.entrypoint is None:
            msg = (
                "a python_model step needs an entrypoint ('package.module:function') — "
                "it is what the generated wrapper imports at run time (RFC 0017 D13)"
            )
            raise ValueError(msg)
        if self.kind != "python_model" and self.entrypoint is not None:
            msg = (
                f"a {self.kind} step declares entrypoint {self.entrypoint!r}, but only a "
                "python_model imports one; a SQL step's body comes from the registry"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _inputs_and_parameters_are_disjoint_identifiers(self) -> Self:
        """The generated wrapper calls the step as
        ``step(**inputs, **parameters)``, so the two namespaces share one
        keyword space: a name in both is ``TypeError: got multiple values``
        at run time, and a name that is not an identifier cannot be passed at
        all. Both are decidable here, from the manifest alone.
        """
        clashing = sorted(set(self.inputs) & set(self.parameters))
        if clashing:
            msg = (
                f"{', '.join(clashing)} is declared as both an input and a parameter; the "
                "generated wrapper passes both as keywords, so the step would be called "
                "with two values for one argument"
            )
            raise ValueError(msg)
        invalid = sorted(
            name for name in (*self.inputs, *self.parameters) if not name.isidentifier()
        )
        if invalid:
            msg = (
                f"input/parameter name(s) {', '.join(invalid)} are not Python identifiers, "
                "so the generated wrapper could not pass them as keyword arguments"
            )
            raise ValueError(msg)
        # Output names are not keyword arguments, but they *are* interpolated
        # into generated source (the wrapper's ``return outputs[…]`` and its
        # docstring), so the same constraint applies for the same reason.
        bad_outputs = sorted(name for name in self.outputs if not name.isidentifier())
        if bad_outputs:
            msg = (
                f"output name(s) {', '.join(bad_outputs)} are not identifiers; output "
                "names reach the generated wrapper's source and must not be able to "
                "carry syntax into it"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _references_point_at_siblings(self) -> Self:
        """Each declared reference names another output of *this* step, and a
        single-column key — the audit compares one column to one key, and a
        composite target would need the reference to name every part of it."""
        for name, output in sorted(self.outputs.items()):
            for column, target in sorted(output.references.items()):
                if target == name:
                    msg = f"output {name!r} declares column {column!r} as referencing itself"
                    raise ValueError(msg)
                sibling = self.outputs.get(target)
                if sibling is None:
                    msg = (
                        f"output {name!r} column {column!r} references {target!r}, which "
                        f"this step does not produce; outputs: {', '.join(sorted(self.outputs))}"
                    )
                    raise ValueError(msg)
                if len(sibling.key) != 1:
                    msg = (
                        f"output {name!r} column {column!r} references {target!r}, whose "
                        f"key is composite ({', '.join(sibling.key)}); a single column "
                        "cannot reference it"
                    )
                    raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _references_are_acyclic(self) -> Self:
        """References order the outputs' models, so a cycle is a cycle.

        Each reference becomes a real ``depends_on`` edge — the audit has to
        read the sibling's *snapshot*, not a virtual-layer view — so two
        outputs referencing each other is a DAG cycle SQLMesh refuses at load,
        long after the manifest that caused it. Refused here, where the
        message can name the outputs.
        """
        edges = {
            name: {target for _column, target in output.references.items()}
            for name, output in self.outputs.items()
        }
        state: dict[str, int] = {}

        def walk(node: str, path: list[str]) -> None:
            state[node] = 1
            for target in sorted(edges.get(node, ())):
                if state.get(target) == 1:
                    cycle = " → ".join([*path, node, target])
                    msg = (
                        f"outputs reference each other in a cycle: {cycle}. Each reference "
                        "orders the two models so the audit can read a materialized "
                        "sibling, and a cycle has no order"
                    )
                    raise ValueError(msg)
                if state.get(target) is None:
                    walk(target, [*path, node])
            state[node] = 2

        for name in sorted(edges):
            if state.get(name) is None:
                walk(name, [])
        return self

    @model_validator(mode="after")
    def _sql_macro_produces_one_expression(self) -> Self:
        """Tier 1 is an *expression* (§5.1): it splices into a SELECT, so it
        has exactly one output of exactly one column. A macro declaring a
        table shape is really a Tier 2 step wearing the wrong kind, and the
        splice would have no single value to substitute."""
        if self.kind != "sql_macro":
            return self
        if len(self.outputs) != 1:
            msg = (
                f"a sql_macro declares {len(self.outputs)} outputs; it splices into a "
                "SELECT as one expression, so it has exactly one. Fix: declare it as a "
                "sql_model if it produces a relation"
            )
            raise ValueError(msg)
        (output,) = self.outputs.values()
        if len(output.produces) != 1:
            msg = (
                f"a sql_macro's output produces {len(output.produces)} columns; an "
                "expression is one value. Fix: declare it as a sql_model"
            )
            raise ValueError(msg)
        return self
