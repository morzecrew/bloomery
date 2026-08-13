"""Signature closure: a type in a public signature is itself public
(RFC 0018 D1).

``bloomery.__all__`` used to export functions whose parameters and returns a
caller could not name. `compile_project` returned ``tuple[EmittedArtifact,
...]`` and took a ``NamingPolicy``, and neither name existed at the root — so
the documented way to call the compiler was to deep-import types the package
did not advertise. That is not a hole review can hold shut across 24k lines,
which is why it is a test.

**The walk is over names, not objects.** ``typing.get_type_hints`` resolves
``ColumnDescriptor.type`` to ``StringType | IntType | …`` — seven classes and
no mention of ``LogicalType``, which is the name a caller actually writes. The
alias is what has to be exported, so the walk reads the raw annotation string,
extracts its identifiers, and resolves each one in the module that declared it.
``get_type_hints`` is still called, on every export, because an annotation that
cannot resolve is its own defect (RFC 0018 D10) and the walk would silently
under-report if one came back.

**Where it stops.** ``ProjectIR``, ``Project`` and ``Catalog`` are *handles*:
values a caller receives and passes back without reading a field. Descending
into them would drag the whole IR tree into the root namespace — 65 names,
measured — which is RFC 0003's internals wearing a public import path (D9). A
handle that grows a documented field stops being one, and this set shrinks.

Two more exclusions, both narrower than they look. ``bloomery.errors`` is
allowlisted: the hierarchy is large, the root keeps ``BloomeryError``, and
leaves stay behind a declared ``__all__`` (D2). Private fields are skipped —
``StepRegistry._steps`` names ``StepManifest``, but a caller who cannot read
the field cannot need the name.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sys
import types
import typing

import pytest

import bloomery
import bloomery.errors

pytestmark = pytest.mark.unit

#: Values a caller receives and passes back, never destructuring (RFC 0018 D9).
#: The walk does not descend into these; their fields stay internal.
HANDLE_TYPES = frozenset({"Catalog", "Project", "ProjectIR"})

#: The one allowlisted subpackage (RFC 0018 D2) — an exemption in code rather
#: than in someone's head.
ERROR_MODULE_PREFIX = "bloomery.errors"


def _identifiers(annotation: str) -> list[str]:
    """Every bare name in an annotation string, in source order.

    ``tuple[EmittedArtifact, ...]`` yields ``tuple`` and ``EmittedArtifact``;
    ``Op | None`` yields ``Op``. Non-names (string literals inside ``Literal``)
    are not identifiers and do not appear.
    """
    try:
        tree = ast.parse(annotation, mode="eval")
    except SyntaxError:  # pragma: no cover — an annotation that will not parse
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
    return names


def _defining_module(obj: object) -> types.ModuleType | None:
    return sys.modules.get(getattr(obj, "__module__", "") or "")


def _owning_package(value: object) -> str:
    """Which package declares ``value``, seeing through aliases.

    A union alias (``LogicalType = StringType | IntType | …``) is a
    :class:`types.UnionType`, whose ``__module__`` is ``types`` — so the alias
    is attributed to its members instead, which is where it is really declared.
    """
    if isinstance(value, types.UnionType):
        return next(
            (
                owner
                for member in typing.get_args(value)
                if (owner := _owning_package(member)).startswith("bloomery")
            ),
            "",
        )
    if isinstance(value, typing.TypeAliasType):
        return value.__module__
    return getattr(value, "__module__", "") or ""


def _raw_annotations(obj: object) -> dict[str, str]:
    """Annotations as written, public members only.

    Covers all three ways a type reaches a caller: a function's parameters and
    return, a dataclass's fields (read across the MRO, so an inherited field is
    not invisible), and a class's constructor and properties. The last matters —
    ``StepRegistry.steps`` is the only path by which ``StepManifest`` is public,
    and a walk over fields alone would miss it and call the surface closed.
    """
    collected: dict[str, object] = {}
    if inspect.isfunction(obj):
        collected = dict(getattr(obj, "__annotations__", {}))
    elif isinstance(obj, type):
        if dataclasses.is_dataclass(obj):
            for klass in reversed(obj.__mro__):
                collected.update(getattr(klass, "__annotations__", {}) or {})
        for klass in reversed(obj.__mro__):
            for member, value in vars(klass).items():
                accessor = value.fget if isinstance(value, property) else None
                if member == "__init__" and inspect.isfunction(value):
                    accessor = value
                if accessor is None:
                    continue
                for parameter, annotation in getattr(accessor, "__annotations__", {}).items():
                    label = member if parameter == "return" else f"{member}({parameter})"
                    collected[label] = annotation
    return {
        member: annotation if isinstance(annotation, str) else _spell(annotation)
        for member, annotation in collected.items()
        if not member.startswith("_")
    }


def _spell(annotation: object) -> str:
    """An already-evaluated annotation, back in source form."""
    return getattr(annotation, "__name__", None) or str(annotation)


def _closure() -> dict[str, set[str]]:
    """Every bloomery-declared name a caller meets, mapped to where it is met.

    Names already in ``bloomery.__all__`` are walked through and not reported;
    what comes back is exactly the set that closure requires and the root does
    not yet export.
    """
    missing: dict[str, set[str]] = {}
    seen: set[str] = set()
    frontier: list[tuple[str, object]] = [
        (name, getattr(bloomery, name))
        for name in bloomery.__all__
        if name not in HANDLE_TYPES
    ]

    while frontier:
        name, obj = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        module = _defining_module(obj)
        if module is None:
            continue

        for member, annotation in _raw_annotations(obj).items():
            for identifier in _identifiers(annotation):
                value = getattr(module, identifier, None)
                if value is None:
                    continue
                package = _owning_package(value)
                if not package.startswith("bloomery"):
                    continue
                if package.startswith(ERROR_MODULE_PREFIX):
                    continue
                if identifier not in bloomery.__all__:
                    missing.setdefault(identifier, set()).add(f"{name}.{member}")
                if identifier not in HANDLE_TYPES and identifier not in seen:
                    frontier.append((identifier, value))

    return missing


def test_every_public_annotation_resolves() -> None:
    """The precondition for the walk below (RFC 0018 D10).

    ``from __future__ import annotations`` plus a ``TYPE_CHECKING``-only import
    leaves a name that does not exist at run time. The closure walk would then
    read past it and report a smaller surface than the real one, which is worse
    than failing.
    """
    unresolvable: dict[str, str] = {}
    for name in bloomery.__all__:
        obj = getattr(bloomery, name)
        # Instances are skipped deliberately: `get_type_hints` resolves an
        # instance's annotations against `__globals__`, which an instance does
        # not have, so `EMPTY_REGISTRY` would fail for its class's reasons and
        # report them against the wrong name. The class is walked on its own.
        walkable = inspect.isfunction(obj) or (
            isinstance(obj, type) and dataclasses.is_dataclass(obj)
        )
        if not walkable:
            continue
        try:
            typing.get_type_hints(obj)
        except NameError as exc:
            unresolvable[name] = str(exc)

    assert not unresolvable, (
        "annotations must be resolvable at run time; lift the TYPE_CHECKING "
        f"guard on the public signature: {unresolvable}"
    )


def test_signature_closure_holds() -> None:
    """Any type reachable from a public signature is itself root-exported."""
    missing = _closure()
    assert not missing, "not exported from `bloomery`: " + ", ".join(
        f"{name} (via {', '.join(sorted(reached))})" for name, reached in sorted(missing.items())
    )


def test_the_walk_sees_through_a_union_alias() -> None:
    """The regression guard for this module's central subtlety.

    ``LogicalType`` is a bare union, so its ``__module__`` is ``types`` and a
    naive walk drops it — which is how the RFC's own inventory missed it. If
    this passes while :func:`test_signature_closure_holds` is green, the alias
    is genuinely exported rather than merely invisible.
    """
    from bloomery.typing import LogicalType

    assert isinstance(LogicalType, types.UnionType)
    assert _owning_package(LogicalType).startswith("bloomery")


def test_the_walk_skips_non_class_exports() -> None:
    """``bloomery.errors.guaranteed`` is a function (RFC 0003 D11), not a type.

    Treating it as one would make the walk raise rather than report.
    """
    assert "guaranteed" in bloomery.errors.__all__
    assert not isinstance(bloomery.errors.guaranteed, type)
    assert _raw_annotations(bloomery.errors.guaranteed)


def test_private_fields_are_out_of_scope() -> None:
    """A caller who cannot read the field cannot need its type."""
    from bloomery.steps import StepRegistry

    assert any(field.name.startswith("_") for field in dataclasses.fields(StepRegistry))
    assert not any(member.startswith("_") for member in _raw_annotations(StepRegistry))


SUBPACKAGES = [
    "",
    "dialects",
    "emit",
    "errors",
    "ir",
    "naming",
    "plan",
    "planner",
    "resolve",
    "runtime",
    "spec",
    "steps",
    "transforms",
    "typing",
]


@pytest.mark.parametrize("subpackage", SUBPACKAGES)
def test_every_exported_name_resolves(subpackage: str) -> None:
    """No stale entry in any ``__all__`` — a name a package promises and cannot
    produce is a broken import for whoever believes the declaration."""
    name = f"bloomery.{subpackage}" if subpackage else "bloomery"
    module = __import__(name, fromlist=["__all__"])
    declared = getattr(module, "__all__", None)
    assert declared, f"{module.__name__} declares no __all__"
    missing = [name for name in declared if not hasattr(module, name)]
    assert not missing, f"{module.__name__}.__all__ names {missing}, which do not resolve"


def test_the_root_export_list_is_sorted() -> None:
    """Sorted so a diff to it is readable and two branches adding an export do
    not conflict on the same line."""
    assert bloomery.__all__ == sorted(bloomery.__all__)
