"""The lineage-namespace guard (RFC 0051 §5.2, D6–D8).

Every node id but an entity field's is kind-prefixed, so an entity named after
one of those four prefixes mints ids in another kind's namespace. The
reservation is unconditional, and it has to hold on both paths that name an
entity: the authored entity model, and a step output named after the relation
its wiring binds.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import GuardrailError, ReservedEntityName
from bloomery.ir import NODE_ID_PREFIXES
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit


def _entity_model(name: str) -> str:
    return f"""
spec_version: 1
entities:
  {name}:
    grain: one row per thing
    key: [thing_id]
    fields:
      thing_id: {{type: string, required: true}}
      revenue: {{type: string}}
"""


def _mapping(name: str) -> str:
    return f"""
mapping_version: 1
source: raw__things
target: {name}
key:
  thing_id: {{from: "$.id", transform: [to_string]}}
fields:
  revenue: {{from: "$.revenue"}}
"""


def _compile(name: str) -> None:
    build_project_ir(
        load_project({"entity_model": _entity_model(name), "mapping": _mapping(name)})
    )


@pytest.mark.parametrize("name", NODE_ID_PREFIXES)
def test_each_reserved_name_is_refused_for_an_authored_entity(name: str) -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile(name)
    assert isinstance(caught.value.collected[0], ReservedEntityName)


def test_the_refusal_names_the_collision_and_the_way_out() -> None:
    with pytest.raises(GuardrailError, match="reserved as the four node-id prefixes") as caught:
        _compile("metric")
    message = str(caught.value)
    assert "a metric is spelled 'metric.<name>'" in message
    # The witness is a real field of the offending entity, not a placeholder.
    assert "'revenue'" in message
    assert "Fix: rename the entity" in message


def test_an_unreserved_entity_name_compiles() -> None:
    """The reservation is four names, not a naming policy."""
    _compile("thing")


# ....................... #
# The second path to an entity name (D8)


_MANIFEST = {
    "ref": "resolve_things",
    "version": 1,
    "kind": "python_model",
    "determinism": "pure",
    "runtime_lock": "sha256:a91f",
    "entrypoint": "platform_steps.resolve_things:resolve",
    "inputs": {"raw": {"grain": "thing_source_row", "requires": ["thing_id"]}},
    "outputs": {
        "out": {
            "grain": "thing",
            "key": ["thing_id"],
            "produces": {"thing_id": {"type": "string", "required": True}},
        }
    },
}


def _wiring(relation: str) -> str:
    return f"""
steps_version: 1
steps:
  - use: resolve_things@1
    inputs: {{raw: silver.thing_raw}}
    outputs: {{out: {relation}}}
"""


def _compile_step(relation: str) -> None:
    build_project_ir(
        load_project({"entity_model": "spec_version: 1\nentities: {}\n", "steps": _wiring(relation)}),
        steps=StepRegistry({("resolve_things", 1): StepManifest.model_validate(_MANIFEST)}),
    )


def test_a_step_output_bound_to_a_reserved_relation_is_refused() -> None:
    """The spec layer never sees this name — it is the last segment of a bound
    relation — so a check over the authored entity model alone would miss it.
    """
    with pytest.raises(GuardrailError) as caught:
        _compile_step("silver.metric")
    assert isinstance(caught.value.collected[0], ReservedEntityName)


def test_a_step_output_bound_elsewhere_compiles() -> None:
    _compile_step("silver.thing")


def test_the_source_refusal_does_not_claim_a_collision_it_cannot_show() -> None:
    """A bronze extraction's id carries a third segment
    (``source.<relation>.<path>``) and a field name is one identifier, so no
    entity field ever equals one. `source` is still reserved — the rule an
    author remembers is "never a node-id prefix", and one that held for three
    of four names would be learned as four exceptions — but a message
    describing a collision the author can check and find absent is worse than
    no message.
    """
    with pytest.raises(GuardrailError) as caught:
        _compile("source")
    message = str(caught.value)
    assert "mints an id in the source namespace" in message
    assert "are one id" not in message
