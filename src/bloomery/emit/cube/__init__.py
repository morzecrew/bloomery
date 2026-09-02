"""The Cube emitter (RFC 0008 §5.4) — the semantic target.

One ``model/cubes/<mart>.yml`` per mart (``sql_table`` from
``NamingPolicy.relation(mart, Layer.GOLD)`` — the same pair the SQLMesh mart
build uses, so the cube and the built table cannot disagree) plus one
``model/views/<mart>_view.yml`` exposing the mart's members (RFC 0008 §10 → D17:
one view per **mart**, and not per metric-grain group — two marts may share
a grain, and merging them would need a ``join_path`` between cubes that
bloomery models no relationship to build from; per metric would repeat the
whole dimension set once per measure, since each metric already resolves to
exactly one mart).
The YAML is **dialect-independent**: measure SQL is the metric's canonical
neutral expression and ``ctx.dialect`` is never consulted — Cube renders SQL
against its own configured database.

Deterministic choices pinned here (each golden/unit-tested):

- Dimensions come from ``MartIR.dimensions``. A date-role bucket column
  (``ref.role`` set) is a ``time`` dimension with ``meta.granularity`` naming
  its bucket; every other column maps by logical type (string / number /
  boolean / time) — an int dimension is never declared a string.
- A metric served by several marts lands as a measure on exactly one:
  :func:`bloomery.emit.metricflow.measure_owners` — the same cheapest-mart
  rule the MetricFlow emitter and the planner's coverage precheck apply, so
  the three surfaces cannot disagree.
- Measures carry ``meta.additivity`` / ``meta.grain`` from ``MetricIR``;
  a semi-additive measure additionally carries ``meta.semi_additive``
  (``over``/``rule``). The measure still emits with its declared aggregation:
  RFC 0008 §5.1 gates *trusting* Cube's semi-additive behavior on the
  equivalence suite (RFC 0009 §5.8), not on emission — the meta is what that
  suite (and any consumer) audits against.
- A ``count`` metric emits ``type: count`` with no ``sql``: Cube's ``count``
  counts rows, which at the mart's grain equals counting the non-null key
  expression the metric declares.
- A non-additive ratio is **never a stored aggregate**: it emits as a
  calculated ``number`` measure over its additive components
  (``{num} / NULLIF({den}, 0)`` via Cube's ``{member}`` templating), and only
  on the mart owning both components. Naming it in ``MartIR.measures`` is an
  ordinary request — that field is "metrics this mart serves" — so it is
  skipped by the stored-measure pass and picked up by the calculated one. A
  named ratio whose components are *not* on the mart is simply absent, which
  is what the MetricFlow emitter does with the same spec.
- A non-additive metric backed by an **additive decomposition rather than a
  ratio** is refused with :class:`~bloomery.errors.UnsupportedByTarget`. The
  additivity guardrail accepts either form (RFC 0006 §5.4), and only the ratio
  has a Cube shape: ``{num} / NULLIF({den}, 0)``. Refusing is not a
  formality — without it such a metric is dropped from the stored pass and
  skipped by the calculated one, so it vanishes from the artifact, and a ratio
  naming it as a component emits ``{member}`` templating against a measure the
  cube does not define (RFC 0008 D3: fail loud, never approximate).
- Cube has no SCD/incremental concepts — their absence here is *irrelevance
  rather than error*: Cube consumes tables SQLMesh maintains (RFC 0008 §5.4).
- **Nothing about how a relation is built is Cube's to refuse** (RFC 0017 D52).
  This emitter writes no silver model, no reject table, no replay statement and
  no audit — a project full of quality rules compiles to cubes and views and
  nothing else, and always has. Steps and mart assertions were briefly singled
  out for a refusal on the grounds that "their output relations would simply be
  missing", which is equally true of every silver entity here and was never a
  reason to refuse one. The sentence above is the whole contract: Cube consumes
  tables SQLMesh maintains, and it is deliberately silent about *how*.
"""

from __future__ import annotations

import yaml

from bloomery.emit.base import (
    ArtifactKind,
    EmitContext,
    EmittedArtifact,
)
from bloomery.emit.lower import mart_column_type, measure_owners, metric_filter_sql
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import (
    Additivity,
    Layer,
    MartIR,
    MetricIR,
    ProjectIR,
)
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

# ----------------------- #

__all__ = [
    "CubeEmitter",
]

#: Logical type → Cube dimension type. ``variant`` degrades to ``string`` —
#: Cube has no semi-structured dimension type, and string is the widest
#: faithful projection of a JSON value.
_DIMENSION_TYPES: dict[type[LogicalType], str] = {
    StringType: "string",
    IntType: "number",
    DecimalType: "number",
    BoolType: "boolean",
    DateType: "time",
    TimestampType: "time",
    VariantType: "string",
}

#: Metric ``agg`` → Cube measure type (the closed honest set; anything else
#: is ``UnsupportedByTarget``, never approximated).
_MEASURE_TYPES: dict[str, str] = {
    "avg": "avg",
    "count": "count",
    "count_distinct": "count_distinct",
    "max": "max",
    "min": "min",
    "sum": "sum",
}


def _header(ctx: EmitContext) -> str:
    return f"# Generated by bloomery — do not edit.\n# fingerprint: {ctx.fingerprint}\n"


# ....................... #


def _yaml(document: dict[str, object]) -> str:
    """Byte-stable YAML: keys keep the deterministic insertion order built
    here (member order is semantic surface; ``sort_keys`` would shuffle
    ``name`` below ``sql_table``), block style, pinned width."""

    return yaml.safe_dump(
        document, sort_keys=False, default_flow_style=False, width=100, allow_unicode=True
    )


# ....................... #


def _metric_meta(metric: MetricIR) -> dict[str, object]:
    meta: dict[str, object] = {"additivity": metric.additivity.value}

    if metric.grain:
        # A metric with no measure of its own — a ratio, and since RFC 0034 a
        # `derived:` metric — has no grain: its components carry theirs, and an
        # empty grain entry would be noise rather than metadata.
        meta["grain"] = metric.grain

    if metric.semi_additive is not None:
        meta["semi_additive"] = {
            "over": metric.semi_additive.over.qualified,
            "rule": metric.semi_additive.rule.value,
        }

    return meta


# ....................... #


def _dimensions(mart: MartIR) -> list[object]:
    types_by_column = {column.name: column.type for column in mart.columns}
    dimensions: list[object] = []

    for dimension in mart.dimensions:  # sorted by column name on MartIR
        entry: dict[str, object] = {"name": dimension.column, "sql": dimension.column}
        if dimension.ref.role is not None:
            # A date-role bucket column (RFC 0010 D4): a time dimension whose
            # bucket is recorded as meta.granularity.
            entry["type"] = "time"
            entry["meta"] = {"granularity": dimension.ref.dimension}
        else:
            entry["type"] = _DIMENSION_TYPES[type(types_by_column[dimension.column])]
        dimensions.append(entry)

    return dimensions


# ....................... #


def _stored_measure(metric: MetricIR, mart: MartIR) -> dict[str, object]:
    measure_type = _MEASURE_TYPES.get(metric.agg) if metric.agg is not None else None

    if measure_type is None:
        msg = (
            f"metric {metric.name!r} uses aggregation {metric.agg!r}, which has no Cube "
            f"measure type mapping; supported: {sorted(_MEASURE_TYPES)}"
        )
        raise UnsupportedByTarget(msg)

    if metric.expr is None:
        msg = (
            f"metric {metric.name!r} has no expression to emit as a Cube measure — only "
            "agg-over-expr metrics lower to stored measures (RFC 0008 §5.4)"
        )
        raise UnsupportedByTarget(msg)

    entry: dict[str, object] = {"name": metric.name, "type": measure_type}

    if measure_type != "count":
        # Cube's ``count`` counts rows and takes no sql (see module docstring).
        entry["sql"] = metric.expr.sql

    if metric.filter:
        # Cube's own measure-level filter (RFC 0034): the same clauses the
        # MetricFlow manifest carries, rendered by the shared function and
        # differing only in how a column is spelled — `{CUBE}.col` here,
        # `{{ Dimension('entity__col') }}` there (D15).
        entry["filters"] = [
            {
                "sql": metric_filter_sql(
                    clause,
                    ref=f"{{CUBE}}.{clause.dimension}",
                    declared=mart_column_type(mart, clause.dimension),
                )
            }
            for clause in metric.filter
        ]

    entry["meta"] = _metric_meta(metric)
    return entry


# ....................... #


def _measures(mart: MartIR, ir: ProjectIR, owners: dict[str, MartIR]) -> list[object]:
    metrics_by_name = {metric.name: metric for metric in ir.metrics}
    owned = [name for name in mart.measures if owners[name] is mart]  # sorted on MartIR

    # A mart's `measures:` is "metrics this mart serves" (spec reference), not
    # "numbers this mart stores". A non-additive metric is served by *computing*
    # it from components the mart does store, so it is skipped here and picked up
    # by the ratio pass below — which is what MetricFlow already did with the
    # same spec. Refusing it made Cube the one target that rejected a project the
    # other three compiled, and only when the author named the metric explicitly:
    # leaving it out of `measures:` emitted the very same calculated measure.
    #
    # Only the *ratio* form has a calculated shape, so the skip has to be exactly
    # as wide as the pass that picks it back up. A non-additive metric carrying an
    # additive decomposition instead — which the additivity guardrail accepts
    # (RFC 0006 §5.4) — is refused here rather than skipped: skipping it drops it
    # from the artifact silently, and a ratio naming it as a component then
    # templates `{member}` against a measure the cube does not define.
    for name in owned:
        metric = metrics_by_name[name]
        if metric.additivity is Additivity.NON_ADDITIVE and metric.ratio is None:
            msg = (
                f"metric {name!r} is non_additive and declares an additive decomposition "
                "rather than a ratio, which Cube has no calculated-measure shape for — "
                "only ratio: {numerator, denominator} lowers to "
                "'{num} / NULLIF({den}, 0)' (RFC 0008 §5.4). Fix: give the metric a "
                f"ratio naming its two additive components, or drop {name!r} from this "
                "mart's measures: and let a target that can decompose it serve the metric"
            )
            raise UnsupportedByTarget(msg)

    measures: list[object] = [
        _stored_measure(metrics_by_name[name], mart)
        for name in owned
        if metrics_by_name[name].additivity is not Additivity.NON_ADDITIVE
    ]
    owned_set = frozenset(owned)

    for metric in ir.metrics:  # sorted by name on ProjectIR
        ratio = metric.ratio
        if (
            metric.additivity is Additivity.NON_ADDITIVE
            and ratio is not None
            and ratio.numerator in owned_set
            and ratio.denominator in owned_set
        ):
            measures.append(
                {
                    "name": metric.name,
                    "type": "number",
                    "sql": f"{{{ratio.numerator}}} / NULLIF({{{ratio.denominator}}}, 0)",
                    "meta": _metric_meta(metric),
                }
            )

    return measures


# ....................... #


def _cube_artifact(
    mart: MartIR, ir: ProjectIR, owners: dict[str, MartIR], ctx: EmitContext
) -> EmittedArtifact:
    namespace, relation = ctx.naming.relation(mart.name, Layer.GOLD)
    document: dict[str, object] = {
        "cubes": [
            {
                "name": mart.name,
                "sql_table": f"{namespace}.{relation}",
                "dimensions": _dimensions(mart),
                "measures": _measures(mart, ir, owners),
            }
        ]
    }
    return EmittedArtifact.create(
        path=f"model/cubes/{mart.name}.yml",
        content=_header(ctx) + _yaml(document),
        kind=ArtifactKind.MODEL,
    )


# ....................... #


def _view_artifact(mart: MartIR, ctx: EmitContext) -> EmittedArtifact:
    document: dict[str, object] = {
        "views": [
            {
                "name": f"{mart.name}_view",
                "cubes": [{"join_path": mart.name, "includes": "*"}],
            }
        ]
    }
    return EmittedArtifact.create(
        path=f"model/views/{mart.name}_view.yml",
        content=_header(ctx) + _yaml(document),
        kind=ArtifactKind.MODEL,
    )


# ....................... #


def _refuse_time_shaped(ir: ProjectIR) -> None:
    """Refuse the two RFC 0034 forms Cube has no measure shape for (D11).

    Project-wide rather than per mart, and by *existence* rather than by a
    mart naming the metric: a derived metric need not be listed in any mart's
    ``measures:`` at all (RFC 0034 D4), so a per-mart check would let one pass
    unmentioned — Cube would emit a complete-looking model quietly missing the
    metric, which is the silent hole the refusal exists to prevent.

    **Period-over-period is not missing from Cube, it lives elsewhere in it.**
    Cube answers it at query time (``compareDateRange`` over a time dimension)
    rather than as a stored measure definition, so there is nothing here to
    emit and a Cube consumer is not blocked. A cumulative window maps onto
    ``rolling_window`` in its trailing form only, and ``grain_to_date`` has no
    equivalent; refusing both is one rule where supporting half would be a rule
    and an exception.
    """

    for metric in ir.metrics:  # sorted by name on ProjectIR
        if metric.derived is not None:
            msg = (
                f"metric {metric.name!r} is derived: over other metrics, which Cube has no "
                "measure shape for — a stored measure aggregates a column, and an offset "
                "input has no static form at all (Cube compares periods at query time via "
                "compareDateRange). Fix: keep the metric for the MetricFlow manifest and "
                "ask Cube for the comparison at query time, or express a division as "
                "ratio: {numerator, denominator}, which does lower here"
            )
            raise UnsupportedByTarget(msg)

        if metric.cumulative is not None:
            msg = (
                f"metric {metric.name!r} declares cumulative:, which Cube expresses only "
                "as a trailing rolling_window — grain_to_date has no equivalent, and "
                "supporting one form silently would make what a cumulative metric means "
                "depend on which of the two was written. Fix: keep the metric for the "
                "MetricFlow manifest, or drop cumulative: and accumulate downstream"
            )
            raise UnsupportedByTarget(msg)


# ....................... #


class CubeEmitter:
    """RFC 0008 §5.4: one cube per mart, one view per mart — YAML data model
    files, dialect-independent by construction."""

    name = "cube"

    # ....................... #

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]:
        """Lower every mart to a cube and a view; artifacts sorted by path,
        content ending in exactly one newline (RFC 0003 §5.5 rule 5). A
        project without marts emits nothing — Cube has no silver surface."""

        _refuse_time_shaped(ir)
        owners = measure_owners(ir)
        artifacts: list[EmittedArtifact] = []

        for mart in ir.marts:  # sorted by name on ProjectIR
            artifacts.append(_cube_artifact(mart, ir, owners, ctx))
            artifacts.append(_view_artifact(mart, ctx))

        return tuple(sorted(artifacts, key=lambda a: a.path))
