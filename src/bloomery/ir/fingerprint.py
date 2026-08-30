"""The ``project_fingerprint`` content hash (RFC 0003 §5.4).

``_canon_bytes`` walks the frozen dataclass tree emitting a purpose-built
length-prefixed, type-tagged byte stream — deliberately not JSON, which tempts
float formatting and key-ordering bugs. Floats are rejected with ``TypeError``
(RFC 0003 D5); enums encode by value; ``Decimal`` by ``str()``. The stream is
stable across processes, machines, and ``PYTHONHASHSEED`` values, proven by
the subprocess determinism guard (RFC 0003 §5.6).
"""

from __future__ import annotations

import dataclasses
import hashlib
from decimal import Decimal
from enum import Enum
from typing import cast

from bloomery.ir.nodes import ProjectIR

# ----------------------- #

__all__ = [
    "project_fingerprint",
]


def _write_tagged(out: bytearray, tag: bytes, payload: bytes) -> None:
    out += tag + str(len(payload)).encode("ascii") + b":" + payload


# ....................... #


def _write(out: bytearray, value: object) -> None:
    # Order matters: bool before int (bool is an int subclass); Enum before
    # int/str (IntEnum/StrEnum are subclasses of both).
    if value is None:
        out += b"N"
    elif isinstance(value, bool):
        out += b"B1" if value else b"B0"
    elif isinstance(value, float):
        msg = f"floats are banned in the IR (RFC 0003 D5), got {value!r}"
        raise TypeError(msg)
    elif isinstance(value, Enum):
        _write_tagged(out, b"E", str(value.value).encode("utf-8"))
    elif isinstance(value, int):
        _write_tagged(out, b"I", str(value).encode("ascii"))
    elif isinstance(value, str):
        _write_tagged(out, b"S", value.encode("utf-8"))
    elif isinstance(value, Decimal):
        _write_tagged(out, b"D", str(value).encode("ascii"))
    elif isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        out += b"T" + str(len(items)).encode("ascii") + b":"
        for item in items:
            _write(out, item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = dataclasses.fields(value)
        out += b"C"
        _write_tagged(out, b"S", type(value).__name__.encode("utf-8"))
        out += str(len(fields)).encode("ascii") + b":"
        for f in fields:
            _write_tagged(out, b"S", f.name.encode("utf-8"))
            _write(out, getattr(value, f.name))
    else:
        msg = f"unsupported value in IR canonical encoding: {type(value).__name__}"
        raise TypeError(msg)


# ....................... #


def _canon_bytes(ir: object) -> bytes:
    """Canonically encode an IR node tree (RFC 0003 §5.4): length-prefixed,
    type-tagged, field names included, tuples length-prefixed."""
    out = bytearray()
    _write(out, ir)

    return bytes(out)


# ....................... #


def project_fingerprint(ir: ProjectIR) -> str:
    """The ``blm1:``-prefixed SHA-256 content hash of a :class:`ProjectIR`.

    Stable within a bloomery version (``bloomery_ir_version`` is part of the
    stream), explicitly not across versions (RFC 0003 D3).
    """

    return "blm1:" + hashlib.sha256(_canon_bytes(ir)).hexdigest()
