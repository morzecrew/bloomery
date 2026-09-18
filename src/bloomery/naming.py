"""Naming policies (S-0025/ports): logical name → physical
``(namespace, relation)`` — the only tenant-shaped seam in the package.

Tenant scoping enters compilation as ordinary constructor values on a policy
instance (hard invariant #3): :class:`PrefixNaming` prefixes every namespace
with a caller-chosen tenant prefix, and nothing else in the package knows the
concept exists. (S-0025 spells this class ``TenantPrefixNaming``; the
tenant-agnosticism guard (S-0026/guard-tests-determinism-and-tenant-agnosticism) restricts the word to docstrings in
this module, so the class carries the neutral name.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bloomery.ir import Layer

# ----------------------- #

__all__ = [
    "DefaultNaming",
    "NamingPolicy",
    "PrefixNaming",
]


class NamingPolicy(Protocol):
    """Maps a logical entity (or mart) name and layer to a physical
    ``(namespace, relation)`` pair (S-0025/D-1)."""

    def relation(self, entity: str, layer: Layer) -> tuple[str, str]: ...


# ....................... #


@dataclass(frozen=True, slots=True)
class DefaultNaming:
    """The layer-named default: bronze relations pass through under the
    ``bronze`` namespace, silver entities live at ``("silver", entity)``,
    gold marts at ``("gold", "mart_<name>")`` (S-0025/ports, S-0025/sqlmesh-emitter-primary)."""

    def relation(self, entity: str, layer: Layer) -> tuple[str, str]:
        if layer is Layer.GOLD:
            return ("gold", f"mart_{entity}")

        return (layer.value, entity)


# ....................... #


@dataclass(frozen=True, slots=True)
class PrefixNaming:
    """Tenant-scoped naming: every namespace gains a prefix, e.g.
    ``("acme_silver", entity)`` — tenant scoping as ordinary spec values,
    per hard invariant #3 (S-0025/ports)."""

    prefix: str

    # ....................... #

    def relation(self, entity: str, layer: Layer) -> tuple[str, str]:
        namespace, relation = DefaultNaming().relation(entity, layer)
        return (f"{self.prefix}_{namespace}", relation)
