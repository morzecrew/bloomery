"""Shared SELECT lowering (RFC 0008 §5.2): the dialect-neutral SQLGlot ASTs
every SQL-emitting target renders through its ``DialectPort``.

SQLMesh and dbt emit the *same* silver/gold SELECT for the same entity or
mart under the same dialect — only the envelope differs (RFC 0008 D1: target
and dialect never collapse). Keeping the AST construction here makes that a
structural property instead of a convention: an emitter that built its own
SELECT would be reintroducing the N×M template duplication the three-port
split exists to prevent (RFC 0008 §2).

Everything here is one dialect-neutral AST per artifact — never per-dialect
templates. Where engines disagree syntactically (the ``dim_date`` calendar),
the neutral node is chosen so SQLGlot's generators produce legal SQL on every
shipped dialect; the choice is documented at the node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.dialects import DialectFeature
from bloomery.errors import EmitError, UnsupportedByTarget
from bloomery.ir import (
    AuditIR,
    DateDimensionIR,
    EntityIR,
    Layer,
    MartColumnIR,
    MartIR,
    OnFail,
    ProjectIR,
    QualityRuleIR,
    ReconcileIR,
    SCDKind,
    SqlExpr,
    generic_type,
)
from bloomery.marts import DATE_BUCKETS, HAS_QUALITY_FLAGS
from bloomery.quality import (
    ENTITY_GRAIN_ROW,
    FLAGS_COLUMN,
    INGESTION_METADATA,
    OK_COLUMN,
    QUALITY_MEASURE_COLUMNS,
    QUALITY_RUN_ROLE,
    RECONCILE_SUFFIX,
    REJECT_COLUMNS,
    REJECT_SUFFIX,
    ROW_ID_COLUMN,
    SUPERSEDED_RULE,
    ReconcileSide,
    RunContext,
    conjunction,
    dedupe_order,
    disjunction,
    disposition,
    empty_flags,
    flag_member,
    flags_expression,
    grouped,
    indexed_params,
    is_not_null,
    is_null,
    params_of,
    parse_side,
    payload_key,
    quality_ok,
    ref_alias,
    reject_id,
    routing_predicate,
    sole_via_column,
    source_alias,
    unknown_member_case,
    verdict,
    violation,
    window_alias,
    windowed,
    with_dedupe_qualify,
)
from bloomery.typing import DecimalType, IntType, LogicalType

if TYPE_CHECKING:
    from bloomery.emit.base import EmitContext

__all__ = [
    "THIS_MODEL",
    "audit_predicate",
    "column_type",
    "conservation_audit",
    "conservation_audit_select",
    "dim_date_select",
    "entity_select",
    "enum_literal",
    "fail_audits",
    "ROW_ID_COUNT_COLUMN",
    "ingestion_audit_predicate",
    "mart_select",
    "quality_mart_select",
    "reconcile_audit_blocking",
    "reconcile_audit_predicate",
    "reconcile_keys",
    "reconcile_relation",
    "reconcile_select",
    "REJECT_KEY",
    "reject_relation",
    "reject_select",
    "reject_when_matched",
    "replay_statements",
]

# ....................... #
# Data quality (RFC 0016 §5.4–§5.6). The fixed pipeline order — extract →
# transform → dedupe → field rules → row rules → route — is rendered as
# nested SELECTs, one level per group of stages, so the emitted SQL reads in
# the order the RFC declares:
#
#   level 1  ``_extract``    stages 1–3: projections, ingestion metadata,
#                            the dedupe ``QUALIFY``
#   level 2  ``_evaluated``  stages 4–6: the rule predicates, the single
#                            ``_quality_flags`` pass, the routing ``WHERE``
#   level 3  the model       ``_quality_ok``, generated from the flag column
#
# Both SQL targets share every line of this: SQLMesh and dbt emit the same
# silver SELECT for the same entity under the same dialect (RFC 0008 D1).

#: The alias of the extract/dedupe subquery. Entity columns are qualified with
#: it so a ``referential`` LEFT JOIN can never make a reference ambiguous.
_EXTRACT_ALIAS = "_extract"
#: The alias of the *inner* extract, below the staging level that computes
#: window-valued rule verdicts (:data:`~bloomery.quality.WINDOWED_KINDS`).
_DEDUPED_ALIAS = "_deduped"
_EVALUATED_ALIAS = "_evaluated"
_TARGET_ALIAS = "_target"
#: The column the D21 audit body projects its duplicate count under.
ROW_ID_COUNT_COLUMN = "_row_id_count"


def _schema_column(name: str, schema: tuple[str, ...], role: str) -> str:
    """``name``, checked to be a member of ``schema``.

    The point is the *dependency*, stated where it can be read: these constants
    single out one column of a schema tuple declared elsewhere, and they are
    only correct while that column is still in it. The shape this replaces —
    ``next(n for n in SCHEMA if n == "reject_id")`` — is an identity filter that
    spells the name twice and, on the day the column leaves the tuple, raises a
    bare ``StopIteration`` at *import time* naming neither the column nor the
    schema. A module that cannot be imported deserves a sentence saying why.
    """
    if name not in schema:
        msg = (
            f"{role} is spelled {name!r}, which is no longer one of {', '.join(schema)} — "
            "the schema tuple moved and this constant did not follow it"
        )
        raise EmitError(msg)
    return name


#: The recency column of the ingestion-metadata contract — drawn from the
#: contract tuple rather than spelled again, so the two cannot drift.
_INGESTED_AT_COLUMN = _schema_column(
    "_ingested_at", INGESTION_METADATA, "the dedupe recency column"
)
_REPLAY_ALIAS = "_replay"


def reject_relation(entity: EntityIR) -> str:
    """``<entity>__reject`` — one per entity, never per mapping (RFC 0016
    §5.6, D10): per-mapping tables multiply into the small-file problem and
    make replay N-way."""
    return f"{entity.name}{REJECT_SUFFIX}"


def _arrays(ctx: EmitContext) -> bool:
    return ctx.dialect.supports(DialectFeature.ARRAY)


def _rules(entity: EntityIR, *dispositions: OnFail) -> tuple[QualityRuleIR, ...]:
    """The entity's rules with one of ``dispositions``, in canonical order."""
    return tuple(rule for rule in entity.quality if disposition(rule) in dispositions)


def _recorded_rules(entity: EntityIR) -> tuple[QualityRuleIR, ...]:
    """Every rule whose name a reject row records in ``failed_rules`` (D18).

    All of them — a reject row is the full account of why a row is not in the
    entity, "its flag-level failures included", and by the same argument its
    blocking ones. Excluding ``fail`` rules left the account silent about the
    most serious thing that happened to the row.
    """
    return _rules(entity, OnFail.FLAG, OnFail.QUARANTINE, OnFail.FAIL)


def _windowed_rules(entity: EntityIR) -> tuple[QualityRuleIR, ...]:
    """The entity's rules whose predicate is a window function, in canonical
    order (:data:`~bloomery.quality.WINDOWED_KINDS`)."""
    return tuple(rule for rule in entity.quality if windowed(rule))


def _stage(select: exp.Select, entity: EntityIR) -> exp.Select:
    """Wrap an extract SELECT in the level that computes windowed verdicts.

    The window is deliberately computed **above** the dedupe ``QUALIFY``, not
    beside it: rules run after dedupe (§5.4's fixed order), so ``unique`` must
    see the survivors and not the raw deliveries. A row that lost its key to a
    later delivery is not a duplicate — it is a superseded version, which is
    dedupe's business and never ``unique``'s (D5).

    No windowed rules means no extra level: the specialization is the general
    form evaluated at compile.
    """
    rules = _windowed_rules(entity)
    if not rules:
        return select
    return (
        exp.Select()
        .select(
            exp.Star(),
            *(
                # Parenthesised: a bare ``a AND b AS name`` reads correctly to
                # every parser here, and reads *ambiguously* to every human.
                cast("Expression", exp.alias_(grouped(violation(rule)), window_alias(rule)))
                for rule in rules
            ),
        )
        .from_(select.subquery(alias=_DEDUPED_ALIAS))
    )


def _flag_pairs(rules: tuple[QualityRuleIR, ...], table: str) -> list[tuple[str, Expression]]:
    return [(rule.name, verdict(rule, table)) for rule in rules]


def _carries_metadata(entity: EntityIR) -> bool:
    """Whether the ingestion-metadata columns ride through to silver.

    An entity using ``quarantine`` or ``dedupe`` needs them at run time, not
    only at compile: dedupe's final sort key is ``_source_row_id``, the reject
    table's identity is built from it, replay compares incumbents by it, and
    the D21 blocking audit reads all three off the model.
    """
    return entity.dedupe is not None or entity.quarantine is not None


def _referential_rules(entity: EntityIR) -> tuple[QualityRuleIR, ...]:
    return tuple(rule for rule in entity.quality if rule.kind == "referential")


def _with_probes(select: exp.Select, entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """LEFT JOIN one probe per ``referential`` rule (RFC 0016 §5.4).

    The referenced entity is *silver*, and topological ordering (RFC 0005)
    guarantees it is built first — so the probe is an ordinary join, not a
    cross-layer read.
    """
    joined = select
    for rule in _referential_rules(entity):
        params = params_of(rule)
        alias = ref_alias(params["relationship"])
        namespace, relation = ctx.naming.relation(params["to_entity"], Layer.SILVER)
        conditions = [
            exp.EQ(
                this=exp.column(pair.split("=", 1)[0], table=_EXTRACT_ALIAS),
                expression=exp.column(pair.split("=", 1)[1], table=alias),
            )
            for name, pair in rule.params
            if name.startswith("via_")
        ]
        joined = joined.join(
            exp.table_(relation, db=namespace, alias=alias),
            on=conjunction(conditions),
            join_type="LEFT",
        )
    return joined


def _payload_columns(entity: EntityIR) -> tuple[str, ...]:
    """The bronze **columns** ``raw`` carries, sorted — mapped and
    acknowledged-unmapped alike, minus the redacted ones.

    ``raw`` is keyed by top-level bronze column, not by JSONPath, because that
    is what makes replay work: the lowered column expressions read
    ``JSON_EXTRACT_SCALAR(a, '$.b')`` off a *column* ``a``, and replay re-runs
    those same expressions against ``raw`` (RFC 0016 §5.6). Keying by column is
    also the honest reading of "the bronze payload" — a row, not a projection.

    Redaction therefore acts at column granularity, which is exactly the
    granularity ``RedactionConflict`` refuses at (:mod:`bloomery.guardrails.quality`):
    a ``redact:`` path sharing a top-level column with any path the mapping
    reads is a compile error, so redaction can only ever remove a column
    nothing reads.
    """
    redacted = frozenset(
        payload_key(path) for path in (entity.quarantine.redact if entity.quarantine else ())
    )
    paths = {field.source_path for field in entity.source.fields} | set(entity.source.unmapped)
    return tuple(sorted({payload_key(path) for path in paths} - redacted))


def _json_object(pairs: list[tuple[str, Expression]]) -> Expression:
    """``JSON_OBJECT('k', v, …)`` — the one construction SQLGlot renders
    verbatim on every shipped dialect, keys in the caller's (sorted) order."""
    arguments: list[Expression] = []
    for key, value in pairs:
        arguments.extend((exp.Literal.string(key), value))
    return cast("Expression", exp.func("JSON_OBJECT", *arguments))


def _extract_select(
    entity: EntityIR, ctx: EmitContext, *, include_raw: bool = False, from_payload: bool = False
) -> exp.Select:
    """Stages 1–3: the bronze projections, the ingestion metadata, the ``raw``
    payload where a reject table needs it, and the dedupe ``QUALIFY``.

    ``from_payload`` builds the **replay** form of the same stages: the very
    same lowered column expressions, with their bronze column references
    rewritten to extractions out of the reject table's ``raw``. One lowering,
    two sources — replay cannot drift from the pipeline because it *is* the
    pipeline (RFC 0016 §5.6). No ``QUALIFY`` there: the reject table already
    holds one row per source-row identity.
    """
    if from_payload:
        namespace, relation = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    else:
        namespace, relation = ctx.naming.relation(entity.source.relation, Layer.BRONZE)

    def source(node: Expression) -> Expression:
        return _from_payload(node) if from_payload else node

    projections: list[Expression] = [
        cast("Expression", exp.alias_(source(column.expr.ast()), column.name))
        for column in entity.columns
    ]
    if _carries_metadata(entity):
        projections.extend(exp.column(name) for name in INGESTION_METADATA)
    # The coercion-failure marker compares the produced column against the raw
    # source paths it reads — which only exist at *this* level, before the
    # subquery hides them. Project them under the shared alias convention.
    for rule in entity.quality:
        if rule.kind != "coercible":
            continue
        projections.extend(
            cast(
                "Expression",
                exp.alias_(source(SqlExpr(value).ast()), source_alias(rule, index)),
            )
            for index, value in enumerate(indexed_params(rule, "source"))
        )
    if include_raw:
        payload = _json_object(
            [(column, exp.column(column)) for column in _payload_columns(entity)]
        )
        projections.append(cast("Expression", exp.alias_(payload, "_raw")))
    select = exp.Select().select(*projections).from_(exp.table_(relation, db=namespace))
    if from_payload:
        unresolved = select.where(exp.Is(this=exp.column("resolved_at"), expression=exp.null()))
        return _stage(unresolved, entity)
    if entity.dedupe is not None:
        select = with_dedupe_qualify(select, entity.dedupe, entity.key)
    return _stage(select, entity)


def _from_payload(node: Expression) -> Expression:
    """Rewrite bare bronze column references into ``raw`` extractions."""

    def rewritten(child: Expression) -> Expression:
        if isinstance(child, exp.Column) and not child.table:
            return exp.JSONExtractScalar(
                this=exp.column("raw"), expression=exp.Literal.string(f"$.{child.name}")
            )
        return child

    return node.transform(rewritten)


def _entity_projections(entity: EntityIR, table: str) -> list[Expression]:
    """The entity's own columns, qualified — with any ``unknown_member`` fk
    rewritten to the reserved member (RFC 0016 §5.4)."""
    rewrites = {
        sole_via_column(rule): rule
        for rule in _referential_rules(entity)
        if params_of(rule)["on_missing"] == "unknown_member"
    }
    projections: list[Expression] = []
    for column in entity.columns:
        rule = rewrites.get(column.name)
        if rule is None:
            projections.append(exp.column(column.name, table=table))
        else:
            projections.append(
                cast(
                    "Expression",
                    exp.alias_(unknown_member_case(rule, table=table), column.name),
                )
            )
    return projections


def _route_predicate(entity: EntityIR, table: str, *, quarantined: bool) -> Expression | None:
    """Stage 6: the two-way split (RFC 0016 §5.4).

    ``quarantined=True`` selects the diverted rows for ``<entity>__reject``;
    ``False`` is its complement, the rows the entity keeps. ``None`` when the
    entity quarantines nothing: there is no split to emit.

    The predicate itself is :func:`~bloomery.quality.routing_predicate`, which
    is where the three-valued collapse and its reasoning live — shared with the
    §6 rule × disposition matrix, so the matrix executes the routing SQL this
    function emits rather than a restatement of it.
    """
    rules = _rules(entity, OnFail.QUARANTINE)
    if not rules:
        return None
    return routing_predicate(rules, table, quarantined=quarantined)


def _require_try_cast(entity: EntityIR, ctx: EmitContext) -> None:
    """Refuse a coercion-failure marker the dialect cannot express.

    RFC 0016 §5.2 says the marker lowers ``TRY_CAST``-shaped *per dialect*;
    Postgres has no such cast and SQLGlot renders ``TRY_CAST`` there as a
    plain ``CAST``, which would silently turn "quarantine this row" into
    "abort this run". RFC 0008 D3: fail loud, never approximate.
    """
    if not any(rule.kind == "coercible" for rule in entity.quality):
        return
    if ctx.dialect.supports(DialectFeature.TRY_CAST):
        return
    msg = (
        f"entity {entity.name!r} carries coercible quality rules, whose coercion-failure "
        f"marker needs a NULL-on-failure cast, but dialect {ctx.dialect.name!r} has none "
        "(RFC 0016 §5.2). Rendering it as a plain CAST would abort the run where the spec "
        "says quarantine the row. Fix: compile this project for a dialect with TRY_CAST, or "
        "drop the coercible rules"
    )
    raise UnsupportedByTarget(msg, source_path=f"entity_model: entities.{entity.name}")


def _require_try_cast_for_audit(entity: EntityIR, ctx: EmitContext) -> None:
    """Refuse the D21 audit on a dialect with no NULL-on-failure cast.

    D25's castability assertion *is* a ``TRY_CAST``, and SQLGlot renders one on
    a dialect without the feature as a plain ``CAST`` — which raises inside the
    audit query instead of returning the offending row, turning a legible
    blocking audit into an engine error with no ``_source_row_id`` in it.

    :func:`_require_try_cast` covers the common shape already — every entity
    with a ``quality:`` surface has an implicit ``coercible`` rule — and is
    deferred to first, so an author who wrote quality rules reads the message
    about the rules they wrote rather than about a generated audit. What it
    does *not* cover is a **dedupe-only** entity: ``dedupe:`` alone does not
    join the quality system (RFC 0016 D24), so such an entity carries no rules
    at all and still gets this audit. RFC 0016 D30 reads "Postgres cannot host
    quality-carrying entities at all"; this is the edge of that sentence.
    """
    _require_try_cast(entity, ctx)
    if ctx.dialect.supports(DialectFeature.TRY_CAST):
        return
    msg = (
        f"entity {entity.name!r} carries a dedupe:/quarantine: block, so it gets the "
        "ingestion-metadata audit (RFC 0016 D21/D25) asserting that _ingested_at casts to "
        f"timestamp — which needs a NULL-on-failure cast, and dialect {ctx.dialect.name!r} "
        "has none. Rendering it as a plain CAST would abort the audit query instead of "
        "reporting the offending row. Fix: compile this project for a dialect with "
        "TRY_CAST, or drop the block"
    )
    raise UnsupportedByTarget(msg, source_path=f"entity_model: entities.{entity.name}")


#: The dialect features the ``<entity>__reject`` model is built from, with the
#: construction each one names — see :class:`~bloomery.dialects.DialectFeature`.
_REJECT_FEATURES: Final[tuple[tuple[DialectFeature, str], ...]] = (
    (DialectFeature.TEXT_SHA256, "reject_id, a SHA-256 hex digest over the row's canon bytes"),
    (DialectFeature.JSON_OBJECT_POSITIONAL, "the raw and key_values JSON payloads"),
)


def _require_reject_constructions(entity: EntityIR, ctx: EmitContext) -> None:
    """Refuse a reject table the dialect cannot actually run.

    The sibling of :func:`_require_try_cast`, and the same discipline (RFC
    0008 D3: fail loud, never approximate) applied one layer out. ``TRY_CAST``
    is about a marker meaning the wrong thing; these two are about SQL the
    engine refuses outright — verified by executing the emitted model, not by
    reading it, which is how both were found at all. Emitting a model that
    cannot plan is worse than refusing to emit it: the refusal names the
    dialect at compile time, where the author can act on it.
    """
    if entity.quarantine is None:
        return
    missing = [why for feature, why in _REJECT_FEATURES if not ctx.dialect.supports(feature)]
    if not missing:
        return
    msg = (
        f"entity {entity.name!r} declares a quarantine: block, so it emits a "
        f"{entity.name}__reject model — but dialect {ctx.dialect.name!r} cannot express "
        f"{'; '.join(missing)} (RFC 0016 §5.6). The emitted SQL would be rejected by the "
        "engine rather than run, so it is refused here instead. Fix: compile this project "
        "for a dialect that carries the reject table, or drop the quarantine: block"
    )
    raise UnsupportedByTarget(msg, source_path=f"entity_model: entities.{entity.name}")


def _quality_pipeline(entity: EntityIR, ctx: EmitContext, extract: exp.Select) -> exp.Select:
    """Stages 4–6 over an extract SELECT: the rule predicates, the single
    ``_quality_flags`` pass, the routing ``WHERE``, and ``_quality_ok``.

    Shared verbatim by the silver model and by replay's candidate set, so a
    replayed row is admitted by exactly the rules that would have admitted it
    the first time.
    """
    arrays = _arrays(ctx)
    evaluated = (
        exp.Select()
        .select(
            *_entity_projections(entity, _EXTRACT_ALIAS),
            *(
                [exp.column(name, table=_EXTRACT_ALIAS) for name in INGESTION_METADATA]
                if _carries_metadata(entity)
                else []
            ),
            exp.alias_(
                flags_expression(
                    # FLAG **and** FAIL (D18). A quarantine rule cannot appear
                    # on a kept row — firing one diverts it — but a fail rule
                    # can: routing does not move it, the blocking audit stops
                    # the run instead. Leaving its name out made such a row
                    # read as clean everywhere the package looks, including
                    # ``_quality_ok`` and the mart's ``has_quality_flags``,
                    # which is precisely the "currently suspect" meaning §10
                    # says those columns must keep.
                    _flag_pairs(_rules(entity, OnFail.FLAG, OnFail.FAIL), _EXTRACT_ALIAS),
                    arrays=arrays,
                ),
                FLAGS_COLUMN,
            ),
        )
        .from_(extract.subquery(alias=_EXTRACT_ALIAS))
    )
    evaluated = _with_probes(evaluated, entity, ctx)
    kept = _route_predicate(entity, _EXTRACT_ALIAS, quarantined=False)
    if kept is not None:
        evaluated = evaluated.where(kept)
    carried = [column.name for column in entity.columns]
    if _carries_metadata(entity):
        carried.extend(INGESTION_METADATA)
    return (
        exp.Select()
        .select(
            *(exp.column(name, table=_EVALUATED_ALIAS) for name in carried),
            exp.column(FLAGS_COLUMN, table=_EVALUATED_ALIAS),
            exp.alias_(quality_ok(table=_EVALUATED_ALIAS, arrays=arrays), OK_COLUMN),
        )
        .from_(evaluated.subquery(alias=_EVALUATED_ALIAS))
    )


def entity_select(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The silver SELECT: every lowered column expression aliased to its
    declared name, from the bronze relation under the naming policy — plus the
    data-quality pipeline (RFC 0016 §5.4) and the two generated columns
    ``_quality_flags`` / ``_quality_ok`` every silver entity carries (§5.5).

    An entity with no quality rules gets the two columns as constants and no
    extra nesting: the empty collection is what a clean row carries, so the
    specialization is the general form evaluated at compile.
    """
    _require_try_cast(entity, ctx)
    extract = _extract_select(entity, ctx)
    if not entity.quality:
        return extract.select(
            exp.alias_(empty_flags(arrays=_arrays(ctx)), FLAGS_COLUMN),
            exp.alias_(exp.true(), OK_COLUMN),
        )
    return _quality_pipeline(entity, ctx, extract)


def reject_select(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The ``<entity>__reject`` SELECT (RFC 0016 §5.6): the diverted side of
    the stage-6 split, projected into the reject schema.

    ``failed_rules`` records **all** the row's failures — flag-level *and*
    blocking ones (D18): a reject row is the full account of why a row is not
    in the entity, not merely the part that diverted it, and a row that also
    tripped a ``fail`` rule is the case where the omission mattered most.

    ``first_seen`` / ``last_seen`` are both the row's ``_ingested_at`` **as
    written**; what makes them differ is the merge. The reject model is
    ``INCREMENTAL_BY_UNIQUE_KEY`` on ``reject_id``, so a re-delivery of the
    same source row lands on the same reject row (D21), and the merge keeps the
    existing ``first_seen`` while ``last_seen`` takes the new value
    (:func:`reject_when_matched`). The pair used to be a ``MIN``/``MAX`` window
    over ``PARTITION BY _source_row_id`` here — but that partition is a
    singleton by construction (D21 declares the identity unique per source row,
    and dedupe has already run), so both aggregates were the identity and
    ``first_seen`` was clobbered on every re-delivery: two names for one value.

    ``resolved_at`` is null until a replay sets it, and retention — never
    replay — is what eventually deletes the row.
    """
    _require_try_cast(entity, ctx)
    _require_reject_constructions(entity, ctx)
    arrays = _arrays(ctx)
    extract = _extract_select(entity, ctx, include_raw=True)
    recorded = _recorded_rules(entity)
    row_id = exp.column(ROW_ID_COLUMN, table=_EXTRACT_ALIAS)
    ingested = exp.column("_ingested_at", table=_EXTRACT_ALIAS)
    projections: list[Expression] = [
        cast(
            "Expression", exp.alias_(reject_id(entity.source.relation, row_id.copy()), "reject_id")
        ),
        cast(
            "Expression",
            exp.alias_(exp.Literal.string(entity.source.relation), "source_relation"),
        ),
        cast(
            "Expression",
            exp.alias_(exp.Literal.string(f"{entity.source.relation}->{entity.name}"), "mapping"),
        ),
        cast(
            "Expression",
            exp.alias_(exp.Literal.number(entity.source.mapping_version), "mapping_version"),
        ),
        cast(
            "Expression",
            exp.alias_(
                flags_expression(_flag_pairs(recorded, _EXTRACT_ALIAS), arrays=arrays),
                "failed_rules",
            ),
        ),
        cast(
            "Expression",
            exp.alias_(
                _json_object(
                    [(name, exp.column(name, table=_EXTRACT_ALIAS)) for name in sorted(entity.key)]
                ),
                "key_values",
            ),
        ),
        cast("Expression", exp.alias_(exp.column("_raw", table=_EXTRACT_ALIAS), "raw")),
        exp.column("_load_id", table=_EXTRACT_ALIAS),
        ingested.copy(),
        row_id.copy(),
        cast("Expression", exp.alias_(ingested.copy(), "first_seen")),
        cast("Expression", exp.alias_(ingested.copy(), "last_seen")),
        cast(
            "Expression",
            exp.alias_(exp.cast(exp.null(), exp.DataType.build("TIMESTAMP")), "resolved_at"),
        ),
    ]
    select = exp.Select().select(*projections).from_(extract.subquery(alias=_EXTRACT_ALIAS))
    select = _with_probes(select, entity, ctx)
    diverted = _route_predicate(entity, _EXTRACT_ALIAS, quarantined=True)
    if diverted is not None:  # pragma: no branch — a reject model implies one
        select = select.where(diverted)
    return select


#: The merge aliases SQLMesh resolves inside a ``when_matched`` clause — its
#: documented spelling for "the row already there" and "the row arriving".
_MERGE_TARGET = "target"
_MERGE_SOURCE = "source"

#: The reject columns whose value on a re-delivery is the **existing** one, not
#: the arriving one (RFC 0016 §5.6). Only ``first_seen``: it records when the
#: problem started, and every other column describes the latest observation.
_PRESERVED_ON_MERGE = frozenset({"first_seen"})

#: The reject table's unique key — the column the merge matches on and the
#: model's declared ``unique_key``, drawn from the schema tuple rather than
#: spelled once per emitter (:func:`_schema_column` on why it is checked
#: against the tuple rather than filtered out of it).
REJECT_KEY = _schema_column("reject_id", REJECT_COLUMNS, "the reject table's unique key")


def reject_when_matched() -> tuple[Expression, ...]:
    """The assignments of the reject table's ``WHEN MATCHED`` clause
    (RFC 0016 §5.6, D21).

    "A re-delivery updates ``last_seen``, ``_load_id``, and ``failed_rules`` on
    the existing row" — which is a statement about the *merge*, not about the
    SELECT: both timestamps are written as the row's ``_ingested_at``, and what
    keeps ``first_seen`` at its original value is this clause. The default
    merge overwrites every column from the source, so without it ``first_seen``
    tracked the newest delivery and the pair carried one fact under two names.

    ``COALESCE`` rather than a bare ``target.first_seen``: a row inserted
    before this clause existed may carry a null there, and the first
    re-delivery should heal it rather than pin the null forever.

    ``reject_id`` itself is absent from the assignments: it is the merge key,
    equal on both sides by the ``ON`` clause, and several engines refuse to let
    a ``MERGE`` assign to the column it matched on.

    **Assignments, not an ``exp.Whens``** — and that is not a style choice.
    Importing ``sqlmesh`` extends SQLGlot *globally*, and one of the things it
    changes is how a ``Whens`` node renders (it gains a wrapping paren and a
    different indent). Emitting one would therefore make the compiled bytes a
    function of whether the calling process had imported the target framework,
    which is precisely the determinism invariant RFC 0003 exists to hold. The
    assignment nodes render identically either way, and the clause around them
    is envelope text — pre-rendered strings interpolated by the emitter, the
    RFC 0008 D4 doctrine.
    """
    assignments: list[Expression] = []
    for column in (name for name in REJECT_COLUMNS if name != REJECT_KEY):
        arriving = exp.column(column, table=_MERGE_SOURCE)
        value: Expression = (
            exp.Coalesce(this=exp.column(column, table=_MERGE_TARGET), expressions=[arriving])
            if column in _PRESERVED_ON_MERGE
            else arriving
        )
        assignments.append(exp.EQ(this=exp.column(column, table=_MERGE_TARGET), expression=value))
    return tuple(assignments)


def _uncastable_ingested_at() -> Expression:
    """``_ingested_at IS NOT NULL AND TRY_CAST(_ingested_at AS TIMESTAMP) IS NULL``
    — RFC 0016 D25/D31, the third condition of the D21 audit.

    The ``IS NOT NULL`` half is not redundant with the audit's own
    ``_ingested_at IS NULL`` disjunct: it keeps this term meaning exactly
    "present but uncastable", so the two conditions stay separately readable
    in the emitted body and a reader can tell an absent recency value from a
    corrupt one.
    """
    ingested = exp.column(_INGESTED_AT_COLUMN)
    castable = exp.TryCast(this=ingested.copy(), to=exp.DataType.build("TIMESTAMP"))
    return conjunction(
        [
            exp.Not(this=exp.Is(this=ingested, expression=exp.null())),
            exp.Is(this=castable, expression=exp.null()),
        ]
    )


def ingestion_audit_predicate(entity: EntityIR, ctx: EmitContext) -> Expression:
    """The D21 blocking audit's violating-row predicate.

    ``_source_row_id`` is declared NOT NULL and unique per source row, and
    ``_ingested_at`` is declared castable to timestamp — data properties no
    compiler can check, so the lowering emits a **blocking** audit instead: a
    null or duplicated identity, or a recency value that does not cast, stops
    the run rather than silently corrupting dedupe order or ``reject_id``.

    The castability half (RFC 0016 D25) closes the hole D6's disposition
    forcing cannot reach: forcing applies to *mapped fields*, and the
    ingestion-metadata columns are not mapped, so no ``coercible`` rule is ever
    generated for ``_ingested_at``. Without this term an uncastable recency
    value survives with the dedupe order silently undefined.

    The duplicate half is a window count, and SQL forbids a window function in
    ``WHERE`` — so the audit body wraps the model in a subquery that projects
    the count as :data:`ROW_ID_COUNT_COLUMN`, and this predicate reads that
    column. The two halves of that arrangement live one function apart on
    purpose: the name is a constant here, not a string in a template.
    """
    # The predicate itself is entity-independent — the contract is the same
    # three columns for every entity; ``entity`` reaches only the refusal,
    # which names the entity that cannot be compiled.
    _require_try_cast_for_audit(entity, ctx)
    parts: list[Expression] = [
        exp.Is(this=exp.column(name), expression=exp.null()) for name in INGESTION_METADATA
    ]
    parts.append(exp.GT(this=exp.column(ROW_ID_COUNT_COLUMN), expression=exp.Literal.number(1)))
    parts.append(_uncastable_ingested_at())
    return disjunction(parts)


#: The target-side macro standing for the audited model's own relation. Both
#: shipped SQL targets spell it this way; the audit bodies below reference it
#: rather than a naming-policy relation so an audit stays attached to whatever
#: physical table the framework built (a dev/prod virtual layer moves it).
THIS_MODEL = "@this_model"

#: Aliases inside the conservation audit body. Named constants because the
#: body references them across three nesting levels.
_SURVIVORS_CTE = "_survivors"
_CONSERVATION_ALIAS = "_conservation"
_ENTITY_ALIAS = "_entity"


def _this_model(alias: str) -> exp.Table:
    """``@this_model AS <alias>`` with the macro left unquoted.

    ``exp.table_`` would quote it — ``@`` is not an identifier character — and
    a quoted macro is a table named ``@this_model``, which does not exist.
    """
    return exp.Table(this=exp.to_identifier(THIS_MODEL, quoted=False), alias=alias)


def _count_of(relation: Expression) -> Expression:
    return exp.Subquery(this=exp.Select().select(exp.Count(this=exp.Star())).from_(relation))


def _counted_as(predicate: Expression, name: str) -> Expression:
    """``SUM(CASE WHEN <predicate> THEN 1 ELSE 0 END) AS <name>``."""
    case = exp.Case(
        ifs=[exp.If(this=predicate, true=exp.Literal.number(1))], default=exp.Literal.number(0)
    )
    return cast("Expression", exp.alias_(exp.Sum(this=case), name))


def conservation_audit(entity: EntityIR) -> bool:
    """Whether the conservation audit can be emitted for this entity.

    **A scope limit, recorded rather than worked around.** An audit body may
    address exactly two relations: the audited model, through the target's
    ``@this_model`` macro, and the model's external upstream. It may *not*
    address a sibling model — SQLMesh rewrites model references inside a MODEL
    query to the physical snapshot table but does **not** do so inside an AUDIT
    body, so a literal ``silver.<sibling>`` there resolves to a virtual-layer
    view that does not exist yet on a first plan, and the run fails at the very
    audit that was meant to protect it.

    That rules the audit out for exactly one shape: an entity whose *routing*
    predicate reads a sibling entity, i.e. a ``referential`` rule carrying
    ``on_missing: quarantine``. Everywhere else the law rides on bronze and the
    model itself. The property tier covers the law for every shape (RFC 0016
    §6); this is about what can be checked at run time, on this target.
    """
    if entity.quarantine is None:
        return False
    return not any(rule.kind == "referential" for rule in _rules(entity, OnFail.QUARANTINE))


def conservation_audit_select(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The conservation law as a **runtime** audit (RFC 0016 §6).

    §6 does not merely ask for a property test — it asks for the law to be
    "emitted as a runtime audit on every production run, not only a test",
    which is the difference between knowing the compiler is right and knowing
    *this* run was. The law: every bronze row lands in exactly one of the
    entity, an unresolved reject, or the deduped count. Written over the two
    quantities an audit body can reach::

        entity_rows + diverted_rows = surviving_rows   (the split is total and
                                                        disjoint — a row in
                                                        neither leg is a row
                                                        silently dropped)

    with ``deduped = bronze_rows - surviving_rows`` falling out as the second
    leg. ``entity_rows`` is scoped to the source-row identities of *this* run's
    survivors, which is what keeps the audit exact under an incremental entity
    and stable across a replay: a replayed row's bronze identity has aged out
    of the window, so it is outside the scope on both sides at once.

    **One leg, not two** (RFC 0016 D61). The audit also carried
    ``surviving_rows <= bronze_rows`` — "dedupe removes rows, it never invents
    any" — which reads like a second guarantee and is a tautology: the
    ``_survivors`` CTE *is* the bronze relation with a ``QUALIFY`` over it, so
    the two counts are taken over the same rows and one is a filter of the
    other. It could not fail for any spec, any data, or any bug, and a check
    that cannot fail is indistinguishable from a check that is not there —
    worse, it reads as coverage. ``bronze_rows`` stays as a **projected**
    column: an audit reports its violating rows, and the deduped count is what
    makes the reported numbers legible.

    The reject table is deliberately **not** read — see
    :func:`conservation_audit`. ``diverted_rows`` is recomputed from the same
    routing predicate the reject model routes by, which is the same claim
    without the cross-model reference.

    Blocking, like the D21 metadata audit: silent row loss is the failure this
    whole package exists to make impossible.
    """
    # The audited entity is addressed through THIS_MODEL, never through the
    # naming policy: an audit must follow the model into whatever physical
    # table the framework's virtual layer put it in.
    bronze_namespace, bronze_rel = ctx.naming.relation(entity.source.relation, Layer.BRONZE)
    diverted = _route_predicate(entity, _SURVIVORS_CTE, quarantined=True)
    if diverted is None:  # pragma: no cover — a quarantine block implies rules
        diverted = exp.false()

    in_scope = exp.In(
        this=exp.column(ROW_ID_COLUMN, table=_ENTITY_ALIAS),
        query=exp.Select().select(exp.column(ROW_ID_COLUMN)).from_(_SURVIVORS_CTE).subquery(),
    )
    entity_rows = exp.Subquery(
        this=exp.Select()
        .select(exp.Count(this=exp.Star()))
        .from_(_this_model(_ENTITY_ALIAS))
        .where(in_scope)
    )
    counted = (
        exp.Select()
        .select(
            cast("Expression", exp.alias_(exp.Count(this=exp.Star()), "surviving_rows")),
            _counted_as(diverted, "diverted_rows"),
            cast(
                "Expression",
                exp.alias_(_count_of(exp.table_(bronze_rel, db=bronze_namespace)), "bronze_rows"),
            ),
            cast("Expression", exp.alias_(entity_rows, "entity_rows")),
        )
        .from_(_SURVIVORS_CTE)
    )
    violated = exp.NEQ(
        this=exp.Add(this=exp.column("entity_rows"), expression=exp.column("diverted_rows")),
        expression=exp.column("surviving_rows"),
    )
    return (
        exp.Select()
        .with_(_SURVIVORS_CTE, as_=_extract_select(entity, ctx))
        .select(exp.Star())
        .from_(counted.subquery(alias=_CONSERVATION_ALIAS))
        .where(violated)
    )


def fail_audits(
    entity: EntityIR, ctx: EmitContext
) -> tuple[tuple[str, exp.Select | exp.Union], ...]:
    """``(audit name, violating-row query)`` per ``on_fail: fail`` rule.

    **Two populations, unioned** (RFC 0016 D32, completed by D67) — because a
    blocking rule is a statement about the entity, and there are two ways a row
    can be one of its rows:

    *The rows this run evaluated*, read off the staged extract **before** the
    stage-6 split. Severity order is ``fail > quarantine > flag``, and routing
    runs before the audit does, so an audit over the model alone sees only the
    rows the split *kept*: a row failing a blocking rule **and** a quarantine
    rule would sit in the reject table with the run carrying on, which inverts
    the order the RFC pins. That is D32's leg and it is unchanged.

    *The rows already in the entity*, read off ``@this_model``. D32's move left
    this population uncovered, and it is not empty: a **replayed** row is
    merged into the entity from the reject table (§5.6), and its bronze source
    has aged out of the incremental window by construction — that is the whole
    premise of ``replay_scope`` (§5.7). Such a row sat in silver with the
    blocking rule recorded in its own ``_quality_flags`` while the audit for
    that very rule reported nothing: a model contradicting its own data, which
    reads as coverage. Replay deliberately does **not** filter ``fail`` rules
    out of its MERGE — refusing to merge them would be quarantine outranking
    fail all over again, the exact inversion D32 exists to prevent — so the row
    lands and the audit is what stops the next run.

    The entity leg reads the **recorded** verdict (``_quality_flags`` carries
    FAIL-disposition names, D32) rather than re-deriving the predicate over
    model columns. That is forced, not stylistic: over the model the coercion
    marker's source conjuncts are gone, so ``coercible`` would degenerate to
    ``col IS NULL`` and quietly re-define itself as ``not_null``. It is also
    the same doctrine the quality mart's rule rows follow (D23). Its recorded
    price: the leg covers rows evaluated under the *current* spec, and a rule
    added or renamed classifies RESTATING (D11), whose backfill is what
    re-derives the flags.

    ``UNION`` rather than ``UNION ALL``: in the ordinary case a violating row
    is in **both** populations, and reporting it twice tells an operator
    nothing the once did not. The projection is the entity's own columns plus
    the ingestion metadata where the entity carries it — the columns that exist
    on *both* sides, and the ones a violation report is read by
    (``_source_row_id`` names the offending row).

    The body addresses exactly two relations — the bronze source through the
    extract, and the audited model through the macro — so it stays inside the
    audit-body scope limit D29 records. That costs nothing here: ``referential``
    is the one rule kind that reads a sibling entity, and it cannot carry a
    ``fail`` disposition at all (D6).
    """
    _require_try_cast(entity, ctx)
    arrays = _arrays(ctx)
    columns = [column.name for column in entity.columns]
    if _carries_metadata(entity):
        columns.extend(INGESTION_METADATA)
    audits: list[tuple[str, exp.Select | exp.Union]] = []
    for rule in _rules(entity, OnFail.FAIL):
        evaluated = (
            exp.Select()
            .select(*(exp.column(name, table=_EXTRACT_ALIAS) for name in columns))
            .from_(_extract_select(entity, ctx).subquery(alias=_EXTRACT_ALIAS))
            .where(verdict(rule, _EXTRACT_ALIAS))
        )
        stored = (
            exp.Select()
            .select(*(exp.column(name, table=_ENTITY_ALIAS) for name in columns))
            .from_(_this_model(_ENTITY_ALIAS))
            .where(
                flag_member(exp.column(FLAGS_COLUMN, table=_ENTITY_ALIAS), rule.name, arrays=arrays)
            )
        )
        audits.append((f"{entity.name}_{rule.name}", exp.union(evaluated, stored)))
    return tuple(audits)


def _one_winner_per_key(select: exp.Select, entity: EntityIR) -> exp.Select:
    """Keep exactly one row per entity key, by the D20 total order.

    The pipeline's own ``QUALIFY`` cannot do this job for replay: it lives
    inside :func:`_extract_select`, which reads *bronze*, and replay reads the
    reject table. And the reject table genuinely holds several rows on one
    entity key — an entity may carry ``quarantine:`` without ``dedupe:``, and
    even with it the reject table accumulates across runs while its identity is
    the source row, not the key.

    D22 says "multiple rejects resolving to one key are ordered the same way"
    as the pipeline orders duplicates. Without this the merge source offers two
    candidates for one key, both match the ``ON`` clause, and the entity ends
    up holding two rows at a grain it declares as one — every mart measure over
    it doubled. The ``MERGE``'s own ``WHEN MATCHED`` comparison cannot rescue
    that: it arbitrates candidate against *incumbent*, never candidate against
    candidate.
    """
    if entity.dedupe is not None:
        return with_dedupe_qualify(select, entity.dedupe, entity.key)
    # The no-``dedupe:`` form of the total order is its final sort key alone
    # (D20): the stable source-row identity, which D21 guarantees exists and is
    # unique on any entity with a reject table.
    winner = exp.EQ(
        this=exp.Window(
            this=exp.RowNumber(),
            partition_by=[exp.column(name) for name in entity.key],
            order=exp.Order(
                expressions=[
                    exp.Ordered(this=exp.column(ROW_ID_COLUMN), desc=True, nulls_first=False)
                ]
            ),
        ),
        expression=exp.Literal.number(1),
    )
    qualified = select.copy()
    qualified.set("qualify", exp.Qualify(this=winner))
    return qualified


def _replay_candidates(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The unresolved reject rows that now pass, re-derived from ``raw`` — one
    per entity key.

    Replay "re-runs the current mapping against ``raw``" for unresolved rows
    (RFC 0016 §5.6). Running them back through :func:`_quality_pipeline` is
    what makes "passers merge, the rest stay" true by construction: a
    candidate that still fires a quarantine rule is filtered out by the very
    same routing predicate the pipeline uses. :func:`_one_winner_per_key` then
    applies the D20 order the pipeline would have applied (D22).
    """
    pipeline = _quality_pipeline(entity, ctx, _extract_select(entity, ctx, from_payload=True))
    return _one_winner_per_key(pipeline, entity)


def _reevaluated(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """``(_source_row_id, failed_rules)`` re-derived from ``raw`` for every
    unresolved reject row (RFC 0016 §5.6).

    The very same flag construction the reject model writes with, over the very
    same extract replay's candidates come from — so "still failing" and "would
    have been quarantined" are one evaluation, not two implementations that
    have to be kept in agreement.

    Plus one entry the reject model never writes —
    :data:`~bloomery.quality.SUPERSEDED_RULE`, recorded exactly when the row
    now passes routing (RFC 0016 D69). Read with the third statement's ``resolved_at IS
    NULL`` filter, that pair of facts has one meaning — the row was admitted by
    every rule and still did not enter the entity, so another row won its key:
    it lost :func:`_one_winner_per_key`'s contest among candidates, or the
    MERGE's own comparison against the incumbent. Without the marker the honest
    re-derivation is *empty*, and ``resolved_at IS NULL, failed_rules = []``
    reads as "quarantined for these reasons: none" on a row that will lose that
    contest for as long as it exists and can only leave by retention.
    """
    pairs = _flag_pairs(_recorded_rules(entity), _EXTRACT_ALIAS)
    kept = _route_predicate(entity, _EXTRACT_ALIAS, quarantined=False)
    if kept is not None:  # pragma: no branch — a reject table implies a split
        pairs.append((SUPERSEDED_RULE, kept))
    select = (
        exp.Select()
        .select(
            exp.column(ROW_ID_COLUMN, table=_EXTRACT_ALIAS),
            exp.alias_(flags_expression(pairs, arrays=_arrays(ctx)), "failed_rules"),
        )
        .from_(_extract_select(entity, ctx, from_payload=True).subquery(alias=_EXTRACT_ALIAS))
    )
    return _with_probes(select, entity, ctx)


def _dedupe_columns(entity: EntityIR, table: str) -> list[Expression]:
    """The columns replay compares an incumbent and a candidate by, in the
    D20 sort order.

    An entity may carry ``quarantine:`` **without** ``dedupe:`` — deduplicating
    is not a statement about coercibility, so the two opt in separately. The
    total order does not disappear with the block: D20 makes the stable
    source-row identity the *final* sort key, and D21 guarantees it exists and
    is unique on any entity with a reject table. So the no-dedupe form of the
    order is that last key alone, and the comparison stays total.

    (Before this was spelled out, the comparison collapsed to ``() > ()`` in
    the emitted replay artifact — invalid SQL on every dialect. The shipped
    golden fixture declares ``dedupe:``, so only the execution tier over an
    entity without one could see it, RFC 0016 §6.)
    """
    order = dedupe_order(entity.dedupe, table=table) if entity.dedupe else ()
    return [term.this for term in order] or [exp.column(ROW_ID_COLUMN, table=table)]


def _candidate_wins(entity: EntityIR) -> Expression:
    """Whether the replay candidate outranks the incumbent under the **same**
    order :func:`~bloomery.quality.dedupe_order` ranks candidates by.

    Spelled out per column rather than as a row constructor over the two
    tuples. ``(a, b) > (c, d)`` looks like the same question and is not:
    SQL's row comparison does not propagate NULL the way ``DESC NULLS LAST``
    orders it — DuckDB sorts NULL as the *largest* value there, the exact
    inverse — so a nullable ``dedupe.field`` or ``tie_break`` broke the
    correspondence in both directions. A candidate that ranked first was not
    merged, and its reject row was then stamped with D69's ``(superseded)``
    marker, which asserts another row won its key — false. Worse, a candidate
    with a NULL sort value *evicted* a non-null incumbent, silently restating
    the entity against what D20 says the order is.

    ``dedupe_order`` and this predicate are the two places the total order is
    expressed, and they now say the same thing: for each column in order, a
    non-null beats a null, then a greater value beats a lesser one, then the
    next column decides. Asserted exhaustively over a NULL-bearing domain by
    the execution tier, not re-derived by eye.
    """
    candidate = _dedupe_columns(entity, _REPLAY_ALIAS)
    incumbent = _dedupe_columns(entity, _TARGET_ALIAS)
    decided: exp.Condition | None = None
    # Built back to front: each column's verdict falls through to the tail it
    # already has, which is the lexicographic order read literally.
    for cand, inc in zip(reversed(candidate), reversed(incumbent), strict=True):
        beats = exp.or_(
            exp.and_(is_not_null(cand.copy()), is_null(inc.copy())),
            exp.and_(
                is_not_null(cand.copy()),
                is_not_null(inc.copy()),
                exp.GT(this=cand.copy(), expression=inc.copy()),
            ),
        )
        if decided is None:
            decided = beats
            continue
        # Equal under DESC NULLS LAST — both null, or both non-null and equal
        # — is what hands the decision to the next column.
        tied = exp.or_(
            exp.and_(is_null(cand.copy()), is_null(inc.copy())),
            exp.EQ(this=cand.copy(), expression=inc.copy()),
        )
        decided = exp.or_(beats, exp.and_(exp.paren(tied), exp.paren(decided)))
    # Never None: _dedupe_columns is non-empty by construction.
    return exp.paren(cast("exp.Condition", decided))


def replay_statements(entity: EntityIR, ctx: EmitContext) -> tuple[Expression, ...]:
    """The replay artifact (RFC 0016 §5.6, D22): one MERGE and two updates.

    §5.6 states replay in one sentence — "re-runs the current mapping against
    ``raw`` for unresolved rows, merging passers into the entity by key and
    updating ``failed_rules``/``last_seen`` on the rest" — and each clause is a
    statement here:

    1. the **MERGE**, which admits the passers. Candidates are ordered against
       each other by the D20 total order before they reach it
       (:func:`_one_winner_per_key`) and against the incumbent by the same
       order inside it, which is what makes re-running replay re-derive
       identical winners. The comparison is the row constructor over exactly
       :func:`~bloomery.quality.dedupe_order`'s columns; null ordering is the
       D21 blocking audit's job, upstream of here.
    2. the **resolution stamp**, setting ``resolved_at`` on the rows that made
       it into the entity;
    3. the **re-evaluation stamp** — the clause that had no statement. A reject
       row that still fails has been read against the current mapping and found
       wanting again: ``failed_rules`` is re-derived from that evaluation, so
       the reject table's account of why a row is out never ages into a
       statement about a spec nobody runs any more. It also carries
       :data:`~bloomery.quality.SUPERSEDED_RULE` for the row that now fails
       nothing and still did not enter the entity (D69).

    Order matters between 2 and 3: the stamp runs first, so 3's
    ``resolved_at IS NULL`` filter is exactly "the rest".

    **``last_seen`` is one clock — the data's** (RFC 0016 D70). It is written
    as the row's ``_ingested_at`` and advanced only by a re-delivery's merge,
    and statement 3 deliberately leaves it alone: retention measures unresolved
    reject rows *from* ``last_seen`` (§5.6), so a replay run advancing it makes
    an unresolved row immortal for as long as replay keeps running — §9's PII
    lake with its stated mitigation removed. The re-evaluation is recorded by
    ``failed_rules``, which is the clause §5.6 names first.

    The resolution stamp reads the **executing engine's** clock
    (``CURRENT_TIMESTAMP``) — bloomery never reads a clock (RFC 0003), it emits
    the statements and the caller runs them. The reject row is kept as audit
    history; retention, never replay, is what deletes it.
    """
    entity_namespace, entity_relation = ctx.naming.relation(entity.name, Layer.SILVER)
    reject_namespace, reject_rel = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    columns = [
        *(column.name for column in entity.columns),
        *INGESTION_METADATA,
        FLAGS_COLUMN,
        OK_COLUMN,
    ]
    non_key = [name for name in columns if name not in entity.key]

    wins = _candidate_wins(entity)
    matched = exp.When(
        matched=True,
        condition=wins,
        then=exp.Update(
            expressions=[
                # The **left** side of a MERGE ``SET`` is deliberately
                # unqualified. Standard SQL says the assignment target is a
                # bare column of the merge target — DuckDB, Postgres and Trino
                # all reject a qualified one outright ("Qualified column names
                # in UPDATE .. SET not supported"), and only a couple of
                # engines accept it as an extension. Qualifying it here made
                # the emitted replay artifact unrunnable on every shipped
                # dialect; caught by the execution tier (RFC 0016 §6), which is
                # what that tier is for. The right side stays qualified — it
                # names the *source* row and would be ambiguous otherwise.
                exp.EQ(
                    this=exp.column(name),
                    expression=exp.column(name, table=_REPLAY_ALIAS),
                )
                for name in non_key
            ]
        ),
    )
    not_matched = exp.When(
        matched=False,
        then=exp.Insert(
            this=exp.Tuple(expressions=[exp.column(name) for name in columns]),
            expression=exp.Tuple(
                expressions=[exp.column(name, table=_REPLAY_ALIAS) for name in columns]
            ),
        ),
    )
    merge = exp.Merge(
        this=exp.table_(entity_relation, db=entity_namespace, alias=_TARGET_ALIAS),
        using=_replay_candidates(entity, ctx).subquery(alias=_REPLAY_ALIAS),
        on=conjunction(
            [
                exp.EQ(
                    this=exp.column(name, table=_TARGET_ALIAS),
                    expression=exp.column(name, table=_REPLAY_ALIAS),
                )
                for name in entity.key
            ]
        ),
        whens=exp.Whens(expressions=[matched, not_matched]),
    )
    resolve = exp.Update(
        this=exp.table_(reject_rel, db=reject_namespace),
        expressions=[exp.EQ(this=exp.column("resolved_at"), expression=exp.CurrentTimestamp())],
        where=exp.Where(
            this=conjunction(
                [
                    exp.Is(this=exp.column("resolved_at"), expression=exp.null()),
                    exp.In(
                        this=exp.column(ROW_ID_COLUMN),
                        query=exp.Select()
                        .select(exp.column(ROW_ID_COLUMN, table=_TARGET_ALIAS))
                        .from_(
                            exp.table_(entity_relation, db=entity_namespace, alias=_TARGET_ALIAS)
                        )
                        .subquery(),
                    ),
                ]
            )
        ),
    )
    still_failing = exp.Merge(
        this=exp.table_(reject_rel, db=reject_namespace, alias=_TARGET_ALIAS),
        using=_reevaluated(entity, ctx).subquery(alias=_REPLAY_ALIAS),
        on=exp.EQ(
            this=exp.column(ROW_ID_COLUMN, table=_TARGET_ALIAS),
            expression=exp.column(ROW_ID_COLUMN, table=_REPLAY_ALIAS),
        ),
        whens=exp.Whens(
            expressions=[
                exp.When(
                    matched=True,
                    # "the rest": everything the resolution stamp above did not
                    # just claim. Reading it off ``resolved_at`` rather than
                    # recomputing membership keeps the two statements agreeing
                    # by construction.
                    condition=exp.Is(
                        this=exp.column("resolved_at", table=_TARGET_ALIAS), expression=exp.null()
                    ),
                    then=exp.Update(
                        expressions=[
                            exp.EQ(
                                this=exp.column("failed_rules"),
                                expression=exp.column("failed_rules", table=_REPLAY_ALIAS),
                            )
                        ]
                    ),
                )
            ]
        ),
    )
    return (merge, resolve, still_failing)


# ....................... #
# Reconcile (RFC 0016 §5.3/§5.4): one model plus a non-blocking audit per
# check — "the check that catches a *correct formula over wrong data*". The
# two sides come from the closed grammar in :mod:`bloomery.quality.reconcile`
# and are built as a SQLGlot AST like everything else here; no string SQL ever
# reaches an artifact.

_LEFT_ALIAS = "_left"
_RIGHT_ALIAS = "_right"
_LEFT_VALUE = "left_value"
_RIGHT_VALUE = "right_value"

_AGGREGATES: dict[str, type[exp.AggFunc]] = {
    "avg": exp.Avg,
    "count": exp.Count,
    "max": exp.Max,
    "min": exp.Min,
    "sum": exp.Sum,
}


def reconcile_relation(check: ReconcileIR) -> str:
    """``<check>__reconcile`` — one relation per check, mirroring the reject
    table's naming (RFC 0016 §5.3)."""
    return f"{check.name}{RECONCILE_SUFFIX}"


def _resolved_side(text: str, ir: ProjectIR) -> tuple[ReconcileSide, EntityIR, tuple[str, ...]]:
    """One side parsed and bound to its entity, with the keys it compares by.

    Both grammar shapes produce the same thing — one value per key — which is
    what makes the comparison a plain join. The aggregate shape is keyed by
    its ``by`` columns; the plain-column shape by the entity's declared key.
    """
    side = parse_side(text)
    entity = next(
        (e for e in ir.entities if side is not None and e.name == side.entity),
        None,
    )
    if side is None or entity is None:  # pragma: no cover — the guardrail stage refuses both
        msg = (
            f"reconcile side {text!r} did not parse or names an unbuilt entity — the "
            "guardrail stage should have refused this (RFC 0016 §5.3)"
        )
        raise EmitError(msg)
    return side, entity, side.by if side.aggregated else tuple(entity.key)


def reconcile_keys(check: ReconcileIR, ir: ProjectIR) -> tuple[str, ...]:
    """The grain of a check's model: the columns its left side compares by
    (the guardrail stage has already refused sides keyed differently)."""
    _side, _entity, keys = _resolved_side(check.left, ir)
    return keys


def _reconcile_side(
    text: str, ir: ProjectIR, ctx: EmitContext, *, value: str
) -> tuple[exp.Select, tuple[str, ...]]:
    """One side lowered to a keyed value relation: ``(select, key columns)``."""
    side, _entity, keys = _resolved_side(text, ir)
    namespace, relation = ctx.naming.relation(side.entity, Layer.SILVER)
    select = exp.Select().from_(exp.table_(relation, db=namespace))
    if side.agg is None:
        return (
            select.select(
                *(exp.column(key) for key in keys),
                exp.alias_(exp.column(side.column), value),
            ),
            keys,
        )
    aggregated = _AGGREGATES[side.agg](this=exp.column(side.column))
    return (
        select.select(*(exp.column(key) for key in keys), exp.alias_(aggregated, value)).group_by(
            *(exp.column(key) for key in keys)
        ),
        keys,
    )


def reconcile_select(check: ReconcileIR, ir: ProjectIR, ctx: EmitContext) -> exp.Select:
    """The ``<check>__reconcile`` model: both sides, their difference, and the
    tolerance verdict, one row per compared key.

    A **FULL** join, deliberately: a key present on one side only is the
    loudest disagreement there is, and an inner join would hide exactly that
    by returning fewer rows instead of a failing one. Its ``difference`` is
    NULL and ``within_tolerance`` is FALSE — the ``COALESCE`` collapses the
    three-valued comparison at this one seam, the same way the routing
    predicate does (§5.4), because a verdict column has to be a verdict.
    """
    left, left_keys = _reconcile_side(check.left, ir, ctx, value=_LEFT_VALUE)
    right, right_keys = _reconcile_side(check.right, ir, ctx, value=_RIGHT_VALUE)
    # The guardrail stage has already refused sides keyed differently, so the
    # two key sets agree; join on the sorted order for deterministic bytes and
    # project in the left side's authored order.
    joined = sorted(set(left_keys) & set(right_keys))
    difference = exp.Abs(
        this=exp.Sub(
            this=exp.column(_LEFT_VALUE, table=_LEFT_ALIAS),
            expression=exp.column(_RIGHT_VALUE, table=_RIGHT_ALIAS),
        )
    )
    within = exp.Coalesce(
        this=grouped(
            exp.LTE(
                this=difference.copy(),
                # ``tolerance`` is a Decimal in the IR (RFC 0003 D5): it
                # reaches SQL as a numeric *literal*, never a float.
                expression=exp.Literal.number(str(check.tolerance)),
            )
        ),
        expressions=[exp.false()],
    )
    projections: list[Expression] = [
        cast(
            "Expression",
            exp.alias_(
                exp.Coalesce(
                    this=exp.column(key, table=_LEFT_ALIAS),
                    expressions=[exp.column(key, table=_RIGHT_ALIAS)],
                ),
                key,
            ),
        )
        for key in left_keys
    ]
    projections.extend(
        (
            exp.column(_LEFT_VALUE, table=_LEFT_ALIAS),
            exp.column(_RIGHT_VALUE, table=_RIGHT_ALIAS),
            cast("Expression", exp.alias_(difference.copy(), "difference")),
            cast("Expression", exp.alias_(within, "within_tolerance")),
        )
    )
    return (
        exp.Select()
        .select(*projections)
        .from_(left.subquery(alias=_LEFT_ALIAS))
        .join(
            right.subquery(alias=_RIGHT_ALIAS),
            on=conjunction(
                [
                    exp.EQ(
                        this=exp.column(key, table=_LEFT_ALIAS),
                        expression=exp.column(key, table=_RIGHT_ALIAS),
                    )
                    for key in joined
                ]
            ),
            join_type="FULL OUTER",
        )
    )


def reconcile_audit_predicate() -> Expression:
    """The violating-row predicate of a check's audit: rows outside tolerance.

    ``within_tolerance`` is already two-valued, so ``NOT`` is total here.
    """
    return exp.Not(this=exp.column("within_tolerance"))


def reconcile_audit_blocking(check: ReconcileIR) -> bool:
    """Whether a reconcile check's audit **stops the run** (RFC 0016 §5.3).

    ``reconcile`` carries an ``on_fail`` like every other disposition-bearing
    surface, and §5.3 gives it a job no rule can do: "a pipeline-stopping
    orphan gate, where genuinely wanted, is expressed as a ``reconcile`` check
    instead". That sentence is only true if ``on_fail: fail`` actually blocks.
    Emitting the same non-blocking audit for all three values made the field
    decoration — the mart said ``disposition = 'fail'`` while the run carried
    on regardless.

    ``flag`` stays non-blocking, and deliberately so: a reconcile disagreement
    means the numbers are wrong, which is exactly when a human needs to read
    the comparison table, and stopping the run would withhold the evidence.

    ``quarantine`` also lowers non-blocking — a reconcile check compares two
    aggregates and routes **no row** (§5.4's table: "separate model +
    non-blocking audit"), so there is nothing for a quarantine disposition to
    divert. Refusing the value belongs to the spec surface, where ``on_fail``
    is typed; treating it as "report, do not stop" is the conservative reading
    until that refusal lands.
    """
    return check.on_fail is OnFail.FAIL


# ....................... #
# The quality mart (RFC 0016 §5.8): every rule evaluation as one row of an
# ordinary gold model. Counts only — the reject *rows* are never exposed
# through the semantic layer (§7.4), and nothing here reads a clock.

_QUALITY_CTE_PREFIX = "_quality_rows_"
_FLAGS_ALIAS = "_flags"
_QUARANTINED_ALIAS = "_quarantined"
_EVALUATIONS_ALIAS = "_evaluations"
_STAMPED_ALIAS = "_stamped"
#: The per-evaluation columns a branch projects, in §5.8's schema order.
_BRANCH_COLUMNS = (
    "entity",
    "mapping",
    "rule",
    "disposition",
    *(column for column, _metric in QUALITY_MEASURE_COLUMNS),
)


def _mapping_identity(entity: EntityIR) -> str:
    """The ``mapping`` dimension's value — the same string the reject table
    records, so the two surfaces name one mapping the same way."""
    return f"{entity.source.relation}->{entity.name}"


def _quality_rows_cte(entity: EntityIR, ctx: EmitContext) -> exp.Select | exp.Union:
    """Every row the entity's rules were evaluated over, with the flag
    collection each carries and which side of the split it landed on.

    The union of the entity and its **unresolved** rejects is exactly §6's
    conservation-law population: a replayed row lives in the entity and its
    reject row is retained as audit history with ``resolved_at`` set, so
    excluding resolved rejects is what makes a replayed row count once.
    """
    namespace, relation = ctx.naming.relation(entity.name, Layer.SILVER)
    kept = (
        exp.Select()
        .select(
            exp.alias_(exp.column(FLAGS_COLUMN), _FLAGS_ALIAS),
            exp.alias_(exp.false(), _QUARANTINED_ALIAS),
        )
        .from_(exp.table_(relation, db=namespace))
    )
    if entity.quarantine is None:
        return kept
    reject_namespace, reject_rel = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    diverted = (
        exp.Select()
        .select(
            exp.alias_(exp.column("failed_rules"), _FLAGS_ALIAS),
            exp.alias_(exp.true(), _QUARANTINED_ALIAS),
        )
        .from_(exp.table_(reject_rel, db=reject_namespace))
        .where(exp.Is(this=exp.column("resolved_at"), expression=exp.null()))
    )
    return exp.union(kept, diverted, distinct=False)


def _counted(predicate: Expression) -> Expression:
    """``COALESCE(SUM(CASE WHEN <predicate> THEN 1 ELSE 0 END), 0)`` — a count
    that is 0, never NULL, on an empty **or** never-matching partition
    (RFC 0016 D68).

    The two halves answer different things and both are needed. ``ELSE 0``
    covers the partition that has rows and matches none of them; the
    ``COALESCE`` covers the partition with no rows at all, where ``SUM`` has
    nothing to sum and returns NULL — an entity whose source delivered nothing
    this run, which is an ordinary Tuesday and not an error. Without it every
    measure of that entity's mart rows is NULL, and a NULL measure does not
    read as a small number: it drops silently out of the ``SUM`` behind
    ``quality_quarantine_rate``, so the rate answers over a population smaller
    than the one it names.
    """
    return exp.Coalesce(
        this=exp.Sum(
            this=exp.Case(
                ifs=[exp.If(this=predicate, true=exp.Literal.number(1))],
                default=exp.Literal.number(0),
            )
        ),
        expressions=[exp.Literal.number(0)],
    )


def _rows_deduped(entity: EntityIR, ctx: EmitContext) -> Expression:
    """Rows dedupe removed before the rules ran — read off the dedupe stage
    itself, not as a residual against the surviving surfaces.

    ``bronze rows − rows that survived the stage-3 QUALIFY``. Both sides are
    scalar subqueries over **this run's** population, which is what makes the
    result a count: it is a difference between two numbers measured at the same
    moment, over the same relation, and it cannot be negative because the
    subtrahend is a subset of the minuend by construction.

    It used to be ``bronze − (entity rows + unresolved rejects)``. That looks
    like the same quantity and is not: the entity is rebuilt in full each run
    while the reject table is ``INCREMENTAL_BY_UNIQUE_KEY`` and *accumulates*,
    so as soon as bronze's incremental window moves past a row that is still an
    unresolved reject, the subtrahend exceeds the minuend and the "count" goes
    negative. A count that can be negative is not a count.

    Zero where it cannot be measured honestly: an entity without ``dedupe``
    loses nothing (the subtraction would always yield 0 anyway, at the cost of
    a bronze scan), and an SCD type 2 entity stores version history rather than
    one row per source row, so the difference would not be a dedupe count.
    """
    if entity.dedupe is None or entity.scd is SCDKind.TYPE2:
        return exp.Literal.number(0)
    namespace, relation = ctx.naming.relation(entity.source.relation, Layer.BRONZE)
    bronze = (
        exp.Select()
        .select(exp.Count(this=exp.Star()))
        .from_(exp.table_(relation, db=namespace))
        .subquery()
    )
    survivors = (
        exp.Select()
        .select(exp.Count(this=exp.Star()))
        .from_(_extract_select(entity, ctx).subquery(alias=_EXTRACT_ALIAS))
        .subquery()
    )
    return exp.Sub(this=bronze, expression=survivors)


def _branch(entity: EntityIR, rule: str, verdict: str, counts: list[Expression]) -> exp.Select:
    """One mart row over an entity's population CTE, in §5.8's schema order."""
    values: list[Expression] = [
        exp.Literal.string(entity.name),
        exp.Literal.string(_mapping_identity(entity)),
        exp.Literal.string(rule),
        exp.Literal.string(verdict),
        *counts,
    ]
    return (
        exp.Select()
        .select(
            *(
                cast("Expression", exp.alias_(value, name))
                for name, value in zip(_BRANCH_COLUMNS, values, strict=True)
            )
        )
        .from_(exp.table_(f"{_QUALITY_CTE_PREFIX}{entity.name}"))
    )


def _entity_branch(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The entity's **accounting row**: the counts that belong to the entity
    rather than to any one rule (RFC 0016 §5.8, resolved per D12 — see
    :data:`~bloomery.quality.ENTITY_GRAIN_ROW`).

    ``rows_evaluated``, ``rows_quarantined`` and ``rows_deduped`` are facts
    about the *population*: how many rows the rules ran over, how many of them
    the split diverted, how many dedupe removed first. Carrying them on every
    rule row — which is what the schema's flat shape invites — makes them fan
    out: ``SUM(rows_evaluated)`` over an entity with eight rules returns eight
    times the population, and the quarantine rate built from it is wrong by
    that factor and again by the number of rules a diverted row happened to
    trip. Giving each count exactly one row to live on is what makes every
    measure of this mart additive, which is the only property that lets §5.8's
    "a plain ``MetricRequest``" be true at *any* group-by.
    """
    return _branch(
        entity,
        ENTITY_GRAIN_ROW,
        ENTITY_GRAIN_ROW,
        [
            exp.Count(this=exp.Star()),
            exp.Literal.number(0),
            _counted(exp.column(_QUARANTINED_ALIAS)),
            _rows_deduped(entity, ctx),
        ],
    )


def _rule_branch(entity: EntityIR, rule: QualityRuleIR, *, arrays: bool) -> exp.Select:
    """One row of the quality mart: what one rule did to one entity's rows.

    Counts are read back off the **recorded** flag names (D23), never by
    re-evaluating the rule: the rule already ran upstream, the reject table no
    longer carries the source columns a re-evaluation would need, and a second
    implementation of a predicate is a second thing to keep in agreement.

    A rule row reports ``rows_failed`` and nothing else. The population counts
    beside it are the entity's, and they live on the entity's own row
    (:func:`_entity_branch`); ``rows_quarantined`` is there too, counting
    *rows* rather than rule-level diversions, because two quarantine rules
    firing on one row divert one row and not two. For a ``quarantine``-
    disposition rule ``rows_failed`` **is** the number of rows it diverted —
    firing one diverts the row — so nothing is lost by the move.
    """
    fired = flag_member(exp.column(_FLAGS_ALIAS), rule.name, arrays=arrays)
    return _branch(
        entity,
        rule.name,
        str(disposition(rule)),
        [
            exp.Literal.number(0),
            _counted(fired),
            exp.Literal.number(0),
            exp.Literal.number(0),
        ],
    )


def _reconcile_branch(check: ReconcileIR, ir: ProjectIR, ctx: EmitContext) -> exp.Select:
    """One row per reconcile check, read off its own model.

    Reconcile names share the rule-name grammar precisely so they can land in
    this ``rule`` dimension (see ``RULE_NAME_PATTERN``). ``entity`` and
    ``mapping`` name the check's **left** side: a reconcile relates two
    entities, and the left is the one whose aggregate is under test.

    A rule row, therefore counted like one: ``rows_failed`` is the number of
    compared keys outside tolerance, and the population columns stay zero. A
    reconcile's own row count is a count of *keys*, not of the left entity's
    rows — adding it to that entity's ``rows_evaluated`` would mix two grains
    under one column and put a second wrong number into the quarantine rate.
    """
    _side, entity, _keys = _resolved_side(check.left, ir)
    namespace, relation = ctx.naming.relation(reconcile_relation(check), Layer.SILVER)
    values: list[Expression] = [
        exp.Literal.string(entity.name),
        exp.Literal.string(_mapping_identity(entity)),
        exp.Literal.string(check.name),
        exp.Literal.string(str(check.on_fail)),
        exp.Literal.number(0),
        _counted(reconcile_audit_predicate()),
        exp.Literal.number(0),  # a reconcile check routes no row (§5.3)
        exp.Literal.number(0),
    ]
    return (
        exp.Select()
        .select(
            *(
                cast("Expression", exp.alias_(value, name))
                for name, value in zip(_BRANCH_COLUMNS, values, strict=True)
            )
        )
        .from_(exp.table_(relation, db=namespace))
    )


def _run_column(macro: str | None, name: str, type_name: str) -> Expression:
    """One run-context column: the engine's expression, or declared-but-NULL.

    bloomery never reads a clock (RFC 0003), so neither value can be computed
    here. Where the target framework offers a macro, its literal text is
    substituted; where it does not, the column is emitted as a typed NULL
    carrying an inline comment naming what the caller supplies — the schema
    §5.8 promises, with no pretence that a value is present.
    """
    if macro is not None:
        return cast("Expression", exp.alias_(exp.cast(exp.var(macro), type_name), name))
    column = cast(
        "Expression", exp.alias_(exp.cast(exp.null(), exp.DataType.build(type_name)), name)
    )
    column.comments = [
        (
            f" {name}: supplied by the executing engine's run context (RFC 0016 §5.8); "
            "the pinned target exposes no macro for it — fill this column in your runner "
        )
    ]
    return column


def quality_mart_select(ir: ProjectIR, ctx: EmitContext, run: RunContext) -> exp.Select:
    """``gold.mart_data_quality`` (RFC 0016 §5.8): one row per rule
    evaluation, plus one per reconcile check.

    Three nested levels, so each concern is readable on its own: the branches
    count, the middle level stamps the run context once, and the outer level
    buckets ``run_date`` into the date role's columns the way any mart's date
    role is bucketed. Each quality-carrying entity's population is a CTE, so
    an entity with ten rules is one scan, not ten.
    """
    arrays = _arrays(ctx)
    branches: list[exp.Select] = []
    entities = [entity for entity in ir.entities if entity.quality]
    for entity in entities:  # sorted on ProjectIR; rules sorted on EntityIR
        branches.append(_entity_branch(entity, ctx))
        branches.extend(_rule_branch(entity, rule, arrays=arrays) for rule in entity.quality)
    branches.extend(_reconcile_branch(check, ir, ctx) for check in ir.reconcile)
    evaluations: exp.Select | exp.Union = branches[0]
    for branch in branches[1:]:
        evaluations = exp.union(evaluations, branch, distinct=False)

    stamped = (
        exp.Select()
        .select(
            *(exp.column(name, table=_EVALUATIONS_ALIAS) for name in _BRANCH_COLUMNS),
            _run_column(run.run_id, "run_id", "TEXT"),
            _run_column(run.run_date, "run_date", "DATE"),
        )
        .from_(evaluations.subquery(alias=_EVALUATIONS_ALIAS))
    )
    run_date = exp.column("run_date", table=_STAMPED_ALIAS)
    projections: dict[str, Expression] = {
        name: exp.column(name, table=_STAMPED_ALIAS)
        for name in (*_BRANCH_COLUMNS, "run_id", "run_date")
    }
    for bucket in DATE_BUCKETS:
        bucketed = exp.func("DATE_TRUNC", exp.Literal.string(bucket), run_date.copy())
        projections[f"{QUALITY_RUN_ROLE}_{bucket}"] = cast(
            "Expression",
            exp.alias_(
                exp.cast(bucketed, exp.DataType.build("DATE")), f"{QUALITY_RUN_ROLE}_{bucket}"
            ),
        )
    select = (
        exp.Select()
        # Sorted by column name, exactly as ``mart_select`` projects a mart's
        # own (sorted) columns — the emitted SELECT and ``MartIR.columns``
        # agree position by position.
        .select(*(projections[name] for name in sorted(projections)))
        .from_(stamped.subquery(alias=_STAMPED_ALIAS))
    )
    for entity in entities:
        select = select.with_(
            f"{_QUALITY_CTE_PREFIX}{entity.name}", as_=_quality_rows_cte(entity, ctx)
        )
    return select


# ....................... #
# Mart lowering (RFC 0010 / RFC 0008 D11) — the only join-emitting path.


def _column_owner(mart: MartIR, column: MartColumnIR) -> str:
    """The join alias owning a flattened column: the base entity for its own
    (and date-role, and ``has_quality_flags``) columns, else the prefix of the
    join that flattened it."""
    if column.source_entity == mart.base and (
        column.ref is not None
        or column.name == column.source_column
        or column.name == HAS_QUALITY_FLAGS
    ):
        return mart.base
    return next(
        join.prefix
        for join in mart.joins
        if join.entity == column.source_entity
        and column.name == f"{join.prefix}{column.source_column}"
    )


def _mart_projection(mart: MartIR, column: MartColumnIR) -> Expression:
    source = exp.column(column.source_column, table=_column_owner(mart, column))
    if column.name == HAS_QUALITY_FLAGS:
        # RFC 0016 §5.5: an ordinary dimension, *derived* from the base's
        # generated ``_quality_ok`` (D23) rather than re-evaluated. ``NOT`` is
        # two-valued here by construction — ``_quality_ok`` is generated from
        # a never-NULL flag collection, so it is never NULL either.
        return cast("Expression", exp.alias_(exp.Not(this=source), column.name))
    if column.ref is None:
        # ``alias_`` is annotated with the ``Expr`` base, but always returns
        # an ``Expression`` here (cf. ir.nodes on ``parse_one``).
        return cast("Expression", exp.alias_(source, column.name))
    # Date-role bucket (RFC 0010 D4): DATE_TRUNC over the base source column,
    # cast to DATE so the emitted column has the declared IR type everywhere.
    # Built via ``exp.func`` — ``exp.DateTrunc``'s custom ``__init__`` is
    # untyped in this sqlglot version.
    bucketed = exp.func("DATE_TRUNC", exp.Literal.string(column.ref.dimension), source)
    return cast(
        "Expression", exp.alias_(exp.cast(bucketed, exp.DataType.build("DATE")), column.name)
    )


def mart_select(mart: MartIR, ctx: EmitContext) -> exp.Select:
    """The wide SELECT: base silver relation LEFT-joined once per resolved
    ``MartJoinIR``, projecting the full flattened column set."""
    owners = {
        column.name: (_column_owner(mart, column), column.source_column)
        for column in mart.columns
        if column.ref is None
    }
    base_namespace, base_relation = ctx.naming.relation(mart.base, Layer.SILVER)
    select = (
        exp.Select()
        .select(*[_mart_projection(mart, column) for column in mart.columns])
        .from_(exp.table_(base_relation, db=base_namespace, alias=mart.base))
    )
    for join in mart.joins:
        namespace, relation = ctx.naming.relation(join.entity, Layer.SILVER)
        conditions = [
            exp.EQ(
                this=exp.column(owners[from_column][1], table=owners[from_column][0]),
                expression=exp.column(to_column, table=join.prefix),
            )
            for from_column, to_column in join.on
        ]
        select = select.join(
            exp.table_(relation, db=namespace, alias=join.prefix),
            on=exp.and_(*conditions),
            join_type="LEFT",
        )
    return select


# ....................... #
# Date dimension (RFC 0008 D13, RFC 0013 R1 rule 4)

# Canonical dialect-neutral calendar body, re-parsed at emit like any SqlExpr
# (RFC 0003 D2). Bounds interpolate as spec-validated integers only — the SQL
# is a pure function of the catalog definition, never of a clock.
#
# The series is a FROM-clause table function, not a projection-level UNNEST:
# ``SELECT UNNEST(...)`` is illegal on Trino (UNNEST is FROM-only there) and
# on Postgres (``UNNEST`` takes an array, ``generate_series`` returns a set).
# From this one neutral node SQLGlot generates ``GENERATE_SERIES(...) AS
# date_day(date_day)`` on DuckDB/Postgres and ``UNNEST(SEQUENCE(...))`` on
# Trino. Trino's generator carries only the *table* alias onto the UNNEST
# column, so the alias is named ``date_day`` — making the column resolve to
# the same name on every shipped dialect.
_DIM_DATE_BODY = (
    "SELECT"
    " CAST(date_day AS DATE) AS date_day,"
    " CAST(DATE_TRUNC('month', date_day) AS DATE) AS date_month,"
    " CAST(DATE_TRUNC('quarter', date_day) AS DATE) AS date_quarter,"
    " CAST(DATE_TRUNC('week', date_day) AS DATE) AS date_week,"
    " CAST(DATE_TRUNC('year', date_day) AS DATE) AS date_year"
    " FROM GENERATE_SERIES("
    "CAST('{start_year}-01-01' AS DATE), CAST('{end_year}-12-31' AS DATE),"
    " INTERVAL '1' DAY) AS date_day(date_day)"
)


def dim_date_select(dim: DateDimensionIR) -> Expression:
    """The deterministic ``dim_date`` calendar SELECT — a generate-series
    calendar over the catalog's year bounds, no clock involved."""
    body = _DIM_DATE_BODY.format(start_year=dim.start_year, end_year=dim.end_year)
    # ``parse_one`` is annotated with the ``Expr`` base, but every node it
    # returns is an ``Expression`` (cf. ir.nodes).
    return cast("Expression", parse_one(body))


# ....................... #
# Audit predicates (RFC 0006 §5.6/D7)


def column_type(entity: EntityIR, name: str) -> LogicalType:
    """The declared logical type of one entity column."""
    return next(column.type for column in entity.columns if column.name == name)


def _bound_literal(value: str, bound_type: LogicalType) -> Expression:
    """A typed literal for an audit bound: numeric columns take number
    literals, everything else a string literal cast to the column type (so
    temporal comparisons never rely on engine coercion)."""
    if isinstance(bound_type, (IntType, DecimalType)):
        return exp.Literal.number(value)
    return exp.cast(exp.Literal.string(value), generic_type(bound_type))


def enum_literal(value: str, member_type: LogicalType) -> Expression:
    """An ``accepted_values`` member literal, typed by the audited column."""
    if isinstance(member_type, IntType):
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def audit_predicate(entity: EntityIR, audit: AuditIR, *, violations: bool) -> Expression:
    """The predicate for one custom-bodied audit kind (``min``/``max``/
    ``regex``/``reconcile``).

    ``violations=True`` selects the failing rows (SQLMesh audit bodies pass
    when the query returns none); ``violations=False`` is the row-level
    assertion that must hold (dbt ``expression_is_true``-shaped tests). Both
    forms are built here, side by side, so the two targets cannot drift.
    """
    column = exp.column(audit.column)
    params = dict(audit.params)
    if audit.kind == "min":
        bound = _bound_literal(params["value"], column_type(entity, audit.column))
        if violations:
            return exp.LT(this=column, expression=bound)
        return exp.GTE(this=column, expression=bound)
    if audit.kind == "max":
        bound = _bound_literal(params["value"], column_type(entity, audit.column))
        if violations:
            return exp.GT(this=column, expression=bound)
        return exp.LTE(this=column, expression=bound)
    if audit.kind == "regex":
        matches = exp.RegexpLike(this=column, expression=exp.Literal.string(params["pattern"]))
        return exp.Not(this=matches) if violations else matches
    # "reconcile" — the only remaining custom kind (RFC 0006 D7): row-level
    # disagreement between the derived column and its __direct shadow.
    shadow = exp.column(params["shadow"])
    if violations:
        return exp.NullSafeNEQ(this=column, expression=shadow)
    return exp.NullSafeEQ(this=column, expression=shadow)
