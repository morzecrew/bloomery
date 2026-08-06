"""The total ``BloomeryError`` hierarchy (RFC 0002 §5.4).

Every failure the package can raise derives from :class:`BloomeryError` and
carries a human message plus an optional ``source_path`` — a dotted/bracketed
address into the authored spec document (RFC 0002 §5.3). All leaf classes are
declared here, in one module importable without pulling in any pipeline stage,
so callers can write a single ``except BloomeryError`` (RFC 0002 D3).

Batched stages (parse — RFC 0002 D6; resolution — RFC 0005 D7; guardrails —
RFC 0006 D2) collect their individual failures and raise one aggregate error
listing every path: authors fix a spec in one round-trip, not one error at a
time. The aggregation surface is :attr:`BloomeryError.collected` plus the
:meth:`BloomeryError.from_collected` constructor.
"""

from __future__ import annotations

from typing import Self

__all__ = [
    "BloomeryError",
    "SpecParseError",
    "UnknownTransformError",
    "TypeCheckError",
    "TransformRegistrationError",
    "ResolutionError",
    "CircularDerivation",
    "MissingReference",
    "GuardrailError",
    "UnitMismatch",
    "TaxBasisMismatch",
    "CurrencyMismatch",
    "GrainMismatch",
    "AdditivityViolation",
    "AssertLoweringError",
    "GrainViolation",
    "FanoutRisk",
    "NonAdditiveWithoutComponents",
    "MartMissingTimeDimension",
    "PlanError",
    "ContractViolation",
    "RenameTargetMissing",
    "EmitError",
    "UnsupportedByTarget",
    "PlannerError",
    "UnknownMember",
    "UnreachableAtGrain",
    "AmbiguousDimension",
    "InvalidRequest",
    "FilterTypeMismatch",
]


class BloomeryError(Exception):
    """Base of every error bloomery raises (RFC 0002 §5.4).

    Carries the human message (``str(exc)``), the ``source_path`` into the
    authored document that caused the failure (always set by the parse stage,
    best-effort elsewhere), and — for the batched stages — the ``collected``
    tuple of individual failures this aggregate reports.
    """

    def __init__(
        self,
        message: str,
        *,
        source_path: str | None = None,
        collected: tuple[BloomeryError, ...] = (),
    ) -> None:
        super().__init__(message)
        self.source_path = source_path
        self.collected = collected

    @classmethod
    def from_collected(cls, errors: tuple[BloomeryError, ...]) -> Self:
        """Build one aggregate error whose message lists every collected path.

        Used by the batched stages (RFC 0002 D6): the individual failures stay
        machine-readable on :attr:`collected`; the message enumerates each one
        in collection order (callers pre-sort where determinism demands it).
        """
        lines = [f"{len(errors)} error(s):"]
        for err in errors:
            prefix = f"{err.source_path}: " if err.source_path else ""
            lines.append(f"  - {prefix}{err}")
        return cls("\n".join(lines), collected=errors)


# ....................... #
# Parse stage — RFC 0002


class SpecParseError(BloomeryError):
    """Raised by the parse stage (loaders, RFC 0002): YAML failures, duplicate
    keys, shape/unknown-key validation failures — batched per document (D6)."""


# ....................... #
# Typing and transforms — RFC 0004


class UnknownTransformError(BloomeryError):
    """Raised by the typecheck stage (RFC 0004) when a transform chain names a
    transform absent from the registry; the message names the closest match."""


class TypeCheckError(BloomeryError):
    """Raised by the type layer (RFC 0004): unparsable type strings and
    transform chains whose terminal type is not assignable to the declared."""


class TransformRegistrationError(BloomeryError):
    """Raised by ``register_transform`` (RFC 0004) when a transform spec is
    invalid or collides with an already-registered name."""


# ....................... #
# Resolution — RFC 0005


class ResolutionError(BloomeryError):
    """Raised by the resolution stage (RFC 0005): cross-spec reference and
    recipe failures over the dependency DAG — batched per stage (D7)."""


class CircularDerivation(ResolutionError):
    """Raised by the resolution stage (RFC 0005 D4) on any cycle in the
    dependency DAG; the message names the full cycle path."""


class MissingReference(ResolutionError):
    """Raised by the resolution stage (RFC 0005 D7) when a spec references a
    nonexistent entity, field, canonical field, template, or relationship end."""


# ....................... #
# Guardrails — RFC 0006 (mart-level leaves: RFC 0010; MetricFlow: RFC 0013)


class GuardrailError(BloomeryError):
    """Raised by the guardrail stage (RFC 0006): the aggregate whose
    ``collected`` violations are sorted by ``(source_path, type name)``."""


class UnitMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.2): operands of ``+``/``-`` with differing
    or unknown ``unit`` metadata."""


class TaxBasisMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.2): ``net`` and ``gross`` (or unknown)
    tax bases meeting in additive arithmetic."""


class CurrencyMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.2): two operands with distinct declared
    ISO-4217 currency codes and no explicit ``convert`` in the chain."""


class GrainMismatch(GuardrailError):
    """Guardrail stage (RFC 0006 §5.3): expression combining columns of
    different grains without an explicit aggregation."""


class AdditivityViolation(GuardrailError):
    """Guardrail stage (RFC 0006 §5.4): an aggregation that contradicts the
    metric's declared additivity."""


class AssertLoweringError(GuardrailError):
    """Guardrail stage (RFC 0006 D8): an ``assert:`` clause ill-typed against
    the field's logical type."""


class GrainViolation(GuardrailError):
    """Guardrail stage, mart-level (RFC 0010 D2): a mart measure whose grain
    does not strictly equal the mart grain."""


class FanoutRisk(GuardrailError):
    """Guardrail stage, mart-level (RFC 0010 D3): a mart ``via:`` flatten step
    over a ``one_to_many`` relationship."""


class NonAdditiveWithoutComponents(GuardrailError):
    """Guardrail stage (RFC 0006 §5.4, RFC 0011 D5): a non-additive metric
    without a ratio / additive decomposition to recompute it from."""


class MartMissingTimeDimension(GuardrailError):
    """Guardrail stage (RFC 0010 §5.5 rule 6, RFC 0013 R1): a measure-carrying
    mart that declares no date role."""


# ....................... #
# Plan — RFC 0007


class PlanError(BloomeryError):
    """Raised by the plan stage (RFC 0007) when a spec diff cannot produce a
    safe migration plan."""


class ContractViolation(PlanError):
    """Plan stage (RFC 0007 D5): dropping or narrowing a field still
    referenced by a reachable metric — expand/contract enforced."""


class RenameTargetMissing(PlanError):
    """Plan stage (RFC 0007 D3): a ``renamed_from`` annotation whose old name
    is absent from the old IR (stale one-shot annotation)."""


# ....................... #
# Emit — RFC 0008


class EmitError(BloomeryError):
    """Raised by the emit stage (RFC 0008) when the IR cannot be lowered to a
    target artifact."""


class UnsupportedByTarget(EmitError):
    """Emit stage (RFC 0008 D3): an IR construct the selected target or
    dialect cannot express — fail loud, never approximate."""


# ....................... #
# Planner — RFC 0011 (backend: RFC 0013). Deliberately NOT batched (0011 D9).


class PlannerError(BloomeryError):
    """Raised by the query planner (RFC 0011) on malformed or unanswerable
    requests; planner errors are not batched (D9)."""


class UnknownMember(PlannerError):
    """Planner stage (RFC 0011 D3): a request names a metric or dimension that
    does not exist; the message carries a ``did_you_mean`` closest match."""


class UnreachableAtGrain(PlannerError):
    """Planner stage (RFC 0011 D3): no single mart can answer the request at
    the requested grain — refuse, never join at plan time."""


class AmbiguousDimension(PlannerError):
    """Planner stage (RFC 0011 D6): an unqualified reference to a dimension
    with multiple roles; the message names the available roles."""


class InvalidRequest(PlannerError):
    """Planner stage (RFC 0011 D9): bad filter/order/limit shapes or raw SQL
    where a structured request member is required."""


class FilterTypeMismatch(PlannerError):
    """Planner stage (RFC 0013 D8): a filter value whose type contradicts the
    dimension's logical type — refused before any SQL is rendered."""
