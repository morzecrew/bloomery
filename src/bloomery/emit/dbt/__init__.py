"""The dbt emitter (RFC 0008 §5.5) — the compatibility target.

Its real job is proving the port abstraction (RFC 0008 D5, spec §9): it ships
minimal but honest, and every SELECT is the **same** dialect-port-rendered
AST the SQLMesh emitter renders (:mod:`bloomery.emit.lowering`) — only the
envelope differs. Do not read it as production-grade dbt scaffolding.

Artifacts:

- ``dbt_project.yml`` — the scaffold, so ``dbt parse`` has a project.
- ``models/sources.yml`` — every bronze relation the entities read, grouped
  by bronze namespace under the naming policy.
- ``models/<silver_ns>/<entity>.sql`` per SCD type 1 entity, with a
  ``{{ config(...) }}`` header. Materialization maps honestly: ``full`` →
  ``table``; both incremental kinds → ``incremental`` with the entity key as
  ``unique_key`` — dbt has no native time-range kind, and merge-on-key is the
  equivalent that can never silently duplicate rows (RFC 0008 D3: adapt
  loudly-documented, never degrade silently).
- ``snapshots/<entity>_snapshot.sql`` per SCD type 2 entity — dbt's native
  SCD2. Strategy is ``check`` over all columns (``check_cols: all``): the IR
  declares no updated-at marker, so a ``timestamp`` strategy would invent
  one. A composite-key SCD2 entity raises
  :class:`~bloomery.errors.UnsupportedByTarget` — dbt snapshot ``unique_key``
  is a single expression, and concatenating key parts would be a silent
  approximation. The snapshot **replaces** the silver model: dbt builds the
  history table directly at ``<silver_ns>.<entity>_snapshot``.
- ``models/<gold_ns>/<mart>.sql`` per mart and the ``dim_date`` calendar —
  the same gold SELECTs SQLMesh emits.
- ``models/<namespace>/<relation>.sql`` per Tier 2 step output (RFC 0017 D52) —
  the same SELECT SQLMesh emits, in a ``config(materialized='table')`` envelope.
  Tier 1 needs nothing (spliced at lowering); Tier 3 is refused, because dbt's
  Python models run only on adapters bloomery does not target.
- ``models/schema.yml`` — audits lowered to schema tests (RFC 0006 →
  RFC 0008 §5.5, §10 → D16): ``not_null`` and ``enum``/``accepted_values``
  builtin, because dbt-core has a native test meaning exactly that clause;
  ``min``/``max``/``regex``/``reconcile`` as ``bloomery_expression_is_true``
  tests whose row-level assertion is the shared audit predicate rendered
  through the dialect port, because dbt-core has none. SCD type 2
  entities' tests attach under ``snapshots:``. An audit kind with no honest
  test mapping raises :class:`~bloomery.errors.UnsupportedByTarget` naming
  the entity and kind — fail loud, never approximate (RFC 0008 D3).
- ``macros/bloomery_expression_is_true.sql`` — the generic test the above
  names, emitted iff ``schema.yml`` declares it (RFC 0008 D18). bloomery's
  own rather than ``dbt_utils``': a package reference leaves the emitted
  project *incomplete*, declaring a test no ``dbt compile`` can build until
  someone runs ``dbt deps`` against the network — which is the opposite of a
  compiler whose output is a pure function of its input.
"""

from __future__ import annotations

import jinja2
import yaml

from bloomery.emit.base import (
    ArtifactKind,
    EmitContext,
    EmittedArtifact,
    Feature,
    TargetCapabilities,
)
from bloomery.emit.lowering import (
    audit_predicate,
    column_type,
    dim_date_select,
    entity_select,
    mart_select,
)
from bloomery.emit.steps import (
    refuse_coverage,
    refuse_mart_asserts,
    refuse_python_models,
    refuse_step_audits,
    step_body,
    step_output_relation,
)
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import (
    AuditIR,
    DateDimensionIR,
    EntityIR,
    Layer,
    MartIR,
    Materialization,
    ProjectIR,
    SCDKind,
    StepKind,
)
from bloomery.quality import is_quality_mart
from bloomery.typing import IntType

__all__ = [
    "DbtEmitter",
]

#: The custom audit kinds that lower to :data:`_EXPRESSION_TEST`.
_EXPRESSION_KINDS = frozenset({"min", "max", "regex", "reconcile"})

#: The generic test carrying the shared audit predicate on the dbt side, and
#: the name of the macro file that defines it. bloomery's own rather than
#: ``dbt_utils``' (RFC 0008 D18): a package reference makes the emitted project
#: incomplete — it declares a test no ``dbt compile`` can build until someone
#: runs ``dbt deps`` against the network.
_EXPRESSION_TEST = "bloomery_expression_is_true"

# The macro body is dbt-Jinja that must reach the file *verbatim*, so it is a
# plain literal: a template would consume the very braces this exists to emit,
# and interpolating the name above would be one more escaping layer to get
# wrong. The name is therefore spelled twice; a mismatch is not a silent
# defect, because the schema entry would then reference a macro the project
# does not define and `dbt compile` refuses that outright (RFC 0008 D19).
#
# The body is ``dbt_utils``' ``default__test_expression_is_true`` minus the
# ``column_name`` branch bloomery never takes, so the semantics of the test it
# replaces are preserved exactly — including that a NULL expression *passes*,
# since ``NOT NULL`` is NULL and selects no row. That is RFC 0016 D19's Kleene
# discipline, reached from dbt's side.
_EXPRESSION_TEST_MACRO = """\
{% test bloomery_expression_is_true(model, expression) %}
SELECT *
FROM {{ model }}
WHERE NOT ({{ expression }})
{% endtest %}
"""

# The envelope sees pre-rendered strings only (RFC 0008 D4) — the config
# header is built in Python, the SELECT arrives through the dialect port.
# SQL is not HTML: autoescaping would corrupt it (cf. the SQLMesh envelope).
_MODEL_ENVELOPE = jinja2.Template(  # nosec B701
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
{{ config_line }}

{{ select }}
""",
    autoescape=False,
)

# The dbt-Jinja block markers are pre-rendered strings too — this template
# never nests Jinja inside Jinja.
_SNAPSHOT_ENVELOPE = jinja2.Template(  # nosec B701
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
{{ open_line }}
{{ config_line }}

{{ select }}

{{ close_line }}
""",
    autoescape=False,
)


def _header(ctx: EmitContext) -> str:
    return f"# Generated by bloomery — do not edit.\n# fingerprint: {ctx.fingerprint}\n"


def _yaml(document: dict[str, object]) -> str:
    """Byte-stable YAML: deterministic insertion order (``sort_keys`` would
    shuffle ``name`` below ``schema``), block style, pinned width."""
    return yaml.safe_dump(
        document, sort_keys=False, default_flow_style=False, width=100, allow_unicode=True
    )


def _unique_key(key: tuple[str, ...]) -> str:
    if len(key) == 1:
        return f"unique_key='{key[0]}'"
    members = ", ".join(f"'{part}'" for part in key)
    return f"unique_key=[{members}]"


def _config_line(materialization: Materialization, key: tuple[str, ...]) -> str:
    if materialization is Materialization.FULL:
        return "{{ config(materialized='table') }}"
    return f"{{{{ config(materialized='incremental', {_unique_key(key)}) }}}}"


def _refuse_quarantine(entity: EntityIR) -> None:
    """dbt has no reject/replay lowering in this wave (RFC 0016 §5.4).

    Target coverage is stated honestly rather than approximated: SQLMesh emits
    the full quality set (split models, reject tables, replay merge), and dbt
    raises here for the reject/replay artifacts — the port-proof scope
    (RFC 0008 §5.5, D3: fail loud, never degrade silently). Flag-only quality
    surfaces still emit, because ``_quality_flags`` is the *same* shared
    SELECT both targets render.
    """
    if entity.quarantine is None:
        return
    msg = (
        f"entity {entity.name!r} declares a quarantine policy, which needs the "
        f"{entity.name}__reject model and its replay merge (RFC 0016 §5.6); the dbt "
        "emitter lowers neither in this wave — it is the compatibility target, minimal "
        "but honest (RFC 0008 §5.5). Fix: compile this project for the sqlmesh target, or "
        "reduce the entity's rules to flag dispositions"
    )
    raise UnsupportedByTarget(msg, source_path=f"entity_model: entities.{entity.name}.quarantine")


def _refuse_reconcile(ir: ProjectIR) -> None:
    """dbt lowers no reconcile artifacts in this wave (RFC 0016 D58).

    A second, *separate* claim from ``_refuse_quarantine`` above, and it needed
    its own decision row: §5.4's target-coverage sentence authorized dbt's
    refusal only for the reject/replay artifacts, so refusing ``reconcile:``
    under the same sentence was scope the RFC never granted. D58 grants it, on
    this argument — a reconcile check is a model *and* a **non-blocking** audit,
    and dbt's test surface has no non-blocking equivalent that would not
    silently turn "report the disagreement" into "fail the build" (RFC 0008 D3:
    fail loud, never degrade silently). Refusing names the target that does.
    """
    if not ir.reconcile:
        return
    names = ", ".join(check.name for check in ir.reconcile)
    msg = (
        f"project declares reconcile check(s) {names}, which lower to a model plus a "
        "non-blocking audit (RFC 0016 §5.3); the dbt emitter lowers neither in this wave, "
        "and has no non-blocking test to approximate the audit with — it is the "
        "compatibility target, minimal but honest (RFC 0008 §5.5, RFC 0016 D58). Fix: "
        "compile this project for the sqlmesh target, or drop the reconcile block"
    )
    raise UnsupportedByTarget(msg, source_path="entity_model: reconcile")


def _step_artifacts(ir: ProjectIR, ctx: EmitContext) -> list[EmittedArtifact]:
    """Tier 2 step outputs as dbt models (RFC 0017 D52).

    ``sql_macro`` contributes nothing here for the same reason it contributes
    nothing to SQLMesh — it was spliced into the consuming SELECT at lowering,
    so it is already inside whichever model reads it, on every target. Tier 3
    is refused before this runs.

    Materialized ``table``, matching the ``FULL`` the SQLMesh wrapper declares:
    a step writes its whole output, and an IR that means one thing on one
    target and another on the next is the drift the shared lowering exists to
    prevent.
    """
    artifacts: list[EmittedArtifact] = []
    for step in ir.steps:
        if step.kind is not StepKind.SQL_MODEL:
            continue
        for output in step.outputs:
            namespace, relation = step_output_relation(output, ctx)
            artifacts.append(
                _model_artifact(
                    path=f"models/{namespace}/{relation}.sql",
                    config_line=_config_line(Materialization.FULL, output.key),
                    select=ctx.dialect.render(step_body(step)),
                    ctx=ctx,
                )
            )
    return artifacts


def _model_artifact(
    *, path: str, config_line: str, select: str, ctx: EmitContext
) -> EmittedArtifact:
    content = _MODEL_ENVELOPE.render(
        fingerprint=ctx.fingerprint, config_line=config_line, select=select
    )
    return EmittedArtifact.create(
        path=path, content=content.rstrip("\n") + "\n", kind=ArtifactKind.MODEL
    )


def _snapshot_artifact(entity: EntityIR, ctx: EmitContext) -> EmittedArtifact:
    if len(entity.key) != 1:
        msg = (
            f"entity {entity.name!r} is SCD type 2 with composite key "
            f"({', '.join(entity.key)}) — dbt snapshot unique_key takes a single "
            "expression, and concatenating key parts would be a silent approximation "
            "(feature: scd_type_2)"
        )
        raise UnsupportedByTarget(msg)
    namespace, _relation = ctx.naming.relation(entity.name, Layer.SILVER)
    config_line = (
        f"{{{{ config(target_schema='{namespace}', unique_key='{entity.key[0]}', "
        "strategy='check', check_cols='all') }}"
    )
    content = _SNAPSHOT_ENVELOPE.render(
        fingerprint=ctx.fingerprint,
        open_line=f"{{% snapshot {entity.name}_snapshot %}}",
        close_line="{% endsnapshot %}",
        config_line=config_line,
        select=ctx.dialect.render(entity_select(entity, ctx)),
    )
    return EmittedArtifact.create(
        path=f"snapshots/{entity.name}_snapshot.sql",
        content=content.rstrip("\n") + "\n",
        kind=ArtifactKind.MODEL,
    )


def _dim_date_artifact(dim: DateDimensionIR, ctx: EmitContext) -> EmittedArtifact:
    namespace, _mart_relation = ctx.naming.relation(dim.name, Layer.GOLD)
    return _model_artifact(
        path=f"models/{namespace}/{dim.name}.sql",
        config_line="{{ config(materialized='table') }}",
        select=ctx.dialect.render(dim_date_select(dim)),
        ctx=ctx,
    )


def _mart_artifact(mart: MartIR, ir: ProjectIR, ctx: EmitContext) -> EmittedArtifact:
    namespace, relation = ctx.naming.relation(mart.name, Layer.GOLD)
    if is_quality_mart(mart):
        # RFC 0016 §5.4 puts the quality mart in **SQLMesh's** set, and it is
        # built from the surfaces dbt already refuses: the reject tables and
        # the reconcile models. Counting rows in tables this target does not
        # build would be a mart of zeroes — the silent degradation RFC 0008 D3
        # exists to prevent. In practice the two refusals below fire first
        # (the mart cannot exist without quality rules or a reconcile block);
        # this is the branch that keeps that true if either ever narrows.
        msg = (
            "the data-quality mart (RFC 0016 §5.8) counts rule evaluations over the reject "
            "tables and reconcile models, neither of which the dbt emitter lowers in this "
            "wave — it is the compatibility target, minimal but honest (RFC 0008 §5.5). "
            "Fix: compile this project for the sqlmesh target"
        )
        raise UnsupportedByTarget(msg, source_path="entity_model: quality")
    base = next(entity for entity in ir.entities if entity.name == mart.base)
    return _model_artifact(
        path=f"models/{namespace}/{relation}.sql",
        config_line=_config_line(mart.materialization, base.key),
        select=ctx.dialect.render(mart_select(mart, ctx)),
        ctx=ctx,
    )


# ....................... #
# Audit lowering → schema.yml (RFC 0006 → RFC 0008 §5.5)


def _accepted_values(entity: EntityIR, audit: AuditIR) -> dict[str, object]:
    member_type = column_type(entity, audit.column)
    values: list[object] = [
        int(value) if isinstance(member_type, IntType) else value for _name, value in audit.params
    ]
    return {"accepted_values": {"values": values}}


def _entity_tests(
    entity: EntityIR, ctx: EmitContext
) -> tuple[dict[str, list[object]], list[object]]:
    """The per-column tests (column → test list) and the model-level
    expression tests for one entity, in the deterministic ``EntityIR.audits``
    order (sorted by kind, column)."""
    column_tests: dict[str, list[object]] = {}
    model_tests: list[object] = []
    for audit in entity.audits:
        if audit.kind == "not_null":
            column_tests.setdefault(audit.column, []).append("not_null")
        elif audit.kind == "enum":
            column_tests.setdefault(audit.column, []).append(_accepted_values(entity, audit))
        elif audit.kind in _EXPRESSION_KINDS:
            expression = ctx.dialect.render(audit_predicate(entity, audit, violations=False))
            model_tests.append({_EXPRESSION_TEST: {"expression": expression}})
        else:
            msg = (
                f"entity {entity.name!r} audit kind {audit.kind!r} on column "
                f"{audit.column!r} has no honest dbt schema-test mapping "
                "(feature: audits) — refusing rather than approximating (RFC 0008 D3)"
            )
            raise UnsupportedByTarget(msg)
    return column_tests, model_tests


def _schema_entry(entity: EntityIR, name: str, ctx: EmitContext) -> dict[str, object]:
    column_tests, model_tests = _entity_tests(entity, ctx)
    entry: dict[str, object] = {"name": name}
    if model_tests:
        entry["data_tests"] = model_tests
    if column_tests:
        entry["columns"] = [
            {"name": column, "data_tests": tests} for column, tests in sorted(column_tests.items())
        ]
    return entry


def _schema_artifact(ir: ProjectIR, ctx: EmitContext) -> EmittedArtifact | None:
    models: list[object] = []
    snapshots: list[object] = []
    for entity in ir.entities:  # sorted by name on ProjectIR
        if not entity.audits:
            continue
        if entity.scd is SCDKind.TYPE2:
            snapshots.append(_schema_entry(entity, f"{entity.name}_snapshot", ctx))
        else:
            _namespace, relation = ctx.naming.relation(entity.name, Layer.SILVER)
            models.append(_schema_entry(entity, relation, ctx))
    if not models and not snapshots:
        return None
    document: dict[str, object] = {"version": 2}
    if models:
        document["models"] = models
    if snapshots:
        document["snapshots"] = snapshots
    return EmittedArtifact.create(
        path="models/schema.yml",
        content=_header(ctx) + _yaml(document),
        kind=ArtifactKind.CONFIG,
    )


def _sources_artifact(ir: ProjectIR, ctx: EmitContext) -> EmittedArtifact | None:
    relations_by_namespace: dict[str, set[str]] = {}
    for entity in ir.entities:
        namespace, relation = ctx.naming.relation(entity.source.relation, Layer.BRONZE)
        relations_by_namespace.setdefault(namespace, set()).add(relation)
    if not relations_by_namespace:
        return None
    document: dict[str, object] = {
        "version": 2,
        "sources": [
            {
                "name": namespace,
                "schema": namespace,
                "tables": [{"name": table} for table in sorted(tables)],
            }
            for namespace, tables in sorted(relations_by_namespace.items())
        ],
    }
    return EmittedArtifact.create(
        path="models/sources.yml",
        content=_header(ctx) + _yaml(document),
        kind=ArtifactKind.CONFIG,
    )


def _expression_macro_artifact(ctx: EmitContext) -> EmittedArtifact:
    """The generic test the ``min``/``max``/``regex``/``reconcile`` audits
    name. :data:`ArtifactKind.AUDIT` rather than ``CONFIG``: it is the custom
    audit *body* for this target, the exact counterpart of the
    ``audits/<name>.sql`` file the SQLMesh emitter writes for the same three
    kinds — and, like it, built from :func:`audit_predicate` so the two targets
    cannot drift (RFC 0008 D16)."""
    return EmittedArtifact.create(
        path=f"macros/{_EXPRESSION_TEST}.sql",
        content=(
            "-- Generated by bloomery — do not edit.\n"
            f"-- fingerprint: {ctx.fingerprint}\n{_EXPRESSION_TEST_MACRO}"
        ),
        kind=ArtifactKind.AUDIT,
    )


def _project_artifact(ctx: EmitContext) -> EmittedArtifact:
    document: dict[str, object] = {
        "name": "bloomery",
        "version": "1.0.0",
        "profile": "bloomery",
        "model-paths": ["models"],
        "snapshot-paths": ["snapshots"],
        # Declared though it matches dbt's default, exactly as `model-paths`
        # and `snapshot-paths` above are: the emitted project states its own
        # layout rather than inheriting one that a later dbt could change.
        "macro-paths": ["macros"],
    }
    return EmittedArtifact.create(
        path="dbt_project.yml",
        content=_header(ctx) + _yaml(document),
        kind=ArtifactKind.CONFIG,
    )


class DbtEmitter:
    """RFC 0008 §5.5: the port-abstraction proof (RFC 0008 D5) — same
    lowered SELECTs as SQLMesh, dbt envelopes, honest capability answers."""

    name = "dbt"

    def capabilities(self) -> TargetCapabilities:
        """Declared support per RFC 0008 §5.1 (amended D6): dbt builds the
        same silver/gold tables SQLMesh does — SCD type 2 (lowered to a
        snapshot), variant columns, incrementality (merge-on-key), audits
        (schema tests), and all additivity features."""
        return TargetCapabilities(
            supported=frozenset(
                {
                    Feature.SCD_TYPE_2,
                    Feature.VARIANT_COLUMN,
                    Feature.INCREMENTAL,
                    Feature.AUDITS,
                    Feature.SEMI_ADDITIVE,
                    Feature.NON_ADDITIVE,
                    Feature.CUMULATIVE,
                    Feature.DERIVED_METRIC,
                }
            )
        )

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]:
        """Lower every entity to a model (SCD type 2 → snapshot), every mart
        and the date dimension to gold models, audits to ``schema.yml``, plus
        the project scaffold and bronze sources; artifacts sorted by path,
        content ending in exactly one newline (RFC 0003 §5.5 rule 5)."""
        refuse_python_models(ir, "dbt")
        refuse_step_audits(ir, ctx, "dbt")
        refuse_mart_asserts(ir, "dbt")
        refuse_coverage(ir, "dbt")
        _refuse_reconcile(ir)
        artifacts: list[EmittedArtifact] = [_project_artifact(ctx), *_step_artifacts(ir, ctx)]
        for entity in ir.entities:
            # A step output is an entity in the DAG (RFC 0017 D36) but its rows
            # are the step's to write, and its lowered `expr` is the column
            # referring to itself — emitting the ordinary entity model here
            # would produce a model selecting from the relation it defines.
            if entity.produced_by is not None:
                continue
            _refuse_quarantine(entity)
            if entity.scd is SCDKind.TYPE2:
                artifacts.append(_snapshot_artifact(entity, ctx))
                continue
            namespace, relation = ctx.naming.relation(entity.name, Layer.SILVER)
            artifacts.append(
                _model_artifact(
                    path=f"models/{namespace}/{relation}.sql",
                    config_line=_config_line(entity.materialization, entity.key),
                    select=ctx.dialect.render(entity_select(entity, ctx)),
                    ctx=ctx,
                )
            )
        artifacts.extend(_mart_artifact(mart, ir, ctx) for mart in ir.marts)
        if ir.date_dimension is not None:
            artifacts.append(_dim_date_artifact(ir.date_dimension, ctx))
        schema = _schema_artifact(ir, ctx)
        for optional in (schema, _sources_artifact(ir, ctx)):
            if optional is not None:
                artifacts.append(optional)
        # Emitted iff the schema actually names it. Deriving the condition from
        # the emitted bytes rather than re-deriving it from the IR is what keeps
        # the two in step: any future entity filter that changes which tests are
        # written changes this with it, and a project can neither declare the
        # test without the macro nor carry the macro unused.
        if schema is not None and _EXPRESSION_TEST in schema.content:
            artifacts.append(_expression_macro_artifact(ctx))
        return tuple(sorted(artifacts, key=lambda a: a.path))
