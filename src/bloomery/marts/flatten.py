"""Mart flattening: ``lower_marts(mart_set, draft) -> MartLowering``
(RFC 0010 §5.4–§5.5, D6).

Pure: spec in, wide schema out — every consumer sees the *resolved* column
set, never the flatten recipe. Each mart resolves against the draft IR's
entities, relationships, and reachable metrics: the base entity anchors the
grain; ``via:`` steps flatten declared ``many_to_one``/``one_to_one``
relationships transitively in authored order under mandatory prefixes;
``date:`` steps expand a base-entity date/timestamp column into
``<role>_<bucket>`` columns for exactly ``{day, week, month, quarter, year}``
(RFC 0010 D4). Every flattened column becomes a requestable
:class:`~bloomery.ir.MartDimensionIR` (RFC 0010 §10), and every column traces
to exactly one source entity column.

Validation is total — this module never raises. Violations are collected as
:class:`~bloomery.errors.GuardrailError` leaves: :class:`GrainViolation`
(mart grain must equal the base grain, and measure grain must strictly equal
mart grain — RFC 0010 D2), :class:`FanoutRisk` (a ``via:`` step that is not
a declared, transitively reachable ``many_to_one``/``one_to_one``
relationship — RFC 0010 D3), :class:`HistoricalFanout` (a ``via:`` step onto an
``scd: type2`` entity without an ``as_of:`` anchor, an anchor declared on an
entity that is not historical or naming a base column that is not temporal,
or a ``base:`` of a ``type2`` entity — RFC 0023 D1/D2, §5.3),
:class:`MartMissingTimeDimension` (a
measure-carrying mart without a date role — RFC 0010 D9), and untyped
:class:`GuardrailError` leaves for collisions and unresolvable names. The
guardrail stage (RFC 0006 §5.1) batches them into its single aggregate; a
mart with any violation contributes no :class:`~bloomery.ir.MartIR`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.errors import (
    FanoutRisk,
    GrainViolation,
    GuardrailError,
    HistoricalFanout,
    MartMissingTimeDimension,
    MeasureRef,
)
from bloomery.ir import (
    OK_COLUMN,
    REJECT_SUFFIX,
    Cardinality,
    DimensionRef,
    MartAssertIR,
    MartColumnIR,
    MartDimensionIR,
    MartIR,
    MartJoinIR,
    Materialization,
    SCDKind,
    carries_quality_flags,
    partition_specs,
)
from bloomery.spec.marts import ViaStep
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

if TYPE_CHECKING:
    from bloomery.ir import EntityIR, ProjectIR, RelationshipIR
    from bloomery.spec.marts import DateRoleStep, Mart, MartSet

# ----------------------- #

__all__ = [
    "DATE_BUCKETS",
    "HAS_QUALITY_FLAGS",
    "MartLowering",
    "lower_marts",
]

#: The bucket set a date role expands into — exactly the RFC 0011 ``TimeGrain``
#: set minus ``hour``, which is deliberately not expanded (RFC 0010 D4).
DATE_BUCKETS = ("day", "week", "month", "quarter", "year")

#: The quality dimension every mart over a quality-carrying entity flattens in
#: (RFC 0016 §5.5, D9 — the RFC 0010 amendment). It is an **ordinary
#: dimension**, which is the whole point: "revenue excluding flagged rows"
#: becomes a plain ``MetricRequest`` filter, not a new planner concept. It is
#: *derived* from the base entity's generated ``_quality_ok`` per the D23
#: physical contract (``has_quality_flags = NOT _quality_ok``) — never by
#: re-evaluating the rules over the mart, which would be a second
#: implementation of the same predicate and the two would drift.
HAS_QUALITY_FLAGS = "has_quality_flags"

_TYPE_NAMES: dict[type[LogicalType], str] = {
    StringType: "string",
    IntType: "int",
    BoolType: "bool",
    DateType: "date",
    TimestampType: "timestamp",
    VariantType: "variant",
}


def _type_name(t: LogicalType) -> str:
    if isinstance(t, DecimalType):
        return f"decimal({t.precision}, {t.scale})"

    return _TYPE_NAMES[type(t)]


# ....................... #


@dataclass(frozen=True, slots=True)
class MartLowering:
    """The flattener's product: cleanly lowered marts (sorted by name) and
    every violation found, as guardrail leaves for the stage aggregate."""

    marts: tuple[MartIR, ...]
    violations: tuple[GuardrailError, ...]


# ....................... #


@dataclass(slots=True)
class _Flatten:
    """Mutable per-mart flatten state, threaded through the authored steps.

    ``prefixes`` maps each flattened entity to its *earliest* prefix (``""``
    for the base): when the same entity is flattened twice, chains keep
    resolving against the first flatten — deterministic, authored-order rule.
    """

    columns: dict[str, MartColumnIR]
    prefixes: dict[str, str]
    joins: list[MartJoinIR]
    roles: list[str]


# ....................... #


def _grain_prose(entity_name: str, entities: dict[str, EntityIR]) -> str:
    entity = entities.get(entity_name)
    return entity.grain if entity is not None else "undeclared in this project"


# ....................... #


#: What a `type2` entity's author is told to do instead. The two sides of the
#: refusal used to share one line, because there was one shipped answer; the
#: as-of join (RFC 0023 §5.3) gave the *flatten* side a better one and left the
#: base side where it was, so they are now two.
#:
#: A join can be qualified by an anchor. A base cannot: there is nothing to
#: qualify, and the grain lie — a mart declaring one row per entity over a
#: relation holding one per version — is untouched by any predicate. Telling a
#: base-side author to add an `as_of:` would route them to a clause with
#: nowhere to go.
_HISTORICAL_FLATTEN_FIX = (
    "Fix: declare an anchor — as_of: <a date or timestamp column of the base> — "
    "to read the dimension as of that instant, or declare the entity scd: type1"
)

_HISTORICAL_BASE_FIX = (
    "Fix: declare the entity scd: type1, or build a type1 current-view entity "
    "from it and base the mart on that"
)


def _historical_leaf(
    step: ViaStep,
    rel: RelationshipIR,
    entities: dict[str, EntityIR],
    base: EntityIR,
    step_path: str,
) -> list[GuardrailError]:
    """The leaves for the historical/anchor pairing on this step (RFC 0023
    D1, §5.3), or ``[]``.

    Three states, and only the first two are refusals:

    * ``type2`` with no ``as_of:`` — the join would be an equality on the
      relationship's columns and nothing else, and a ``type2`` relation holds
      one row per version per key, so it matches every version and multiplies
      the base grain. Nothing downstream notices: the declared cardinality is
      about the domain, and it is usually correct.
    * ``as_of:`` on a relation that is not ``type2`` — there is no version to
      choose between, so the anchor names a reading that does not exist. Left
      accepted it would emit a predicate against columns the relation does
      not have.
    * ``type2`` with a valid ``as_of:`` — the as-of join, which is the whole
      of RFC 0023 §5.3.

    A list rather than an optional so the callers can splice it into whatever
    they were already returning: these leaves never *replace* a structural
    refusal, they accompany one.

    An entity no mapping lowers yields ``[]``: it has no ``scd`` to read, and
    its own leaf is the one worth reporting.
    """
    to_entity = entities.get(rel.to_entity)

    if to_entity is None:
        return []

    historical = to_entity.scd is SCDKind.TYPE2

    if historical and step.as_of is None:
        msg = (
            f"flatten step joins entity {rel.to_entity!r} through relationship "
            f"{rel.name!r} ({rel.cardinality}), and {rel.to_entity!r} is declared "
            "scd: type2 — without an anchor the emitted join carries no validity "
            f"predicate, so it matches every version of each {rel.to_entity!r} key "
            "and each base row is multiplied by that key's version count. The "
            "declared cardinality is a claim about the domain; the relation holds "
            f"one row per version (RFC 0023 D1). {_HISTORICAL_FLATTEN_FIX}"
        )
        return [HistoricalFanout(msg, source_path=step_path)]

    if not historical and step.as_of is not None:
        msg = (
            f"flatten step declares as_of: {step.as_of!r}, but {rel.to_entity!r} is not "
            "scd: type2 — it holds one row per key, so there is no version to read the "
            "join as of, and the validity columns the anchor joins against do not exist "
            "on it (RFC 0023 §5.3). Fix: drop the as_of, or declare the entity scd: type2"
        )
        return [HistoricalFanout(msg, source_path=step_path)]

    if step.as_of is None:
        return []

    return _anchor_leaves(step.as_of, base, rel, step_path)


# ....................... #


def _anchor_leaves(
    as_of: str, base: EntityIR, rel: RelationshipIR, step_path: str
) -> list[GuardrailError]:
    """The anchor must be a temporal column *of the base entity*.

    On the base rather than anywhere in the mart because that is where a fact's
    own date lives, including in the two-hop shape RFC 0023 §5.3 calls the
    common case: there the anchor is on the fact and only the foreign key comes
    through another flatten. Refusing a non-temporal anchor here rather than
    letting it reach SQL is the same call the SQLMesh time-column check makes —
    comparing a string to an interval bound is a comparison an engine will
    happily perform and answer wrongly.
    """
    column = next((c for c in base.columns if c.name == as_of), None)

    if column is None:
        known = sorted(c.name for c in base.columns)
        msg = (
            f"flatten step declares as_of: {as_of!r}, which names no column of the mart's "
            f"base entity {base.name!r}; known: {known}. The anchor is the fact's own "
            "date, so it is read from the base row (RFC 0023 §5.3). Fix: name a date or "
            "timestamp column of the base"
        )
        return [HistoricalFanout(msg, source_path=step_path)]

    if not isinstance(column.type, DateType | TimestampType):
        # `_type_name`, not the dataclass repr: the author wrote `type: int`,
        # and telling them `IntType()` names a class they have never seen.
        msg = (
            f"flatten step declares as_of: {as_of!r}, which is {_type_name(column.type)} on "
            f"{base.name!r} — an anchor is compared against {rel.to_entity!r}'s validity "
            "interval, and only a date or timestamp orders against one (RFC 0023 §5.3). "
            "Fix: name a date or timestamp column of the base"
        )
        return [HistoricalFanout(msg, source_path=step_path)]

    return []


# ....................... #


def _flatten_via(
    step: ViaStep,
    index: int,
    path: str,
    draft: ProjectIR,
    entities: dict[str, EntityIR],
    base: EntityIR,
    state: _Flatten,
) -> list[GuardrailError]:
    """One ``via:`` step: validate the relationship, record the resolved join,
    and flatten the joined entity's columns under the step's prefix."""
    step_path = f"{path}.flatten[{index}].via"
    rel = next((r for r in draft.relationships if r.name == step.via), None)

    if rel is None:
        known = sorted(r.name for r in draft.relationships)
        msg = f"flatten step names no declared relationship {step.via!r}; known: {known}"
        return [FanoutRisk(msg, source_path=step_path)]

    # Historical is checked *beside* the structural rules below rather than
    # after them, because the two are independent: ``one_to_many`` is a
    # property of the relationship and ``scd: type2`` a property of the
    # entity, and a step can be wrong in both ways at once. Behind an early
    # return it was the second reason that never got reported — and putting it
    # first would only have suppressed the other one instead. The stage exists
    # so an author fixes a spec in one round-trip, so both leaves go out.
    historical = _historical_leaf(step, rel, entities, base, step_path)

    if rel.cardinality is Cardinality.ONE_TO_MANY:
        msg = (
            f"relationship {rel.name!r} is one_to_many: flattening it multiplies the "
            f"mart's own rows once per {rel.to_entity!r} row (RFC 0006 §5.3). Fix: "
            "flatten only many_to_one/one_to_one relationships, or model a mart at "
            f"the grain of {rel.to_entity!r}"
        )
        return [*historical, FanoutRisk(msg, source_path=step_path)]

    if rel.from_entity not in state.prefixes:
        msg = (
            f"relationship {rel.name!r} joins from entity {rel.from_entity!r}, which is "
            "neither the base nor a previously flattened entity — chains flatten "
            "transitively in authored order (RFC 0010 D3). Fix: flatten a relationship "
            f"reaching {rel.from_entity!r} first"
        )
        return [*historical, FanoutRisk(msg, source_path=step_path)]

    to_entity = entities.get(rel.to_entity)

    if to_entity is None:
        msg = (
            f"relationship {rel.name!r} joins entity {rel.to_entity!r}, which no mapping "
            "lowers — a mart cannot flatten an unbuilt entity"
        )
        return [GuardrailError(msg, source_path=step_path)]

    if historical:
        return historical

    from_prefix = state.prefixes[rel.from_entity]
    state.joins.append(
        MartJoinIR(
            relationship=rel.name,
            entity=rel.to_entity,
            prefix=step.prefix,
            on=tuple((f"{from_prefix}{from_col}", to_col) for from_col, to_col in rel.via),
            as_of=step.as_of,
        )
    )
    violations: list[GuardrailError] = []

    for column in to_entity.columns:  # sorted by name on EntityIR
        flattened = f"{step.prefix}{column.name}"
        existing = state.columns.get(flattened)
        if existing is not None:
            msg = (
                f"flattened column {flattened!r} (column {column.name!r} of entity "
                f"{rel.to_entity!r}) collides with the column already flattened from "
                f"entity {existing.source_entity!r} — collisions are errors, never "
                "auto-renamed (RFC 0010 D3). Fix: change the prefix"
            )
            violations.append(GuardrailError(msg, source_path=f"{path}.flatten[{index}].prefix"))
            continue
        state.columns[flattened] = MartColumnIR(
            name=flattened,
            type=column.type,
            source_entity=rel.to_entity,
            source_column=column.name,
        )

    state.prefixes.setdefault(rel.to_entity, step.prefix)

    return violations


# ....................... #


def _flatten_date(
    step: DateRoleStep,
    index: int,
    path: str,
    base: EntityIR,
    state: _Flatten,
) -> list[GuardrailError]:
    """One ``date:`` step: validate role and source column, then expand into
    the ``<role>_<bucket>`` columns with their :class:`DimensionRef`s."""
    role_path = f"{path}.flatten[{index}].role"

    if step.role in state.roles:
        msg = (
            f"date role {step.role!r} is declared more than once — a mart may declare "
            "the same role at most once (RFC 0010 §5.2). Fix: rename one of the roles"
        )
        return [GuardrailError(msg, source_path=role_path)]

    state.roles.append(step.role)
    date_path = f"{path}.flatten[{index}].date"
    source = next((c for c in base.columns if c.name == step.date), None)

    if source is None:
        known = sorted(c.name for c in base.columns)
        msg = (
            f"date role {step.role!r} names column {step.date!r}, which is not a column "
            f"of base entity {base.name!r}; known columns: {known}"
        )
        return [GuardrailError(msg, source_path=date_path)]

    if not isinstance(source.type, (DateType, TimestampType)):
        msg = (
            f"date role source column {step.date!r} has type "
            f"{_type_name(source.type)!r}; a role-playing time dimension requires a "
            "date or timestamp column (RFC 0010 §5.2)"
        )
        return [GuardrailError(msg, source_path=date_path)]

    violations: list[GuardrailError] = []

    for bucket in DATE_BUCKETS:
        name = f"{step.role}_{bucket}"
        existing = state.columns.get(name)
        if existing is not None:
            msg = (
                f"date-role column {name!r} collides with the column already flattened "
                f"from entity {existing.source_entity!r} — collisions are errors, never "
                "auto-renamed (RFC 0010 D3). Fix: rename the role"
            )
            violations.append(GuardrailError(msg, source_path=role_path))
            continue
        state.columns[name] = MartColumnIR(
            name=name,
            type=DateType(),  # buckets are calendar dates; emitters cast (RFC 0010 D4)
            source_entity=base.name,
            source_column=step.date,
            ref=DimensionRef(dimension=bucket, role=step.role),
        )

    return violations


# ....................... #


def _flatten_quality(base: EntityIR, path: str, state: _Flatten) -> list[GuardrailError]:
    """Flatten ``has_quality_flags`` when the base entity carries rules
    (RFC 0016 §5.5 — the RFC 0010 amendment).

    Only the **base** contributes it: a mart is a fact table at exactly its
    base grain, so "was this row suspect" is a statement about the base row.
    Joined dimension entities keep their own flags on their own silver models
    (their generated columns are not ``EntityIR.columns`` and so never flatten
    through a ``via:`` step at all).

    An entity with no rules gets no column rather than a constant ``FALSE``
    one: the dimension would then be present-but-meaningless on marts whose
    base never evaluates anything, and a request filtering on it would read as
    "no flagged rows" instead of "nothing to flag".

    **A step-produced base gets none unless its relation actually has the two
    columns** — :func:`~bloomery.ir.carries_quality_flags` is the one
    definition of that, shared with the quality mart and with the Tier 2
    emission that puts them there. A ``python_model`` output's rows are
    written by the generated wrapper, which projects exactly the manifest's
    declared columns, so there is no ``_quality_flags`` to reduce and no
    ``_quality_ok`` to negate; and a ``fail`` rule stops the run rather than
    marking a row (RFC 0017 §5.8), so nothing survives to be flagged in the
    first place. Flattening the dimension anyway emitted
    ``NOT customer._quality_ok`` against a relation with no such column: a mart
    that compiled clean, passed every golden, and failed on its first run with
    a binder error naming a generated column the author never wrote. A
    ``sql_model`` output carrying an ``on_fail: flag`` rule *does* have them
    (RFC 0051 §5.3), and gets the dimension like any other base.
    """

    if not base.quality or not carries_quality_flags(base):
        return []

    existing = state.columns.get(HAS_QUALITY_FLAGS)

    if existing is not None:
        msg = (
            f"base entity {base.name!r} declares quality rules, so the mart flattens in the "
            f"reserved dimension {HAS_QUALITY_FLAGS!r} (RFC 0016 §5.5) — but the base already "
            f"has a column of that name. Collisions are errors, never auto-renamed "
            f"(RFC 0010 D3). Fix: rename the entity field"
        )
        return [GuardrailError(msg, source_path=f"{path}.base")]

    state.columns[HAS_QUALITY_FLAGS] = MartColumnIR(
        name=HAS_QUALITY_FLAGS,
        type=BoolType(),
        source_entity=base.name,
        # Traced to the generated ``_quality_ok`` (D23), not re-derived: the
        # mart projection is ``NOT <base>._quality_ok``.
        source_column=OK_COLUMN,
    )

    return []


# ....................... #


def _check_measures(
    mart: Mart,
    path: str,
    draft: ProjectIR,
    entities: dict[str, EntityIR],
) -> list[GuardrailError]:
    """RFC 0010 §5.5 rules 1 and 5: measures are reachable metrics whose
    grain strictly equals the mart grain."""
    metrics = {m.name: m for m in draft.metrics}
    unreachable = {u.name: u for u in draft.unreachable}
    violations: list[GuardrailError] = []

    for measure in mart.measures:
        measure_path = f"{path}.measures.{measure}"
        metric = metrics.get(measure)
        if metric is None:
            if measure in unreachable:
                missing = list(unreachable[measure].missing)
                msg = (
                    f"measure {measure!r} is an unreachable metric — its leaves "
                    f"{missing} have no mapped derivation path (RFC 0005 §5.3), so the "
                    "mart cannot serve it. Fix: map the missing leaves, or remove the "
                    "measure"
                )
            else:
                msg = f"measure names no declared metric {measure!r}; known: {sorted(metrics)}"
            violations.append(GuardrailError(msg, source_path=measure_path))
            continue
        if metric.grain != mart.grain:
            msg = (
                f"measure {measure!r} has grain {metric.grain!r} "
                f"({_grain_prose(metric.grain, entities)}), not the mart's grain "
                f"{mart.grain!r} ({_grain_prose(mart.grain, entities)}) — measure grain "
                "must strictly equal mart grain (RFC 0010 D2). Flattened into the mart "
                f"it is duplicated once per {mart.grain!r} row and any SUM over it "
                "overstates. Fix: remove it from this mart's measures, or serve it "
                f"from a mart at grain {metric.grain!r}"
            )
            violations.append(
                GrainViolation(
                    msg,
                    source_path=measure_path,
                    offending_measures=(MeasureRef(measure=measure, grain=metric.grain),),
                )
            )

    return violations


# ....................... #


def _check_asserts(mart: Mart, path: str, state: _Flatten) -> list[GuardrailError]:
    """Every assertion names columns of the **flattened** mart (RFC 0016 D89).

    Checked against ``state.columns`` rather than the base entity's, because
    that is the schema the audit runs over: a ``by:`` naming a bucket column a
    ``date:`` role produced is legitimate — it is the ``ordered_month`` case
    §10's example is about — and a ``measure:`` naming a prefixed column
    flattened from a joined entity is too.

    Names are checked here rather than at parse for the reason every other
    resolution check is: the mart's column set does not exist until the
    flatten steps have run (RFC 0002 D4).
    """
    violations: list[GuardrailError] = []
    seen: set[str] = set()

    for index, clause in enumerate(mart.assert_):
        where = f"{path}.assert[{index}]"
        if clause.name in seen:
            msg = (
                f"two assertions on this mart are named {clause.name!r} — the name is the "
                "audit's identity, so the second would overwrite the first's artifact"
            )
            violations.append(GuardrailError(msg, source_path=f"{where}.name"))
        seen.add(clause.name)
        for role, column in (("measure", clause.measure), *(("by", name) for name in clause.by)):
            if column in state.columns:
                continue
            msg = (
                f"assertion {clause.name!r} names {role} column {column!r}, which this mart "
                f"does not carry; flattened columns: {sorted(state.columns)}"
            )
            violations.append(GuardrailError(msg, source_path=f"{where}.{role}"))

    return violations


# ....................... #


def _materialization(mart: Mart) -> Materialization:
    """RFC 0002 D7, applied to marts as to entities (RFC 0010 §4): explicit
    wins; else partitioned marts default to incremental-by-partition."""

    if mart.materialization is not None:
        return Materialization(mart.materialization)

    if mart.partition_by:
        return Materialization.INCREMENTAL_BY_PARTITION

    return Materialization.FULL


# ....................... #


def _mart_ir(name: str, mart: Mart, state: _Flatten) -> MartIR:
    columns = tuple(sorted(state.columns.values(), key=lambda c: c.name))
    # Every flattened column is a requestable dimension (RFC 0010 §10). A
    # bucket column's ref.qualified equals its column name, so sorting by
    # column name is sorting by qualified name.
    dimensions = tuple(
        MartDimensionIR(
            ref=column.ref if column.ref is not None else DimensionRef(dimension=column.name),
            column=column.name,
        )
        for column in columns
    )
    return MartIR(
        name=name,
        grain=mart.grain,
        base=mart.base,
        columns=columns,
        measures=tuple(sorted(mart.measures)),
        dimensions=dimensions,
        joins=tuple(state.joins),  # authored order — join order is semantic
        partition_by=partition_specs(mart.partition_by),
        materialization=_materialization(mart),
        asserts=_mart_asserts(mart),
        cost_hint=mart.cost_hint,
    )


# ....................... #


def _mart_asserts(mart: Mart) -> tuple[MartAssertIR, ...]:
    """The mart's aggregate assertions, sorted by name (RFC 0016 D89).

    Bounds ride in ``params`` as text, the carrier every other bounded rule in
    this compiler uses (RFC 0016 D57): a ``range`` bound and a mart assertion's
    bound are the same kind of value, and a second representation for it is how
    the two come to disagree about ``1e3``.
    """

    return tuple(
        sorted(
            (
                MartAssertIR(
                    name=clause.name,
                    column=clause.measure,
                    agg=clause.agg,
                    by=clause.by,
                    params=tuple(
                        sorted(
                            (bound, str(value))
                            for bound, value in (("min", clause.min), ("max", clause.max))
                            if value is not None
                        )
                    ),
                    blocking=clause.on_fail == "fail",
                )
                for clause in mart.assert_
            ),
            key=lambda clause: clause.name,
        )
    )


# ....................... #


def _reject_base(mart: Mart) -> str | None:
    """The message refusing a mart based on a reject table, or ``None``.

    RFC 0016 D15: a mart's ``base`` must be a **silver entity**, never a
    ``<entity>__reject`` table. Reject tables hold raw source payloads under
    their own retention and are deliberately *not* an analytic surface (§7.4:
    they are never exposed through ``MetricRequest``) — a mart over one would
    publish quarantined PII through the semantic layer and report numbers
    built from rows the pipeline decided to withhold.

    Refused on the *name*, before the "no mapping lowers this entity" fallback,
    so the author reads why rather than a generic missing-entity message.
    """

    if not mart.base.endswith(REJECT_SUFFIX):
        return None

    entity = mart.base.removesuffix(REJECT_SUFFIX)
    return (
        f"mart base names the reject table {mart.base!r}: a mart's base must be a silver "
        f"entity, never a quarantine surface (RFC 0016 §5.5, D15). Reject rows hold raw "
        "source payloads under their own retention and are deliberately not queryable "
        f"through the semantic layer (§7.4). Fix: base the mart on {entity!r}, and read "
        "quarantine volume from the gold.mart_data_quality mart (§5.8)"
    )


# ....................... #


def _lower_mart(
    name: str, mart: Mart, draft: ProjectIR
) -> tuple[MartIR | None, list[GuardrailError]]:
    path = f"marts: marts.{name}"
    entities = {e.name: e for e in draft.entities}
    rejected = _reject_base(mart)

    if rejected is not None:
        return None, [GuardrailError(rejected, source_path=f"{path}.base")]

    base = entities.get(mart.base)

    if base is None:
        msg = (
            f"mart base names entity {mart.base!r}, which no mapping lowers; "
            f"mapped entities: {sorted(entities)}"
        )
        return None, [GuardrailError(msg, source_path=f"{path}.base")]

    violations: list[GuardrailError] = []

    if base.scd is SCDKind.TYPE2:
        # RFC 0023 D2. Nothing is multiplied here — there is no join — but the
        # mart declares one row per entity while the relation holds one per
        # entity per version, so every measure over it counts revisions rather
        # than entities. That is the same grain lie ``GrainViolation`` refuses
        # above, arriving through the physical relation instead of the header.
        msg = (
            f"mart base names entity {mart.base!r}, which is declared scd: type2 — the "
            f"relation holds one row per {mart.base!r} version, while the mart's grain "
            f"({mart.grain!r}) claims one row per {mart.base!r}. Every measure over it "
            f"counts revisions (RFC 0023 D2). {_HISTORICAL_BASE_FIX}"
        )
        violations.append(HistoricalFanout(msg, source_path=f"{path}.base"))

    if mart.grain != mart.base:
        msg = (
            f"mart grain {mart.grain!r} does not equal its base entity {mart.base!r} "
            f"(grain: {base.grain}) — a mart is a fact table at exactly its base grain "
            f"(RFC 0010 D2). Fix: declare grain: {mart.base}, or rebase the mart"
        )
        violations.append(GrainViolation(msg, source_path=f"{path}.grain"))

    state = _Flatten(
        columns={
            column.name: MartColumnIR(
                name=column.name,
                type=column.type,
                source_entity=base.name,
                source_column=column.name,
            )
            for column in base.columns
        },
        prefixes={base.name: ""},
        joins=[],
        roles=[],
    )
    violations.extend(_flatten_quality(base, path, state))

    for index, step in enumerate(mart.flatten):
        if isinstance(step, ViaStep):
            violations.extend(_flatten_via(step, index, path, draft, entities, base, state))
        else:
            violations.extend(_flatten_date(step, index, path, base, state))

    violations.extend(_check_measures(mart, path, draft, entities))
    violations.extend(_check_asserts(mart, path, state))

    if mart.measures and not state.roles:
        msg = (
            f"mart carries measures {sorted(mart.measures)} but declares no date role — "
            "MetricFlow requires agg_time_dimension on every measure and fails obscurely "
            "without one (RFC 0010 D9). Fix: add a date role flatten step, e.g. "
            "{date: <date/timestamp column>, role: <role>}"
        )
        violations.append(MartMissingTimeDimension(msg, source_path=path))

    if violations:
        return None, violations

    return _mart_ir(name, mart, state), []


# ....................... #


def lower_marts(mart_set: MartSet | None, draft: ProjectIR) -> MartLowering:
    """Resolve every authored mart against the draft IR (RFC 0010 D6).

    Total — never raises: the cleanly lowered marts come back sorted by name,
    and every violation across all marts comes back as guardrail leaves for
    the stage's single aggregate (RFC 0006 §5.1). A mart with any violation
    contributes no :class:`MartIR`; a project without a marts document lowers
    to the empty tuple (RFC 0010 D7).
    """

    if mart_set is None:
        return MartLowering(marts=(), violations=())

    marts: list[MartIR] = []
    violations: list[GuardrailError] = []

    for name in sorted(mart_set.marts):
        mart_ir, found = _lower_mart(name, mart_set.marts[name], draft)
        violations.extend(found)
        if mart_ir is not None:
            marts.append(mart_ir)

    return MartLowering(marts=tuple(marts), violations=tuple(violations))
