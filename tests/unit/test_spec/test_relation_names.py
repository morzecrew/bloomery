"""Entity and mart names are identifiers (RFC 0002 D14).

A field name reaches SQL through SQLGlot, which quotes and escapes it — that
path was always safe and is asserted here so the distinction stays visible. A
*relation* name travels further: it also reaches the SQLMesh ``MODEL (...)``
envelope, which is Jinja over pre-rendered strings and quotes nothing. An
entity named ``t"; DROP TABLE x --`` put those characters into the model
definition verbatim.
"""

from __future__ import annotations

import pytest
import yaml

from bloomery import Target, compile_project, load_project
from bloomery.errors import SpecParseError

pytestmark = pytest.mark.unit

HOSTILE = 't"; DROP TABLE x --'


def entity_model(name: str) -> str:
    return (
        f"spec_version: 1\nentities:\n  {name}:\n    grain: one row per t\n"
        "    key: [k]\n    fields: {k: {type: string, required: true}}\n"
    )


def mapping(name: str) -> str:
    return (
        f"mapping_version: 1\ntarget: {name}\nsource: raw__t\n"
        'key:\n  k: {from: "$.k", transform: [to_string]}\n'
    )


def test_an_entity_name_that_is_not_an_identifier_is_refused() -> None:
    with pytest.raises(SpecParseError, match=r"\^\[a-z\]\[a-z0-9_\]\*\$"):
        load_project({"entity_model": entity_model(HOSTILE), "mapping": mapping(HOSTILE)})


def test_a_mart_name_that_is_not_an_identifier_is_refused() -> None:
    marts = f'marts_version: 1\nmarts:\n  {HOSTILE}:\n    base: t\n    grain: one row per t\n'
    with pytest.raises(SpecParseError):
        load_project(
            {"entity_model": entity_model("t"), "mapping": mapping("t"), "marts": marts}
        )


@pytest.mark.parametrize("name", ["order", "order_item", "dirty_ref_parent", "t2"])
def test_ordinary_names_still_load(name: str) -> None:
    """The control — every shape the fixture corpus actually uses."""
    project = load_project({"entity_model": entity_model(name), "mapping": mapping(name)})
    assert name in project.entity_model.entities


def test_a_field_name_was_never_the_problem() -> None:
    """The other half of the finding, kept because it is what makes the fix
    specific. A hostile *field* name reaches SQL through SQLGlot, which quotes
    it and doubles the inner quote — so it compiles, and it is safe. Only the
    envelope path needed the pattern."""
    hostile_field = 'amt") OR 1=1 --'
    # Dumped rather than hand-written: the name contains a quote, so getting
    # the YAML escaping right by hand is its own bug waiting to happen.
    model = yaml.safe_dump(
        {
            "spec_version": 1,
            "entities": {
                "t": {
                    "grain": "one row per t",
                    "key": ["k"],
                    "fields": {
                        "k": {"type": "string", "required": True},
                        hostile_field: {"type": "string"},
                    },
                }
            },
        }
    )
    mapped = yaml.safe_dump(
        {
            "mapping_version": 1,
            "target": "t",
            "source": "raw__t",
            "key": {"k": {"from": "$.k", "transform": ["to_string"]}},
            "fields": {hostile_field: {"from": "$.a", "transform": ["to_string"]}},
        }
    )
    artifacts = compile_project(
        load_project({"entity_model": model, "mapping": mapped}),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    body = next(a.content for a in artifacts if a.path.endswith(".sql"))
    # Quoted, with the inner quote doubled — the identifier cannot break out.
    assert '"amt"") OR 1=1 --"' in body
