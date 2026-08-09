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
from bloomery.errors import CircularDerivation, StepDeterminismError, StepError, UnknownStep
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
    with pytest.raises(StepError, match="written by two things"):
        build_project_ir(project, steps=registry)


def test_two_steps_writing_one_relation_under_different_namespaces_are_refused() -> None:
    """`a.customer` and `b.customer` are different bindings and the *same*
    emitted model — the naming policy owns the namespace. Comparing the
    authored strings let both through and produced two files at one path."""
    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "steps": """
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs: {raw: silver.customer_raw}
    outputs: {customer: a.customer}
  - use: other_step@1
    outputs: {customer: b.customer}
""",
        }
    )
    other = manifest(
        ref="other_step",
        version=1,
        inputs={},
        outputs={
            "customer": {
                "grain": "customer",
                "key": ["canonical_id"],
                "produces": {"canonical_id": {"type": "string"}},
            }
        },
        parameters={},
    )
    registry = StepRegistry({("resolve_customers", 3): manifest(), ("other_step", 1): other})
    with pytest.raises(StepError, match="written by two things"):
        build_project_ir(project, steps=registry)


def test_a_step_output_colliding_with_an_entity_is_refused() -> None:
    """The case nothing checked at all: an entity model and a step both
    claiming ``event`` emit two models at one path."""
    project = load_project(
        {
            "entity_model": (
                "spec_version: 1\nentities:\n  customer:\n"
                "    grain: one row per customer\n    key: [id]\n"
                "    fields:\n      id: {type: string, required: true}\n"
            ),
            "steps": (
                "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
                "    inputs: {raw: silver.raw}\n    outputs: {customer: silver.customer}\n"
            ),
        }
    )
    registry = StepRegistry({("resolve_customers", 3): manifest(parameters={})})
    with pytest.raises(StepError, match="entity 'customer'"):
        build_project_ir(project, steps=registry)


def test_a_sql_macro_is_not_wired_in_the_steps_document() -> None:
    """Tier 1 writes no relation, so it has no output to bind here — and one
    wiring per ref (D13) would make a macro usable in exactly one mapping,
    with one parameter set. It is referenced from the mapping that uses it
    instead (D50), and the refusal says so rather than saying "not yet"."""
    with pytest.raises(StepError, match="referenced from the mapping"):
        build(
            kind="sql_macro",
            entrypoint=None,
            outputs={"o": {"grain": "row", "key": ["a"], "produces": {"a": {"type": "string"}}}},
        )


def _with_rule(on_fail: str) -> str:
    return WIRING + (
        "    quality:\n"
        '      - {rule: expression, name: confident, expr: "confidence >= 0.8", '
        f"on_fail: {on_fail}}}\n"
        "    applies_to: {confident: customer}\n"
    )


@pytest.mark.parametrize("disposition", ["flag", "quarantine"])
def test_a_routed_quality_rule_on_an_output_is_refused(disposition: str) -> None:
    """The half that cannot lower (D39). Both dispositions compile into the
    silver SELECT — the `_quality_flags` projection and the routing WHERE —
    and a step-produced relation has neither, because its wrapper writes the
    rows. Accepting them would be a rule that never evaluates, which is the
    worst possible failure for a feature whose job is catching bad data."""
    with pytest.raises(StepError, match="on_fail: fail"):
        build(_with_rule(disposition))


def test_a_fail_rule_on_an_output_lowers_onto_the_synthesized_entity() -> None:
    """The half that can (D39): `fail` needs no SELECT — it reads the finished
    relation and returns violating rows, which is what a blocking audit is."""
    ir = build(_with_rule("fail"))
    (entity,) = [e for e in ir.entities if e.name == "customer"]
    assert [(rule.name, rule.kind) for rule in entity.quality] == [("confident", "expression")]


def test_a_sql_model_without_a_body_is_refused() -> None:
    """Without one the emitter rendered a MODEL with an empty SELECT — a
    syntactically fine artifact no engine can run."""
    with pytest.raises(StepError, match="registry carries no body"):
        build(kind="sql_model", entrypoint=None)


def test_a_non_finite_parameter_is_a_bloomery_error_not_a_decimal_crash() -> None:
    """``Decimal("NaN")`` constructs fine and raises on comparison, so a guard
    around construction alone let ``InvalidOperation`` cross the compile
    boundary — which RFC 0002's error contract forbids."""
    for spelling in ("NaN", "sNaN"):
        with pytest.raises(StepError):
            build(WIRING.replace("threshold: 0.9", f"threshold: '{spelling}'"))


def test_a_failing_step_still_contributes_to_the_collision_check() -> None:
    """Skipping it meant an author fixed a determinism error, re-ran, and only
    then learned two steps claim one relation — the second round-trip this
    module exists to prevent."""
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
        ref="other_step",
        version=1,
        determinism="nondeterministic",
        inputs={},
        outputs={
            "customer": {
                "grain": "customer",
                "key": ["canonical_id"],
                "produces": {"canonical_id": {"type": "string"}},
            }
        },
        parameters={},
    )
    registry = StepRegistry({("resolve_customers", 3): manifest(), ("other_step", 1): other})
    with pytest.raises(StepError) as excinfo:
        build_project_ir(project, steps=registry)
    kinds = {type(leaf).__name__ for leaf in excinfo.value.collected}
    assert kinds == {"StepDeterminismError", "StepError"}


def test_two_steps_in_a_mutual_loop_are_refused() -> None:
    """A step reading another step's output is the common case, and the edge
    for it was missing entirely — so a mutual loop between two steps compiled
    clean and would have deadlocked at run time. Cycle detection through the
    entity table alone never saw it, because a step-produced relation is not
    an entity."""

    def one(ref: str, output: str) -> StepManifest:
        return manifest(
            ref=ref,
            version=1,
            inputs={"src": {"grain": "g"}},
            parameters={},
            outputs={
                output: {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}}
            },
        )

    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "steps": """
steps_version: 1
steps:
  - use: s@1
    inputs: {src: silver.b}
    outputs: {out_a: silver.a}
  - use: t@1
    inputs: {src: silver.a}
    outputs: {out_b: silver.b}
""",
        }
    )
    registry = StepRegistry({("s", 1): one("s", "out_a"), ("t", 1): one("t", "out_b")})
    with pytest.raises(CircularDerivation, match="step.s"):
        build_project_ir(project, steps=registry)


@pytest.mark.parametrize(
    ("declared", "value"),
    [("int", "2.5"), ("int", "abc"), ("decimal", "abc"), ("date", "nope"), ("timestamp", "x")],
)
def test_a_parameter_that_cannot_parse_as_its_type_is_refused(declared: str, value: str) -> None:
    """The wrapper rebuilds a real value from this text, so an unparseable one
    used to surface as a bare ``ValueError`` out of ``int()`` — crossing the
    compile boundary as a non-``BloomeryError`` — or as an exception at model
    import in somebody's warehouse."""
    with pytest.raises(StepError, match="as the manifest declares"):
        build(
            WIRING.replace("threshold: 0.9", f"threshold: '{value}'"),
            parameters={"threshold": {"type": declared}},
        )


def test_an_unparseable_manifest_default_is_refused_too() -> None:
    """Defaults resolve into the IR exactly like an authored value, and were
    the path that crashed."""
    with pytest.raises(StepError, match="as the manifest declares"):
        build(
            WIRING.replace("    parameters: {threshold: 0.9}\n", ""),
            parameters={"threshold": {"type": "int", "default": "abc"}},
        )


def test_a_date_parameter_may_not_carry_a_time_component() -> None:
    """The check has to use the constructor the *emitter* uses, not a wider
    one. Validated with ``datetime.fromisoformat``, a ``date`` parameter set
    to ``2024-01-01T10:00:00`` passed compile and then emitted
    ``_blm_date.fromisoformat('2024-01-01T10:00:00')`` — which raises at model
    import, the exact failure this check exists to move to compile time.
    """
    with pytest.raises(StepError, match="not an ISO date"):
        build(
            WIRING.replace("threshold: 0.9", "threshold: '2024-01-01T10:00:00'"),
            parameters={"threshold": {"type": "date"}},
        )


def test_a_timestamp_parameter_still_accepts_a_time_component() -> None:
    """The control for the test above: narrowing ``date`` must not narrow
    ``timestamp``, whose whole point is carrying a time."""
    ir = build(
        WIRING.replace("threshold: 0.9", "threshold: '2024-01-01T10:00:00'"),
        parameters={"threshold": {"type": "timestamp"}},
    )
    assert ir.steps[0].parameters[0].value == "2024-01-01T10:00:00"


def test_a_body_that_fails_to_tokenize_is_a_step_error_not_a_crash() -> None:
    """``TokenError`` is a *sibling* of ``ParseError`` under ``SqlglotError``,
    so an unterminated string slipped the handler entirely and crossed the
    compile boundary as a non-``BloomeryError`` — which RFC 0002 forbids and
    D30(b) was written to prevent for the parameter path.
    """
    project = load_project(
        {
            "entity_model": ENTITY_MODEL,
            "steps": """
steps_version: 1
steps:
  - use: s@1
    outputs: {out: silver.a}
""",
        }
    )
    body = manifest(
        ref="s",
        version=1,
        kind="sql_model",
        entrypoint=None,
        inputs={},
        parameters={},
        outputs={
            "out": {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}},
        },
    )
    registry = StepRegistry({("s", 1): body}, sql_bodies={("s", 1): "SELECT 'abc"})
    with pytest.raises(StepError, match="does not parse as SQL"):
        build_project_ir(project, steps=registry)
