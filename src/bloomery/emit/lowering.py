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

from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.dialects import DialectFeature
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import (
    AuditIR,
    DateDimensionIR,
    EntityIR,
    Layer,
    MartColumnIR,
    MartIR,
    OnFail,
    QualityRuleIR,
    SqlExpr,
    generic_type,
)
from bloomery.quality import (
    FLAGS_COLUMN,
    INGESTION_METADATA,
    OK_COLUMN,
    REJECT_SUFFIX,
    ROW_ID_COLUMN,
    conjunction,
    dedupe_order,
    disjunction,
    disposition,
    empty_flags,
    flags_expression,
    grouped,
    indexed_params,
    params_of,
    payload_key,
    quality_ok,
    ref_alias,
    reject_id,
    source_alias,
    unknown_member_case,
    violation,
    with_dedupe_qualify,
)
from bloomery.typing import DecimalType, IntType, LogicalType

if TYPE_CHECKING:
    from bloomery.emit.base import EmitContext

__all__ = [
    "audit_predicate",
    "column_type",
    "dim_date_select",
    "entity_select",
    "enum_literal",
    "fail_audits",
    "ROW_ID_COUNT_COLUMN",
    "ingestion_audit_predicate",
    "mart_select",
    "reject_relation",
    "reject_select",
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
_EVALUATED_ALIAS = "_evaluated"
_TARGET_ALIAS = "_target"
#: The column the D21 audit body projects its duplicate count under.
ROW_ID_COUNT_COLUMN = "_row_id_count"
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


def _flag_pairs(rules: tuple[QualityRuleIR, ...], table: str) -> list[tuple[str, Expression]]:
    return [(rule.name, violation(rule, table=table)) for rule in rules]


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
        return select.where(exp.Is(this=exp.column("resolved_at"), expression=exp.null()))
    if entity.dedupe is not None:
        select = with_dedupe_qualify(select, entity.dedupe, entity.key)
    return select


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
        params_of(rule)["via_0000"].split("=", 1)[0]: rule
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
    ``False`` is its complement, the rows the entity keeps. The complement is
    ``NOT (…)``, which is ``UNKNOWN`` — and therefore *not* kept — only if the
    disjunction is ``UNKNOWN``; every violation predicate is definitively TRUE
    or not (D19), so the two sides partition the rows exactly.
    """
    rules = _rules(entity, OnFail.QUARANTINE)
    if not rules:
        return None
    # Collapse three-valued to two-valued **here**, at the routing seam, and
    # nowhere else: a rule predicate must stay silent on UNKNOWN (D19), but
    # routing has to be a partition — without the collapse a row whose only
    # quarantine rule evaluated UNKNOWN would satisfy neither ``fired`` nor
    # ``NOT fired`` and would vanish from both sides, breaking §6's
    # conservation law. "Did any quarantine rule *definitively* fire" is
    # exactly ``COALESCE(…, FALSE)``.
    fired = exp.Coalesce(
        this=grouped(disjunction([violation(rule, table=table) for rule in rules])),
        expressions=[exp.false()],
    )
    return fired if quarantined else exp.Not(this=fired)


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
                    _flag_pairs(_rules(entity, OnFail.FLAG), _EXTRACT_ALIAS), arrays=arrays
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

    ``failed_rules`` records **all** the row's failures, flag-level ones
    included (D18) — a reject row is the full account of why a row is not in
    the entity, not merely the part that diverted it. ``first_seen`` /
    ``last_seen`` are the batch's window over the row identity; ``resolved_at``
    is null until a replay sets it, and retention — never replay — is what
    eventually deletes the row.
    """
    _require_try_cast(entity, ctx)
    arrays = _arrays(ctx)
    extract = _extract_select(entity, ctx, include_raw=True)
    recorded = _rules(entity, OnFail.FLAG, OnFail.QUARANTINE)
    row_id = exp.column(ROW_ID_COLUMN, table=_EXTRACT_ALIAS)
    ingested = exp.column("_ingested_at", table=_EXTRACT_ALIAS)
    seen_window = [row_id.copy()]
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
        cast(
            "Expression",
            exp.alias_(
                exp.Window(this=exp.Min(this=ingested.copy()), partition_by=seen_window),
                "first_seen",
            ),
        ),
        cast(
            "Expression",
            exp.alias_(
                exp.Window(
                    this=exp.Max(this=ingested.copy()),
                    partition_by=[row_id.copy()],
                ),
                "last_seen",
            ),
        ),
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


def ingestion_audit_predicate(entity: EntityIR) -> Expression:
    """The D21 blocking audit's violating-row predicate.

    ``_source_row_id`` is declared NOT NULL and unique per source row — data
    properties no compiler can check, so the lowering emits a **blocking**
    audit instead: a null or duplicated identity stops the run rather than
    silently corrupting dedupe order or ``reject_id``.

    The duplicate half is a window count, and SQL forbids a window function in
    ``WHERE`` — so the audit body wraps the model in a subquery that projects
    the count as :data:`ROW_ID_COUNT_COLUMN`, and this predicate reads that
    column. The two halves of that arrangement live one function apart on
    purpose: the name is a constant here, not a string in a template.
    """
    del entity  # the contract is the same three columns for every entity
    parts: list[Expression] = [
        exp.Is(this=exp.column(name), expression=exp.null()) for name in INGESTION_METADATA
    ]
    parts.append(exp.GT(this=exp.column(ROW_ID_COUNT_COLUMN), expression=exp.Literal.number(1)))
    return disjunction(parts)


def fail_audits(entity: EntityIR) -> tuple[tuple[str, Expression], ...]:
    """``(audit name, violating-row predicate)`` per ``on_fail: fail`` rule.

    SQLMesh audits run over the model's own output, so the predicate is
    rendered over model columns. For ``coercible`` that means the marker's
    source conjuncts are unavailable and the audit reduces to ``col IS NULL``
    — **stricter** than the marker, never weaker: every coercion failure is a
    null, so no violation can slip past, and the extra rows it can catch
    (a source that was genuinely null) are rows a fail-disposition coercible
    rule already declares intolerable.
    """
    audits: list[tuple[str, Expression]] = []
    for rule in _rules(entity, OnFail.FAIL):
        if rule.kind == "coercible":
            predicate: Expression = exp.Is(
                this=exp.column(rule.column or ""), expression=exp.null()
            )
        else:
            predicate = violation(rule)
        audits.append((f"{entity.name}_{rule.name}", predicate))
    return tuple(audits)


def _replay_candidates(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The unresolved reject rows that now pass, re-derived from ``raw``.

    Replay "re-runs the current mapping against ``raw``" for unresolved rows
    (RFC 0016 §5.6). Running them back through :func:`_quality_pipeline` is
    what makes "passers merge, the rest stay" true by construction: a
    candidate that still fires a quarantine rule is filtered out by the very
    same routing predicate the pipeline uses.
    """
    return _quality_pipeline(entity, ctx, _extract_select(entity, ctx, from_payload=True))


def _dedupe_tuple(entity: EntityIR, table: str) -> exp.Tuple:
    order = dedupe_order(entity.dedupe, table=table) if entity.dedupe else ()
    return exp.Tuple(expressions=[term.this for term in order])


def replay_statements(entity: EntityIR, ctx: EmitContext) -> tuple[Expression, ...]:
    """The replay artifact (RFC 0016 §5.6, D22): one MERGE plus the resolution
    stamp.

    Replay merges by the **same dedupe ordering as the pipeline** — a replayed
    candidate wins or loses against an incumbent by the dedupe total order
    (recency field, tie-breaks, ``_source_row_id``), which is what makes
    re-running replay re-derive identical winners. The comparison is the row
    constructor over exactly :func:`~bloomery.quality.dedupe_order`'s columns;
    null ordering is the D21 blocking audit's job, upstream of here.

    ``resolved_at`` is stamped by the **executing engine's** clock
    (``CURRENT_TIMESTAMP``) — bloomery never reads a clock (RFC 0003), it
    emits the statement and the caller runs it. The reject row is kept as
    audit history; retention, never replay, is what deletes it.
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

    wins = exp.GT(
        this=_dedupe_tuple(entity, _REPLAY_ALIAS),
        expression=_dedupe_tuple(entity, _TARGET_ALIAS),
    )
    matched = exp.When(
        matched=True,
        condition=wins,
        then=exp.Update(
            expressions=[
                exp.EQ(
                    this=exp.column(name, table=_TARGET_ALIAS),
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
    return (merge, resolve)


# ....................... #
# Mart lowering (RFC 0010 / RFC 0008 D11) — the only join-emitting path.


def _column_owner(mart: MartIR, column: MartColumnIR) -> str:
    """The join alias owning a flattened column: the base entity for its own
    (and date-role) columns, else the prefix of the join that flattened it."""
    if column.source_entity == mart.base and (
        column.ref is not None or column.name == column.source_column
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
