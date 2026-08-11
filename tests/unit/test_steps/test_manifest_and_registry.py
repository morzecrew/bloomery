"""The step manifest and the registry compile input (RFC 0017 §5.2–§5.3).

What is asserted here is the *contract surface*: what a manifest may declare,
what the registry refuses, and the two properties the purity argument rests on
— the snapshot and the frozen leaves (D14). Emission and the runtime contract
are other modules' tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from bloomery.errors import UnknownStep
from bloomery.steps import EMPTY_REGISTRY, StepManifest, StepRegistry

pytestmark = pytest.mark.unit


def manifest(**overrides: object) -> StepManifest:
    base: dict[str, object] = {
        "ref": "resolve_customers",
        "version": 3,
        "kind": "python_model",
        "determinism": "pure",
        "runtime_lock": "sha256:a91f",
        "entrypoint": "platform_steps.resolve_customers:resolve",
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
    }
    return StepManifest.model_validate(base | overrides)


# ....................... #
# The manifest shape (§5.2, D2)


def test_the_worked_manifest_parses() -> None:
    parsed = manifest()
    assert (parsed.ref, parsed.version, parsed.kind) == ("resolve_customers", 3, "python_model")
    assert parsed.outputs["customer"].key == ("canonical_id",)
    assert parsed.lineage == "column"


def test_a_key_naming_an_unproduced_column_is_refused() -> None:
    """The key is what the runtime assertion groups by, so a key naming a
    column the step does not produce is an assertion that cannot run."""
    with pytest.raises(ValidationError, match="key names nope"):
        manifest(
            outputs={
                "customer": {
                    "grain": "customer",
                    "key": ["nope"],
                    "produces": {"canonical_id": {"type": "string"}},
                }
            }
        )


def test_a_python_model_without_an_entrypoint_is_refused() -> None:
    with pytest.raises(ValidationError, match="needs an entrypoint"):
        manifest(entrypoint=None)


def test_a_sql_step_declaring_an_entrypoint_is_refused() -> None:
    """A SQL step has no Python to call; a manifest naming one describes
    something the emitter would silently ignore."""
    with pytest.raises(ValidationError, match="only a python_model imports one"):
        manifest(kind="sql_model", entrypoint="platform_steps.x:y")


def test_a_sql_macro_producing_a_relation_is_refused() -> None:
    """Tier 1 splices into a SELECT as one expression (§5.1), so it has
    exactly one output of exactly one column — anything else is a Tier 2 step
    wearing the wrong kind, and the splice has no single value to substitute."""
    with pytest.raises(ValidationError, match="an expression is one value"):
        manifest(
            kind="sql_macro",
            entrypoint=None,
            outputs={
                "scored": {
                    "grain": "row",
                    "key": ["a"],
                    "produces": {"a": {"type": "string"}, "b": {"type": "string"}},
                }
            },
        )


def test_a_sql_macro_with_one_column_is_accepted() -> None:
    parsed = manifest(
        kind="sql_macro",
        entrypoint=None,
        outputs={"scored": {"grain": "row", "key": ["a"], "produces": {"a": {"type": "string"}}}},
    )
    assert parsed.kind == "sql_macro"


def test_inverted_parameter_bounds_are_refused() -> None:
    with pytest.raises(ValidationError, match="bounds are inverted"):
        manifest(parameters={"threshold": {"type": "decimal(4,3)", "min": 1, "max": 0}})


def test_a_parameter_default_is_never_a_float() -> None:
    """RFC 0003 D5 reaches the manifest too: a YAML float would arrive as a
    binary approximation of the number the platform team wrote."""
    parsed = manifest(parameters={"threshold": {"type": "decimal(4,3)", "default": 0.85}})
    assert parsed.parameters["threshold"].default == Decimal("0.85")
    assert not isinstance(parsed.parameters["threshold"].default, float)


def test_a_ref_may_not_look_like_a_path() -> None:
    """The absence of any path-like spelling is part of why a spec can never
    name code to load (§5.3)."""
    for bad in ("../escape", "pkg/mod", "Resolve", "resolve-customers"):
        with pytest.raises(ValidationError):
            manifest(ref=bad)


def test_the_manifest_is_frozen() -> None:
    """Half of D14: the registry's snapshot is only sufficient because the
    values it holds cannot be mutated in place."""
    with pytest.raises(ValidationError):
        manifest().ref = "other"  # type: ignore[misc]


# ....................... #
# The registry as a compile input (§5.3, D3, D14)


def test_the_empty_registry_holds_nothing() -> None:
    assert EMPTY_REGISTRY.steps == ()


def test_resolve_returns_the_manifest() -> None:
    registry = StepRegistry({("resolve_customers", 3): manifest()})
    assert registry.resolve("resolve_customers", 3).version == 3


def test_an_unknown_version_names_the_available_ones() -> None:
    """The refusal is the whole world: there is no dynamic loading path to
    fall back on, so the message has to carry what *is* there (D3)."""
    registry = StepRegistry(
        {("resolve_customers", 2): manifest(version=2), ("resolve_customers", 3): manifest()}
    )
    with pytest.raises(UnknownStep, match=r"has no version 5; available: @2, @3"):
        registry.resolve("resolve_customers", 5)


def test_an_unknown_ref_names_the_registered_steps() -> None:
    registry = StepRegistry({("resolve_customers", 3): manifest()})
    with pytest.raises(UnknownStep, match="registered steps: resolve_customers"):
        registry.resolve("dedupe_orders", 1)


def test_an_empty_registry_says_so_rather_than_listing_nothing() -> None:
    with pytest.raises(UnknownStep, match="the registry is empty"):
        EMPTY_REGISTRY.resolve("resolve_customers", 3)


def test_the_registry_snapshots_its_input() -> None:
    """The other half of D14. A caller mutating the dict it passed must not
    change what a later compilation sees — otherwise "same specs in ⇒
    byte-identical artifacts out" depends on what the caller does next."""
    source = {("resolve_customers", 3): manifest()}
    registry = StepRegistry(source)
    source[("evil", 1)] = manifest(ref="evil", version=1)
    assert registry.get("evil", 1) is None
    assert len(registry.steps) == 1


def test_the_registry_is_canonically_sorted_whatever_the_caller_built() -> None:
    """Insertion order is the caller's business; the compile input's order is
    not (RFC 0003: no ambient nondeterminism)."""
    # Each manifest is keyed by the identity it declares — the registry refuses
    # a disagreement (D55), and this helper defaults to version 3.
    one = manifest(ref="a_step", version=1)
    two = manifest(ref="a_step", version=2)
    forwards = StepRegistry({("a_step", 2): two, ("a_step", 1): one})
    backwards = StepRegistry({("a_step", 1): one, ("a_step", 2): two})
    assert [key for key, _ in forwards.steps] == [key for key, _ in backwards.steps]
    assert [key for key, _ in forwards.steps] == [("a_step", 1), ("a_step", 2)]


def test_bodies_are_carried_for_the_two_sql_tiers() -> None:
    registry = StepRegistry(
        {("m", 1): manifest(ref="m", version=1, kind="sql_macro", entrypoint=None,
                            outputs={"o": {"grain": "row", "key": ["a"],
                                           "produces": {"a": {"type": "string"}}}})},
        macro_bodies={("m", 1): "LOWER(:col)"},
        sql_bodies={("s", 1): "SELECT 1"},
    )
    assert registry.macro_body("m", 1) == "LOWER(:col)"
    assert registry.sql_body("s", 1) == "SELECT 1"
    assert registry.macro_body("m", 2) is None


def test_a_python_model_has_no_body_in_the_registry() -> None:
    """Bloomery never sees Python step code — only the manifest describing
    it. The absence is the security property (§5.3)."""
    registry = StepRegistry({("resolve_customers", 3): manifest()})
    assert registry.macro_body("resolve_customers", 3) is None
    assert registry.sql_body("resolve_customers", 3) is None


def test_an_input_and_a_parameter_may_not_share_a_name() -> None:
    """The wrapper calls the step as ``step(**inputs, **parameters)``, so the
    two namespaces share one keyword space — a name in both is a run-time
    ``TypeError: got multiple values``, decidable here from the manifest."""
    with pytest.raises(ValidationError, match="both an input and a parameter"):
        manifest(
            inputs={"threshold": {"grain": "row"}},
            parameters={"threshold": {"type": "decimal"}},
        )


def test_a_non_identifier_input_name_is_refused() -> None:
    with pytest.raises(ValidationError, match="not Python identifiers"):
        manifest(inputs={"raw data": {"grain": "row"}})


def test_the_rfc_worked_manifest_spells_a_bare_decimal_parameter() -> None:
    """§5.2 writes ``{type: decimal, default: 0.85}``. The implementation
    rejected it and the corpus quietly wrote ``decimal(4,3)`` instead, hiding
    the divergence — the RFC is the authority."""
    parsed = manifest(parameters={"threshold": {"type": "decimal", "default": "0.85"}})
    assert parsed.parameters["threshold"].type == "decimal"


def test_an_output_name_that_is_not_an_identifier_is_refused() -> None:
    """Output names reach the wrapper's ``return outputs[…]`` and its
    docstring; a name carrying a quote or a newline made the generated module
    a syntax error."""
    for bad in ('a"] ) or print("PWN"', "a\nb", "a b"):
        with pytest.raises(ValidationError, match="not identifiers"):
            manifest(
                outputs={
                    bad: {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}}
                }
            )


def test_a_key_disagreeing_with_its_manifest_is_refused() -> None:
    """RFC 0017 D55. The registry is keyed by ``(ref, version)`` and the
    manifest carries the same pair, so the two can disagree — and the
    disagreement was silent, not loud: ``lower_steps`` builds ``StepIR`` from
    the *manifest* identity while the wiring's canonical links and
    ``on_fail: fail`` rules are keyed by the *wiring* identity, so those stop
    matching and are dropped without a word.

    Checked at construction because the registry is a frozen compile input —
    one place, once, for every later reader."""
    from bloomery.errors import StepError

    with pytest.raises(StepError, match=r"key wrong@9 does not match.*resolve_customers@3"):
        StepRegistry({("wrong", 9): manifest()})


def test_the_matching_key_is_still_accepted() -> None:
    """The control: a check that refused everything would pass the test above."""
    assert StepRegistry({("resolve_customers", 3): manifest()}).get("resolve_customers", 3)
