"""Naming policies (S-0025/ports): logical name → physical
``(namespace, relation)``, or ``(catalog, namespace, relation)`` — the only
tenant-shaped seam in the package.

Tenant scoping enters compilation as ordinary constructor values on a policy
instance (hard invariant #3): :class:`PrefixNaming` prefixes every namespace
with a caller-chosen tenant prefix, and nothing else in the package knows the
concept exists. (S-0025 spells this class ``TenantPrefixNaming``; the
tenant-agnosticism guard (S-0026/guard-tests-determinism-and-tenant-agnosticism) restricts the word to docstrings in
this module, so the class carries the neutral name.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol

from sqlglot import exp

from bloomery.ir import Layer

# ----------------------- #

__all__ = [
    "DefaultNaming",
    "NamingPolicy",
    "PrefixNaming",
    "QualifiedName",
    "qualified",
]


class NamingPolicy(Protocol):
    """Maps a logical entity (or mart) name and layer to a physical
    ``(namespace, relation)`` pair (S-0025/D-1), or to
    ``(catalog, namespace, relation)`` where the relation lives in a catalog
    other than the engine's default (S-0025/D-23): a DuckDB project reading
    an attached Postgres and writing a DuckLake, or Trino, Unity, Snowflake
    databases and BigQuery projects. A ``None`` catalog, or a pair, means the
    default one.

    **Two composing projects must be compiled under the same policy**
    (S-0002/D-7). An imported relation is built by the upstream and named by
    the downstream — SQLMesh names it directly, dbt refs it across projects —
    so a downstream compiled under a different policy names relations the
    upstream never created. Nothing refuses that today: the policy is a
    compile argument and the upstream IR records nothing about the one it was
    compiled under, so a mismatch surfaces in the warehouse rather than in the
    compile. Recording it on the IR is what would turn the constraint into a
    refusal. The catalog is part of that contract: it is part of the name.
    """

    def relation(
        self, entity: str, layer: Layer
    ) -> tuple[str, str] | tuple[str | None, str, str]: ...


# ....................... #


class QualifiedName(NamedTuple):
    """One relation's physical name, with its catalog where it has one."""

    catalog: str | None
    namespace: str
    relation: str

    # ....................... #

    @property
    def dotted(self) -> str:
        """``catalog.namespace.relation``, or ``namespace.relation`` without a
        catalog: a model name, a ``sql_table``, a MetricFlow relation name."""

        return ".".join(part for part in self if part)

    # ....................... #

    @property
    def path(self) -> str:
        """The same parts as a relative path, ``catalog/namespace/relation``:
        where a target's ``models/`` tree keeps the relation's file, so two
        catalogs holding one namespace never write one file."""

        return "/".join(part for part in self if part)

    # ....................... #

    def table(self, alias: str | None = None) -> exp.Table:
        """The relation as a table reference, its catalog a real third part.

        A catalog folded into the namespace instead renders as one quoted
        identifier, ``"lake.silver".order``, naming a schema that does not
        exist (#389).
        """

        return exp.table_(self.relation, db=self.namespace, catalog=self.catalog, alias=alias)


# ....................... #


def qualified(naming: NamingPolicy, name: str, layer: Layer) -> QualifiedName:
    """What ``naming`` names ``name`` in ``layer``, a pair read as having no
    catalog. Every reference the package builds goes through here, so the
    catalog reaches each one or none."""

    parts = naming.relation(name, layer)

    if len(parts) == 2:
        return QualifiedName(None, *parts)

    catalog, namespace, relation = parts
    return QualifiedName(catalog or None, namespace, relation)


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
