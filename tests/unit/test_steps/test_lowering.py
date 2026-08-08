"""Step lowering and its compile-time refusals (RFC 0017 §5.5–§5.6).

Two things are being pinned. First, that every refusal §5.5 and §5.8 name
actually fires — a determinism tier that is not enforced is documentation.
Second, that the lowered :class:`StepIR` carries *everything that can change
behaviour*, because that — not any special-casing in `plan()` — is the whole
mechanism by which a `runtime_lock` bump restates history (D6, D11, D15).
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import StepDeterminismError, StepError, UnknownStep
from bloomery.ir import Determinism, StepKind, project_fingerprint
from bloomery.steps import StepManifest, StepRegistry
from bloomery.typing import DecimalType, StringType

pytestmark = pytest.mark.unit

ENTITY_MODEL = "spec_version: 1\nentities: {}\n"


def manifest(**overrides: object) -> StepManifest:
    base: dict[str, object] = {
        "ref": "resolve_customers",
        "version": 3,
        "kind": "python_model",
        "determinism": "pure",
        "runtime_lock": "sha256:a91f",
        "entrypoint": "platform_steps.resolve_customers:resolve",
        "inputs": {"raw": {"grain": "customer_source_row", "requires": ["email"]}},
        "outputs": {
            "customer": {
                "grain": "customer",
                "key": ["canonical_id"],
                "produces": {
                    "canonical_id": {"type": "string", "required": True},
                    "confidence": {"type": "decimal(4,3)"},
                },
            }
        },
        "parameters": {"threshold": {"type": "decimal(4,3)", "default": 0.85, "min": 0, "max": 1}},
    }
    return StepManifest.model_validate(base | overrides)


WIRING = """
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs: {raw: silver.customer_raw}
    outputs: {customer: silver.customer}
    parameters: {threshold: 0.9}
"""


def build(wiring: str = WIRING, **manifest_overrides: object):  # noqa: ANN201 — ProjectIR
    project = load_project({"entity_model": ENTITY_MODEL, "steps": wiring})
    registry = StepRegistry({("resolve_customers", 3): manifest(**manifest_overrides)})
    return build_project_ir(project, steps=registry)


# ....................... #
# What the IR carries (§5.6, D11/D15)


def test_the_lowered_step_carries_the_manifest_identity() -> None:
    (step,) = build().steps
    assert (step.ref, step.version) == ("resolve_customers", 3)
    assert step.kind is StepKind.PYTHON_MODEL
    assert step.determinism is Determinism.PURE
    assert step.runtime_lock == "sha256:a91f"
    assert step.entrypoint == "platform_steps.resolve_customers:resolve"


def test_the_output_contract_is_resolved_into_the_ir() -> None:
    """Downstream models typecheck against this, on trust (§5.4) — so the
    types are resolved ``LogicalType``s, the same values a mapped column
    carries, not the manifest's strings."""
    (step,) = build().steps
    (output,) = step.outputs
    assert (output.name, output.relation, output.key) == ("customer", "silver.customer", ("canonical_id",))
    assert [(c.name, c.type, c.required) for c in output.columns] == [
        ("canonical_id", StringType(), True),
        ("confidence", DecimalType(precision=4, scale=3), False),
    ]


def test_a_manifest_default_is_resolved_not_left_implicit() -> None:
    """A step whose behaviour depends on a default must restate when that
    default changes, and it can only do that if the value is recorded (D15)."""
    (step,) = build(WIRING.replace("    parameters: {threshold: 0.9}\n", "")).steps
    assert [(p.name, p.value) for p in step.parameters] == [("threshold", "0.85")]


def test_the_wiring_overrides_the_default() -> None:
    (step,) = build().steps
    assert [(p.name, p.value) for p in step.parameters] == [("threshold", "0.9")]


def test_parameters_are_stringified_never_floats() -> None:
    """RFC 0003 D5 — the canonical encoding raises on a float, so the IR must
    never hold one."""
    (step,) = build().steps
    assert all(isinstance(p.value, str) for p in step.parameters)


def test_a_parameter_carries_its_declared_type() -> None:
    """Text alone cannot be *called* with. A generated wrapper has to hand the
    body a real ``Decimal``, and only the declared type says which
    constructor — so it travels beside the value rather than being guessed
    from how the digits look."""
    (step,) = build().steps
    assert [(p.name, p.type) for p in step.parameters] == [("threshold", "decimal(4,3)")]


# ....................... #
# The fingerprint mechanism (§5.6, D6/D11)


def test_a_runtime_lock_bump_alone_changes_the_fingerprint() -> None:
    """The claim the whole restatement story rests on. Nothing else about the
    project moves — same wiring, same outputs, same parameters — and the
    fingerprint still shifts, because the encoder walks the IR generically."""
    before = project_fingerprint(build())
    after = project_fingerprint(build(runtime_lock="sha256:beef"))
    assert before != after


@pytest.mark.parametrize(
    ("label", "wiring"),
    [
        ("parameter", WIRING.replace("threshold: 0.9", "threshold: 0.8")),
        ("output relation", WIRING.replace("silver.customer", "silver.customer_v2")),
        ("input relation", WIRING.replace("silver.customer_raw", "silver.raw_v2")),
    ],
)
def test_a_wiring_change_changes_the_fingerprint(label: str, wiring: str) -> None:
    """D15: a parameter, seed or wiring change is a RESTATING diff exactly
    like a ``runtime_lock`` bump, and for the same reason — it is in the IR."""
    assert project_fingerprint(build()) != project_fingerprint(build(wiring)), label


def test_a_project_with_no_steps_has_an_empty_tuple() -> None:
    project = load_project({"entity_model": ENTITY_MODEL})
    assert build_project_ir(project).steps == ()


# ....................... #
# Determinism (§5.5, D5) — the load-bearing refusal


def test_a_nondeterministic_step_is_refused() -> None:
    with pytest.raises(StepDeterminismError, match="destroys restatement"):
        build(determinism="nondeterministic")


def test_a_seeded_step_without_a_seed_is_refused() -> None:
    with pytest.raises(StepDeterminismError, match="sets no seed"):
        build(determinism="seeded")


def test_a_seeded_step_with_a_seed_is_accepted_and_records_it() -> None:
    (step,) = build(WIRING + "    seed: 7\n", determinism="seeded").steps
    assert (step.determinism, step.seed) == (Determinism.SEEDED, 7)


def test_a_seed_on_a_pure_step_is_refused() -> None:
    """Silently ignoring it would leave an author believing something is
    pinned that is not."""
    with pytest.raises(StepDeterminismError, match="nothing would consume it"):
        build(WIRING + "    seed: 7\n")


# ....................... #
# Resolution and bindings (§5.3, §5.8)


def test_an_unknown_version_is_refused_naming_what_exists() -> None:
    with pytest.raises(UnknownStep, match="available: @3"):
        build(WIRING.replace("resolve_customers@3", "resolve_customers@9"))


def test_binding_an_undeclared_output_is_refused() -> None:
    with pytest.raises(StepError, match="which the manifest does not declare"):
        build(WIRING.replace("{customer: silver.customer}", "{ghost: silver.ghost}"))


def test_leaving_a_declared_output_unbound_is_refused() -> None:
    """Each output becomes its own model (D16), so an unbound one is a
    relation nobody named."""
    two_outputs = {
        "customer": {"grain": "customer", "key": ["canonical_id"],
                     "produces": {"canonical_id": {"type": "string"}}},
        "customer_xref": {"grain": "xref", "key": ["source_id"],
                          "produces": {"source_id": {"type": "string"}}},
    }
    with pytest.raises(StepError, match="leaves output\\(s\\) customer_xref unbound"):
        build(outputs=two_outputs)


def test_not_binding_a_declared_input_is_refused() -> None:
    with pytest.raises(StepError, match="does not bind input"):
        build(WIRING.replace("    inputs: {raw: silver.customer_raw}\n", ""))


def test_an_undeclared_parameter_is_refused() -> None:
    with pytest.raises(StepError, match="the manifest does not declare"):
        build(WIRING.replace("threshold: 0.9", "nope: 1"))


def test_a_parameter_outside_its_bounds_is_refused() -> None:
    """The enforcement half of parameterize-never-fork: bounds are only a
    contract if exceeding them is an error (§5.7)."""
    with pytest.raises(StepError, match="outside the declared bounds"):
        build(WIRING.replace("threshold: 0.9", "threshold: 1.5"))


def test_a_parameter_at_a_bound_is_accepted() -> None:
    assert build(WIRING.replace("threshold: 0.9", "threshold: 1")).steps


# ....................... #
# Batching (RFC 0006 D2) and the duplicate-relation refusal (§5.8, D8)


def test_every_refusal_arrives_in_one_aggregate() -> None:
    """An author fixing a wiring should see all of it in one round-trip."""
    broken = WIRING.replace("threshold: 0.9", "threshold: 5").replace(
        "inputs: {raw: silver.customer_raw}", "inputs: {wrong: silver.x}"
    )
    with pytest.raises(StepError) as excinfo:
        build(broken, determinism="nondeterministic")
    assert len(excinfo.value.collected) >= 3


def test_two_steps_writing_one_relation_are_refused() -> None:
    """Settles Document 5 §11.5 explicitly: one relation with two writers is
    two models at one path, and whichever ran last would silently win."""
    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "steps": """
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs: {raw: silver.customer_raw}
    outputs: {customer: silver.customer}
  - use: other_step@1
    outputs: {customer: silver.customer}
""",
        }
    )
    other = manifest(
        ref="other_step", version=1, inputs={},
        outputs={"customer": {"grain": "customer", "key": ["canonical_id"],
                              "produces": {"canonical_id": {"type": "string"}}}},
        parameters={},
    )
    registry = StepRegistry(
        {("resolve_customers", 3): manifest(), ("other_step", 1): other}
    )
    with pytest.raises(StepError, match="written by two step outputs"):
        build_project_ir(project, steps=registry)
