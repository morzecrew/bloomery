"""The dbt emitter (RFC 0008 §5.5) — the compatibility target.

**Compatible with dbt ``>=1.10.8,<2``** (RFC 0008 D22). Stated because "the
compatibility target" had never said compatible with *what*: the emitted
``schema.yml`` nests generic-test arguments under ``arguments``, so the range
and the emitted form are one decision.

The floor is where dbt makes that nesting the **default**, not where the
property arrived — and that boundary is not a minor version. 1.9 rejects the
nested form outright, and so do 1.10.0–1.10.7: through 1.10.7 it needs the
``require_generic_test_arguments_property`` behaviour flag, and without it dbt
passes ``arguments`` to the macro as a literal keyword. Measured rather than
read off a changelog: the matrix lives in ``tests/unit/test_emit/test_dbt.py``
beside the test that pins the emitted form, and covers six real installs from
1.9.10 to 1.12.0 — including the pair that locates the boundary: 1.10.7, the
last release that rejects the nested form without the flag, and 1.10.8, the
first that accepts it without one. ``pyproject.toml`` carries the same bound.
An earlier version of this line said ``>=1.10``, which admits the seven
patch releases that reject what this emitter writes.


Its real job is proving the port abstraction (RFC 0008 D5, spec §9): every
SELECT is the **same** dialect-port-rendered AST the SQLMesh emitter renders
(:mod:`bloomery.emit.lower`) — only the envelope and the way inputs are *named*
differ. Do not read it as production-grade dbt scaffolding.

It used to say "minimal but honest", which was RFC 0008 §5.5's sentence about an
emitter that produced no audits whatsoever. RFC 0026 gave it the whole audit
surface and RFC 0052 the whole data-quality one, so the coverage claim is now
the artifact list below plus two refusals: ``python_model`` steps, and
``on_fail: quarantine`` on a *step output* — the second on every target, and
unrelated to the entity-level ``quarantine:`` that this emitter now lowers.

That last qualifier is D20's. A dbt model states its inputs as ``ref()`` and
``source()`` rather than as literal relations, because a project without those
edges is one dbt cannot order — so the lowered AST is rendered through
:func:`_render`, which rewrites table nodes and touches nothing else. D5's
claim survives it exactly: resolve the references and the two targets' SQL is
identical, which is the tighter statement of "no lowering is duplicated".

Artifacts:

- ``dbt_project.yml`` — the scaffold, plus one ``+schema`` per model
  directory so each relation materializes where the naming policy put it.
- ``macros/generate_schema_name.sql`` — the override making ``+schema`` mean
  the namespace verbatim rather than dbt's default ``<target>_<custom>``
  (RFC 0008 D20). Without it ``ref()`` really would cost the naming port its
  ownership of namespaces, which is the objection RFC 0009 D22 raised.
- ``models/sources.yml`` — every bronze relation the entities read, grouped
  by bronze namespace under the naming policy. Sources do not pass through
  ``generate_schema_name``, so their namespace was always the policy's.
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
  entities' tests attach under ``snapshots:``. Native tests stay preferred
  where dbt has one (RFC 0026 D4) — a builtin names its column in ``dbt test``
  output and appears in ``dbt docs``, and a hand-rolled query does neither.
- ``tests/<audit>.sql`` — a **singular test** per check that groups, joins or
  aggregates (RFC 0026): a ``.sql`` file whose query returns the rows that
  fail, which is dbt's own artifact for a check that is not a row predicate.
  Its model reference goes through the same reference map every model body
  does, so the test participates in dbt's DAG rather than naming a table by
  accident. **On dbt these run under ``dbt build``, not ``dbt run``** — the
  operator contract in ``pages/docs/how-to/emit-dbt.md`` states it, along with
  the mirror case that ``--warn-error`` promotes a flagging check.
- ``macros/bloomery_expression_is_true.sql`` — the generic test the above
  names, emitted iff ``schema.yml`` declares it (RFC 0008 D18). bloomery's
  own rather than ``dbt_utils``': a package reference leaves the emitted
  project *incomplete*, declaring a test no ``dbt compile`` can build until
  someone runs ``dbt deps`` against the network — which is the opposite of a
  compiler whose output is a pure function of its input.
- ``models/<silver_ns>/<entity>__reject.sql`` per quarantining entity
  (RFC 0052 §5.1) — ``materialized='incremental'`` on ``reject_id``, with
  ``incremental_strategy='delete+insert'`` named rather than left to the
  adapter. Two **pre-rendered** SELECTs chosen by ``{% if is_incremental() %}``:
  the first-run one is :func:`~bloomery.emit.lower.reject_select`, exactly as
  SQLMesh emits it, and the incremental one resolves ``first_seen`` and
  ``last_evaluated_at`` against ``{{ this }}`` because dbt has no
  ``when_matched`` clause that can express a ``COALESCE``.
- ``macros/replay_<entity>.sql`` per quarantining entity — the replay
  statements as a ``run-operation``, kind :data:`ArtifactKind.REPLAY` despite
  the path. A bare ``.sql`` file would be runnable by nothing: the statements
  name relations through ``ref()``, which resolves only inside dbt's Jinja.
- ``models/<silver_ns>/<check>__reconcile.sql`` and
  ``tests/<check>_reconcile.sql`` per reconcile check (RFC 0052 §5.3) — the
  comparison SQLMesh renders, and a singular test over it whose ``severity``
  is the check's own ``on_fail``.
- ``models/<gold_ns>/mart_data_quality.sql`` — the quality mart, an ordinary
  gold model, with dbt's run context: ``invocation_id`` and
  ``run_started_at``. The pinned sqlmesh exposes no run-identifier macro and
  emits ``run_id`` declared-but-NULL, so this target has the fuller column.
"""

from __future__ import annotations

import jinja2
import yaml
from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.emit.base import (
    ArtifactKind,
    EmitContext,
    EmittedArtifact,
    assert_unique_paths,
)
from bloomery.emit.lower import (
    REJECT_KEY,
    audit_predicate,
    collision_audit,
    collision_audit_select,
    column_type,
    conservation_audit,
    conservation_audit_select,
    coverage_audit_name,
    coverage_audit_select,
    coverage_owner,
    dim_date_select,
    entity_select,
    fail_audits,
    mart_assert_name,
    mart_assert_select,
    mart_select,
    metadata_audit_select,
    quality_mart_select,
    reconcile_audit_blocking,
    reconcile_audit_select,
    reconcile_relation,
    reconcile_select,
    reject_incremental_select,
    reject_relation,
    reject_select,
    replay_statements,
)
from bloomery.emit.steps import (
    consistency_audits,
    quality_audits,
    refuse_python_models,
    step_output_body,
    step_output_relation,
)
from bloomery.errors import UnsupportedByTarget, guaranteed
from bloomery.ir import (
    VALID_FROM,
    VALID_TO,
    AuditIR,
    DateDimensionIR,
    EntityIR,
    Layer,
    MartIR,
    Materialization,
    ProjectIR,
    ReconcileIR,
    SCDKind,
    StepKind,
    StepOutputIR,
)
from bloomery.quality import RunContext, is_quality_mart
from bloomery.typing import IntType

# ----------------------- #

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
_MODEL_ENVELOPE = jinja2.Template(
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
{{ config_line }}

{{ select }}
""",
    autoescape=False,
)

# A singular test (RFC 0026 §5.1): a `.sql` file under `test-paths` whose query
# returns the rows that fail. dbt puts no shape constraint on it whatsoever —
# no per-column binding, no requirement that it be a row predicate — which is
# exactly the shape a check that groups or joins needs, and exactly what every
# bloomery audit body already is. The envelope is the model one with a
# `severity` config in place of a materialization; it is spelled separately
# because a test is not a model and a shared template would invite one to grow
# a branch for the other.
_TEST_ENVELOPE = jinja2.Template(
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
{{ config_line }}

{{ select }}
""",
    autoescape=False,
)

# Two **pre-rendered** SELECTs chosen by the envelope (RFC 0052 D2), never one
# SELECT with Jinja spliced through it: RFC 0008 D4's rule is that envelopes
# interpolate rendered strings, and a conditional inside a rendered SQL string
# is a template no dialect port ever saw. The dbt-Jinja markers are
# pre-rendered strings for the same reason the snapshot's are.
_REJECT_ENVELOPE = jinja2.Template(
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
{{ config_line }}

{{ open_line }}

{{ incremental }}

{{ else_line }}

{{ first_run }}

{{ close_line }}
""",
    autoescape=False,
)

# The replay macro (RFC 0052 §5.2, D3/D14). Each statement arrives already
# wrapped in its own `{% set %}…{% endset %}` block and `run_query` call —
# built in Python, like every other dbt-Jinja marker this module writes.
_REPLAY_ENVELOPE = jinja2.Template(
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
--
-- Run this with `dbt run-operation {{ macro }}`. The three statements below are
-- one unit of work and the macro says so to the engine; bloomery executes
-- nothing — this file is text until you run it.
{{ open_line }}
{{ begin_line }}

{{ body }}

{{ commit_line }}
{{ close_line }}
""",
    autoescape=False,
)


# The dbt-Jinja block markers are pre-rendered strings too — this template
# never nests Jinja inside Jinja.
_SNAPSHOT_ENVELOPE = jinja2.Template(
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


# ....................... #


def _yaml(document: dict[str, object]) -> str:
    """Byte-stable YAML: deterministic insertion order (``sort_keys`` would
    shuffle ``name`` below ``schema``), block style, pinned width."""

    return yaml.safe_dump(
        document, sort_keys=False, default_flow_style=False, width=100, allow_unicode=True
    )


# ....................... #


def _unique_key(key: tuple[str, ...]) -> str:
    if len(key) == 1:
        return f"unique_key='{key[0]}'"

    members = ", ".join(f"'{part}'" for part in key)
    return f"unique_key=[{members}]"


# ....................... #


def _config_line(materialization: Materialization, key: tuple[str, ...]) -> str:
    if materialization is Materialization.FULL:
        return "{{ config(materialized='table') }}"

    return f"{{{{ config(materialized='incremental', {_unique_key(key)}) }}}}"


# ....................... #


def _severity(*, blocking: bool) -> str:
    """``on_fail``/``blocking`` as dbt spells it (RFC 0026 D3).

    ``error`` is dbt's default and is written out anyway, for the same reason
    every other emitted config line is explicit: an artifact that states its
    own disposition cannot be misread by someone who does not know the
    default.

    The mapping is exact and the *disposition* is not, in both directions —
    ``dbt run`` does not run tests at all, and ``--warn-error`` promotes a
    ``warn`` to an error. Both sentences are in the operator contract, because
    a reader given one and not the other has the wrong model of the target.
    """

    return f"{{{{ config(severity='{'error' if blocking else 'warn'}') }}}}"


# ....................... #


def _singular_test(*, name: str, select: str, blocking: bool, ctx: EmitContext) -> EmittedArtifact:
    """One audit as ``tests/<name>.sql`` (RFC 0026 D1, D6, D7).

    The name is the audit's own, unprefixed (D6): audit names are already
    unique per project and constrained to ``[a-z0-9_]+``, and dbt's generic
    tests are named mechanically from their model, column and arguments
    (``accepted_values_order_segment__business__consumer``), so nothing they
    generate can collide with ``<entity>_<rule>``. A prefix would buy nothing
    and cost every failure report its readable name.

    It carries the fingerprint header like every other emitted file (D7). The
    alternative needs a rule about which artifact classes carry one, and no
    such rule exists — uniformity is the cheaper claim to keep true.
    """

    return EmittedArtifact.create(
        path=f"tests/{name}.sql",
        content=_TEST_ENVELOPE.render(
            fingerprint=ctx.fingerprint,
            config_line=_severity(blocking=blocking),
            select=select,
        ).rstrip("\n")
        + "\n",
        kind=ArtifactKind.AUDIT,
    )


# ....................... #


#: dbt's name for "the relation this model is being written into", which is
#: what the incremental branch joins against. It resolves nowhere but inside a
#: dbt model body.
_THIS = "{{ this }}"


def _reject_artifacts(
    entity: EntityIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> tuple[EmittedArtifact, EmittedArtifact]:
    """The ``<entity>__reject`` model and its replay macro (RFC 0016 §5.6,
    RFC 0052 §5.1/§5.2).

    **The model preserves its own columns.** SQLMesh keeps ``first_seen`` and
    ``last_evaluated_at`` in a ``when_matched`` clause; dbt has none that can
    express a ``COALESCE``, so :func:`reject_incremental_select` resolves them
    in the projection instead and the write is left to replace the whole row
    (D1). ``delete+insert`` materializes this SELECT *before* deleting the
    matching keys, so the join against ``{{ this }}`` reads the incumbent row
    rather than the hole where it was.

    **Replay is a macro because a bare `.sql` file would be runnable by
    nothing.** Its statements name relations through ``ref()``, which resolves
    only inside dbt's Jinja — not in a SQL client, which sees braces, and not
    through ``dbt``, which does not execute loose files (D3). It keeps
    :data:`ArtifactKind.REPLAY` despite living under ``macros/``: the kind means
    "a statement the caller runs, not a relation the framework maintains", and a
    caller routing the stream must be able to tell those apart without reading a
    path (D5).
    """
    namespace, relation = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
    model = _REJECT_ENVELOPE.render(
        fingerprint=ctx.fingerprint,
        config_line=(
            f"{{{{ config(materialized='incremental', unique_key='{REJECT_KEY}', "
            "incremental_strategy='delete+insert') }}"
        ),
        open_line="{% if is_incremental() %}",
        incremental=_render(
            reject_incremental_select(entity, ctx, incumbent=_THIS), references, ctx
        ),
        else_line="{% else %}",
        first_run=_render(reject_select(entity, ctx), references, ctx),
        close_line="{% endif %}",
    )
    macro = f"replay_{entity.name}"
    return (
        EmittedArtifact.create(
            path=f"models/{namespace}/{relation}.sql",
            content=model.rstrip("\n") + "\n",
            kind=ArtifactKind.MODEL,
        ),
        EmittedArtifact.create(
            path=f"macros/{macro}.sql",
            content=_REPLAY_ENVELOPE.render(
                fingerprint=ctx.fingerprint,
                macro=macro,
                open_line=f"{{% macro {macro}() %}}",
                begin_line='  {% do run_query("BEGIN") %}',
                body=_replay_body(entity, ctx, references),
                commit_line='  {% do run_query("COMMIT") %}',
                close_line="{% endmacro %}",
            ).rstrip("\n")
            + "\n",
            kind=ArtifactKind.REPLAY,
        ),
    )


# ....................... #


def _replay_body(entity: EntityIR, ctx: EmitContext, references: dict[tuple[str, str], str]) -> str:
    """Each replay statement captured into a variable, then run.

    **A `{% set %}…{% endset %}` block rather than a quoted string**, and this
    is load-bearing rather than stylistic: Jinja renders a block-set's body and
    does *not* render ``{{ ... }}`` inside a string literal. Measured at both
    ends of the supported dbt range — a quoted statement reaches the engine
    with ``{{ ref('order_item') }}`` in it verbatim (`logs/T-0016.md` D-081).

    The statements run in the order :func:`replay_statements` returns them,
    which is the order RFC 0016 §5.6 requires: the resolution stamp before the
    re-evaluation stamp, so the second's ``resolved_at IS NULL`` filter means
    "the rest".
    """
    blocks: list[str] = []

    for index, statement in enumerate(replay_statements(entity, ctx)):
        blocks.append(
            f"  {{% set statement_{index} %}}\n"
            f"{_render(statement, references, ctx)}\n"
            f"  {{% endset %}}\n"
            f"  {{% do run_query(statement_{index}) %}}"
        )

    return "\n".join(blocks)


# ....................... #


def _reconcile_artifacts(
    check: ReconcileIR,
    ir: ProjectIR,
    ctx: EmitContext,
    references: dict[tuple[str, str], str],
) -> tuple[EmittedArtifact, EmittedArtifact]:
    """One reconcile check → a comparison model and a singular test over it
    (RFC 0016 §5.3, RFC 0052 §5.3).

    The two halves of RFC 0016 D58's refusal expired separately. The audit half
    went with RFC 0026: a singular test carrying ``severity='warn'`` *is* a
    non-blocking check, and this target emits five families of them. The model
    half is what this builds, from :func:`reconcile_select` — the same function
    SQLMesh renders, because a second lowering for a comparison both targets
    already agree on is the drift ``emit/lower/`` exists to prevent.

    Blocking-ness is :func:`reconcile_audit_blocking`, also shared, so a check's
    ``on_fail`` means one thing on both targets: ``fail`` stops the run,
    ``flag`` reports and leaves the comparison table readable — which is the
    point of it, since a disagreement is exactly when someone needs to read the
    rows.

    The model is ``materialized='table'``, SQLMesh's ``FULL`` said in dbt's
    vocabulary. A comparison is recomputed whole or it is stale.
    """
    namespace, relation = ctx.naming.relation(reconcile_relation(check), Layer.SILVER)
    return (
        _model_artifact(
            path=f"models/{namespace}/{relation}.sql",
            # `FULL` takes no unique key, and the comparison's grain reaches
            # the artifact through the SELECT rather than through the config —
            # SQLMesh states it in the model's `grain` and dbt has nowhere to
            # put it. Passing `reconcile_keys` here would be a value the
            # envelope discards, which reads as a grain that travelled.
            config_line=_config_line(Materialization.FULL, ()),
            select=_render(reconcile_select(check, ir, ctx), references, ctx),
            ctx=ctx,
        ),
        _singular_test(
            name=f"{check.name}_reconcile",
            select=_render(
                reconcile_audit_select(relation=references[(namespace, relation)]),
                references,
                ctx,
            ),
            blocking=reconcile_audit_blocking(check),
            ctx=ctx,
        ),
    )


# ....................... #


def _step_artifacts(
    ir: ProjectIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> list[EmittedArtifact]:
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
                    select=_render(step_output_body(step, output, ir, ctx), references, ctx),
                    ctx=ctx,
                )
            )

    return artifacts


# ....................... #


def _model_artifact(
    *, path: str, config_line: str, select: str, ctx: EmitContext
) -> EmittedArtifact:
    content = _MODEL_ENVELOPE.render(
        fingerprint=ctx.fingerprint, config_line=config_line, select=select
    )
    return EmittedArtifact.create(
        path=path, content=content.rstrip("\n") + "\n", kind=ArtifactKind.MODEL
    )


# ....................... #


def _snapshot_artifact(
    entity: EntityIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> EmittedArtifact:
    if len(entity.key) != 1:
        msg = (
            f"entity {entity.name!r} is SCD type 2 with composite key "
            f"({', '.join(entity.key)}) — dbt snapshot unique_key takes a single "
            "expression, and concatenating key parts would be a silent approximation "
            "(feature: scd_type_2)"
        )
        raise UnsupportedByTarget(msg)

    namespace, _relation = ctx.naming.relation(entity.name, Layer.SILVER)
    # `snapshot_meta_column_names` renames dbt's `dbt_valid_from`/`dbt_valid_to`
    # to the interval names the IR owns (RFC 0023 §5.3, D7). Without it the two
    # targets name the same interval differently — which is precisely why no
    # as-of predicate could be emitted before — and a mart's join, lowered once
    # for every target, would reference columns that exist on SQLMesh's relation
    # and not on dbt's. The other meta columns keep their dbt names: nothing
    # bloomery emits reads them.
    config_line = (
        f"{{{{ config(target_schema='{namespace}', unique_key='{entity.key[0]}', "
        "strategy='check', check_cols='all', "
        f"snapshot_meta_column_names={{'dbt_valid_from': '{VALID_FROM}', "
        f"'dbt_valid_to': '{VALID_TO}'}}) }}}}"
    )
    content = _SNAPSHOT_ENVELOPE.render(
        fingerprint=ctx.fingerprint,
        open_line=f"{{% snapshot {entity.name}_snapshot %}}",
        close_line="{% endsnapshot %}",
        config_line=config_line,
        select=_render(entity_select(entity, ctx), references, ctx),
    )
    return EmittedArtifact.create(
        path=f"snapshots/{entity.name}_snapshot.sql",
        content=content.rstrip("\n") + "\n",
        kind=ArtifactKind.MODEL,
    )


# ....................... #


def _dim_date_artifact(
    dim: DateDimensionIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> EmittedArtifact:
    namespace, _mart_relation = ctx.naming.relation(dim.name, Layer.GOLD)
    return _model_artifact(
        path=f"models/{namespace}/{dim.name}.sql",
        config_line="{{ config(materialized='table') }}",
        select=_render(dim_date_select(dim), references, ctx),
        ctx=ctx,
    )


# ....................... #


#: dbt's run context (RFC 0016 §5.8, RFC 0052 D8). Both columns are engine-side
#: expressions rather than values bloomery read — `invocation_id` is dbt's own
#: per-run identifier and `run_started_at` is the run's start as a Python
#: datetime, formatted to the `YYYY-MM-DD` the schema declares.
#:
#: Worth stating rather than discovering: this is **more** complete than the
#: SQLMesh context beside it, which emits `run_id` declared-but-NULL because
#: the pinned sqlmesh exposes no run-identifier macro. The compatibility target
#: ends up with the fuller column, which is a fact about the two frameworks.
_DBT_RUN = RunContext(
    run_id="'{{ invocation_id }}'",
    run_date="'{{ run_started_at.strftime(\"%Y-%m-%d\") }}'",
)


def _mart_artifact(
    mart: MartIR, ir: ProjectIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> EmittedArtifact:
    namespace, relation = ctx.naming.relation(mart.name, Layer.GOLD)

    if is_quality_mart(mart):
        # Not a mart over a base entity: its rows are rule evaluations, so the
        # base lookup below has nothing to find. RFC 0016 §5.4 put this in
        # SQLMesh's set alone and this target refused it until RFC 0052 §5.4,
        # on the ground that it counts rows in reject tables and reconcile
        # models dbt did not build. Both are built now, so the refusal is
        # deleted rather than narrowed (D7) — narrowing it is the right change
        # only in the world where this RFC did not ship.
        return _model_artifact(
            path=f"models/{namespace}/{relation}.sql",
            config_line=_config_line(Materialization.FULL, ()),
            select=_render(quality_mart_select(ir, ctx, _DBT_RUN), references, ctx),
            ctx=ctx,
        )

    base = guaranteed(
        (entity for entity in ir.entities if entity.name == mart.base),
        expected=f"the base entity {mart.base!r} of mart {mart.name!r}",
        by="the mart-base guardrail (RFC 0010)",
    )
    return _model_artifact(
        path=f"models/{namespace}/{relation}.sql",
        config_line=_config_line(mart.materialization, base.key),
        select=_render(mart_select(mart, ctx), references, ctx),
        ctx=ctx,
    )


# ....................... #
# Audit lowering → schema.yml (RFC 0006 → RFC 0008 §5.5)


# ....................... #


def _test(name: str, **arguments: object) -> dict[str, object]:
    """One parameterized generic test, arguments nested (RFC 0008 D22).

    dbt < 1.10 took them at the top level and 1.10 moved them under
    ``arguments``, deprecating the flat form — and the two spellings are
    mutually exclusive, not merely stylistic: nesting is a *compilation error*
    on 1.9, which is why adopting it is what sets the floor rather than
    something the floor happens to allow.
    """

    return {name: {"arguments": arguments}}


# ....................... #


def _accepted_values(entity: EntityIR, audit: AuditIR) -> dict[str, object]:
    member_type = column_type(entity, audit.column)
    values: list[object] = [
        int(value) if isinstance(member_type, IntType) else value for _name, value in audit.params
    ]
    return _test("accepted_values", values=values)


# ....................... #


def _entity_tests(
    entity: EntityIR, ctx: EmitContext
) -> tuple[dict[str, list[object]], list[object]]:
    """The per-column tests (column → test list) and the model-level
    expression tests for one entity, in the deterministic ``EntityIR.audits``
    order (sorted by kind, column).

    Native tests stay preferred where dbt has an equivalent (RFC 0026 D4): a
    builtin ``not_null`` names its column in ``dbt test`` output and appears in
    ``dbt docs``, and a hand-rolled query does neither. Everything else routes
    to :func:`unmapped_audits`.
    """
    column_tests: dict[str, list[object]] = {}
    model_tests: list[object] = []

    for audit in entity.audits:
        if audit.kind == "not_null":
            column_tests.setdefault(audit.column, []).append("not_null")
        elif audit.kind == "enum":
            column_tests.setdefault(audit.column, []).append(_accepted_values(entity, audit))
        elif audit.kind in _EXPRESSION_KINDS:
            expression = ctx.dialect.render(audit_predicate(entity, audit, violations=False))
            model_tests.append(_test(_EXPRESSION_TEST, expression=expression))
        else:
            # RFC 0026 §5.4 expected this branch to become a singular-test
            # route and it cannot: there is nothing to route. The `assert:`
            # vocabulary is closed at the six kinds above — `guardrails/
            # asserts.py` and `guardrails/conflict.py` are the only places an
            # `AuditIR` is built — and `audit_predicate` knows exactly the four
            # custom ones, so a seventh kind has no body on *any* target. The
            # guard therefore stays, saying what is actually wrong, and the
            # kind it guards is unreachable from any spec. See
            # logs/T-0003.md D-013.
            msg = (
                f"entity {entity.name!r} audit kind {audit.kind!r} on column "
                f"{audit.column!r} is outside the closed assert: vocabulary "
                "(not_null, enum, min, max, regex, reconcile), so no target has a "
                "predicate to build a check from — refusing rather than approximating "
                "(RFC 0008 D3). Fix: this is an internal inconsistency, not a spec "
                "error; a new audit kind needs a lowering in audit_predicate and a "
                "mapping in every emitter"
            )
            raise UnsupportedByTarget(msg)

    return column_tests, model_tests


# ....................... #


def _entity_test_artifacts(
    entity: EntityIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> list[EmittedArtifact]:
    """The checks over one silver model that no ``schema.yml`` entry can carry.

    Four, and they are the four RFC 0016 and RFC 0024 already generate for
    SQLMesh — this list and the SQLMesh one are asserted equal, per fixture,
    rather than kept in step by whoever edits them
    (``test_the_two_targets_emit_the_same_audits``):

    - the **collision** audit on a merged entity, which groups by the key and
      counts distinct sources (RFC 0024 D5) — the condition the merge is not
      correct without, and the reason a merged entity was SQLMesh-only;
    - the **ingestion-metadata** audit, whose duplicate-identity half is a
      window count and so cannot be a row predicate (RFC 0016 D21);
    - one per ``on_fail: fail`` rule, whose body is a union of two populations
      read from two relations (RFC 0016 D32/D67).

    The last two were never *refused* here — they were silently absent, under
    RFC 0016 §5.4's target-coverage sentence. That sentence was written when
    this emitter had no artifact for them; keeping it after the artifact
    exists would leave a step's ``on_fail: fail`` audit emitting while an
    entity's does not, which is one disposition with two answers decided by
    which spec block the rule sits in.

    The **conservation** audit is the fourth, and it arrived with the reject
    table (RFC 0052 §5.1). It was absent for one reason — the refusal above it
    fired first — and that reason is gone, so leaving it out would mean this
    target builds both sides of the routing split and never checks they add
    up. That is the one audit whose absence is invisible: every model
    materializes, every other test passes, and a silently dropped row is
    exactly what nothing else looks for.

    **The ``fail_audits`` leg went live**, and this paragraph used to say it
    never fired. The reasoning was right: an ``on_fail: fail`` rule needs a
    ``quality:`` surface, declaring one opts the entity into coercion routing
    whose implicit ``coercible`` rules default to ``quarantine``, so every
    entity that reaches this line carries a quarantine disposition — and
    ``_refuse_quarantine`` raised first. It said the leg "goes live the day dbt
    grows a reject model", named that as RFC 0016 §5.4's out-of-scope item, and
    kept the lowering with a test that built the IR directly rather than
    waiting to discover it (`logs/T-0003.md` D-014). RFC 0052 was that day.
    ``quality_precedence`` alone now emits three of these, and
    ``dirty_corpus`` a fourth.
    """
    relation = references[ctx.naming.relation(entity.name, Layer.SILVER)]
    artifacts: list[EmittedArtifact] = []

    if collision_audit(entity):
        artifacts.append(
            _singular_test(
                name=f"{entity.name}_source_collision",
                select=_render(collision_audit_select(entity, ctx), references, ctx),
                # RFC 0024 D5: blocking, and not configurable to a weaker
                # disposition. A key in two sources is either genuine
                # duplication or a shared key space by accident, and both are
                # refusals.
                blocking=True,
                ctx=ctx,
            )
        )

    if entity.dedupe is not None or entity.quarantine is not None:
        artifacts.append(
            _singular_test(
                name=f"{entity.name}_ingestion_metadata",
                select=_render(
                    metadata_audit_select(entity, ctx, relation=relation), references, ctx
                ),
                blocking=True,
                ctx=ctx,
            )
        )

    if conservation_audit(entity):
        artifacts.append(
            _singular_test(
                name=f"{entity.name}_conservation",
                select=_render(
                    conservation_audit_select(entity, ctx, relation=relation), references, ctx
                ),
                # Blocking, as it is on SQLMesh: a bronze row in neither side of
                # the split has been silently dropped, which is the failure this
                # package exists to make impossible.
                blocking=True,
                ctx=ctx,
            )
        )

    artifacts.extend(
        _singular_test(
            name=name,
            select=_render(select, references, ctx),
            blocking=True,
            ctx=ctx,
        )
        for name, select in fail_audits(entity, ctx, relation=relation)
    )

    return artifacts


# ....................... #


def _mart_test_artifacts(
    mart: MartIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> list[EmittedArtifact]:
    """One singular test per mart assertion (RFC 0016 D89).

    Blocking-ness is the clause's own, as it is on SQLMesh: ``fail`` stops the
    build, ``flag`` reports beside it. An assertion aggregates, so there is no
    per-row predicate that expresses "this month's total is out of bounds" and
    therefore no ``schema.yml`` entry that could have carried it.
    """
    relation = references[ctx.naming.relation(mart.name, Layer.GOLD)]
    return [
        _singular_test(
            name=mart_assert_name(mart, clause),
            select=_render(mart_assert_select(mart, clause, relation=relation), references, ctx),
            blocking=clause.blocking,
            ctx=ctx,
        )
        for clause in mart.asserts
    ]


# ....................... #


def _coverage_test_artifacts(
    ir: ProjectIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> list[EmittedArtifact]:
    """One singular test per coverage check (RFC 0016 D90).

    The body joins the referenced entity to the dependent one and groups, which
    is why this was refused: two relations and a ``GROUP BY``, and a schema test
    is neither. Both relations resolve through the reference map — the
    dependent side because it is passed in as this test's own relation, the
    referenced side because it is namespaced and the map rewrites it like any
    other input. dbt orders the test after both, which is what SQLMesh needed
    an explicit ``depends_on`` for.
    """
    artifacts: list[EmittedArtifact] = []

    for check in ir.coverage:
        dependent = coverage_owner(check, ir).from_entity
        relation = references[ctx.naming.relation(dependent, Layer.SILVER)]
        artifacts.append(
            _singular_test(
                name=coverage_audit_name(check),
                select=_render(
                    coverage_audit_select(check, ir, ctx, relation=relation), references, ctx
                ),
                blocking=check.blocking,
                ctx=ctx,
            )
        )

    return artifacts


# ....................... #


def _step_test_artifacts(
    ir: ProjectIR, ctx: EmitContext, references: dict[tuple[str, str], str]
) -> list[EmittedArtifact]:
    """Step-output audits as singular tests (RFC 0017 D39/D40).

    Both kinds are whole-query checks — a join between sibling outputs, or an
    ``on_fail: fail`` rule's blocking body — and neither is a row predicate,
    which is the whole of why they were refused.

    ``quality_audits`` is told how this target spells "the relation this audit
    judges": a ``ref()`` rather than SQLMesh's ``@this_model`` macro, so the
    body is built with dbt's spelling from the start (RFC 0026 D10).
    ``consistency_audits`` needs no such resolver — it compares two siblings,
    and both are namespaced relations the reference map already rewrites.
    """

    def output_reference(output: StepOutputIR) -> str:
        return references[step_output_relation(output, ctx)]

    artifacts: list[EmittedArtifact] = []

    for step in ir.steps:
        # `is not SQL_MODEL`, matching `_step_artifacts`, rather than the
        # `is SQL_MACRO` the SQLMesh side skips on: Tier 3 has no `ref()` in
        # the reference map, so a Tier 3 step reaching `output_reference`
        # would be a KeyError rather than a refusal. `refuse_python_models`
        # runs first today and makes that unreachable — which is exactly why
        # the condition should not be the one that depends on it.
        if step.kind is not StepKind.SQL_MODEL:
            continue
        for body in (
            *consistency_audits(step, ctx),
            *quality_audits(step, ir, ctx, self_relation=output_reference),
        ):
            artifacts.append(
                _singular_test(
                    name=body.name,
                    select=_render(body.select, references, ctx),
                    blocking=body.blocking,
                    ctx=ctx,
                )
            )

    return artifacts


# ....................... #


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


# ....................... #


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


# ....................... #


def _sources_artifact(ir: ProjectIR, ctx: EmitContext) -> EmittedArtifact | None:
    relations_by_namespace: dict[str, set[str]] = {}

    # One ``source()`` per mapping (RFC 0024 D20): a merged entity reads every
    # relation its branches do, and a sources.yml naming only the first would
    # leave dbt unable to resolve the rest.
    for entity in ir.entities:
        for origin in entity.sources:
            namespace, relation = ctx.naming.relation(origin.relation, Layer.BRONZE)
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


# ....................... #


def _reference_map(ir: ProjectIR, ctx: EmitContext) -> dict[tuple[str, str], str]:
    """``(namespace, relation)`` → the dbt reference that resolves to it
    (RFC 0008 D20).

    Keyed on what the *lowered SQL* says, because that is what the rewrite has
    to match: shared lowering builds every input as ``exp.table_(relation,
    db=namespace)`` under the naming policy, identically for both targets, and
    the dbt emitter's job is to say the same thing in dbt's vocabulary rather
    than to lower differently.

    A namespace-less table is never mapped. Nothing here can produce one — the
    naming policy always answers with a namespace — and the exclusion is what
    keeps a CTE reference (``FROM _quality_order``, which parses as a table
    with no ``db``) from being mistaken for a model.
    """
    references: dict[tuple[str, str], str] = {}

    def add(namespace: str, relation: str, reference: str) -> None:
        if namespace:
            references[(namespace, relation)] = reference

    for entity in ir.entities:
        for origin in entity.sources:
            namespace, relation = ctx.naming.relation(origin.relation, Layer.BRONZE)
            add(namespace, relation, f"{{{{ source('{namespace}', '{relation}') }}}}")

    for entity in ir.entities:
        namespace, relation = ctx.naming.relation(entity.name, Layer.SILVER)
        # An SCD2 entity's rows live in the snapshot, which is the only thing
        # dbt builds for it — so a downstream reference to the *entity* has to
        # resolve there. Referencing `relation` would name a model this target
        # never emits, and dbt would refuse the project.
        model = f"{entity.name}_snapshot" if entity.scd is SCDKind.TYPE2 else relation
        add(namespace, relation, f"{{{{ ref('{model}') }}}}")

    for step in ir.steps:
        if step.kind is not StepKind.SQL_MODEL:
            continue
        for output in step.outputs:
            namespace, relation = step_output_relation(output, ctx)
            add(namespace, relation, f"{{{{ ref('{relation}') }}}}")

    # The reject tables and reconcile models are relations like any other, and
    # the quality mart counts over both. Left out of this map they would reach
    # the mart as literal `silver.<name>` — no dependency edge for dbt to order
    # by, and a `FROM` naming a schema the model was not materialized into,
    # which is RFC 0008 D20's finding restated. Found by the build tier, which
    # is the only thing that can see it.
    for entity in ir.entities:
        if entity.quarantine is None:
            continue
        namespace, relation = ctx.naming.relation(reject_relation(entity), Layer.SILVER)
        add(namespace, relation, f"{{{{ ref('{relation}') }}}}")

    for check in ir.reconcile:
        namespace, relation = ctx.naming.relation(reconcile_relation(check), Layer.SILVER)
        add(namespace, relation, f"{{{{ ref('{relation}') }}}}")

    for mart in ir.marts:
        namespace, relation = ctx.naming.relation(mart.name, Layer.GOLD)
        add(namespace, relation, f"{{{{ ref('{relation}') }}}}")

    if ir.date_dimension is not None:
        namespace, _relation = ctx.naming.relation(ir.date_dimension.name, Layer.GOLD)
        add(namespace, ir.date_dimension.name, f"{{{{ ref('{ir.date_dimension.name}') }}}}")

    return references


# ....................... #


def _render(node: Expression, references: dict[tuple[str, str], str], ctx: EmitContext) -> str:
    """Render one lowered SELECT with its inputs stated as dbt references.

    Every model body goes through here rather than through ``ctx.dialect.render``
    directly: a body that reached a file with a literal relation name is exactly
    the defect D20 closes, and a new artifact kind forgetting the rewrite is the
    way it would come back.

    A table the map does not know is **left alone** rather than guessed at. Only
    two kinds reach that branch: a table function (``GENERATE_SERIES`` in the
    date dimension, which parses as a table with no name at all) and a relation
    a step body names that this project does not build. Inventing a ``ref()``
    for the second would name a model dbt cannot find and refuse the whole
    project — the literal name is the honest rendering of "bloomery did not
    write this relation".
    """
    node = node.copy()

    for table in node.find_all(exp.Table):
        reference = references.get((table.db, table.name))
        if reference is None:
            continue
        # `to_identifier(..., quoted=False)` is what lets the braces survive
        # rendering — the same device `_this_model` uses for `@this_model`,
        # which sqlglot would otherwise quote into a literal identifier.
        replacement = exp.Table(this=exp.to_identifier(reference, quoted=False))
        alias = table.args.get("alias")
        if alias is not None:
            replacement.set("alias", alias)
        table.replace(replacement)

    return ctx.dialect.render(node)


# ....................... #


_SCHEMA_MACRO = """\
{% macro generate_schema_name(custom_schema_name, node) -%}
{%- if custom_schema_name is none -%}
{{ target.schema }}
{%- else -%}
{{ custom_schema_name | trim }}
{%- endif -%}
{%- endmacro %}
"""


def _schema_macro_artifact(ctx: EmitContext) -> EmittedArtifact:
    """The override that keeps the naming policy owning namespaces (D20).

    dbt's default ``generate_schema_name`` returns ``<target.schema>_<custom>``,
    so a model configured ``+schema: silver`` against a target schema ``main``
    materializes at ``main_silver`` — while ``sources.yml``, which does not go
    through this macro at all, still says ``bronze``. Half the project would
    honour the naming policy and half would not.

    Returning the configured schema verbatim is what makes ``ref()`` resolve to
    the relation :meth:`NamingPolicy.relation` names. Without it, adopting
    ``ref()`` really would cost the naming port its ownership — which is the
    objection RFC 0009 D22 raised against doing so, and this is its answer
    rather than its acceptance.
    """

    return EmittedArtifact.create(
        path="macros/generate_schema_name.sql",
        content=(
            "-- Generated by bloomery — do not edit.\n"
            f"-- fingerprint: {ctx.fingerprint}\n{_SCHEMA_MACRO}"
        ),
        kind=ArtifactKind.CONFIG,
    )


# ....................... #


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


# ....................... #


#: The operator contract, in the emitted project (RFC 0026 §5.5, §10).
#:
#: It is on the dbt docs page too, and that is not enough on its own: the page
#: is read by whoever compiled the project, and this file is read by whoever
#: *runs* it, who may be neither the same person nor a bloomery user at all.
#: `dbt run` on a bloomery project materializes every model with every check
#: unevaluated, and nothing else in the emitted bytes would say so.
_OPERATOR_CONTRACT = """\
# Build this project with `dbt build`, not `dbt run`. Every check bloomery
# generates is a test — schema tests under models/schema.yml and singular tests
# under tests/ — and `dbt run` does not run tests, so `dbt run` produces models
# with their data-quality gates unevaluated. Some of those gates are the
# correctness condition of the model they guard, not an optional report.
#
# `--warn-error` promotes the other direction: a check bloomery emitted as
# `severity=warn` (an `on_fail: flag` rule) fails the build under that flag.
"""


def _project_artifact(ctx: EmitContext, namespaces: tuple[str, ...]) -> EmittedArtifact:
    document: dict[str, object] = {
        "name": "bloomery",
        "version": "1.0.0",
        "profile": "bloomery",
        "model-paths": ["models"],
        "snapshot-paths": ["snapshots"],
        # Declared though they match dbt's default, exactly as `model-paths`
        # and `snapshot-paths` above are: the emitted project states its own
        # layout rather than inheriting one that a later dbt could change.
        # Neither declaration is what makes discovery work — dbt already looks
        # in `macros/` and `tests/` — so removing one would not break the
        # emitted project, and that is precisely why the claim under test is
        # "the layout is stated", not "the tests are found".
        "macro-paths": ["macros"],
        "test-paths": ["tests"],
    }

    if namespaces:
        # One `+schema` per model directory, the directory *being* the
        # namespace the naming policy chose (D20). With the
        # `generate_schema_name` override this puts each model in exactly the
        # relation `NamingPolicy.relation` names — which is what makes the
        # `ref()` in a downstream model resolve to the same relation the
        # SQLMesh target writes.
        document["models"] = {
            "bloomery": {namespace: {"+schema": namespace} for namespace in namespaces}
        }

    return EmittedArtifact.create(
        path="dbt_project.yml",
        content=_header(ctx) + _OPERATOR_CONTRACT + _yaml(document),
        kind=ArtifactKind.CONFIG,
    )


# ....................... #


class DbtEmitter:
    """RFC 0008 §5.5: the port-abstraction proof (RFC 0008 D5) — same
    lowered SELECTs as SQLMesh, dbt envelopes, honest refusals per construct."""

    name = "dbt"

    # ....................... #

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]:
        """Lower every entity to a model (SCD type 2 → snapshot), every mart
        and the date dimension to gold models, audits to ``schema.yml``, plus
        the project scaffold and bronze sources; artifacts sorted by path,
        content ending in exactly one newline (RFC 0003 §5.5 rule 5)."""
        refuse_python_models(ir, "dbt")
        references = _reference_map(ir, ctx)
        artifacts: list[EmittedArtifact] = list(_step_artifacts(ir, ctx, references))
        artifacts.extend(_step_test_artifacts(ir, ctx, references))

        for entity in ir.entities:
            # A step output is an entity in the DAG (RFC 0017 D36) but its rows
            # are the step's to write, and its lowered `expr` is the column
            # referring to itself — emitting the ordinary entity model here
            # would produce a model selecting from the relation it defines.
            if entity.produced_by is not None:
                continue
            # Before the SCD2 branch, which returns to the loop: a snapshot
            # entity carries checks like any other, and its reference resolves
            # to the snapshot because that is where its rows are.
            artifacts.extend(_entity_test_artifacts(entity, ctx, references))
            if entity.quarantine is not None:
                artifacts.extend(_reject_artifacts(entity, ctx, references))

            if entity.scd is SCDKind.TYPE2:
                artifacts.append(_snapshot_artifact(entity, ctx, references))
                continue
            namespace, relation = ctx.naming.relation(entity.name, Layer.SILVER)
            artifacts.append(
                _model_artifact(
                    path=f"models/{namespace}/{relation}.sql",
                    config_line=_config_line(entity.materialization, entity.key),
                    select=_render(entity_select(entity, ctx), references, ctx),
                    ctx=ctx,
                )
            )

        for check in ir.reconcile:
            artifacts.extend(_reconcile_artifacts(check, ir, ctx, references))

        artifacts.extend(_mart_artifact(mart, ir, ctx, references) for mart in ir.marts)

        for mart in ir.marts:
            artifacts.extend(_mart_test_artifacts(mart, ctx, references))

        artifacts.extend(_coverage_test_artifacts(ir, ctx, references))

        if ir.date_dimension is not None:
            artifacts.append(_dim_date_artifact(ir.date_dimension, ctx, references))

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

        # Read off the emitted model paths for the same reason the macro
        # condition is read off the emitted schema: `models/<ns>/<rel>.sql` is
        # the directory dbt will apply the config to, so taking the namespaces
        # from anywhere else invites a `+schema` that governs no model — or a
        # model directory that no `+schema` governs, which lands the relation
        # somewhere the naming policy never named.
        namespaces = tuple(
            sorted(
                {
                    artifact.path.split("/")[1]
                    for artifact in artifacts
                    if artifact.path.startswith("models/") and artifact.path.count("/") > 1
                }
            )
        )
        artifacts.append(_project_artifact(ctx, namespaces))
        artifacts.append(_schema_macro_artifact(ctx))
        # This target writes `tests/<check>.sql` across five families whose
        # names come from author-chosen parts (RFC 0026), so it needs the guard
        # SQLMesh has had since RFC 0017 — before that it emitted no audit
        # artifacts at all and had nothing to collide.
        assert_unique_paths(artifacts)

        return tuple(sorted(artifacts, key=lambda a: a.path))
