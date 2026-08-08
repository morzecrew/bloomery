"""Step outputs as entities (RFC 0017 §5.8).

§5.8's claim is that "step outputs are entities in the DAG: downstream
mappings, marts, and metrics reference them like any silver entity". That was
prose for a while — outputs lived only inside ``StepIR``, so a mart over one
was refused with "no mapping lowers it" and §5.4's promise that downstream
models typecheck against ``produces`` was not true. These tests are what makes
the claim checkable.
"""

from __future__ import annotations

import dataclasses

import pytest

from bloomery import build_project_ir, load_project, plan
from bloomery.ir import Materialization, SCDKind
from bloomery.plan import ChangeClass
from bloomery.steps import StepRegistry
from support.compiling import compile_fixture, fixture_sources
from support.steps import RESOLVE_CUSTOMERS, registry_for

pytestmark = pytest.mark.unit

ENTITY_MODEL = "spec_version: 1\nentities: {}\n"
WIRING = (
    "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
    "    inputs: {raw: silver.customer_raw}\n"
    "    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}\n"
)


def ir_of(**extra: str):  # noqa: ANN201 — ProjectIR
    docs = {"entity_model": ENTITY_MODEL, "steps": WIRING, **extra}
    registry = StepRegistry({("resolve_customers", 3): RESOLVE_CUSTOMERS})
    return build_project_ir(load_project(docs), steps=registry)


def test_each_output_becomes_an_entity() -> None:
    entities = {e.name: e for e in ir_of().entities}
    assert sorted(entities) == ["customer", "customer_xref"]
    assert entities["customer"].key == ("canonical_id",)
    assert [c.name for c in entities["customer"].columns] == ["canonical_id", "confidence"]


def test_a_synthesized_entity_says_which_step_writes_it() -> None:
    """Without the marker the emitter's entity loop would emit a second model
    at the wrapper's path — the collision refused everywhere else."""
    entities = {e.name: e for e in ir_of().entities}
    assert entities["customer"].produced_by == "resolve_customers@3"
    assert entities["customer"].materialization is Materialization.FULL
    assert entities["customer"].scd is SCDKind.TYPE1


def test_a_mapped_entity_carries_no_marker() -> None:
    project, catalog = compile_fixture("minimal"), None
    del project, catalog
    ir = build_project_ir(load_project(fixture_sources("minimal")))
    assert all(entity.produced_by is None for entity in ir.entities)


def test_the_step_relation_is_emitted_once_by_the_wrapper() -> None:
    """One model per output and no second one: the entity exists for the rest
    of the compiler to reference, and the wrapper owns emission. The `.sql`
    artifact is the D16 consistency audit, not a rival model."""
    models = [
        a.path for a in compile_fixture("step_resolution") if a.path.startswith("models/")
    ]
    assert models == ["models/silver/customer.py", "models/silver/customer_xref.py"]


def test_a_mart_may_be_built_over_a_step_output() -> None:
    """The case that proves §5.8: this was refused with "mart base names
    entity 'customer', which no mapping lowers"."""
    marts = (
        "marts_version: 1\nmarts:\n  customers:\n    grain: customer\n"
        "    base: customer\n    measures: []\n"
    )
    ir = ir_of(marts=marts)
    assert [(m.name, m.base) for m in ir.marts] == [("customers", "customer")]


# ....................... #
# What `plan()` reports (the double-report question, settled)


def test_adding_a_step_reports_both_the_step_and_its_new_entities() -> None:
    """Informative rather than noisy: new relations genuinely did appear, and
    a reader needs their columns before applying."""
    subjects = {c.subject for c in plan(None, ir_of()).changes}
    assert "step:resolve_customers" in subjects
    assert {"entity:customer", "entity:customer_xref"} <= subjects


def test_a_runtime_lock_bump_reports_only_the_step() -> None:
    """The noisy case, and it does not double-report: the synthesized entity
    is byte-identical across the bump, so only the step diffs."""
    before = ir_of()
    after = dataclasses.replace(
        before, steps=(dataclasses.replace(before.steps[0], runtime_lock="sha256:beef"),)
    )
    changes = plan(before, after).changes
    assert [c.subject for c in changes] == ["step:resolve_customers"]
    assert changes[0].change_class is ChangeClass.RESTATING


def test_the_identity_plan_stays_empty_with_steps() -> None:
    """RFC 0007 D2 is normative and has to survive the new entity kind."""
    ir = ir_of()
    assert plan(ir, ir).changes == ()
