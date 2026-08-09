"""The ``<entity>__reject`` identity and payload columns (RFC 0016 §5.6).

``reject_id`` is the sha256 over the **length-prefixed pair**
``(source_relation, _source_row_id)`` — RFC 0003's canon-bytes doctrine
reproduced *in SQL*, so the value is recomputable from the reject row itself.
Each element is written ``S<length>:<value>``, the constant ``source_relation``
folded to a literal at compile and the row identity length-prefixed at run
time.

**One deviation from the Python encoder, recorded here.** ``ir/fingerprint.py``
prefixes the utf-8 **byte** length; this prefixes the **character** length,
because no byte-length function is portable across the shipped dialects —
DuckDB's ``OCTET_LENGTH`` takes ``BLOB`` only, Trino has none, and only
Postgres spells it for text. ``LENGTH`` means characters on all three, and
cross-dialect *agreement* is the property ``reject_id`` actually needs (the
value is computed in SQL and never in Python, so the two encoders never have to
match). What length-prefixing buys — injectivity, so ``('ab', 'c')`` and
``('a', 'bc')`` cannot collide — is unaffected by which length is used.

``_load_id`` is deliberately **not** part of the identity (D21): re-deliveries
of the same source row across loads must land on the **same** reject row —
which is what ``first_seen``/``last_seen`` exist to track. A per-load identity
would mint a new reject row per retry and violate replay idempotence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

__all__ = [
    "REJECT_COLUMNS",
    "SUPERSEDED_RULE",
    "canon_literal",
    "canon_prefixed",
    "reject_id",
]

#: The reserved ``failed_rules`` entry naming the one way a reject row can be
#: out of the entity without failing anything (RFC 0016 D69): another row won
#: its entity key. Parenthesised for the same reason
#: :data:`~bloomery.quality.ENTITY_GRAIN_ROW` is — rule names are constrained
#: to ``[a-z0-9_]+`` at parse and at generation (D23), so no authored or
#: generated name can ever collide with a spelling carrying parentheses.
SUPERSEDED_RULE = "(superseded)"

#: The reject table's column order (RFC 0016 §5.6). Authored order, not sorted:
#: it is a schema, and the emitted projection reads like the RFC's DDL.
REJECT_COLUMNS: tuple[str, ...] = (
    "reject_id",
    "source_relation",
    "mapping",
    "mapping_version",
    "failed_rules",
    "key_values",
    "raw",
    "_load_id",
    "_ingested_at",
    "_source_row_id",
    "first_seen",
    "last_seen",
    "resolved_at",
)


def canon_literal(value: str) -> str:
    """The canonical encoding of a compile-time-known string:
    ``S<character length>:<value>`` (see the module docstring on why this is
    characters and not utf-8 bytes)."""
    return f"S{len(value)}:{value}"


def canon_prefixed(column: Expression) -> tuple[Expression, ...]:
    """The canonical encoding of a run-time string, as SQL fragments:
    ``'S' || LENGTH(col) || ':' || col``."""
    length = exp.cast(exp.Length(this=column.copy()), exp.DataType.build("TEXT"))
    return (exp.Literal.string("S"), length, exp.Literal.string(":"), column)


def reject_id(
    source_relation: str, row_id: Expression, digest: Callable[[Expression], Expression]
) -> Expression:
    """A SHA-256 hex digest over the canon bytes of ``(source_relation,
    _source_row_id)``.

    The pair is serialized in the schema's own order — ``source_relation``
    first, then the row identity — so the value is stable, idempotent under
    replay, and recomputable from the reject row itself.

    ``digest`` comes from the dialect port (RFC 0016 D83). The spellings are
    genuinely different rather than cosmetically so — DuckDB's
    ``SHA256(VARCHAR)`` already returns hex, Postgres' returns ``bytea``, and
    Trino's does not accept text at all — so a single AST here produced a
    value that was hex on one engine, bytes on another, and unplannable on the
    third. Cross-dialect *agreement* is the property ``reject_id`` needs.
    """
    parts: tuple[Expression, ...] = (
        exp.Literal.string(canon_literal(source_relation)),
        *canon_prefixed(row_id),
    )
    return digest(cast("Expression", exp.func("CONCAT", *parts)))
