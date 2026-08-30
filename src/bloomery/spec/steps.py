"""The authored side of a step: wiring, and nothing else (RFC 0017 §5.2, D2).

An authored spec *wires* a platform step — names it by ``ref@version``, binds its
inputs and outputs to relations, sets parameters within the bounds the
manifest declares, and optionally attaches RFC 0016 quality rules to its
outputs. It does not, and cannot, carry a body: there is no field here that
holds code, and no field that names a file to load. That is what keeps a
authored spec from ever becoming an arbitrary-code-execution surface (§5.3, D3)
— the property comes from the *absence* of a surface, not from validating one.

Quality rules on outputs are why RFC 0017 ships as a pair with RFC 0016
(§1): the escape hatch is only safe because declared rules apply at its
boundary, so a step whose output drifts is caught by the same dispositions as
any other silver relation.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from bloomery.spec.common import USE_PATTERN, ParameterValue, SpecModel, StepUse
from bloomery.spec.quality import ExpressionRule

# ----------------------- #

__all__ = [
    "RELATION_PATTERN",
    "USE_PATTERN",
    "BoundRelation",
    "ParameterValue",
    "StepSet",
    "StepUse",
    "StepWiring",
]

#: A bound relation: an optionally-namespaced identifier and nothing else.
#: Constrained because these strings reach *generated source* — a binding of
#: ``x", print("…"))\n@model("y`` produced a wrapper that parsed, carried a
#: second decorator, and executed at model import. The escaping in
#: ``emit.steps`` is the boundary that must hold; this is the second lock, so
#: neither alone is load-bearing (RFC 0017 §5.3, D3).
RELATION_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"

BoundRelation = Annotated[str, StringConstraints(pattern=RELATION_PATTERN)]


class StepWiring(SpecModel):
    """One wired step.

    ``inputs``/``outputs`` bind the manifest's declared names to relations;
    ``parameters`` sets tunables the manifest declares and bounds. ``seed`` is
    required for a ``seeded`` step and refused for the other two tiers — a
    seed on a ``pure`` step is either a lie about the step or a
    misunderstanding of the tier, and both are worth a compile error rather
    than a value nothing reads (§5.5, D5).
    """

    use: StepUse
    inputs: dict[str, BoundRelation] = Field(default_factory=dict[str, BoundRelation])
    outputs: dict[str, BoundRelation] = Field(min_length=1)
    parameters: dict[str, ParameterValue] = Field(default_factory=dict[str, ParameterValue])
    seed: int | None = None
    #: ``expression`` rules only, deliberately. The other entity-level rule
    #: kind is ``referential``, which is identified by its ``via`` — a
    #: relationship the entity model declares between two *entities*. A step
    #: output only becomes an entity as the step is lowered, so there is no
    #: relationship to name yet, and the rule has no ``name`` for
    #: ``applies_to`` to key on either. Widening this is an RFC amendment,
    #: not a config change (RFC 0016 D5's closed-catalogue discipline).
    quality: tuple[ExpressionRule, ...] = ()
    #: Which declared output each quality rule applies to, by rule name. A
    #: step has several outputs, so "on this step" is not specific enough to
    #: lower — unlike an entity's ``quality:``, which has one relation.
    applies_to: dict[str, str] = Field(default_factory=dict[str, str])
    #: Which canonical field each produced column *is*, keyed by output then
    #: column (RFC 0017 D49).
    #:
    #: On the wiring rather than in the manifest deliberately: canonical names
    #: are the authored spec's vocabulary, so a manifest naming them could not
    #: be reused by a second project spelling them differently — which is the
    #: fork §5.7 exists to refuse. Without the link a step output's columns
    #: are never *available*, so every metric over one is unreachable; with
    #: it, nothing about metric resolution changes at all.
    #:
    #: Never inferred from a matching column name. Guessing a link nobody
    #: declared is what RFC 0006 refuses, and it does not become acceptable
    #: because the guess is cheap (the same argument D43 made for references).
    canonical: dict[str, dict[str, str]] = Field(default_factory=dict[str, dict[str, str]])

    # ....................... #

    @property
    def ref(self) -> str:
        """The step ref half of ``use``."""

        return self.use.split("@", 1)[0]

    # ....................... #

    @property
    def version(self) -> int:
        """The version half of ``use``."""

        return int(self.use.split("@", 1)[1])

    # ....................... #

    @model_validator(mode="after")
    def _canonical_names_a_bound_output(self) -> Self:
        """Shape-only (RFC 0002): the *output* must be one this wiring binds.
        Whether the column exists is the manifest's business, and the spec
        layer has never seen a manifest — that check waits for lowering."""
        unbound = sorted(set(self.canonical) - set(self.outputs))

        if unbound:
            msg = (
                f"canonical names output(s) {', '.join(unbound)} this step does not bind; "
                f"bound outputs: {', '.join(sorted(self.outputs))}"
            )
            raise ValueError(msg)

        for output, links in sorted(self.canonical.items()):
            bad = sorted(name for pair in links.items() for name in pair if not name.isidentifier())
            if bad:
                msg = (
                    f"canonical.{output} names {', '.join(bad)}, which are not identifiers; "
                    "both a produced column and a canonical field are plain names"
                )
                raise ValueError(msg)

        return self

    # ....................... #

    @model_validator(mode="after")
    def _rules_name_a_bound_output(self) -> Self:
        """Shape-only (RFC 0002): a rule's ``applies_to`` must name an output
        this wiring binds. Whether that output *exists in the manifest* is a
        resolution question and waits for the guardrail stage."""
        declared = {rule.name for rule in self.quality}
        unknown_rules = sorted(set(self.applies_to) - declared)

        if unknown_rules:
            msg = (
                f"applies_to names rule(s) {', '.join(unknown_rules)} this step does not "
                f"declare; declared: {', '.join(sorted(declared)) or '(none)'}"
            )
            raise ValueError(msg)

        unassigned = sorted(declared - set(self.applies_to))

        if unassigned:
            msg = (
                f"quality rule(s) {', '.join(unassigned)} do not say which output they "
                "apply to; a step has several, so add applies_to: {<rule>: <output>}"
            )
            raise ValueError(msg)

        unbound = sorted(set(self.applies_to.values()) - set(self.outputs))

        if unbound:
            msg = (
                f"applies_to points at output(s) {', '.join(unbound)} this step does not "
                f"bind; bound outputs: {', '.join(sorted(self.outputs))}"
            )
            raise ValueError(msg)

        return self


# ....................... #


class StepSet(SpecModel):
    """The ``steps:`` document — the sixth spec kind (RFC 0002 §5.2).

    Its own document rather than a block inside the entity model because a
    step is not an entity: it is a referenced implementation that *produces*
    entities, and mixing the two would put platform-owned wiring inside the
    file spec authors edit most.
    """

    steps_version: Literal[1]
    steps: tuple[StepWiring, ...] = ()

    # ....................... #

    @model_validator(mode="after")
    def _refs_are_unique(self) -> Self:
        """One wiring per ``ref`` — not per ``ref@version``.

        Two wirings of one step are either a copy-paste or a fork attempt
        (§5.7, D7); both want the same answer, and neither can be resolved by
        picking one. Keyed on ``ref@version`` this missed the fork that
        matters: ``resolve_customers@3`` beside ``@4`` compiled, while
        everything downstream keys on ``ref`` alone — ``plan/diff.py`` builds
        ``{step.ref: step}`` and the DAG node is ``step.<ref>`` (D24) — so one
        of the two was silently dropped from the plan meant to restate it. A
        version bump is a step *changing*, not a second step appearing.
        """
        seen: set[str] = set()

        for wiring in self.steps:
            if wiring.ref in seen:
                msg = (
                    f"step {wiring.ref!r} is wired more than once (as {wiring.use!r}); one "
                    "wiring per step ref, since a version bump is that step changing rather "
                    "than a second step"
                )
                raise ValueError(msg)
            seen.add(wiring.ref)

        return self
