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
    "RESOLVE_CUSTOMERS_V4",
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
                "references": {"canonical_id": "customer"},
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

#: The same step, one version on: it also stamps *when* it resolved.
#:
#: A separate version rather than an edit to v3, because a manifest is
#: identity (RFC 0017): changing what a version produces is how a step's
#: consumers silently disagree about its contract. It also lets the corpus
#: carry two versions of one ref, which is the situation `use: ref@version`
#: exists for.
#:
#: `resolved_at` is what makes a mart over the resolved entity legal: RFC 0010
#: D9 requires a measure-carrying mart to declare a time dimension, and a
#: resolved customer has no date of its own — resolution is an event, and this
#: is when it happened.
RESOLVE_CUSTOMERS_V4 = StepManifest.model_validate(
    {
        **RESOLVE_CUSTOMERS.model_dump(by_alias=True, mode="json"),
        "version": 4,
        "runtime_lock": "sha256:b73c",
        # Two inputs, because identity resolution reads two systems. v3's
        # single `raw` input assumed the sources had already been unioned,
        # which is the question the step exists to answer.
        "inputs": {
            "crm": {
                "grain": "customer_source_row",
                "requires": ["source_system", "source_id", "email", "name"],
            },
            "billing": {
                "grain": "customer_source_row",
                "requires": ["source_system", "source_id", "email", "name"],
            },
        },
        "outputs": {
            "customer": {
                "grain": "customer",
                "key": ["canonical_id"],
                "produces": {
                    "canonical_id": {"type": "string", "required": True},
                    "confidence": {"type": "decimal(4,3)"},
                    "resolved_at": {"type": "timestamp", "required": True},
                },
            },
            "customer_xref": {
                "grain": "xref",
                "key": ["source_system", "source_id"],
                "references": {"canonical_id": "customer"},
                "produces": {
                    "source_system": {"type": "string", "required": True},
                    "source_id": {"type": "string", "required": True},
                    "canonical_id": {"type": "string", "required": True},
                    "method": {"type": "string"},
                },
            },
        },
    }
)

_BY_FIXTURE: dict[str, StepRegistry] = {
    "step_resolution": StepRegistry({("resolve_customers", 3): RESOLVE_CUSTOMERS}),
    "identity_resolution": StepRegistry({("resolve_customers", 4): RESOLVE_CUSTOMERS_V4}),
}


def registry_for(fixture: str) -> StepRegistry:
    """The registry a fixture compiles against — empty for the many that wire
    no step, which is the default every existing fixture relies on."""
    return _BY_FIXTURE.get(fixture, EMPTY_REGISTRY)
