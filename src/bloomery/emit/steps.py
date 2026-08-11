"""Step artifacts (RFC 0017 §5.8, D8/D16).

Three kinds, one per tier above the DSL:

- **``sql_macro``** splices into the consuming entity's SELECT and emits no
  artifact of its own — the model stays one query and column-level lineage
  sees straight through it (§5.1). The splice itself happens at *lowering*
  (:mod:`bloomery.steps.splice`), so the macro is already part of the
  consuming column's expression by the time this module sees the IR.
- **``sql_model``** emits an ordinary model artifact from the registry body,
  which reached the IR canonicalized at lowering.
- **``python_model``** emits a generated SQLMesh Python-model ``.py``
  artifact — file-shaped text like every other artifact (RFC 0008 D2) —
  importing the manifest ``entrypoint`` at run time and wrapping it with the
  §5.4 contract assertion.

**One wrapper per declared output** (D16), each executing the step and
returning its own output. The RFC records the cost honestly and so does this
module: N outputs means N executions. That is safe for a *correctly declared*
step — nondeterministic ones are compile-refused and seeded ones re-execute
with the same recorded seed — and the residual risk is a step misdeclared as
pure producing disagreeing sibling outputs within one run, which behavioral
gates (run-to-run) do not catch. Accepted for v1 with the mitigation named in
the RFC, not built here.

Every wrapper asserts **all** declared outputs, not just the one it returns:
a step that lies about one output should be caught wherever the run starts.

**Targets** (RFC 0017 D52). Tier 1 is target-neutral by construction — it was
spliced at lowering, so it is already inside whichever model reads it. Tier 2
is a SELECT and emits for SQLMesh *and* dbt, through :func:`step_body`, with
each target wrapping it in its own envelope. Tier 3 is SQLMesh-only: dbt's
Python models run on Snowflake, BigQuery and Databricks, none of which is a
bloomery dialect. Cube is asked nothing here at all — it builds no relation for
any part of the spec, so a refusal about *how* one is built would single steps
out among everything else it already leaves alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

import jinja2
from sqlglot import exp

from bloomery.emit.base import ArtifactKind, EmittedArtifact
from bloomery.emit.lowering import THIS_MODEL
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import Layer, OnFail, StepKind
from bloomery.quality import is_not_null, verdict
from bloomery.steps.splice import parameter_literal
from bloomery.typing import render_type

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlglot.expressions.core import Expression

    from bloomery.emit.base import EmitContext
    from bloomery.ir import ProjectIR, QualityRuleIR, StepIR, StepOutputIR, StepParameterIR

__all__ = [
    "consistency_audits",
    "refuse_mart_asserts",
    "refuse_python_models",
    "refuse_step_audits",
    "step_artifacts",
    "step_body",
    "step_output_relation",
]


def refuse_python_models(ir: ProjectIR, target: str) -> None:
    """Refuse a Tier 3 step on a target with nowhere to run it (RFC 0017 D52).

    dbt *does* have Python models, which is why this is narrower than D31's
    blanket refusal — but only on Snowflake, BigQuery and Databricks, and
    bloomery ships DuckDB, Postgres and Trino. So there is no adapter in this
    project's reach that would execute the wrapper, and emitting one would
    produce a file dbt refuses to parse rather than a model that runs.

    Tier 2 is a different question and gets a different answer: a ``sql_model``
    is a SELECT, and a SELECT is what dbt is made of.
    """
    refused = sorted(
        f"{step.ref}@{step.version}" for step in ir.steps if step.kind is StepKind.PYTHON_MODEL
    )
    if not refused:
        return
    msg = (
        f"project wires python_model step(s) {', '.join(refused)}, which the {target} "
        "target cannot emit (RFC 0017 D52). dbt's Python models run on Snowflake, "
        "BigQuery and Databricks only, and none of bloomery's dialects is one of them, "
        "so the wrapper would have no adapter to execute it. Fix: compile these steps "
        "for SQLMesh, or express them at a lower tier"
    )
    raise UnsupportedByTarget(msg)


def refuse_step_audits(ir: ProjectIR, ctx: EmitContext, target: str) -> None:
    """Refuse a step whose outputs carry audits on a target without them.

    A step's audits are whole-query checks — a join between sibling outputs
    (D40), or an ``on_fail: fail`` rule's blocking body (D39). dbt's schema
    tests are per-column or per-model *predicates*; neither shape survives the
    translation, and ``_entity_tests`` already refuses an audit kind with "no
    honest dbt schema-test mapping" for exactly this reason (RFC 0008 D3).

    Checked by *building* the audits rather than by inspecting the step,
    because what decides it is whether any were generated — a single-output
    ``sql_model`` with no ``fail`` rules generates none, and refusing it would
    withhold the tier for a reason that does not apply to it.
    """
    named = sorted(
        artifact.path.removeprefix("audits/").removesuffix(".sql")
        for step in ir.steps
        for _owner, artifact in (*consistency_audits(step, ctx), *quality_audits(step, ir, ctx))
    )
    if not named:
        return
    msg = (
        f"step audit(s) {', '.join(named)} are whole-query checks (RFC 0017 D39/D40), "
        f"which the {target} target cannot express: its schema tests are per-column or "
        "per-model predicates, and approximating a cross-relation join with one would "
        "change what the check means. Fix: compile for SQLMesh, or drop the references:/"
        "on_fail: fail declarations these come from"
    )
    raise UnsupportedByTarget(msg)


def step_body(step: StepIR) -> Expression:
    """A Tier 2 body with its parameters substituted, for any target.

    Public because the SELECT is target-neutral while the envelope around it is
    not: SQLMesh wraps it in ``MODEL (...)`` and dbt in a ``config()`` call, and
    the parameter substitution underneath must be the one thing both share
    (RFC 0008 D4).
    """
    return _with_parameters(step)


def step_output_relation(output: StepOutputIR, ctx: EmitContext) -> tuple[str, str]:
    """``(namespace, relation)`` for one output, under the naming policy."""
    return ctx.naming.relation(_relation_name(output), Layer.SILVER)


def refuse_mart_asserts(ir: ProjectIR, target: str) -> None:
    """Refuse a mart assertion on a target that cannot emit it (RFC 0016 D89).

    An assertion lowers to an audit over a grouped aggregate, and dbt's schema
    tests are per-column or per-model *predicates* — there is no grouped form to
    approximate it with. dbt **builds** the mart, so a gate it silently does not
    emit is a gate that does not exist (RFC 0008 D3).

    Cube is not a caller: it builds nothing, emits no audit for anything, and
    refusing it here would single out one check among the many this emitter
    already leaves to whoever maintains the tables (RFC 0017 D52).
    """
    declared = [f"{mart.name}.{clause.name}" for mart in ir.marts for clause in mart.asserts]
    if not declared:
        return
    msg = (
        f"mart assertion(s) {', '.join(sorted(declared))} lower to a SQLMesh audit, which "
        f"the {target} target cannot emit (RFC 0016 D89). Compiling anyway would ship a "
        "project whose declared data-quality gate does not exist. Fix: compile for "
        "SQLMesh, or drop the assert: block for this target"
    )
    raise UnsupportedByTarget(msg)


# The wrapper is Python, so the envelope interpolates *pre-rendered* strings
# exactly as the SQL envelopes do (RFC 0008 D4) — the manifest arrives as a
# JSON literal built by json.dumps, never as template-formatted values.
_WRAPPER = jinja2.Template(  # nosec B701
    '''\
# Generated by bloomery — do not edit.
# fingerprint: {{ fingerprint }}
"""SQLMesh Python model for step {{ ref }}@{{ version }}, output {{ output_name }}.

bloomery emits this wrapper; it never executes the step (RFC 0003). The
contract assertion below is generated and non-optional by construction — see
RFC 0017 §5.4.
"""

from __future__ import annotations

import typing

from sqlmesh import model


@model(
    {{ relation }},
    kind="FULL",
    columns={{ columns }},{% if audits %}
    audits={{ audits }},
    # Declared because an audit reads the sibling: SQLMesh substitutes
    # physical snapshot tables only for relations in the audited model's
    # depends_on, so without this the audit resolves `silver.customer` to a
    # virtual-layer view that does not exist on a first plan — failing the run
    # it exists to protect — and on later plans compares against the *promoted*
    # view rather than this plan's data. Inference is replaced, not extended,
    # so the read relations are listed too.
    depends_on={{ depends_on }},{% endif %}
)
def execute(context: typing.Any, **kwargs: typing.Any) -> typing.Any:
    # Every name this function needs is bound *inside* it, deliberately.
    # SQLMesh computes a Python model's dependencies by serializing the module
    # globals the function references and rebuilding them in a fresh
    # environment; a global holding a non-literal value — a Decimal parameter,
    # say — fails to reconstruct there, and the model does not load at all
    # ("name 'Decimal' is not defined", before anything runs). Local state has
    # nothing to serialize.
    # Every generated name is `_blm_`-prefixed: the entrypoint is imported into
    # this same scope, and a step function called `parameters` or `Decimal`
    # would otherwise shadow the local the next line needs — `Decimal` silently
    # rebinding a value constructor to caller code is the bad one.
    from datetime import date as _blm_date  # noqa: F401
    from datetime import datetime as _blm_datetime  # noqa: F401
    from decimal import Decimal as _blm_Decimal  # noqa: F401, N812

    from bloomery.steps.contract import assert_step_contract as _blm_assert

    from {{ module }} import {{ function }}

    _blm_manifest = {{ manifest }}
    _blm_parameters = {{ parameters }}
    _blm_inputs = { {%- for name, relation in inputs %}
        {{ name }}: context.fetchdf(
            f"SELECT * FROM {context.table({{ relation }})}"
        ),{% endfor %}
    }
    _blm_outputs = {{ function }}(**_blm_inputs, **_blm_parameters)
    _blm_assert(_blm_outputs, _blm_manifest)
    return _blm_outputs[{{ output }}]
''',
    autoescape=False,
)


# A whole-query audit body: the SELECT returns violating rows and the audit
# passes when there are none — the same shape RFC 0016's blocking audits use,
# and the SQL arrives pre-rendered through the dialect port (RFC 0008 D4).
_AUDIT = jinja2.Template(  # nosec B701
    """\
-- Generated by bloomery — do not edit.
-- fingerprint: {{ fingerprint }}
AUDIT (
  name {{ name }}
);

{{ select }}
""",
    autoescape=False,
)


def _python_literal(value: object) -> str:
    """A deterministic Python literal for the wrapper.

    ``repr`` over canonically sorted structures. The obvious alternative —
    ``json.dumps`` then patching ``true``/``false``/``null`` back to Python's
    spelling — is what this used to do, and it edited *string contents* too:
    a column named ``id, null`` came out as ``id, None``, so the embedded
    manifest and the SQLMesh ``columns=`` named a column that does not exist
    and a *correct* step failed its own contract at run time. The wrapper
    still parsed, so no ``ast``-based test noticed.

    ``repr`` is also the escaping boundary. Nothing here interpolates a spec
    value into source text by hand: values arrive from an authored spec, and
    §5.3/D3's promise is that such a spec can never become an
    arbitrary-code-execution surface.
    """
    if isinstance(value, dict):
        pairs = cast("dict[object, object]", value)
        items = ", ".join(
            f"{_python_literal(key)}: {_python_literal(item)}"
            for key, item in sorted(pairs.items(), key=lambda pair: str(pair[0]))
        )
        return "{" + items + "}"
    if isinstance(value, (list, tuple)):
        members: Sequence[object] = cast("Sequence[object]", value)
        return "[" + ", ".join(_python_literal(item) for item in members) + "]"
    if isinstance(value, (str, bool, int)) or value is None:
        return repr(value)
    msg = f"unsupported value in a generated wrapper literal: {type(value).__name__}"
    raise TypeError(msg)


def _manifest_literal(step: StepIR) -> str:
    """The manifest as plain data the wrapper embeds.

    Plain data rather than a re-parsed :class:`StepManifest` so the step
    runtime needs neither pydantic nor bloomery's spec layer to verify a
    contract (D12). Only what the assertion reads is carried — outputs, their
    keys and their produced columns — because anything else would be a second
    copy of the manifest going stale in a generated file.
    """
    return _python_literal(
        {
            "ref": step.ref,
            "version": step.version,
            "outputs": {
                output.name: {
                    "key": list(output.key),
                    "produces": {
                        column.name: {
                            "type": render_type(column.type),
                            "required": column.required,
                        }
                        for column in output.columns
                    },
                }
                for output in step.outputs
            },
        }
    )


def _columns_literal(output: StepOutputIR, ctx: EmitContext) -> str:
    """The SQLMesh ``columns=`` mapping — physical types through the dialect
    port, so a step model declares its schema the same way every other model
    does."""
    return _python_literal(
        {column.name: ctx.dialect.physical_type(column.type) for column in output.columns}
    )


#: How each declared parameter type is reconstructed in the wrapper. The IR
#: holds values as text (canon bytes never meet a float, RFC 0003 D5), but a
#: step body must be *called* with the real thing — a ``threshold`` declared
#: ``decimal`` has to arrive as ``Decimal("0.9")``, not as the string
#: ``"0.9"``, or every comparison inside the step is a type error waiting for
#: the first run.
#:
#: Every entry wraps a ``repr``-produced literal, never a raw value. Building
#: these by string interpolation let an authored parameter close the quote and
#: append an expression — ``PARAMETERS = {"label": "ACME" + __import__("os")…}``
#: parsed and ran. §5.3/D3's promise is that a spec cannot become an
#: arbitrary-code-execution surface, and it is only true if this function
#: holds it.
_PARAMETER_CTORS: Final[dict[str, str]] = {
    "decimal": "_blm_Decimal({literal})",
    "date": "_blm_date.fromisoformat({literal})",
    "timestamp": "_blm_datetime.fromisoformat({literal})",
}


def _parameter_expression(parameter: StepParameterIR) -> str:
    base = parameter.type.split("(", 1)[0].strip()
    if base == "bool":
        return repr(parameter.value.strip().lower() in {"true", "1"})
    if base == "int":
        # Validated at lowering; repr of the parsed int rather than the text,
        # so nothing an author wrote reaches the source unquoted.
        return repr(int(parameter.value))
    template = _PARAMETER_CTORS.get(base)
    if template is None:
        return repr(parameter.value)
    return template.format(literal=repr(parameter.value))


def _with_parameters(step: StepIR) -> Expression:
    """The Tier 2 body with its ``:name`` placeholders substituted.

    Lowering has already refused any disagreement between the placeholders and
    the declared parameters, so every placeholder found here has a value and
    every value is used.
    """
    if step.body is None:  # pragma: no cover — lowering refuses a bodiless Tier 2 step
        msg = f"step {step.ref}@{step.version} is a sql_model with no body"
        raise ValueError(msg)
    values = {parameter.name: parameter for parameter in step.parameters}

    def _substitute(node: Expression) -> Expression:
        if isinstance(node, exp.Placeholder) and isinstance(node.this, str):
            parameter = values.get(node.this)
            if parameter is not None:
                return parameter_literal(parameter.value, parameter.type)
        return node

    return step.body.ast().transform(_substitute)


def _parameters_literal(step: StepIR) -> str:
    """Resolved parameters as a Python dict *expression*, typed per the
    manifest.

    The seed is passed as an ordinary parameter because that is what it is:
    the step draws from it, and every wrapper for the step passes the same
    recorded value — which is precisely what makes N executions of a seeded
    step agree (D16).
    """
    entries = [f"{_python_literal(p.name)}: {_parameter_expression(p)}" for p in step.parameters]
    if step.seed is not None:
        entries.append(f"{_python_literal('seed')}: {step.seed:d}")
    return "{" + ", ".join(entries) + "}"


def _wrapper_artifact(
    step: StepIR,
    output: StepOutputIR,
    ir: ProjectIR,
    ctx: EmitContext,
    audits: tuple[str, ...] = (),
    reads: tuple[str, ...] = (),
) -> EmittedArtifact:
    del ir
    namespace, relation = ctx.naming.relation(_relation_name(output), Layer.SILVER)
    module, function = (step.entrypoint or ":").split(":", 1)
    content = _WRAPPER.render(
        fingerprint=ctx.fingerprint,
        ref=step.ref,
        version=step.version,
        output=_python_literal(output.name),
        # The docstring is prose, so it carries the *name*; every other use is
        # escaped. Both are safe only because the manifest validator forbids a
        # non-identifier output name — belt and braces, since this file writes
        # executable text (D25).
        output_name=output.name,
        relation=_python_literal(f"{namespace}.{relation}"),
        manifest=_manifest_literal(step),
        parameters=_parameters_literal(step),
        columns=_columns_literal(output, ctx),
        # An audit nothing references never runs: SQLMesh loads a bare AUDIT
        # as a *model* audit, executed only where a model's `audits` names it.
        audits=_python_literal(list(audits)) if audits else "",
        depends_on=_python_literal(sorted(reads)) if audits else "",
        module=module,
        function=function,
        inputs=tuple(
            (_python_literal(name), _python_literal(_bound(bound, ctx)))
            for name, bound in step.inputs
        ),
    )
    return EmittedArtifact.create(
        path=f"models/{namespace}/{relation}.py",
        content=content.rstrip("\n") + "\n",
        kind=ArtifactKind.MODEL,
    )


def _bound(relation: str, ctx: EmitContext) -> str:
    """An input binding as the naming policy spells it.

    The output side has always gone through the policy; the input side did
    not, so under a scoping policy a wrapper wrote ``acme_silver.customer``
    and read plain ``silver.customer_raw`` — two different relations, one of
    which may not exist.
    """
    namespace, name = ctx.naming.relation(relation.rsplit(".", 1)[-1], Layer.SILVER)
    return f"{namespace}.{name}"


def _relation_name(output: StepOutputIR) -> str:
    """The bare relation a bound output writes to.

    The wiring binds a qualified name (``silver.customer``); the naming policy
    owns the namespace, so only the last segment is handed to it — otherwise
    a policy that prefixes namespaces would produce ``silver.silver_customer``.
    """
    return output.relation.rsplit(".", 1)[-1]


def _sql_model_artifact(
    step: StepIR,
    output: StepOutputIR,
    ctx: EmitContext,
    envelope: jinja2.Template,
    audits: tuple[str, ...] = (),
    reads: tuple[str, ...] = (),
) -> EmittedArtifact:
    namespace, relation = ctx.naming.relation(_relation_name(output), Layer.SILVER)
    content = envelope.render(
        fingerprint=ctx.fingerprint,
        name=f"{namespace}.{relation}",  # constrained by RELATION_PATTERN
        kind="FULL",
        grain=", ".join(output.key),
        partitioned_by="",
        audits=", ".join(audits),
        depends_on=", ".join(sorted(reads)) if audits else "",
        select=ctx.dialect.render(_with_parameters(step)) if step.body is not None else "",
    )
    return EmittedArtifact.create(
        path=f"models/{namespace}/{relation}.sql",
        content=content.rstrip("\n") + "\n",
        kind=ArtifactKind.MODEL,
    )


#: Aliases for the two sides of a consistency audit. Fixed rather than derived
#: from the output names, which are only identifiers — two outputs could
#: otherwise alias to the same thing.
_PARENT_ALIAS = "_parent"
_CHILD_ALIAS = "_child"


def _qualified(output: StepOutputIR, ctx: EmitContext) -> str:
    """The relation an output writes, as the naming policy spells it."""
    namespace, relation = ctx.naming.relation(_relation_name(output), Layer.SILVER)
    return f"{namespace}.{relation}"


def _audit_relation(output: StepOutputIR, ctx: EmitContext) -> exp.Table:
    """The relation an output writes, as the naming policy spells it.

    Through the policy because every other step path is — the wrapper's
    `@model` name, its `context.table(...)` read, the `sql_model` envelope.
    An audit reading the authored binding instead would query a relation that
    a scoping policy means does not exist, which is the defect D34 fixed on
    the input side and this repeated on the audit side.
    """
    return exp.to_table(_qualified(output, ctx))


def _consistency_select(
    parent: StepOutputIR, child: StepOutputIR, column: str, ctx: EmitContext
) -> exp.Select:
    """Rows of ``child`` whose ``column`` has no match in ``parent``'s key —
    the audit passes when there are none.

    NULL references are excluded, the same three-valued discipline RFC 0016
    applies to ``referential``: a row with no reference is not an orphan, it
    is a row that says nothing, and failing a blocking audit on it would
    punish the ordinary case.
    """
    (key,) = parent.key
    exists = (
        exp.Select()
        .select(exp.Literal.number(1))
        .from_(exp.alias_(_audit_relation(parent, ctx), _PARENT_ALIAS))
        .where(
            exp.EQ(
                this=exp.column(key, table=_PARENT_ALIAS),
                expression=exp.column(column, table=_CHILD_ALIAS),
            )
        )
    )
    return (
        exp.Select()
        .select(exp.column(column, table=_CHILD_ALIAS))
        .from_(exp.alias_(_audit_relation(child, ctx), _CHILD_ALIAS))
        .where(
            exp.and_(
                is_not_null(exp.column(column, table=_CHILD_ALIAS)),
                exp.Not(this=exp.Exists(this=exists)),
            )
        )
    )


def _audit_name(child: StepOutputIR, column: str, parent: StepOutputIR) -> str:
    """Namespaced under ``step_`` so it cannot collide with an RFC 0016
    quality audit, whose names are ``<entity>_<rule>`` over author-chosen
    parts. Two audits at one path is the two-writers collision D28 refuses for
    relations, arrived at through the audit namespace."""
    return f"step_{_relation_name(child)}_{column}_references_{_relation_name(parent)}"


#: The alias a step-output quality audit reads its own relation under. Fixed,
#: like the consistency audit's pair, so the authored predicate is qualified
#: against one known name.
_OUTPUT_ALIAS = "_output"


def _quality_audit_name(output: StepOutputIR, rule: QualityRuleIR) -> str:
    """``step_<output>_<rule>`` — under the same ``step_`` namespace the
    consistency audits use, so an authored rule name cannot collide with an
    RFC 0016 audit (``<entity>_<rule>``) on a mapped entity of the same name.
    """
    return f"step_{_relation_name(output)}_{rule.name}"


def quality_audits(
    step: StepIR, ir: ProjectIR, ctx: EmitContext
) -> tuple[tuple[str, EmittedArtifact], ...]:
    """Blocking audits for ``on_fail: fail`` rules on step outputs (D39),
    returned with the output each is attached to.

    Only ``fail`` reaches here — lowering refuses ``flag`` and ``quarantine``,
    which compile into a silver SELECT that a step-produced relation does not
    have. ``fail`` needs no SELECT: it reads the finished relation and returns
    the rows that violate the rule, which is what a blocking audit is.

    Deliberately *not* RFC 0016's two-leg :func:`fail_audits` shape. Both of
    that function's legs are unavailable here rather than merely unnecessary:
    there is no staged bronze extract to read the evaluated population from —
    the wrapper writes the rows in Python — and no ``_quality_flags`` column to
    read a recorded verdict out of, because the manifest's ``produces`` is the
    entity's whole column set. One leg over the relation itself is the honest
    whole of what can be checked, and it is the population that matters: the
    rows the step actually produced.

    The relation is addressed through ``@this_model``, never through the
    naming policy. That is the doctrine ``lowering.py`` states and D44 had to
    relearn on the consistency audit: a policy-spelled relation resolves to a
    virtual-layer view rather than the plan\'s snapshot.
    """
    rules = {
        entity.name: entity.quality for entity in ir.entities if entity.produced_by is not None
    }
    emitted: list[tuple[str, EmittedArtifact]] = []
    for output in step.outputs:
        for rule in rules.get(_relation_name(output), ()):
            if rule.on_fail is not OnFail.FAIL:  # pragma: no cover — lowering refuses these
                continue
            name = _quality_audit_name(output, rule)
            select = (
                exp.Select()
                .select(exp.Star())
                .from_(
                    # Unquoted: `@` is not an identifier character, and a
                    # quoted macro is a table named `@this_model`.
                    exp.Table(this=exp.to_identifier(THIS_MODEL, quoted=False), alias=_OUTPUT_ALIAS)
                )
                .where(verdict(rule, _OUTPUT_ALIAS))
            )
            content = _AUDIT.render(
                fingerprint=ctx.fingerprint,
                name=name,
                select=ctx.dialect.render(select),
            )
            emitted.append(
                (
                    output.name,
                    EmittedArtifact.create(
                        path=f"audits/{name}.sql",
                        content=content.rstrip("\n") + "\n",
                        kind=ArtifactKind.AUDIT,
                    ),
                )
            )
    return tuple(emitted)


def consistency_audits(step: StepIR, ctx: EmitContext) -> tuple[tuple[str, EmittedArtifact], ...]:
    """Blocking audits that sibling outputs of one step agree (RFC 0017 D16),
    returned with the **child output** each one must be attached to.

    D16 accepts a real residual risk: each output gets its own wrapper, so the
    step runs N times, and that is only safe for a *correctly declared* step.
    A step misdeclared as ``pure`` can produce **disagreeing siblings within a
    single run** — a ``customer_xref`` referencing ``canonical_id``s the
    ``customer`` execution never minted. Every behavioural gate compares run
    to run, so none can see it; ``assert_step_contract`` cannot either,
    because each output is individually valid and only their relationship is
    wrong.

    Emitted only for references the manifest **declares**. Inferring them from
    "one output carries another's key columns" fabricates relationships from
    coincidence: two outputs both keyed ``id`` would get a mutual pair of
    audits asserting their id sets are identical, failing every run on correct
    data — the failure that teaches people to ignore audits.

    The name is returned beside the artifact because an audit nothing
    references never runs: SQLMesh loads a bare ``AUDIT`` as a *model* audit,
    executed only when a model's ``audits`` list names it.
    """
    # No `len(outputs) < 2` shortcut: a single output declares no
    # references (the manifest validator refuses a self-reference), so the
    # loop below is already empty for it. The guard was dead code its own
    # test passed without.
    emitted: list[tuple[str, EmittedArtifact]] = []
    by_name = {output.name: output for output in step.outputs}
    for child in step.outputs:
        for column, target in child.references:
            parent = by_name.get(target)
            if parent is None:  # pragma: no cover — the manifest validator refuses this
                continue
            name = _audit_name(child, column, parent)
            content = _AUDIT.render(
                fingerprint=ctx.fingerprint,
                name=name,
                select=ctx.dialect.render(_consistency_select(parent, child, column, ctx)),
            )
            emitted.append(
                (
                    child.name,
                    EmittedArtifact.create(
                        path=f"audits/{name}.sql",
                        content=content.rstrip("\n") + "\n",
                        kind=ArtifactKind.AUDIT,
                    ),
                )
            )
    return tuple(emitted)


def step_artifacts(
    ir: ProjectIR, ctx: EmitContext, envelope: jinja2.Template
) -> tuple[EmittedArtifact, ...]:
    """Every artifact the project's steps contribute, sorted by path.

    ``sql_macro`` contributes none — it lives inside a consuming model's
    SELECT (§5.1), which is the whole point of the tier.
    """
    artifacts: list[EmittedArtifact] = []
    for step in ir.steps:
        if step.kind is StepKind.SQL_MACRO:
            continue
        audits_by_output: dict[str, list[str]] = {}
        for owner, artifact in (*consistency_audits(step, ctx), *quality_audits(step, ir, ctx)):
            artifacts.append(artifact)
            # The audit is attached to the *child* — the output holding the
            # reference — because that is the model whose rows it judges.
            audits_by_output.setdefault(owner, []).append(
                artifact.path.removeprefix("audits/").removesuffix(".sql")
            )
        by_name = {output.name: output for output in step.outputs}
        for output in step.outputs:
            attached = tuple(sorted(audits_by_output.get(output.name, ())))
            # Inference is replaced by an explicit depends_on, so the relations
            # the model reads must be listed alongside the siblings its audits
            # read — otherwise `context.table(...)` has nothing to resolve.
            reads = tuple(
                sorted(
                    {_bound(relation, ctx) for _name, relation in step.inputs}
                    | {
                        _qualified(by_name[target], ctx)
                        for _column, target in output.references
                        if target in by_name
                    }
                )
            )
            if step.kind is StepKind.PYTHON_MODEL:
                artifacts.append(_wrapper_artifact(step, output, ir, ctx, attached, reads))
            else:
                artifacts.append(_sql_model_artifact(step, output, ctx, envelope, attached, reads))
    return tuple(sorted(artifacts, key=lambda a: a.path))
