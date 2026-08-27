""":mod:`json` for the values the Python API returns (RFC 0020 D4).

The promise is that the CLI is not a second, lossier surface — so this converts
*whole* returned values rather than picking the fields a table happens to show.
:class:`~bloomery.Resolution`'s provenance and topological order are in the JSON
even though :mod:`bloomery.cli.render` prints neither, because a script reading
``--format json`` should not have to drop to Python for a field the function
already returned.

It is a :class:`json.JSONEncoder`, not a walker of its own: ``default`` is asked
only about the types :mod:`json` does not already know, so lists, tuples, dicts
and every ``StrEnum`` recurse through the encoder that was going to run anyway.
The conversion is structural and total — a frozen dataclass becomes an object of
its fields, an enum becomes its value, a ``Decimal`` becomes a string (never a
float: RFC 0003 D5 rules those out of the package, and JSON's number type is a
float in most readers).

Two values are not converted structurally.

A :class:`~bloomery.LogicalType` is a frozen dataclass whose *identity is its
class*: ``StringType()`` has no fields at all, so a field dump renders it ``{}``
and loses the type entirely. It is rendered with the type layer's own
``render_type``, which produces the exact string a spec writes and
``parse_type`` reads back — the canonical form, not a lossy summary. It is
tested before the dataclass branch for that reason.

A :class:`~bloomery.BloomeryError` is not a dataclass at all, and since
:class:`~bloomery.SpecEvidence` carries refusals as *values* (RFC 0022 D2) the
encoder has to know what one looks like or ``bloomery resolve --format json``
fails on exactly the specs it exists to describe. It becomes its class name,
its message, and every attribute the error carries — which is where
``source_path`` lives, and where RFC 0020's structured fix suggestions do, so
they reach a JSON consumer without this module naming a single one of them.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from enum import Enum
from typing import Any

from bloomery.errors import BloomeryError
from bloomery.typing import LogicalType, render_type

__all__ = [
    "SpecEncoder",
]


def _error_as_json(error: BloomeryError) -> dict[str, object]:
    """A refusal as its class, its message, and everything it carries.

    Attributes are read off ``vars()`` rather than from a per-class list: every
    attribute a refusal has was assigned in an ``__init__``, so this covers
    ``source_path``, ``collected`` and each of RFC 0020's structured
    suggestions without naming one of them — and a suggestion added to a sixth
    error reaches JSON in the same commit that adds it, rather than in the one
    that remembers to.

    **The reserved keys are written last, so they win.** They used to lead, and
    a ``**`` expansion after them overwrites rather than yields: an error
    carrying its own ``type`` attribute — which no error in this package does,
    but the hierarchy is public and extensible — replaced the class name with
    its own value, and every consumer branching on ``payload["type"] ==
    "GrainViolation"`` silently stopped matching. Losing an attribute to a name
    collision is a small harm; corrupting the discriminator is not, because
    nothing downstream can detect it.
    """
    return {**vars(error), "type": type(error).__name__, "message": str(error)}


class SpecEncoder(json.JSONEncoder):
    """The encoder every ``--format json`` command dumps through."""

    # `o: Any` is `json.JSONEncoder.default`'s own signature. The encoder is
    # asked about whatever `json` could not serialize, which is by definition
    # not a set of types this module can name in advance.
    def default(self, o: Any) -> object:
        # LogicalType before the dataclass branch: it is a frozen dataclass
        # too, and a field dump would render `StringType()` as `{}`.
        if isinstance(o, LogicalType):
            return render_type(o)
        if isinstance(o, BloomeryError):
            return _error_as_json(o)
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, Decimal):
            return str(o)
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return {field.name: getattr(o, field.name) for field in dataclasses.fields(o)}
        return super().default(o)
