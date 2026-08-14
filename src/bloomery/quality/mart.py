"""``gold.mart_data_quality`` — the quality mart as an **ordinary** semantic
surface (RFC 0016 §5.8, D12).

Every rule evaluation contributes a row ``(entity, mapping, rule, disposition,
rows_evaluated, rows_failed, rows_quarantined, rows_deduped, run_id,
run_date)``. The point of the design is what it *is not*: not a bespoke
observability endpoint, not a log, not a side channel. It is a
:class:`~bloomery.ir.MartIR` with measures and a date role like any other, so
"quarantine rate over the last 30 days by entity" is a plain
``MetricRequest`` — and a rising rate is a *semantic* drift signal structural
detection misses (prices arriving in cents change no schema).

**Two grains in one table, and why the schema still has one shape.** §5.8's
column list is flat, but its four counts are not all facts about a *rule*.
``rows_failed`` is: it is what one predicate did. ``rows_evaluated``,
``rows_quarantined`` and ``rows_deduped`` are facts about the entity's
population — how many rows the rules ran over, how many the split diverted,
how many dedupe removed before any rule saw them. Repeating those on every
rule row is a fan-out: summing them multiplies by the rule count, and the
quarantine rate §5.8 promises comes out wrong by that factor (and wrong again
in its numerator, since a row tripping two quarantine rules is *one* diverted
row). So each entity contributes one extra row — :data:`ENTITY_GRAIN_ROW` in
the ``rule`` and ``disposition`` dimensions — carrying the population counts,
and rule rows carry zero in those columns. Every measure is then additive at
every group-by, which is the only reading under which "a plain
``MetricRequest``" is true rather than true-if-you-group-by-rule.

Deliberate divergences, both recorded in the RFC:

- **No per-customer scoping column.** Document 5 §7.5's schema carries one;
  the mart emitted here does not, and RFC 0016 §5.8 records the divergence.
  Hard invariant #3 and the RFC 0009 D14 guard make namespace scoping via
  ``NamingPolicy`` the *only* seam of that shape in the package — a caller
  wanting a per-customer rollup gets it from their namespace layout, as for
  every other table. (The guard is a source scan, so this module cannot even
  spell the word the RFC uses for it.)
- **Reject tables stay unqueryable.** The mart reports *counts* over reject
  rows; the rows themselves are never exposed through ``MetricRequest``
  (§7.4) — raw payloads, different retention, a deliberately narrow operator
  surface. Nothing here emits a reject relation as a mart base (RFC 0016 D15
  refuses that at compile time).

The mart is bloomery-owned, like the ``dim_date`` calendar: it is synthesized
from the IR rather than authored, so ``base`` names the mart itself — there is
no silver entity underneath it. :func:`is_quality_mart` is the one predicate
every consumer branches on; nothing else in the package pattern-matches the
name.

**Metric names are reserved.** The five metrics below are added to
``ProjectIR.metrics``, which is a flat namespace, so a project declaring a
metric of the same name is a compile-time refusal
(:mod:`bloomery.guardrails.quality`) rather than a silently duplicated name.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from bloomery.ir import (
    Additivity,
    DimensionRef,
    EntityIR,
    MartColumnIR,
    MartDimensionIR,
    MartIR,
    Materialization,
    MetricIR,
    ProjectIR,
    Ratio,
    SqlExpr,
)
from bloomery.typing import DateType, IntType, LogicalType, StringType

__all__ = [
    "ENTITY_GRAIN_ROW",
    "QUALITY_MART",
    "QUALITY_MART_COLUMNS",
    "QUALITY_MEASURE_COLUMNS",
    "QUALITY_METRICS",
    "QUALITY_RUN_ROLE",
    "RunContext",
    "attach_quality_mart",
    "counted_entities",
    "is_quality_mart",
    "quality_mart_ir",
]

#: The reserved ``rule`` / ``disposition`` value of an entity's accounting row
#: (see this module's docstring on the two grains).
#:
#: It carries parentheses **deliberately**: rule names and reconcile names are
#: constrained to ``[a-z0-9_]+`` at spec parse (D23), so no authored name can
#: ever equal this one. A reserved word spelled inside the authorable alphabet
#: would be a collision waiting for the project that uses it.
ENTITY_GRAIN_ROW = "(entity)"

#: The mart's logical name. Under any :class:`~bloomery.naming.NamingPolicy`
#: it becomes the gold relation §5.8 names — ``gold.mart_data_quality`` under
#: the default policy, namespace-prefixed under a scoped one.
QUALITY_MART = "data_quality"

#: The date role over ``run_date`` (RFC 0010 D9: a measure-carrying mart
#: declares one, or ``MartMissingTimeDimension``). It buckets into
#: ``run_day`` … ``run_year`` exactly as an authored role does.
QUALITY_RUN_ROLE = "run"

#: The bucket set a date role expands into. Spelled here rather than imported
#: from :mod:`bloomery.marts` because that package sits *below* this one in the
#: import contract; the two are pinned equal by a unit test.
_DATE_BUCKETS = ("day", "week", "month", "quarter", "year")

#: The four count columns of §5.8, in schema order, with the metric each is
#: measured by. Counts, never rates: a rate is a ratio *metric* over two
#: additive measures, so it stays correct under any group-by.
#:
#: "Additive" is a claim about the emitted rows, not only about the column
#: types, and it is the reason the mart carries an entity accounting row
#: (:data:`ENTITY_GRAIN_ROW`): three of these four counts describe the entity's
#: population, and repeating them per rule would make ``SUM`` return a multiple
#: of the truth. Each count is emitted on exactly one row per entity-and-grain,
#: zero elsewhere — which is what makes the sentence above true rather than
#: aspirational.
QUALITY_MEASURE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rows_evaluated", "quality_rows_evaluated"),
    ("rows_failed", "quality_rows_failed"),
    ("rows_quarantined", "quality_rows_quarantined"),
    ("rows_deduped", "quality_rows_deduped"),
)

#: The dimension columns of §5.8, minus the divergence recorded in this
#: module's docstring. ``run_id``/``run_date`` are the engine's run context.
_DIMENSION_COLUMNS: tuple[tuple[str, LogicalType], ...] = (
    ("entity", StringType()),
    ("mapping", StringType()),
    ("rule", StringType()),
    ("disposition", StringType()),
    ("run_id", StringType()),
    ("run_date", DateType()),
)

#: The quarantine rate §5.8 promises as "a plain ``MetricRequest``": a ratio
#: over two additive measures, so it is correct at every grouping — a stored
#: rate column would not be.
_RATE_METRIC = "quality_quarantine_rate"

#: Every metric name this module owns, sorted — the reserved set the guardrail
#: stage refuses collisions against.
QUALITY_METRICS: tuple[str, ...] = tuple(
    sorted((_RATE_METRIC, *(metric for _column, metric in QUALITY_MEASURE_COLUMNS)))
)

_DESCRIPTIONS: dict[str, str] = {
    "quality_rows_evaluated": (
        "Rows the entity's rules were evaluated over (survivors of dedupe), "
        "reported once per entity."
    ),
    "quality_rows_failed": "Rows whose violation predicate fired, whatever its disposition.",
    "quality_rows_quarantined": (
        "Rows the split diverted to the entity's reject table, counted once per row "
        "however many rules diverted it."
    ),
    "quality_rows_deduped": "Rows dedupe removed before the rules ran (per entity).",
    _RATE_METRIC: "Quarantined rows as a share of rows evaluated.",
}


@dataclass(frozen=True, slots=True)
class RunContext:
    """How the **executing engine** supplies ``run_id`` and ``run_date``.

    bloomery never reads a clock (RFC 0003): a compile that stamped "now" into
    a model would make the artifact a function of when it was compiled, and
    the same specs would stop producing byte-identical output. So the two run
    columns are the engine's to fill, and this value says which expression
    each target substitutes.

    Each field is the *literal text* of an engine-side expression — a macro
    reference such as SQLMesh's ``@execution_ds`` — or ``None``, in which case
    the column is emitted **declared but NULL**, carrying an inline SQL
    comment naming what the caller has to supply. That is the honest lowering
    when the pinned framework offers no such macro: the column exists, the
    schema matches §5.8, and nobody is misled into thinking a value is there.
    """

    run_id: str | None = None
    run_date: str | None = None


def is_quality_mart(mart: MartIR) -> bool:
    """Whether this is the bloomery-owned quality mart.

    The one predicate consumers branch on. It matters because the quality
    mart's ``base`` is *not* a silver entity: emitters that resolve a mart's
    base entity (for its key, or to build the flatten join) must take the
    other path here.
    """
    return mart.name == QUALITY_MART


def _columns() -> tuple[MartColumnIR, ...]:
    columns = [
        MartColumnIR(name=name, type=logical, source_entity=QUALITY_MART, source_column=name)
        for name, logical in _DIMENSION_COLUMNS
    ]
    columns.extend(
        MartColumnIR(name=name, type=IntType(), source_entity=QUALITY_MART, source_column=name)
        for name, _metric in QUALITY_MEASURE_COLUMNS
    )
    columns.extend(
        MartColumnIR(
            name=f"{QUALITY_RUN_ROLE}_{bucket}",
            type=DateType(),
            source_entity=QUALITY_MART,
            source_column="run_date",
            ref=DimensionRef(dimension=bucket, role=QUALITY_RUN_ROLE),
        )
        for bucket in _DATE_BUCKETS
    )
    return tuple(sorted(columns, key=lambda column: column.name))


def quality_mart_ir() -> MartIR:
    """The mart node itself — a pure constant function of the schema above.

    ``FULL`` materialization, deliberately: the mart is a snapshot of the
    latest run's rule evaluations, and its counts are derived from the current
    contents of the silver and reject tables. There is nothing to accumulate
    incrementally that would not double-count.
    """
    columns = _columns()
    return MartIR(
        name=QUALITY_MART,
        grain=QUALITY_MART,
        # Self-based: there is no silver entity under this mart (see
        # ``is_quality_mart``). It is never an authored ``base:``, so RFC 0016
        # D15's "a mart's base must be a silver entity" is untouched — that
        # rule governs what an author may write.
        base=QUALITY_MART,
        columns=columns,
        measures=tuple(sorted(metric for _column, metric in QUALITY_MEASURE_COLUMNS)),
        dimensions=tuple(
            MartDimensionIR(
                ref=column.ref if column.ref is not None else DimensionRef(dimension=column.name),
                column=column.name,
            )
            for column in columns
        ),
        joins=(),
        partition_by=(),
        materialization=Materialization.FULL,
        cost_hint=1,
    )


def quality_metrics() -> tuple[MetricIR, ...]:
    """The four additive counts plus the quarantine rate, sorted by name."""
    metrics = [
        MetricIR(
            name=metric,
            grain=QUALITY_MART,
            additivity=Additivity.ADDITIVE,
            agg="sum",
            expr=SqlExpr(column),
            ratio=None,
            semi_additive=None,
            description=_DESCRIPTIONS[metric],
        )
        for column, metric in QUALITY_MEASURE_COLUMNS
    ]
    metrics.append(
        MetricIR(
            name=_RATE_METRIC,
            grain=QUALITY_MART,
            additivity=Additivity.NON_ADDITIVE,
            agg=None,
            expr=None,
            ratio=Ratio(numerator="quality_rows_quarantined", denominator="quality_rows_evaluated"),
            semi_additive=None,
            description=_DESCRIPTIONS[_RATE_METRIC],
            depends_on=("quality_rows_evaluated", "quality_rows_quarantined"),
        )
    )
    return tuple(sorted(metrics, key=lambda metric: metric.name))


def counted_entities(ir: ProjectIR) -> tuple[EntityIR, ...]:
    """The entities the quality mart can count rows for.

    Rule-carrying, and **not step-produced**. A step's rows are written by its
    generated wrapper, which projects exactly the manifest's declared columns —
    so the relation has no ``_quality_flags`` array to reduce and no
    ``<entity>__reject`` table to count. Its one permitted rule kind is an
    ``expression`` with ``on_fail: fail``, which lowers to a blocking audit
    that stops the run rather than marking a row (RFC 0017 §5.8): there is
    nothing evaluated-but-surviving for the mart to report.

    Counting it anyway emitted ``_quality_flags AS _flags`` against a relation
    with no such column — a gold model that compiled clean, passed every
    golden, and failed on its first run.

    One definition, because :func:`carries_quality` and the emitter's branch
    loop have to agree exactly: if the first says yes and the second finds
    nothing to count, the mart is emitted with no branches at all.
    """
    return tuple(entity for entity in ir.entities if entity.quality and entity.produced_by is None)


def carries_quality(ir: ProjectIR) -> bool:
    """Whether anything in the project evaluates a rule at run time.

    The mart exists only where there is something to report: a project that
    never heard of data quality gets no extra gold model, no extra metrics,
    and no golden churn.
    """
    return bool(counted_entities(ir)) or bool(ir.reconcile)


def attach_quality_mart(ir: ProjectIR) -> ProjectIR:
    """Append the quality mart and its metrics to a finished IR.

    Runs **after** the guardrail stage: the mart is bloomery-owned, so there
    is nothing about it for a guardrail to refuse — what a guardrail *does*
    check is that no authored metric took one of its reserved names, and that
    it can do from the spec alone.
    """
    if not carries_quality(ir):
        return ir
    return replace(
        ir,
        marts=tuple(sorted((*ir.marts, quality_mart_ir()), key=lambda mart: mart.name)),
        metrics=tuple(sorted((*ir.metrics, *quality_metrics()), key=lambda m: m.name)),
    )


#: Every column of the emitted mart, in the order the SELECT projects them —
#: the §5.8 schema, with this module's docstring's divergence applied.
QUALITY_MART_COLUMNS: tuple[str, ...] = tuple(column.name for column in _columns())
