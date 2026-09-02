"""Template instantiation: authored metrics merged with their catalog
templates into one effective view (RFC 0002 §5.5; original spec §3.2).

Runs on reference-clean specs (RFC 0005 §5.5): every ``template:`` ref is
known to exist by the time this module merges. A metric's own values win over
the template's; empty tuples and ``None`` fall through to the template.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, ResolutionError

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog, MetricTemplate
    from bloomery.spec.common import RatioSpec, SemiAdditivePolicy
    from bloomery.spec.metrics import CumulativeSpec, DerivedSpec, Metric, MetricFilter
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "EffectiveMetric",
    "effective_metrics",
]

#: Best-effort source-path prefix for the (single) MetricSet document —
#: parsed models do not retain their document names (RFC 0002 §5.3).
_METRICS_DOC = "metrics"


@dataclass(frozen=True, slots=True)
class EffectiveMetric:
    """One metric after template merge: the values compilation actually uses."""

    name: str
    requires: tuple[str, ...]
    requires_metrics: tuple[str, ...]
    grain: str | None
    additivity: str
    agg: str | None
    expr: str | None
    ratio: RatioSpec | None
    semi_additive: SemiAdditivePolicy | None
    cumulative: CumulativeSpec | None
    derived: DerivedSpec | None
    filter: tuple[MetricFilter, ...]
    description: str | None
    source_path: str


# ....................... #


def _merge(name: str, metric: Metric, template: MetricTemplate | None) -> EffectiveMetric:
    source_path = f"{_METRICS_DOC}: metrics.{name}"
    additivity = metric.additivity or (template.additivity if template else None)

    if additivity is None:
        msg = f"metric {name!r} declares no additivity, directly or via its template"
        raise ResolutionError(msg, source_path=source_path)

    derived = metric.derived or (template.derived if template else None)
    declared = metric.requires_metrics or (template.requires_metrics if template else ())
    # RFC 0034 D3: a derived metric's inputs *are* its metric dependencies, so
    # they are unioned in here rather than written twice by the author. The DAG,
    # reachability, cycle detection and `MetricIR.depends_on` then need no
    # knowledge of `derived:` at all — they read `requires_metrics` as always.
    requires_metrics = (
        tuple(sorted({*declared, *derived.input_metrics})) if derived is not None else declared
    )

    return EffectiveMetric(
        name=name,
        requires=metric.requires or (template.requires if template else ()),
        requires_metrics=requires_metrics,
        grain=metric.grain or (template.grain if template else None),
        additivity=additivity,
        agg=metric.agg or (template.agg if template else None),
        expr=metric.expr or (template.expr if template else None),
        ratio=metric.ratio or (template.ratio if template else None),
        semi_additive=metric.semi_additive or (template.semi_additive if template else None),
        cumulative=metric.cumulative or (template.cumulative if template else None),
        derived=derived,
        filter=metric.filter or (template.filter if template else ()),
        description=metric.description or (template.description if template else None),
        source_path=source_path,
    )


# ....................... #


def effective_metrics(project: Project, catalog: Catalog | None) -> tuple[EffectiveMetric, ...]:
    """Every authored metric merged with its template, sorted by name.

    Assumes reference-clean specs; still raises a batched
    :class:`ResolutionError` for metrics that end up without an additivity —
    a completeness failure no reference check can express.
    """

    if project.metric_set is None:
        return ()

    merged: list[EffectiveMetric] = []
    errors: list[BloomeryError] = []

    for name in sorted(project.metric_set.metrics):
        metric = project.metric_set.metrics[name]
        template = None
        if metric.template is not None and catalog is not None:
            template = catalog.metric_templates.get(metric.template)
        try:
            merged.append(_merge(name, metric, template))
        except ResolutionError as exc:
            errors.append(exc)

    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ResolutionError.from_collected(tuple(errors))

    return tuple(merged)
