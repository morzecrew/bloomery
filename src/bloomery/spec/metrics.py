"""The ``MetricSet`` spec kind (RFC 0002 §5.5; original spec §3.2 templates).

Project-authored metrics mirroring the catalog's ``metric_templates``: a
metric either references a template by ``template:`` or is fully inline
(``expr``/``agg``/``grain``). Additivity is typed — ``semi_additive`` carries
a :class:`~bloomery.spec.common.SemiAdditivePolicy`, ``non_additive`` a
:class:`~bloomery.spec.common.RatioSpec`; their *presence* is shape-validated
here, their necessity is enforced at the guardrail stage
(``NonAdditiveWithoutComponents``, RFC 0006). The ``cumulative:`` form is
reserved spec surface (RFC 0002 D10), parse-validated only.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from bloomery.spec.common import (
    AdditivityName,
    MemberName,
    RatioSpec,
    SemiAdditivePolicy,
    SpecModel,
)

__all__ = [
    "CumulativeSpec",
    "Metric",
    "MetricSet",
]


class CumulativeSpec(SpecModel):
    """Reserved cumulative-metric form (RFC 0002 D10; lowered per RFC 0013):
    exactly one of ``window`` or ``grain_to_date``."""

    window: str | None = None
    grain_to_date: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> CumulativeSpec:
        if (self.window is None) == (self.grain_to_date is None):
            msg = "cumulative requires exactly one of 'window' or 'grain_to_date'"
            raise ValueError(msg)
        return self


class Metric(SpecModel):
    """One authored metric: a template instantiation or an inline definition.

    Shape-only at parse (RFC 0002 D4): whether ``template`` exists, leaves are
    reachable, or the additivity policy is complete is checked downstream
    (resolution RFC 0005; guardrails RFC 0006).
    """

    template: str | None = None
    requires: tuple[str, ...] = ()
    requires_metrics: tuple[str, ...] = ()
    grain: str | None = None
    additivity: AdditivityName | None = None
    agg: str | None = None
    expr: str | None = None
    ratio: RatioSpec | None = None
    semi_additive: SemiAdditivePolicy | None = None
    cumulative: CumulativeSpec | None = None


class MetricSet(SpecModel):
    """The per-project metric document (``metrics_version``), at most one per
    project (RFC 0002 §5.5)."""

    metrics_version: int = Field(ge=1)
    metrics: dict[MemberName, Metric]
