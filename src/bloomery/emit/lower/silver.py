"""The silver entity SELECT (RFC 0016 §5.4–§5.6).

Extract, rules, routing, dedupe, the reject table and replay — one nested
query, built in the pipeline order the RFC declares: extract → transform →
dedupe → field rules → row rules → route. Both SQL targets share every line
of it (RFC 0008 D1).

This is one stage rather than the two RFC 0019 §5.1 sketched. Extract is not a
separable stage: it is level 1 of the same SELECT, and fourteen functions of
the rule pipeline are built from it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects import DialectFeature
from bloomery.emit.lower.predicates import as_of_conditions
from bloomery.errors import EmitError, UnsupportedByTarget, guaranteed
from bloomery.ir import (
    SOURCE_COLUMN,
    EntityIR,
    FxRatesIR,
    Layer,
    OnFail,
    QualityRuleIR,
    SourceIR,
    SqlExpr,
)
from bloomery.quality import (
    FLAGS_COLUMN,
    INGESTION_METADATA,
    OK_COLUMN,
    REJECT_COLUMNS,
    REJECT_SUFFIX,
    REPAIRS_COLUMN,
    ROW_ID_COLUMN,
    SUPERSEDED_RULE,
    branch_alias,
    branch_violation,
    branched,
    conjunction,
    dedupe_order,
    disjunction,
    disposition,
    empty_flags,
    flag_member,
    flags_expression,
    grouped,
    is_not_null,
    is_null,
    params_of,
    payload_key,
    quality_ok,
    ref_alias,
    reject_id,
    repair_alias,
    repair_body,
    repairs,
    routing_predicate,
    sole_via_column,
    unknown_member_case,
    verdict,
    violation,
    window_alias,
    windowed,
    with_dedupe_qualify,
)
from bloomery.transforms import (
    CONVERT_ANCHOR,
    CONVERT_ARITY,
    CONVERT_FROM,
    CONVERT_MARKER,
    CONVERT_TO,
    CONVERT_TYPE,
    iso_text,
    neutral_type,
)
from bloomery.typing import parse_type

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from collections.abc import Mapping as AbcMapping

    from bloomery.emit.base import EmitContext

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


# ....................... #


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


# ....................... #


def _sole_source(entity: EntityIR, feature: str) -> SourceIR:
    """The entity's one source, for a surface that has no merged form.

    The reject projection, the replay merge, the conservation audit and the
    quality mart are all built from compile-time literals off *the* mapping —
    its relation, its version — and from ``_source_row_id``, which is unique
    within one source relation (RFC 0016 D21). RFC 0024 D14 refuses ``dedupe:``
    and ``quarantine:`` on a merged entity for exactly that reason.

    Those two blocks are **not** the emission condition for every caller,
    which is how this raised for a project the resolver admitted: a
    ``reconcile:`` naming a merged entity emits a quality mart with no
    ``dedupe:`` or ``quarantine:`` anywhere, and reached here to fail as an
    internal assertion on SQLMesh while Cube compiled the same project.
    The guardrail stage now refuses that side (see
    :func:`bloomery.guardrails.quality._resolve_side`), so the invariant holds
    again — but it holds because three refusals cover the callers, not because
    two do.

    This stays because the alternative spelling — ``entity.sources[0]`` —
    reads as a choice among N and would quietly become one on the day P2
    lifts D14.
    """

    if len(entity.sources) != 1:
        msg = (
            f"{feature} on entity {entity.name!r} was built from "
            f"{len(entity.sources)} sources; it is defined for one (RFC 0024 D14 refuses "
            "the blocks that emit it on a merged entity, so this is a resolver "
            "invariant that has stopped holding)"
        )
        raise EmitError(msg)

    return entity.sources[0]


# ....................... #


def _arrays(ctx: EmitContext) -> bool:
    return ctx.dialect.supports(DialectFeature.ARRAY)


# ....................... #


def _rules(entity: EntityIR, *dispositions: OnFail) -> tuple[QualityRuleIR, ...]:
    """The entity's rules with one of ``dispositions``, in canonical order."""

    return tuple(rule for rule in entity.quality if disposition(rule) in dispositions)


# ....................... #


def _recorded_rules(entity: EntityIR) -> tuple[QualityRuleIR, ...]:
    """Every rule whose name a reject row records in ``failed_rules`` (D18).

    All of them — a reject row is the full account of why a row is not in the
    entity, "its flag-level failures included", and by the same argument its
    blocking ones. Excluding ``fail`` rules left the account silent about the
    most serious thing that happened to the row.
    """

    return _rules(entity, OnFail.FLAG, OnFail.QUARANTINE, OnFail.FAIL)


# ....................... #


def _windowed_rules(entity: EntityIR) -> tuple[QualityRuleIR, ...]:
    """The entity's rules whose predicate is a window function, in canonical
    order (:data:`~bloomery.quality.WINDOWED_KINDS`)."""

    return tuple(rule for rule in entity.quality if windowed(rule))


# ....................... #


def _stage(select: exp.Select | exp.Union, entity: EntityIR) -> exp.Select | exp.Union:
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


# ....................... #


def _flag_pairs(rules: tuple[QualityRuleIR, ...], table: str) -> list[tuple[str, Expression]]:
    return [(rule.name, verdict(rule, table)) for rule in rules]


# ....................... #


def _carries_metadata(entity: EntityIR) -> bool:
    """Whether the ingestion-metadata columns ride through to silver.

    An entity using ``quarantine`` or ``dedupe`` needs them at run time, not
    only at compile: dedupe's final sort key is ``_source_row_id``, the reject
    table's identity is built from it, replay compares incumbents by it, and
    the D21 blocking audit reads all three off the model.
    """

    return entity.dedupe is not None or entity.quarantine is not None


# ....................... #


def _referential_rules(entity: EntityIR) -> tuple[QualityRuleIR, ...]:
    return tuple(rule for rule in entity.quality if rule.kind == "referential")


# ....................... #


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


# ....................... #


def _payload_columns(entity: EntityIR, origin: SourceIR) -> tuple[str, ...]:
    """The bronze **columns** ``raw`` carries, sorted — mapped and
    acknowledged-unmapped alike, minus the redacted ones.

    ``raw`` is keyed by top-level bronze column, not by JSONPath, because that
    is what makes replay work: the lowered column expressions read
    ``JSON_EXTRACT_SCALAR(a, '$.b')`` off a *column* ``a``, and replay re-runs
    those same expressions against ``raw`` (RFC 0016 §5.6). Keying by column is
    also the honest reading of "the bronze payload" — a row, not a projection.

    **Per branch**, and the two sources of a merge need share no column names
    at all (RFC 0035 §5.3): each branch writes its own payload and replay reads
    it back through that same branch's rewritten expressions, so no expression
    ever reads a payload it did not write.

    Redaction therefore acts at column granularity, which is exactly the
    granularity ``RedactionConflict`` refuses at (:mod:`bloomery.guardrails.quality`):
    a ``redact:`` path sharing a top-level column with any path the mapping
    reads is a compile error, so redaction can only ever remove a column
    nothing reads.
    """
    redacted = frozenset(
        payload_key(path) for path in (entity.quarantine.redact if entity.quarantine else ())
    )
    paths = {field.source_path for field in origin.fields} | set(origin.unmapped)
    return tuple(sorted({payload_key(path) for path in paths} - redacted))


# ....................... #


def _json_object(pairs: list[tuple[str, Expression]], ctx: EmitContext) -> Expression:
    """A JSON object from sorted key/value pairs, spelled by the dialect port.

    Not one construction after all (RFC 0016 D83): the positional
    ``JSON_OBJECT('k', v)`` this used to build is DuckDB's spelling, Postgres
    has no positional ``json_object`` at all (it wants ``json_build_object``),
    and Trino parses only the SQL-standard keyword form. The claim that it was
    portable held because only DuckDB ever executed it.
    """

    return ctx.dialect.json_object(pairs)


# ....................... #


#: The alias the rate subquery binds its relation to. Short and fixed: it is
#: scoped to one subquery, so it cannot collide with anything outside it.
_FX_ALIAS = "fx"


def _bound(marker: exp.Anonymous) -> bool:
    """Whether a marker carries the arguments the resolver binds into it."""

    return len(marker.expressions) == CONVERT_ARITY


def _markers(expr: Expression) -> list[exp.Anonymous]:
    """Every currency-conversion marker in one expression.

    One predicate for all three readers here — the refusal, the rewrite, and
    the walk inside it — because a marker the refusal recognises and the
    rewrite does not is a marker emitted verbatim into SQL.
    """
    return [
        node for node in expr.find_all(exp.Anonymous) if str(node.this).upper() == CONVERT_MARKER
    ]


def _rate_subquery(marker: exp.Anonymous, fx: FxRatesIR, ctx: EmitContext) -> Expression:
    """One ``CONVERT_CURRENCY`` marker as the rate it stands for (RFC 0023 §5.4).

    A **correlated scalar subquery**, not a join::

        (SELECT fx.rate FROM silver.fx_rate AS fx
          WHERE fx.from_ccy = 'EUR' AND fx.to_ccy = 'USD'
            AND <anchor> >= fx.valid_from
            AND (fx.valid_to IS NULL OR <anchor> < fx.valid_to))

    A join would be the more usual shape and is the wrong one here: ``convert``
    is a transform, and a transform is a scalar expression inside one
    projection of the branch SELECT. Adding a join would put the rate table in
    the FROM clause of a SELECT that is also unioned across sources, deduped,
    and re-run against the reject payload on replay — four shapes that would
    each need to learn about it. A scalar expression needs none of them to
    change, and replay in particular keeps working *because* it re-runs this
    same expression (RFC 0016 §5.6).

    The anchor arrives already lowered: ``resolve.build`` replaced the field
    name the author wrote with that field's own lowering, because the anchor's
    silver name does not exist yet where this is projected — both are
    projections of one SELECT, and a lateral column alias is a DuckDB
    extension Postgres and Trino reject.

    A miss is NULL, deliberately (D11): with both interval ends declared, a gap
    in the rate feed matches nothing, and NULL propagates into the amount
    rather than resolving to a neighbouring rate. The alternative — deriving
    the upper bound so that the newest rate runs forward forever — takes that
    choice away from the feed, which can no longer say "this rate ended and
    nothing replaced it".

    The product is **cast back to the type the chain holds here** — carried in
    the marker, because it is what ``convert`` declares as its output and only
    the chain knows it — for the reason
    :func:`~bloomery.transforms._builtins._narrowed` gives for ``multiply`` and
    ``divide``: every engine widens decimal arithmetic differently, so an
    uncast ``decimal(12,4) * rate`` materialises as ``decimal(18,8)`` on DuckDB
    and something else again on Trino and PostgreSQL, while the IR goes on
    claiming ``decimal(12,4)``. Unlike those two the cast is *not* lossless by
    construction — a rate carries its own scale — so it rounds to the precision
    the chain declares at this point, which is the only precision anything
    downstream was promised.

    The running type rather than the *field's* type, for the same reason
    ``multiply`` narrows to its own ``_arith_output``: a later widening step in
    the same chain would otherwise absorb an overflow the compiler believes
    cannot happen here.
    """
    namespace, relation = ctx.naming.relation(fx.relation, Layer.SILVER)
    anchor = guaranteed(
        (marker.expressions[CONVERT_ANCHOR],) if _bound(marker) else (),
        expected=(
            f"a {CONVERT_MARKER} marker carrying its two currencies and a lowered anchor, "
            f"not {len(marker.expressions)} expression(s)"
        ),
        by="resolve.build, which binds every convert step it lowers from key: or fields:",
    )
    conditions = [
        exp.EQ(
            this=exp.column(fx.from_currency, table=_FX_ALIAS),
            expression=marker.expressions[CONVERT_FROM].copy(),
        ),
        exp.EQ(
            this=exp.column(fx.to_currency, table=_FX_ALIAS),
            expression=marker.expressions[CONVERT_TO].copy(),
        ),
        *as_of_conditions(anchor, table=_FX_ALIAS, valid_from=fx.valid_from, valid_to=fx.valid_to),
    ]
    select = (
        exp.Select()
        .select(exp.column(fx.rate, table=_FX_ALIAS))
        .from_(exp.table_(relation, db=namespace, alias=_FX_ALIAS))
        .where(exp.and_(*conditions))
    )

    product = exp.Mul(this=marker.expressions[0].copy(), expression=exp.paren(select.subquery()))

    running = parse_type(
        marker.expressions[CONVERT_TYPE].this,
        source_path=f"transform: convert on {fx.relation}",
    )

    return exp.cast(product, neutral_type(running))


# ....................... #


def _lower_conversions(entity: EntityIR, ctx: EmitContext) -> EntityIR:
    """Rewrite every currency-conversion marker into its rate subquery, or
    refuse the entity that has one with no rates declared (RFC 0023 D4/§5.4).

    Done here rather than in the guardrail stage because here is where the
    marker becomes SQL: :func:`_extract_select` is the one place a
    ``SourceColumnIR.expr`` is realized, so no emission path — model, reject
    table, replay, or fail audit — can reach a marker without passing this.

    Every source, not the first: a merged entity's branches carry independent
    lowerings, so one may convert where another does not, and a pass over one
    branch would emit the other's marker untouched.

    The refusal is what remains of Phase 1's unconditional one. It is no longer
    "no engine can do this" — one can, given rates — but "this project asked to
    convert and declared nothing to convert against", which is a spec gap the
    message can name precisely.
    """
    carriers = [
        column
        for source in entity.sources
        for column in source.columns
        if _markers(column.expr.ast())
    ]

    if not carriers:
        return entity

    if ctx.fx_rates is None:
        column = carriers[0]
        msg = (
            f"column {column.name!r} of entity {entity.name!r} applies the convert "
            "transform, but no rate relation is declared: a currency conversion is a "
            "join against a dated rate table, and the catalog carries no 'fx_rates:' "
            "(RFC 0023 §5.4). Emitted as-is the model would compile here and fail on "
            "its first run. Fix: declare fx_rates: in the catalog with the relation and "
            "its from/to/rate/valid_from/valid_to columns, or drop the convert step and "
            "keep the amounts in their source currency"
        )
        raise UnsupportedByTarget(
            msg, source_path=f"entity_model: entities.{entity.name}.fields.{column.name}"
        )

    fx = ctx.fx_rates
    rewritten = tuple(
        replace(
            source,
            columns=tuple(
                replace(column, expr=SqlExpr(_converted(column.expr.ast(), fx, ctx).sql()))
                if _markers(column.expr.ast())
                else column
                for column in source.columns
            ),
        )
        for source in entity.sources
    )

    return replace(entity, sources=rewritten)


# ....................... #


def _converted(expr: Expression, fx: FxRatesIR, ctx: EmitContext) -> Expression:
    """One column expression with every marker in it replaced."""

    def rewrite(node: Expression) -> Expression:
        if isinstance(node, exp.Anonymous) and str(node.this).upper() == CONVERT_MARKER:
            return _rate_subquery(node, fx, ctx)

        return node

    return expr.transform(rewrite)


# ....................... #


#: The reject columns a branch computes for itself (RFC 0035 D2). Named here
#: rather than inlined because :func:`reject_select` reads exactly these back
#: off the extract, and two lists that have to agree should be one.
_PROVENANCE_COLUMNS = ("reject_id", "source_relation", "mapping", "mapping_version")


def _provenance(entity: EntityIR, origin: SourceIR, ctx: EmitContext) -> list[Expression]:
    """One branch's reject provenance: which relation, which mapping, which
    version, and the identity derived from the first of them.

    All four are compile-time literals *of this branch*. ``reject_id`` is a
    digest over ``(source_relation, _source_row_id)`` — the pair RFC 0016 D21
    designed for exactly this, since the row identity alone is unique only
    within one source relation and a merged entity's reject table holds rows
    from several.
    """

    return [
        cast(
            "Expression",
            exp.alias_(
                reject_id(origin.relation, exp.column(ROW_ID_COLUMN), ctx.dialect.text_sha256),
                "reject_id",
            ),
        ),
        cast("Expression", exp.alias_(exp.Literal.string(origin.relation), "source_relation")),
        cast(
            "Expression",
            exp.alias_(exp.Literal.string(f"{origin.relation}->{entity.name}"), "mapping"),
        ),
        cast(
            "Expression",
            exp.alias_(exp.Literal.number(origin.mapping_version), "mapping_version"),
        ),
    ]


# ....................... #


def _branch_verdicts(
    entity: EntityIR,
    origin: SourceIR,
    produced: AbcMapping[str, Expression],
    source: Callable[[Expression], Expression],
) -> dict[str, Expression]:
    """One branch's verdict for every branched rule, keyed by its alias
    (RFC 0024 D32).

    The facts come from this branch's :class:`~bloomery.ir.SourceColumnIR` —
    the raw extractions ``coercible`` compares against, the ``enum_map``
    targets ``in_enum`` admits — because that is where a fact about one
    mapping's chain is true. A column this branch does not produce has neither,
    and the predicate builders read that emptiness as ``FALSE``: a branch
    projecting a typed NULL for a column it never mapped has not failed a cast.

    ``produced`` is this branch's final expression per column, and it is what
    each verdict reads instead of the column's *name*. At this level the name
    still belongs to **bronze** — the projection defining it is being built in
    the same ``SELECT`` — so left alone, ``coercible`` would have compared the
    raw text against NULL rather than the cast's result and ``in_enum`` would
    have judged the value before its ``enum_map`` chain ran. It is passed into
    the builder rather than substituted afterwards for the reason
    :func:`~bloomery.quality.branch_violation` gives.

    ``source`` is the replay rewrite, applied here for the same reason it is
    applied to the column expressions themselves — a verdict read out of the
    reject payload has to be the *same* verdict, or replay is a second
    implementation of the pipeline rather than the pipeline.
    """
    by_column = {column.name: column for column in origin.columns}
    verdicts: dict[str, Expression] = {}

    for rule in entity.quality:
        if not branched(rule):
            continue

        name = rule.column or ""
        column = by_column.get(name)
        verdicts[branch_alias(rule)] = branch_violation(
            rule,
            sources=() if column is None else [source(SqlExpr(p).ast()) for p in column.sources],
            enum_values=() if column is None else column.enum_values,
            value=produced.get(name),
        )

    return verdicts


# ....................... #


def _branch_predicate(
    origin: SourceIR,
    rule: QualityRuleIR,
    raw: Expression,
    source: Callable[[Expression], Expression],
) -> Expression:
    """A repairable rule's predicate, built where the repair can read it.

    A repair runs at the *extract* level, where a branched rule's verdict is
    being projected in the same ``SELECT`` and so cannot be referred to by
    name. The predicate is therefore built inline here rather than read back
    through :func:`~bloomery.quality.verdict` — the same restriction
    :func:`_over` exists for, one alias along.
    """
    if not branched(rule):
        return violation(rule)

    column = next((c for c in origin.columns if c.name == rule.column), None)
    return branch_violation(
        rule,
        sources=() if column is None else [source(SqlExpr(path).ast()) for path in column.sources],
        enum_values=() if column is None else column.enum_values,
        value=raw,
    )


# ....................... #


def _branch_select(
    entity: EntityIR,
    origin: SourceIR,
    ctx: EmitContext,
    *,
    include_raw: bool = False,
    from_payload: bool = False,
) -> exp.Select:
    """Stages 1–2 for **one** source: its bronze projections, the ingestion
    metadata, and the ``raw`` payload where a reject table needs it.

    One of these per :attr:`EntityIR.sources` entry, unioned by
    :func:`_extract_select` (RFC 0024 D3). Everything below the union lives
    here; everything the merged relation is judged by — the dedupe ``QUALIFY``,
    the windowed verdicts, the rules — lives above it, because a stage
    evaluated per source would judge rows the merged relation does not contain
    (D6).

    ``from_payload`` builds the **replay** form of the same stages: the very
    same lowered column expressions, with their bronze column references
    rewritten to extractions out of the reject table's ``raw``. One lowering,
    two sources — replay cannot drift from the pipeline because it *is* the
    pipeline (RFC 0016 §5.6).
    """

    if from_payload:
        namespace, relation = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    else:
        namespace, relation = ctx.naming.relation(origin.relation, Layer.BRONZE)

    def source(node: Expression) -> Expression:
        return _from_payload(node) if from_payload else node

    repaired = {rule.column: rule for rule in entity.quality if repairs(rule)}
    projections: list[Expression] = []
    #: This branch's final expression per column — what the name means one
    #: level up, and what a branched rule's verdict has to be computed over.
    produced: dict[str, Expression] = {}

    # The lowering, not the schema (RFC 0024 D26): what this SELECT projects is
    # one source's expression per column, and `SourceIR.columns` is sorted by
    # name exactly as `EntityIR.columns` is — and covers it exactly, since the
    # builder fills an unmapped column with a typed NULL (§5.2 rule 3). So
    # every branch projects the same names in the same order, which is what a
    # `UNION ALL` requires.
    for column in origin.columns:
        raw = source(column.expr.ast())
        rule = repaired.get(column.name)
        if rule is None:
            produced[column.name] = raw
            projections.append(cast("Expression", exp.alias_(raw, column.name)))
            continue
        # A repaired column's verdict is computed over the value **as
        # delivered**, before the recipe rewrites it — that is what "the recipe
        # ran" means. The post-repair verdict is a different question, answered
        # one level up over the value this projection produces.
        fired = _branch_predicate(origin, rule, raw, source)
        repaired_value = exp.Case(
            ifs=[exp.If(this=fired, true=_over(repair_body(rule), column.name, raw))],
            default=raw.copy(),
        )
        produced[column.name] = repaired_value
        projections.append(cast("Expression", exp.alias_(repaired_value, column.name)))
        # The recipe *ran* — recorded beside the repaired value because after
        # the rewrite the verdict alone cannot tell "never violated" from
        # "violated and fixed" (RFC 0016 D87).
        projections.append(cast("Expression", exp.alias_(fired.copy(), repair_alias(rule))))

    if _carries_metadata(entity):
        projections.extend(exp.column(name) for name in INGESTION_METADATA)

    # A branched rule's inputs — the raw source paths ``coercible`` compares
    # against, the ``enum_map`` targets ``in_enum`` admits — exist only at
    # *this* level, below the union and before the subquery hides them, and on
    # a merged entity they are one branch's rather than the entity's
    # (RFC 0024 D32). Each branch computes its own verdict and projects it
    # under one shared name, which is what makes the union type-check and lets
    # the rule above it reference a single column.
    projections.extend(
        cast("Expression", exp.alias_(expression, alias))
        for alias, expression in sorted(_branch_verdicts(entity, origin, produced, source).items())
    )

    if include_raw:
        payload = _json_object(
            [(column, exp.column(column)) for column in _payload_columns(entity, origin)], ctx
        )
        projections.append(cast("Expression", exp.alias_(payload, "_raw")))

    if len(entity.sources) > 1:
        # Provenance, and only where it means something (RFC 0024 D7): the
        # collision audit reports *which* sources shared a key, and on a
        # single-source entity the column would be a constant in every row of
        # every relation forever.
        projections.append(
            cast("Expression", exp.alias_(exp.Literal.string(origin.relation), SOURCE_COLUMN))
        )

    if include_raw:
        # The reject table's provenance, computed **here** because it is true of
        # a branch and was only ever true of a model because there was one
        # branch (RFC 0035 D2). ``reject_id`` moves with the three literals out
        # of necessity rather than symmetry: its first argument is this
        # branch's relation name, which the union erases one level up.
        #
        # Gated on ``include_raw`` rather than on ``quarantine:``, because that
        # flag is exactly "this extract feeds the reject model". Gated on the
        # block instead, the entity model computed a SHA-256 per row and
        # projected three literals that nothing above it ever selected.
        projections.extend(_provenance(entity, origin, ctx))

    select = exp.Select().select(*projections).from_(exp.table_(relation, db=namespace))

    if from_payload:
        unresolved: Expression = exp.Is(this=exp.column("resolved_at"), expression=exp.null())

        if len(entity.sources) > 1:
            # Each branch replays **its own** rows (RFC 0035 D3). Without the
            # filter every branch reads every reject row, so one mapping's
            # extraction runs over another mapping's ``raw`` payload — whose
            # keys it does not have — and returns NULLs rather than raising.
            # The literal names exactly one branch because ``(target, source)``
            # is unique (RFC 0024 D12).
            unresolved = cast(
                "Expression",
                exp.and_(
                    unresolved,
                    exp.EQ(
                        this=exp.column("source_relation"),
                        expression=exp.Literal.string(origin.relation),
                    ),
                ),
            )

        return select.where(unresolved)

    return select


# ....................... #


def union_stage(entity: EntityIR, ctx: EmitContext) -> exp.Select | exp.Union:
    """Stages 1–2 for every source, unioned — the relation D13's collision
    audit reads.

    Public because the audit is built in the same module and one other place
    would otherwise re-derive the branch list; :func:`_extract_select` is the
    ordinary caller and adds the dedupe and windowed levels on top.
    """
    lowered = _lower_conversions(entity, ctx)
    branches = [_branch_select(lowered, origin, ctx) for origin in lowered.sources]
    return _union_all(branches) if len(branches) > 1 else branches[0]


# ....................... #


def _extract_select(
    entity: EntityIR, ctx: EmitContext, *, include_raw: bool = False, from_payload: bool = False
) -> exp.Select | exp.Union:
    """Stages 1–3: one :func:`_branch_select` per source, unioned, then the
    dedupe ``QUALIFY`` and the windowed-verdict level over the result.

    **The union is the first stage** (RFC 0024 D6): union → dedupe → rules. A
    rule evaluated per source would judge a row the merged relation does not
    contain, which is the argument that fixed dedupe-before-rules in RFC 0016.

    Branch order is lexicographic by source relation, inherited from
    ``EntityIR.sources`` rather than re-derived, so the emitted text is
    byte-identical across processes (D3). Row order is **not** claimed:
    ``UNION ALL`` is a bag, and where an order is needed it comes from declared
    ordering columns as it does today.

    Returns a ``Select`` for the ordinary single-source entity — the union of
    one is itself, not a one-branch ``UNION`` — so nothing about the existing
    corpus moves except the fingerprint.
    """
    entity = _lower_conversions(entity, ctx)
    branches = [
        _branch_select(entity, origin, ctx, include_raw=include_raw, from_payload=from_payload)
        for origin in entity.sources
    ]

    merged = len(branches) > 1
    union: exp.Select | exp.Union = _union_all(branches) if merged else branches[0]

    if from_payload:
        # No `QUALIFY` on replay: the reject table already holds one row per
        # source-row identity.
        return _stage(union, entity)

    if entity.dedupe is None:
        return _stage(union, entity)

    # A `UNION ALL` takes no `QUALIFY` of its own — the clause belongs to a
    # SELECT — so the union becomes a subquery the dedupe level selects from.
    # That level is also where D6's pipeline order is visible: union first,
    # then dedupe, then the rules.
    level = _dedupe_level(union) if isinstance(union, exp.Union) else union
    return _stage(with_dedupe_qualify(level, entity.dedupe, entity.key, merged=merged), entity)


# ....................... #


def _dedupe_level(union: exp.Select | exp.Union) -> exp.Select:
    """``SELECT * FROM (<union>) AS _extract`` — the level a ``QUALIFY`` can
    attach to.

    Star-projected rather than column-listed: the branches already agree on
    their projection list (that is what makes the union legal), so naming the
    columns here would restate it and give it somewhere to drift.
    """

    return exp.Select().select(exp.Star()).from_(union.subquery(alias=_EXTRACT_ALIAS))


# ....................... #


def _union_all(branches: list[exp.Select]) -> exp.Union:
    """``branches`` folded left into one ``UNION ALL``, in the order given.

    ``UNION ALL``, never ``UNION`` (RFC 0024, alternatives): distinct would make
    the collision audit unnecessary for exact duplicates by *hiding* them, and
    two sources agreeing on every column of one key is a fact an operator
    should see. It is also an expensive way to be silent on a wide relation.
    """
    folded: exp.Select | exp.Union = branches[0]

    for branch in branches[1:]:
        folded = exp.Union(this=folded, expression=branch, distinct=False)

    return cast("exp.Union", folded)


# ....................... #


def _over(node: Expression, column: str, value: Expression) -> Expression:
    """``node`` with every bare reference to ``column`` replaced by ``value``.

    A repair lives at the *extract* level, where the column it repairs is being
    defined in the same ``SELECT`` and so cannot be referred to by name. Both
    halves of the construction — the verdict that decides whether the recipe
    runs and the recipe itself — are therefore rewritten to read the column's
    expression directly.

    Only unqualified references are rewritten: a qualified one belongs to some
    other level, and a repairable rule's predicate never has one (the kinds
    whose predicates reach outside their own column — ``coercible`` through its
    source aliases, ``unique`` through a window, the row rules through a join —
    are exactly the kinds that cannot carry a repair at all).
    """

    def substitute(child: Expression) -> Expression:
        if isinstance(child, exp.Column) and not child.table and child.name == column:
            return value.copy()

        return child

    return node.transform(substitute)


# ....................... #


def _from_payload(node: Expression) -> Expression:
    """Rewrite bare bronze column references into ``raw`` extractions."""

    def rewritten(child: Expression) -> Expression:
        if isinstance(child, exp.Column) and not child.table:
            return exp.JSONExtractScalar(
                this=exp.column("raw"), expression=exp.Literal.string(f"$.{child.name}")
            )

        return child

    return node.transform(rewritten)


# ....................... #


def _entity_projections(entity: EntityIR, table: str) -> list[Expression]:
    """The entity's own columns, qualified — with any ``unknown_member`` fk
    rewritten to the reserved member (RFC 0016 §5.4), and ``_source`` on a
    merged entity.

    ``_source`` is a real column of the merged silver relation, not a stage
    detail: RFC 0024 D19 says provenance stays reachable because "a per-source
    view is a filter rather than a schema", and D18 reserves the name
    unconditionally so nothing can collide with it. It survived the P1
    pipeline by accident — a merged entity carried no rules, so the model was
    ``SELECT *`` over the union — and naming the columns for the first time is
    what made the accident visible.
    """
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

    if len(entity.sources) > 1:
        projections.append(exp.column(SOURCE_COLUMN, table=table))

    return projections


# ....................... #


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


# ....................... #


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


# ....................... #


def _require_unicode_normalize(entity: EntityIR, ctx: EmitContext) -> None:
    """Refuse a ``normalize`` rule the dialect cannot evaluate.

    The rule's whole content is the comparison against a normal form; there is
    no weaker reading of it. A dialect with no normalization would render
    ``NORMALIZE(...)`` — SQLGlot emits it verbatim for any generator — and the
    engine would fail at run time on a function it does not define, which is
    the "renders beautifully, aborts the run" shape RFC 0008 D3 refuses.
    """

    if not any(rule.kind == "normalize" for rule in entity.quality):
        return

    if ctx.dialect.supports(DialectFeature.UNICODE_NORMALIZE):
        return

    msg = (
        f"entity {entity.name!r} carries a normalize quality rule, which compares a value "
        f"against its Unicode normal form, but dialect {ctx.dialect.name!r} has no "
        "normalization function (RFC 0016 D86). Fix: compile this project for a dialect "
        "with one, or drop the normalize rules"
    )
    raise UnsupportedByTarget(msg, source_path=f"entity_model: entities.{entity.name}")


# ....................... #


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


# ....................... #


def _repair_projections(entity: EntityIR, *, arrays: bool) -> list[Expression]:
    """``_quality_repairs``, or nothing at all (RFC 0016 D87).

    The distinct marker D17 made a condition of the disposition landing:
    "repaired, now correct" and "currently flagged bad" are different facts, so
    ``has_quality_flags`` keeps meaning *currently suspect* and a repaired row
    is simply clean.

    A rule is recorded when its recipe **ran and worked** — it fired over the
    value as delivered (``_rep_…``, projected one level down) and no longer
    fires over the value that replaced it. A recipe that ran and failed leaves
    the rule violated, so the rule's ``fallback`` disposes of the row through
    the ordinary routing and this column stays silent about it: the row is not
    repaired, and saying so twice in two columns is how they come to disagree.

    Absent entirely on an entity with no repair rule, unlike the two universal
    columns — §12 budgeted the silver-schema churn once, and a third column
    that is empty for every project not using the feature is not worth
    re-opening every golden and fingerprint for.
    """
    repaired = [rule for rule in entity.quality if repairs(rule)]

    if not repaired:
        return []

    pairs = [
        (
            rule.name,
            exp.And(
                this=exp.column(repair_alias(rule), table=_EXTRACT_ALIAS),
                expression=grouped(exp.Not(this=grouped(verdict(rule, _EXTRACT_ALIAS)))),
            ),
        )
        for rule in repaired
    ]
    return [cast("Expression", exp.alias_(flags_expression(pairs, arrays=arrays), REPAIRS_COLUMN))]


# ....................... #


def _quality_pipeline(
    entity: EntityIR, ctx: EmitContext, extract: exp.Select | exp.Union
) -> exp.Select:
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
            *_repair_projections(entity, arrays=arrays),
        )
        .from_(extract.subquery(alias=_EXTRACT_ALIAS))
    )
    evaluated = _with_probes(evaluated, entity, ctx)
    kept = _route_predicate(entity, _EXTRACT_ALIAS, quarantined=False)

    if kept is not None:
        evaluated = evaluated.where(kept)

    carried = [column.name for column in entity.columns]

    if len(entity.sources) > 1:
        # Provenance is a column of the merged relation, not a stage detail
        # (RFC 0024 D18/D19) — see :func:`_entity_projections`. Carried here as
        # well because this is the *other* path to the same relation, and the
        # two disagreeing is a merged entity whose schema depends on whether it
        # declared a rule.
        carried.append(SOURCE_COLUMN)

    if _carries_metadata(entity):
        carried.extend(INGESTION_METADATA)

    return (
        exp.Select()
        .select(
            *(exp.column(name, table=_EVALUATED_ALIAS) for name in carried),
            exp.column(FLAGS_COLUMN, table=_EVALUATED_ALIAS),
            exp.alias_(quality_ok(table=_EVALUATED_ALIAS, arrays=arrays), OK_COLUMN),
            *(
                [exp.column(REPAIRS_COLUMN, table=_EVALUATED_ALIAS)]
                if any(repairs(rule) for rule in entity.quality)
                else []
            ),
        )
        .from_(evaluated.subquery(alias=_EVALUATED_ALIAS))
    )


# ....................... #


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
    _require_unicode_normalize(entity, ctx)
    extract = _extract_select(entity, ctx)

    if entity.quality:
        return _quality_pipeline(entity, ctx, extract)

    flags = exp.alias_(empty_flags(arrays=_arrays(ctx)), FLAGS_COLUMN)
    ok = exp.alias_(exp.true(), OK_COLUMN)

    if isinstance(extract, exp.Select):
        return extract.select(flags, ok)

    # A merged entity that declares no rules and no `dedupe:` — the union is
    # then the whole body, and the two generated columns ride one level above
    # it. ``.select()`` on a ``UNION`` would attach them to its last branch
    # alone, which parses and is wrong: the other branches would be short two
    # columns.
    return exp.Select().select(exp.Star(), flags, ok).from_(extract.subquery(alias=_EXTRACT_ALIAS))


# ....................... #


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
    _require_unicode_normalize(entity, ctx)
    arrays = _arrays(ctx)
    # `reject_id`, `source_relation`, `mapping` and `mapping_version` are
    # compile-time literals **of one branch** and are projected there
    # (RFC 0035 D2), so this level reads them by name like any other extract
    # column. One reject table per entity still (RFC 0016 D10): what became
    # N-way is the projection, not the relation.
    extract = _extract_select(entity, ctx, include_raw=True)
    recorded = _recorded_rules(entity)
    row_id = exp.column(ROW_ID_COLUMN, table=_EXTRACT_ALIAS)
    ingested = exp.column("_ingested_at", table=_EXTRACT_ALIAS)
    projections: list[Expression] = [
        *(exp.column(name, table=_EXTRACT_ALIAS) for name in _PROVENANCE_COLUMNS),
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
                    [(name, exp.column(name, table=_EXTRACT_ALIAS)) for name in sorted(entity.key)],
                    ctx,
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
        # NULL for the same reason ``resolved_at`` is, and for one more: this
        # column is *replay's* to write (D88), and a model query may not read a
        # clock at all without breaking §6's idempotence and
        # backfill-equivalence gates.
        cast(
            "Expression",
            exp.alias_(exp.cast(exp.null(), exp.DataType.build("TIMESTAMP")), "last_evaluated_at"),
        ),
    ]
    select = exp.Select().select(*projections).from_(extract.subquery(alias=_EXTRACT_ALIAS))
    select = _with_probes(select, entity, ctx)
    diverted = _route_predicate(entity, _EXTRACT_ALIAS, quarantined=True)

    if diverted is not None:  # pragma: no branch — a reject model implies one
        select = select.where(diverted)

    return select


# ....................... #


#: The merge aliases SQLMesh resolves inside a ``when_matched`` clause — its
#: documented spelling for "the row already there" and "the row arriving".
_MERGE_TARGET = "target"
_MERGE_SOURCE = "source"

#: The reject columns whose value on a re-delivery is the **existing** one, not
#: the arriving one (RFC 0016 §5.6). ``first_seen`` records when the problem
#: started; ``last_evaluated_at`` records a *replay* run, and the reject model
#: — which is the merge's source — projects it NULL because a model query may
#: not read a clock (D88). Without it here, a re-delivery would erase the
#: replay history of a row nobody replayed, which is the opposite of what a
#: re-delivery observed. Every other column describes the latest delivery.
_PRESERVED_ON_MERGE = frozenset({"first_seen", "last_evaluated_at"})

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


# ....................... #


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
    # Marked as ISO text (RFC 0027), which is what makes the question the same
    # question on every engine. Unmarked, this is a bare `TRY_CAST(text AS
    # TIMESTAMP)` — and Trino's cast does not accept the ISO `T` separator, so
    # `TRY_CAST('2026-01-06T12:00:00' AS TIMESTAMP)` is NULL there and the audit
    # reported *every* row as an uncastable timestamp. A blocking audit, so the
    # run stopped on correct data: the worst failure available to a generated
    # check (RFC 0024 D13). `parse_ts: ISO8601` already went through the marker;
    # this cast asks the same thing of the same text and did not.
    castable = exp.TryCast(this=iso_text(ingested.copy()), to=exp.DataType.build("TIMESTAMP"))
    return conjunction(
        [
            exp.Not(this=exp.Is(this=ingested, expression=exp.null())),
            exp.Is(this=castable, expression=exp.null()),
        ]
    )


# ....................... #


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


# ....................... #


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

#: The alias the metadata audit reads its windowed subquery under.
_METADATA_ALIAS = "_metadata"


def metadata_audit_select(
    entity: EntityIR, ctx: EmitContext, *, relation: str = THIS_MODEL
) -> exp.Select:
    """The D21 ingestion-metadata audit as a whole query.

    The duplicate-identity half of :func:`ingestion_audit_predicate` is a
    window count, and SQL forbids a window function in ``WHERE`` — so the body
    wraps the model once and filters over the projected count. Same
    arrangement SQLMesh's envelope has always had, as a tree rather than as
    template text, for the reason :func:`predicate_audit_select` gives.
    """
    # `PARTITION BY _source, _source_row_id` on a merged entity (RFC 0024 D34).
    # D21 makes the row identity unique within **one** source relation, so two
    # sources with ordinary per-table row sequences collide on the first run —
    # and this audit is blocking, which would stop the run on correct data.
    # That is the false refusal D13 names as the worst failure available to a
    # generated audit, and the one-word fix is this partition rather than a
    # weaker disposition.
    partition = [exp.column(ROW_ID_COLUMN)]

    if len(entity.sources) > 1:
        partition.insert(0, exp.column(SOURCE_COLUMN))

    counted = (
        exp.Select()
        .select(
            exp.Star(),
            cast(
                "Expression",
                exp.alias_(
                    exp.Window(this=exp.Count(this=exp.Star()), partition_by=partition),
                    ROW_ID_COUNT_COLUMN,
                ),
            ),
        )
        .from_(_this_model(alias="", relation=relation))
    )
    return (
        exp.Select()
        .select(exp.Star())
        .from_(counted.subquery(alias=_METADATA_ALIAS))
        .where(ingestion_audit_predicate(entity, ctx))
    )


# ....................... #


def _this_model(alias: str = "", relation: str = THIS_MODEL) -> exp.Table:
    """``<relation> AS <alias>``, with the relation left unquoted.

    An empty alias means unaliased — the shape a whole-query audit uses, whose
    predicate names columns without qualifying them.

    ``exp.table_`` would quote it — ``@`` is not an identifier character — and
    a quoted macro is a table named ``@this_model``, which does not exist. A
    dbt ``{{ ref('…') }}`` needs exactly the same treatment for exactly the
    same reason, which is why one function spells both.

    The default is SQLMesh's macro because that is the older of the two and
    every existing caller means it. A target whose audits attach by reference
    passes its own spelling (RFC 0026 D10), so the body is built with it from
    the start — the alternative, emitting ``@this_model`` and rewriting the
    finished file, is the substitution D10 refuses.
    """

    return exp.Table(this=exp.to_identifier(relation, quoted=False), alias=alias)


# ....................... #


def _summed(counts: Iterable[Expression]) -> Expression:
    """``a + b + …``, folded left — one term on a single-source entity, so the
    ordinary case renders exactly as it did."""
    folded: Expression | None = None

    for count in counts:
        folded = count if folded is None else exp.Add(this=folded, expression=count)

    return guaranteed(
        (folded,) if folded is not None else (),
        expected="at least one relation to count",
        by="every mapped entity having at least one source (resolve.build)",
    )


# ....................... #


def _count_of(relation: Expression) -> Expression:
    return exp.Subquery(this=exp.Select().select(exp.Count(this=exp.Star())).from_(relation))


# ....................... #


def _counted_as(predicate: Expression, name: str) -> Expression:
    """``SUM(CASE WHEN <predicate> THEN 1 ELSE 0 END) AS <name>``."""
    case = exp.Case(
        ifs=[exp.If(this=predicate, true=exp.Literal.number(1))], default=exp.Literal.number(0)
    )
    return cast("Expression", exp.alias_(exp.Sum(this=case), name))


# ....................... #


#: The column the collision audit projects its per-key source count under.
COLLISION_COUNT_COLUMN = "sources"


def collision_audit(entity: EntityIR) -> bool:
    """Whether a merged entity's key-collision audit is emitted (RFC 0024 D5).

    Merged entities only, not every mapped one. Emitting it unconditionally
    would make the artifact set uniform and cost a scan per entity for a check
    that cannot fire — a single-source entity has one value of ``_source``, so
    ``COUNT(DISTINCT _source) > 1`` is false by construction — and it would
    also need a ``_source`` column on every relation to group by, which D7
    refuses for the same reason it refuses the uniform column.
    """

    return len(entity.sources) > 1


# ....................... #


def collision_audit_select(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The disjointness law as a **runtime** audit (RFC 0024 §5.4, D5, D13).

    The compiler has no data, so it cannot know two sources' key sets are
    disjoint. This is the run-time half of that split, and it is the same split
    ``dedupe`` and ``referential`` already live with::

        SELECT <key…>, COUNT(DISTINCT _source) AS sources
        FROM (<the union of every branch>)
        GROUP BY <key…>
        HAVING COUNT(DISTINCT _source) > 1

    **Grouped by every declared key column**, generated from ``entity.key``.
    The single-column form §5.4 illustrates is one instance and not the spec: a
    composite key grouped by its first column alone merges distinct keys and
    blocks valid data, which on a blocking audit is the worst failure available
    (D13).

    **It reads the union stage, not the model**, which is D13 verbatim. Dedupe
    is precisely the operation that collapses rows sharing an entity key, so an
    audit below it would be reading the one relation guaranteed not to contain
    what it looks for: two sources colliding on a key are two rows the
    ``QUALIFY`` keeps one of, and a model-reading audit would then find one
    ``_source`` per key and pass. P1 could read the model because ``dedupe:``
    was refused on a merged entity and nothing between the union and the output
    collapsed anything; P2b restores the block and with it the distinction.

    Reading the union rather than a materialized stage costs a second scan of
    bronze. The alternative is emitting the union as its own relation for every
    merged entity — a model an operator did not ask for, in the layer their
    lineage tools read — which is a larger price for the same check.

    ``COUNT(DISTINCT _source) > 1`` deliberately does **not** fire on a key
    duplicated *within* one source: that is ordinary duplication and ``dedupe:``
    already owns it.
    """
    # ``COUNT(DISTINCT …)`` is an ``exp.Distinct`` *inside* the count, not a
    # keyword argument on it: ``exp.Count(distinct=True)`` is silently ignored
    # and renders a plain ``COUNT``, which would fire on a key duplicated
    # within one source — ordinary duplication that ``dedupe:`` owns and that
    # D5 says this audit must never refuse.
    distinct_sources = exp.Count(this=exp.Distinct(expressions=[exp.column(SOURCE_COLUMN)]))
    return (
        exp.Select()
        .select(
            *(exp.column(column) for column in entity.key),
            cast("Expression", exp.alias_(distinct_sources, COLLISION_COUNT_COLUMN)),
        )
        .from_(union_stage(entity, ctx).subquery(alias=_ENTITY_ALIAS))
        .group_by(*(exp.column(column) for column in entity.key))
        .having(exp.GT(this=distinct_sources.copy(), expression=exp.Literal.number(1)))
    )


# ....................... #


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


# ....................... #


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
    # Summed over every branch (RFC 0035): the law is "bronze rows = surviving
    # + diverted", and a merged entity's bronze side is every relation it reads.
    bronze_relations = [
        exp.table_(relation, db=namespace)
        for namespace, relation in (
            ctx.naming.relation(origin.relation, Layer.BRONZE) for origin in entity.sources
        )
    ]
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
                exp.alias_(_summed(_count_of(table) for table in bronze_relations), "bronze_rows"),
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


# ....................... #


def fail_audits(
    entity: EntityIR, ctx: EmitContext, *, relation: str = THIS_MODEL
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
    _require_unicode_normalize(entity, ctx)
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
            .from_(_this_model(_ENTITY_ALIAS, relation))
            .where(
                flag_member(exp.column(FLAGS_COLUMN, table=_ENTITY_ALIAS), rule.name, arrays=arrays)
            )
        )
        audits.append((f"{entity.name}_{rule.name}", exp.union(evaluated, stored)))

    return tuple(audits)


# ....................... #


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

    merged = len(entity.sources) > 1

    if entity.dedupe is not None:
        return with_dedupe_qualify(select, entity.dedupe, entity.key, merged=merged)

    # The no-``dedupe:`` form of the total order is its final sort key alone
    # (D20): the stable source-row identity, which D21 guarantees exists and is
    # unique on any entity with a reject table — within **one** source
    # relation, which is why a merged entity puts ``_source`` ahead of it here
    # exactly as the dedupe order does (RFC 0024 D35). Without it two rejected
    # rows from different sources on one key compare equal and replay's winner
    # is undefined.
    tail = [ROW_ID_COLUMN] if not merged else [SOURCE_COLUMN, ROW_ID_COLUMN]
    winner = exp.EQ(
        this=exp.Window(
            this=exp.RowNumber(),
            partition_by=[exp.column(name) for name in entity.key],
            order=exp.Order(
                expressions=[
                    exp.Ordered(this=exp.column(name), desc=True, nulls_first=False)
                    for name in tail
                ]
            ),
        ),
        expression=exp.Literal.number(1),
    )
    qualified = select.copy()
    qualified.set("qualify", exp.Qualify(this=winner))

    return qualified


# ....................... #


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


# ....................... #


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


# ....................... #


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

    On a merged entity the order carries ``_source`` (RFC 0024 D35) — the same
    order, because replay's whole correctness argument is that it re-derives
    the winner the pipeline would have picked, and an order that differed here
    would pick a different one.
    """
    merged = len(entity.sources) > 1
    order = dedupe_order(entity.dedupe, table=table, merged=merged) if entity.dedupe else ()
    return [term.this for term in order] or [exp.column(ROW_ID_COLUMN, table=table)]


# ....................... #


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


# ....................... #


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
       identical winners. The comparison is :func:`_candidate_wins` — read it
       before changing it. It is deliberately **not** a row constructor over
       ``dedupe_order``'s columns, which is what this sentence used to
       describe and what D74 refutes: row comparison orders NULL as the
       largest value, the inverse of ``DESC NULLS LAST``, and null ordering
       here is *not* the D21 audit's job (D21 covers ``_source_row_id`` and
       ``_ingested_at``, never a mapped ``dedupe.field``).
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

    **``last_evaluated_at`` is the other clock — the engine's** (D88). D70
    named it as the escape hatch for what that decision gave up, and this is
    it: statements 2 and 3 both stamp it, so it reads "when replay last looked
    at this row" for every row in the table rather than for the unresolved
    ones only. It is safe to advance precisely because **retention never reads
    it** — unresolved rows age from ``last_seen``, resolved ones from
    ``resolved_at``, and neither is touched here. The two statements are
    disjoint by ``resolved_at IS NULL``, so a row is stamped exactly once per
    run; on the resolving branch it is a second ``CURRENT_TIMESTAMP`` beside
    ``resolved_at`` rather than a copy of it, so the two may differ by however
    long the statement takes on engines that do not pin a transaction clock.

    The resolution stamp reads the **executing engine's** clock
    (``CURRENT_TIMESTAMP``) — bloomery never reads a clock (RFC 0003), it emits
    the statements and the caller runs them. The reject row is kept as audit
    history; retention, never replay, is what deletes it.
    """
    entity_namespace, entity_relation = ctx.naming.relation(entity.name, Layer.SILVER)
    reject_namespace, reject_rel = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    columns = [
        *(column.name for column in entity.columns),
        # A merged entity's relation carries provenance, so the MERGE has to
        # write it — and `_candidate_wins` compares by it (RFC 0024 D35), which
        # a source that did not project it could not answer.
        *((SOURCE_COLUMN,) if len(entity.sources) > 1 else ()),
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
        expressions=[
            exp.EQ(this=exp.column("resolved_at"), expression=exp.CurrentTimestamp()),
            exp.EQ(this=exp.column("last_evaluated_at"), expression=exp.CurrentTimestamp()),
        ],
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
                            ),
                            exp.EQ(
                                this=exp.column("last_evaluated_at"),
                                expression=exp.CurrentTimestamp(),
                            ),
                        ]
                    ),
                )
            ]
        ),
    )
    return (merge, resolve, still_failing)
