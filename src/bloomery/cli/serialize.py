"""``--format json``: the values the Python API returns, as JSON (RFC 0020 D4).

The promise is that the CLI is not a second, lossier surface — so this converts
*whole* returned values rather than picking the fields a table happens to show.
:class:`~bloomery.Resolution`'s provenance and topological order are in the JSON
even though :mod:`bloomery.cli.render` prints neither, because a script reading
``--format json`` should not have to drop to Python for a field the function
already returned.

The conversion is structural and total: a frozen dataclass becomes an object of
its fields, an enum becomes its value, a tuple becomes an array, a ``Decimal``
becomes a string (never a float — RFC 0003 D5 rules those out of the package,
and JSON's number type is a float in most readers).

Two values are not converted structurally.

A :class:`~bloomery.LogicalType` is a frozen dataclass whose *identity is its
class*: ``StringType()`` has no fields at all, so a field dump renders it ``{}``
and loses the type entirely. It is rendered with the type layer's own
``render_type``, which produces the exact string a spec writes and
``parse_type`` reads back — the canonical form, not a lossy summary.

A :class:`~bloomery.BloomeryError` is not a dataclass at all, and since
:class:`~bloomery.SpecEvidence` carries refusals as *values* (RFC 0022 D2) the
converter has to know what one looks like or ``bloomery resolve --format json``
fails on exactly the specs it exists to describe. It becomes its class name,
its message, and every attribute the error carries — which is where
``source_path`` lives, and where RFC 0020's structured fix suggestions do, so
they reach a JSON consumer without this module naming a single one of them.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, cast

from bloomery.errors import BloomeryError
from bloomery.typing import LogicalType, render_type

if TYPE_CHECKING:
    from bloomery import EmittedArtifact

__all__ = [
    "artifacts_as_json",
    "as_json_value",
]


def _error_as_json(error: BloomeryError) -> dict[str, object]:
    """A refusal as its class, its message, and everything it carries.

    Read off ``vars()`` rather than from a per-class list: every attribute a
    refusal has was assigned in an ``__init__``, so this covers ``source_path``,
    ``collected`` and each of RFC 0020's structured suggestions without naming
    one of them — and a suggestion added to a sixth error reaches JSON in the
    same commit that adds it, rather than in the one that remembers to.

    Keys are sorted for the same reason every other collection here is.
    """
    return {
        "type": type(error).__name__,
        "message": str(error),
        **{name: as_json_value(attribute) for name, attribute in sorted(vars(error).items())},
    }


def as_json_value(value: object) -> object:
    """Any value the public API returns, as JSON-serializable data."""
    if isinstance(value, LogicalType):
        return render_type(value)
    if isinstance(value, BloomeryError):
        return _error_as_json(value)
    if isinstance(value, Enum):
        return as_json_value(value.value)
    if isinstance(value, Decimal):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: as_json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, (list, tuple)):
        entries = cast("list[object] | tuple[object, ...]", value)
        return [as_json_value(item) for item in entries]
    if isinstance(value, dict):
        entries_map = cast("dict[object, object]", value)
        return {str(key): as_json_value(item) for key, item in entries_map.items()}
    return value


def artifacts_as_json(artifacts: tuple[EmittedArtifact, ...]) -> list[object]:
    """Compiled artifacts as JSON — content included.

    ``bloomery compile --out`` writes files; ``--format json`` is for a caller
    that wants to place them itself, which is the same position the library
    puts a Python caller in. Dropping ``content`` would make the JSON a
    manifest of files nobody received.
    """
    return [as_json_value(artifact) for artifact in artifacts]
