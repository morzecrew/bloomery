"""The compiled IR as a file: :func:`ir_json` and :func:`ir_from_json`.

Composition takes the upstream's compiled IR as a *value* (S-0002/D-2), which
until now made it reachable from Python and from nothing else — a project with
an imports document had no way to name an upstream at the command line. The
file form is what a caller assembles by hand, a checkout or a CI artifact
carries (S-0002/D-8); nothing here discovers, resolves or fetches anything.

The dump walks the same type-driven shape :mod:`bloomery.ir.fingerprint`
walks, so the bytes are a function of the IR and of nothing else: field order
is the dataclass's, keys are sorted, floats are refused (S-0020/D-5), enums
carry their value and ``Decimal`` its ``str()``. Deliberately *not* the
fingerprint's own encoding, which is one-way by design — this one has to come
back, so each node carries its type name and the loader reconstructs by it.

The version is checked before anything is reconstructed (S-0020/D-3): an IR
written by another bloomery is refused with the message ``plan()`` gives for
the same mismatch, rather than raising on whichever field moved.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import types as _types
import typing
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, cast

from bloomery.errors import SpecParseError
from bloomery.ir import nodes
from bloomery.ir.nodes import ProjectIR
from bloomery.typing import types

# ----------------------- #

__all__ = [
    "ir_from_json",
    "ir_json",
]

#: The single key naming what a JSON object reconstructs as. ``$`` because no
#: dataclass field can be spelled that way, so a tag can never shadow a field.
_NODE = "$node"
_ENUM = "$enum"
_DECIMAL = "$decimal"

#: Every class the walk can meet, by name. Built from the two modules the IR is
#: made of rather than written down: a node added to either is loadable without
#: anyone remembering this file.
_CLASSES: dict[str, type] = {
    name: value
    for module in (nodes, types)
    for name, value in vars(module).items()
    if isinstance(value, type)
    and value.__module__ in {nodes.__name__, types.__name__}
    and (dataclasses.is_dataclass(value) or issubclass(value, Enum))
}


def _dump(value: object) -> Any:
    """One IR value as JSON data. Order matters exactly as it does in the
    fingerprint's walk: bool before int, Enum before int/str."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        msg = f"floats are banned in the IR (S-0020/D-5), got {value!r}"
        raise TypeError(msg)
    if isinstance(value, Enum):
        return {_ENUM: type(value).__name__, "value": value.value}
    if isinstance(value, int | str):
        return value
    if isinstance(value, Decimal):
        return {_DECIMAL: str(value)}
    if isinstance(value, tuple):
        return [_dump(item) for item in cast("tuple[object, ...]", value)]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        dumped: dict[str, Any] = {_NODE: type(value).__name__}
        for field in dataclasses.fields(value):
            dumped[field.name] = _dump(getattr(value, field.name))
        return dumped

    msg = f"unsupported value in IR JSON encoding: {type(value).__name__}"
    raise TypeError(msg)


# ....................... #


def _class(name: object) -> type:
    if not isinstance(name, str) or name not in _CLASSES:
        msg = f"unknown IR node type {name!r}"
        raise ValueError(msg)

    return _CLASSES[name]


# ....................... #


@functools.cache
def _hints(cls: type) -> dict[str, object]:
    """A node class's field annotations, resolved once."""
    return typing.get_type_hints(cls)


def _fits(value: object, hint: object) -> bool:
    """Whether a reconstructed *value* is of the shape *hint* declares.

    The IR's fields are scalars, enums, ``Decimal``, nodes, tuples of those and
    optionals of those (S-0020/ir-shape), which is the whole grammar this reads.
    A hint it does not know admits anything rather than refusing a tree the
    dump wrote — the check exists to keep a foreign document out of the
    resolver, not to re-derive the dataclass.
    """
    origin = typing.get_origin(hint)
    if origin in (typing.Union, _types.UnionType):
        return any(_fits(value, arg) for arg in typing.get_args(hint))
    if origin is typing.Literal:
        return value in typing.get_args(hint)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        args = typing.get_args(hint)
        items = cast("tuple[object, ...]", value)
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_fits(item, args[0]) for item in items)
        return len(args) == len(items) and all(
            _fits(i, a) for i, a in zip(items, args, strict=True)
        )
    if hint is type(None):
        return value is None
    if hint is bool:
        return isinstance(value, bool)
    if hint is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(hint, type) and (
        hint in (str, Decimal) or issubclass(hint, Enum) or dataclasses.is_dataclass(hint)
    ):
        return isinstance(value, hint)
    return True


def _node(cls: type, fields: dict[str, object]) -> object:
    """One node from its reconstructed fields, each checked against its
    annotation before the dataclass is built — a document that names the right
    node type and puts a string where a node belongs would otherwise reach the
    resolver and fail there as an attribute error, which the compile boundary
    promises never to raise (S-0008/D-1)."""
    hints = _hints(cls)
    for name, value in fields.items():
        hint = hints.get(name)
        if hint is not None and not _fits(value, hint):
            msg = f"{cls.__name__}.{name} is not a {hint}: got {type(value).__name__}"
            raise TypeError(msg)
    return cls(**fields)


def _load(value: object) -> object:
    """JSON data back to the IR value :func:`_dump` was given."""
    if isinstance(value, list):
        return tuple(_load(item) for item in cast("list[object]", value))
    if isinstance(value, dict):
        node = cast("dict[str, object]", value)
        if _DECIMAL in node:
            return Decimal(str(node[_DECIMAL]))
        if _ENUM in node:
            return _class(node[_ENUM])(node["value"])
        return _node(
            _class(node[_NODE]),
            {key: _load(item) for key, item in node.items() if key != _NODE},
        )

    return value


# ....................... #


def ir_json(ir: ProjectIR) -> str:
    """A :class:`~bloomery.ir.ProjectIR` as canonical JSON text.

    A function of the IR alone — no clock, no path, no environment — so two
    compiles of one project write the same file, and a fingerprint taken over
    what :func:`ir_from_json` reads back equals the one taken over what was
    written.
    """

    return json.dumps(_dump(ir), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ....................... #


def ir_from_json(text: str) -> ProjectIR:
    """The IR :func:`ir_json` wrote, or :class:`~bloomery.errors.SpecParseError`.

    Refuses another bloomery's IR by version before reconstructing anything,
    with the message ``plan()`` gives for the same mismatch: the two cases are
    one — an IR whose shape this compiler has never heard of — and the fix is
    the same one.
    """
    try:
        payload = json.loads(text)
    except ValueError as exc:
        msg = f"not a bloomery IR document: {exc}"
        raise SpecParseError(msg) from exc

    if not isinstance(payload, dict) or payload.get(_NODE) != ProjectIR.__name__:
        msg = f"not a bloomery IR document: expected a {ProjectIR.__name__} object"
        raise SpecParseError(msg)

    version = cast("dict[str, object]", payload).get("bloomery_ir_version")
    expected = ProjectIR().bloomery_ir_version
    if version != expected:
        msg = (
            f"cannot diff IR version {version} against "
            f"{expected} — recompile both sides with one compiler"
        )
        raise SpecParseError(msg)

    try:
        return cast("ProjectIR", _load(payload))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        msg = f"not a bloomery IR document: {exc}"
        raise SpecParseError(msg) from exc
