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
from bloomery.errors import (
    DuplicateNodeId,
    GuardrailError,
    ReservedEntityName,
    SpecParseError,
)
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


def test_a_step_output_s_refusal_points_at_the_wiring_that_named_it() -> None:
    """The source path has to name a document the author can open.

    A step-synthesized entity has no `entity_model: entities.<name>` entry —
    the name came from `outputs: {out: silver.metric}` in the `steps:`
    document — so pointing there sends the author to a document with nothing
    of that name in it, for a refusal whose whole value is naming the fix.
    """
    with pytest.raises(GuardrailError) as caught:
        _compile_step("silver.metric")
    assert caught.value.collected[0].source_path == "steps: steps.resolve_things@1.outputs"


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


# ....................... #
# RFC 0062 §9 — two nodes, one identity


def _metrics(**bodies: str) -> str:
    lines = ["metrics_version: 1", "metrics:"]
    for name, body in bodies.items():
        lines.append(f"  {name}:")
        lines.extend(f"    {line}" for line in body.strip().splitlines())
    return "\n".join(lines) + "\n"


_SIMPLE = "grain: order\nadditivity: additive\nagg: count\nexpr: order_id"


def _project(metrics: str) -> None:
    """Compile a one-entity project carrying ``metrics``; raises on refusal."""

    build_project_ir(
        load_project(
            {
                "entity_model": _entity_model("order"),
                "metrics": metrics,
            }
        )
    )


def test_a_copied_id_is_refused_naming_both_metrics() -> None:
    """§9's risk: duplicating a spec and forgetting to change ``id:``."""

    with pytest.raises(GuardrailError) as raised:
        _project(
            _metrics(
                revenue=f"id: mtr_1\n{_SIMPLE}",
                revenue_net=f"id: mtr_1\n{_SIMPLE}",
            )
        )

    duplicates = [e for e in raised.value.collected if isinstance(e, DuplicateNodeId)]
    assert len(duplicates) == 1
    assert "'revenue', 'revenue_net'" in str(duplicates[0])
    assert "metric.mtr_1" in str(duplicates[0])


def test_an_id_equal_to_another_metrics_name_is_refused() -> None:
    """The collision partial adoption makes likely, which §9 does not name.

    One metric adopts ``id: revenue``; another is *named* ``revenue`` and
    adopts nothing. Both mint ``metric.revenue``. Comparing ids to each other
    would miss this entirely — there is only one id.
    """

    with pytest.raises(GuardrailError) as raised:
        _project(
            _metrics(
                revenue=_SIMPLE,
                revenue_net=f"id: revenue\n{_SIMPLE}",
            )
        )

    duplicates = [e for e in raised.value.collected if isinstance(e, DuplicateNodeId)]
    assert len(duplicates) == 1
    assert "metric.revenue" in str(duplicates[0])


def test_an_id_equal_to_a_renamed_metrics_old_name_is_accepted() -> None:
    """The control, and the reason the check reads keys rather than ids.

    ``revenue`` carries ``id: net`` and ``net`` carries ``id: gross``: the keys
    are ``net`` and ``gross``, which do not collide. A rule comparing ids to
    names would refuse this legal project — and it is the shape a rollout
    produces, where an id is chosen to match a name something else already has.
    """

    _project(
        _metrics(
            revenue=f"id: net\n{_SIMPLE}",
            net=f"id: gross\n{_SIMPLE}",
        )
    )


def test_two_kinds_sharing_a_key_do_not_collide() -> None:
    """``metric.`` and ``canonical.`` are separate namespaces.

    Checking across kinds would refuse a project whose metric and canonical
    field happen to share a name, which every project is free to do today.
    """

    _project(_metrics(unit_price=f"id: shared\n{_SIMPLE}"))


def test_an_empty_id_is_refused_rather_than_minting_a_bare_prefix() -> None:
    """An id that identifies nothing is not an identity.

    ``id: ""`` passed the opacity rule — it is a string, compared and never
    parsed — and minted the node id ``metric.``, which is the prefix and
    nothing else. The metric then answers to a name no reader would guess and
    disappears from every lookup of its own name, with no refusal anywhere.

    Non-emptiness is a boundary constraint, not the parsing D2 forbids: nothing
    reads *into* the value, and any non-empty string is still accepted whatever
    it contains.

    It refuses at **parse**, not here, which is where a shape rule belongs
    (RFC 0002 D4) and is earlier than the stage this module's other refusals
    reach. The test lives beside them because the defect it prevents is a node
    id, and that is what a reader looking for this will be reading about.
    """

    with pytest.raises(SpecParseError) as raised:
        _project(_metrics(revenue=f'id: ""\n{_SIMPLE}'))

    assert "at least 1 character" in str(raised.value)


def test_a_duplicate_points_at_one_of_the_colliding_specs() -> None:
    """The refusal's ``source_path`` follows the document convention.

    A bare ``metrics`` sends an author to a file and leaves them to find which
    of its entries is at fault; the message names every claimant and the path
    anchors on the first, which is what every other guardrail in this stage
    does.
    """

    with pytest.raises(GuardrailError) as raised:
        _project(
            _metrics(
                revenue=f"id: mtr_1\n{_SIMPLE}",
                revenue_net=f"id: mtr_1\n{_SIMPLE}",
            )
        )

    duplicates = [e for e in raised.value.collected if isinstance(e, DuplicateNodeId)]
    assert duplicates[0].source_path == "metrics: metrics.revenue"


def test_a_node_kind_with_no_population_raises_rather_than_going_unchecked() -> None:
    """The kind lists in ``node_keys`` and in the refusal must stay in step.

    Both enumerate the same three kinds, so reverting the refusal to iterate its
    own list changed no test (`logs/T-0032.md`) — they agree today. What the
    guard buys is the day they do not: a kind added to the key map and forgotten
    here would be a kind whose collisions nobody checks, and silence is the one
    outcome a duplicate-detector must not have.
    """

    from unittest.mock import patch

    from bloomery.guardrails import lineage

    with patch.object(
        lineage, "node_keys", return_value={"metric": {}, "canonical": {}, "step": {}, "mart": {}}
    ), pytest.raises(KeyError, match="mart"):
        lineage.check_node_ids(load_project({"entity_model": _entity_model("order")}), None)
