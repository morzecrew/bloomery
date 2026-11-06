"""An optional step input (#402, S-0034/D-61).

A platform step serving projects with and without a source declares the input
optional, with typed columns. A wiring may leave it out, and the body then reads
an empty relation of those columns wherever it names the input, so one body
serves both kinds of project with no conditionals in it.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from bloomery import Target, build_project_ir, compile_project, load_project, plan
from bloomery.errors import StepError
from bloomery.naming import PrefixNaming
from bloomery.plan import ChangeClass
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

ENTITY_MODEL = """spec_version: 1
entities:
  order_line:
    grain: one row per order line
    key: [line_id]
    fields:
      line_id: {type: string, required: true}
      product_id: {type: string}
      quantity: {type: int}
  return_line:
    grain: one row per returned line
    key: [return_id]
    fields:
      return_id: {type: string, required: true}
      product_id: {type: string}
      quantity: {type: int}
"""

MAPPINGS = {
    "mapping_lines": (
        "mapping_version: 1\nsource: shop__lines\ntarget: order_line\n"
        'key:\n  line_id: {from: "$.id"}\n'
        'fields:\n  product_id: {from: "$.product_id"}\n  quantity: {from: "$.quantity"}\n'
    ),
    "mapping_returns": (
        "mapping_version: 1\nsource: shop__returns\ntarget: return_line\n"
        'key:\n  return_id: {from: "$.id"}\n'
        'fields:\n  product_id: {from: "$.product_id"}\n  quantity: {from: "$.quantity"}\n'
    ),
}

RETURNS: dict[str, object] = {
    "grain": "return_line",
    "optional": True,
    "columns": {"product_id": "string", "quantity": "int"},
}


def manifest(returns: dict[str, object] | None = None, **overrides: object) -> StepManifest:
    base: dict[str, object] = {
        "ref": "net_units",
        "version": 1,
        "kind": "sql_model",
        "determinism": "pure",
        "runtime_lock": "sha256:x",
        "inputs": {
            "lines": {"grain": "order_line", "requires": ["product_id", "quantity"]},
            "returns": RETURNS if returns is None else returns,
        },
        "outputs": {
            "net": {
                "grain": "one row per product",
                "key": ["product_id"],
                "produces": {"product_id": {"type": "string"}, "units": {"type": "int"}},
            }
        },
    }
    return StepManifest.model_validate(base | overrides)


#: Names the optional input by its name, as the input it is, and the required
#: one by the relation its wiring binds, as every body did before.
BODY = (
    "SELECT l.product_id, SUM(l.quantity) - COALESCE(MAX(r.quantity), 0) AS units "
    "FROM silver.order_line AS l LEFT JOIN returns AS r ON r.product_id = l.product_id "
    "GROUP BY l.product_id"
)


def wiring(*, returns: bool) -> str:
    bound = ", returns: silver.return_line" if returns else ""
    return (
        "steps_version: 1\nsteps:\n  - use: net_units@1\n"
        f"    inputs: {{lines: silver.order_line{bound}}}\n"
        "    outputs: {net: silver.net_units}\n"
    )


def project(*, returns: bool, entity_model: str = ENTITY_MODEL):  # noqa: ANN201 — Project
    mappings = MAPPINGS if returns else {"mapping_lines": MAPPINGS["mapping_lines"]}
    return load_project({"entity_model": entity_model, **mappings, "steps": wiring(returns=returns)})


def registry(body: str = BODY, **overrides: object) -> StepRegistry:
    return StepRegistry({("net_units", 1): manifest(**overrides)}, sql_bodies={("net_units", 1): body})


def step_model(target: str, *, returns: bool, dialect: str = "duckdb") -> str:
    artifacts = compile_project(
        project(returns=returns),
        target=target,
        dialect=dialect,
        naming=PrefixNaming("t0"),
        steps=registry(),
    )
    return flat(next(a.content for a in artifacts if a.path.endswith("/net_units.sql")))


def flat(sql: str) -> str:
    """The emitted query on one line, as the assertions spell it."""
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", " ".join(sql.split())))


# ....................... #
# The manifest


@pytest.mark.parametrize(
    ("returns", "match"),
    [
        ({"grain": "return_line", "optional": True}, "declares no columns"),
        ({"grain": "return_line", "columns": {"quantity": "int"}}, "only an optional input"),
        (RETURNS | {"requires": ["quantity"]}, "its columns are what it requires"),
        (RETURNS | {"columns": {"quantity": "integer"}}, "integer"),
    ],
)
def test_an_optional_input_is_declared_with_its_typed_columns_alone(
    returns: dict[str, object], match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        manifest(returns)


def test_only_a_sql_model_reads_an_optional_input() -> None:
    """A python_model's wrapper reads every input as a bound relation."""
    with pytest.raises(ValidationError, match="only a sql_model"):
        manifest(kind="python_model", entrypoint="platform.steps:net")


# ....................... #
# Unbound


def test_a_wiring_may_leave_an_optional_input_unbound() -> None:
    (step,) = build_project_ir(project(returns=False), steps=registry()).steps
    assert step.inputs == (("lines", "silver.order_line"),)


def test_a_wiring_must_still_bind_every_required_input() -> None:
    text = wiring(returns=True).replace("lines: silver.order_line, ", "")
    wired = load_project({"entity_model": ENTITY_MODEL, **MAPPINGS, "steps": text})

    with pytest.raises(StepError, match=r"does not bind input\(s\) lines the"):
        build_project_ir(wired, steps=registry())


@pytest.mark.parametrize("target", ["sqlmesh", "dbt"])
def test_an_unbound_optional_input_reads_as_an_empty_relation_of_its_columns(target: str) -> None:
    model = step_model(target, returns=False)

    assert (
        "LEFT JOIN (SELECT * FROM (SELECT CAST(NULL AS TEXT) AS product_id, "
        "CAST(NULL AS BIGINT) AS quantity) AS _blm_empty WHERE FALSE) AS r"
    ) in model
    assert "return_line" not in model


def test_the_empty_relation_spells_its_types_for_the_target_s_engine() -> None:
    model = step_model("sqlmesh", returns=False, dialect="bigquery")
    assert "CAST(NULL AS STRING) AS product_id, CAST(NULL AS INT64) AS quantity" in model


def test_an_unaliased_read_keeps_the_input_s_name() -> None:
    """Columns the body qualifies by the input's name still resolve."""
    body = (
        "SELECT l.product_id, SUM(l.quantity) - COALESCE(MAX(returns.quantity), 0) AS units "
        "FROM silver.order_line AS l LEFT JOIN returns ON returns.product_id = l.product_id "
        "GROUP BY l.product_id"
    )
    artifacts = compile_project(
        project(returns=False), target=Target.SQLMESH, dialect="duckdb", steps=registry(body)
    )
    model = flat(next(a.content for a in artifacts if a.path.endswith("/net_units.sql")))
    assert re.search(r"WHERE FALSE\) AS returns ON returns\.product_id", model)


def test_an_unquoted_name_folds_to_the_input_s() -> None:
    body = BODY.replace("LEFT JOIN returns AS r", "LEFT JOIN RETURNS AS r")
    artifacts = compile_project(
        project(returns=False), target=Target.SQLMESH, dialect="duckdb", steps=registry(body)
    )
    model = flat(next(a.content for a in artifacts if a.path.endswith("/net_units.sql")))
    assert "WHERE FALSE) AS r ON" in model


# ....................... #
# Bound


@pytest.mark.parametrize("target", ["sqlmesh", "dbt"])
def test_a_bound_optional_input_reads_its_relation_through_the_naming_policy(target: str) -> None:
    model = step_model(target, returns=True)
    read = "t0_silver.return_line AS r" if target == "sqlmesh" else "{{ ref('return_line') }} AS r"

    assert read in model
    assert "_blm_empty" not in model


def test_a_bound_optional_input_must_carry_its_columns() -> None:
    lacking = ENTITY_MODEL.replace(
        "      return_id: {type: string, required: true}\n      product_id: {type: string}\n",
        "      return_id: {type: string, required: true}\n",
    )
    mappings = MAPPINGS | {
        "mapping_returns": MAPPINGS["mapping_returns"].replace(
            '  product_id: {from: "$.product_id"}\n', ""
        )
    }
    wired = load_project({"entity_model": lacking, **mappings, "steps": wiring(returns=True)})

    with pytest.raises(StepError, match=r"input 'returns' requires product_id, which 'silver.return_line'"):
        build_project_ir(wired, steps=registry())


@pytest.mark.parametrize(
    ("declared", "bound", "refused"),
    [
        ("int", "string", True),
        ("decimal(14,3)", "decimal(10,2)", False),  # assignable: no digit lost
        ("decimal(10,2)", "decimal(14,3)", True),  # narrowing
        ("variant", "int", False),
    ],
)
def test_a_bound_optional_input_s_columns_must_take_its_types(
    declared: str, bound: str, refused: bool
) -> None:
    entity_model = ENTITY_MODEL.replace(
        "      return_id: {type: string, required: true}\n      product_id: {type: string}\n"
        "      quantity: {type: int}\n",
        f"      return_id: {{type: string, required: true}}\n      product_id: {{type: string}}\n"
        f"      quantity: {{type: '{bound}'}}\n",
    )
    returns = RETURNS | {"columns": {"product_id": "string", "quantity": declared}}
    wired = load_project({"entity_model": entity_model, **MAPPINGS, "steps": wiring(returns=True)})

    if refused:
        with pytest.raises(StepError, match=rf"column quantity is {re.escape(bound)} on 'silver.return_line'"):
            build_project_ir(wired, steps=registry(returns=returns))
    else:
        assert build_project_ir(wired, steps=registry(returns=returns)).steps


# ....................... #
# The body


@pytest.mark.parametrize(
    "body",
    [
        # By the relation a wiring might bind: nothing marks it as the input.
        "SELECT l.product_id, 0 AS units FROM silver.order_line AS l "
        "LEFT JOIN silver.return_line AS r ON r.product_id = l.product_id",
        # A CTE of the input's name is the body's own relation.
        "WITH returns AS (SELECT 'a' AS product_id) SELECT l.product_id, 0 AS units "
        "FROM silver.order_line AS l LEFT JOIN returns ON returns.product_id = l.product_id",
        # A qualified name is a relation, not the input.
        "SELECT l.product_id, 0 AS units FROM silver.order_line AS l "
        "LEFT JOIN silver.returns AS r ON r.product_id = l.product_id",
        # A quoted name in another case is another relation on a case-sensitive engine.
        'SELECT l.product_id, 0 AS units FROM silver.order_line AS l '
        'LEFT JOIN "RETURNS" AS r ON r.product_id = l.product_id',
    ],
)
def test_a_body_must_read_an_optional_input_by_its_name(body: str) -> None:
    """Checked bound or not, so a body that only works while bound is found in
    the project that binds it."""
    with pytest.raises(StepError, match=r"never reads a table named returns"):
        build_project_ir(project(returns=True), steps=registry(body))


# ....................... #
# Plan and lineage


def test_binding_an_optional_input_restates_the_output() -> None:
    old = build_project_ir(project(returns=False), steps=registry())
    new = build_project_ir(project(returns=True), steps=registry())

    result = plan(old, new)
    step = next(change for change in result.changes if change.subject == "step:net_units")

    assert step.change_class is ChangeClass.RESTATING
    assert "net_units" in result.backfill_scope.entities


def test_an_unbound_optional_input_has_no_upstream() -> None:
    from bloomery import resolve

    graph = resolve(project(returns=False), steps=registry()).graph
    feeding = {edge.src.name for edge in graph.edges if edge.label == "step_input"}

    assert feeding
    assert not any(name.startswith("return_line") for name in feeding)
