"""Step registries for the fixture corpus (RFC 0017 §5.3).

Manifests live here rather than under ``tests/fixtures/`` on purpose: a
registry is *not* a spec. It is assembled by the caller and handed to
``compile_project``, and ``fixtures/`` holds YAML spec projects only
(``tests/README.md``). Keeping them apart is the same separation the RFC
draws — the platform owns manifests, the authored spec owns wiring.
"""

from __future__ import annotations

from bloomery.steps import EMPTY_REGISTRY, StepManifest, StepRegistry

__all__ = [
    "RESOLVE_CUSTOMERS",
    "registry_for",
]

#: The worked manifest from RFC 0017 §5.2, near-verbatim. Two outputs, so the
#: one-wrapper-per-output rule (D16) shows up in the goldens as two files
#: rather than as a claim in prose.
RESOLVE_CUSTOMERS = StepManifest.model_validate(
    {
        "ref": "resolve_customers",
        "version": 3,
        "kind": "python_model",
        "entrypoint": "platform_steps.resolve_customers:resolve",
        "determinism": "pure",
        "runtime_lock": "sha256:a91f",
        "lineage": "coarse",
        "inputs": {
            "raw": {
                "grain": "customer_source_row",
                "requires": ["source_system", "source_id", "email", "name"],
            }
        },
        "outputs": {
            "customer": {
                "grain": "customer",
                "key": ["canonical_id"],
                "produces": {
                    "canonical_id": {"type": "string", "required": True},
                    "confidence": {"type": "decimal(4,3)"},
                },
            },
            "customer_xref": {
                "grain": "xref",
                "key": ["source_system", "source_id"],
                "produces": {
                    "source_system": {"type": "string", "required": True},
                    "source_id": {"type": "string", "required": True},
                    "canonical_id": {"type": "string", "required": True},
                    "method": {"type": "string"},
                },
            },
        },
        "parameters": {
            "threshold": {"type": "decimal(4,3)", "default": "0.85", "min": 0, "max": 1}
        },
    }
)

_BY_FIXTURE: dict[str, StepRegistry] = {
    "step_resolution": StepRegistry({("resolve_customers", 3): RESOLVE_CUSTOMERS}),
}


def registry_for(fixture: str) -> StepRegistry:
    """The registry a fixture compiles against — empty for the many that wire
    no step, which is the default every existing fixture relies on."""
    return _BY_FIXTURE.get(fixture, EMPTY_REGISTRY)
