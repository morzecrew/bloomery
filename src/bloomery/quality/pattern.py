"""Per-dialect validation of ``pattern`` regexes (RFC 0016 §5.3, D5).

The spec layer already rejects the non-portable *syntax* — lookaround and
named groups — and refuses a pattern Python cannot compile. That is the subset
every dialect agrees on, checked once, at parse. What it cannot check is
whether a given **registered dialect** can express the rule at all: a regex
that works on DuckDB and silently means something else on Trino is exactly the
bug this project exists to prevent, so the compile stage renders the lowered
``REGEXP_LIKE`` through *every* registered dialect port and refuses the ones
that cannot carry it.

Two failure modes are detected, both mechanically, both through SQLGlot:

1. the dialect does not declare :attr:`DialectFeature.REGEXP_EXTRACT` — it has
   no regex surface, so the rule could never run;
2. the rendered SQL does not survive a round-trip through that dialect's
   parser with the pattern literal intact — the generator rewrote or dropped
   the regex, which is the silent-divergence case.

Either is a compile-time :class:`~bloomery.errors.GuardrailError` naming the
dialect (§5.3 states the refusal without minting a named leaf, as it does for
the non-string ``unknown_member`` fk in §5.4 — the five named leaves of §5.9
are the complete new-error list).
"""

from __future__ import annotations

from sqlglot import exp, parse_one

from bloomery.dialects import DialectFeature, DialectPort, SQLGlotDialect, registered_dialects

__all__ = [
    "unsupported_dialects",
]


def _sqlglot_name(dialect: DialectPort) -> str:
    """The SQLGlot generator an extension port renders through. Extension
    dialects that are not :class:`SQLGlotDialect` subclasses are probed under
    their own name — SQLGlot resolves it or the round-trip refuses."""
    if isinstance(dialect, SQLGlotDialect):
        return dialect.sqlglot_dialect
    return dialect.name


def _expressible(pattern: str, sqlglot_dialect: str) -> bool:
    """Whether ``pattern`` survives a render/re-parse round-trip intact."""
    node = exp.RegexpLike(this=exp.column("_probe"), expression=exp.Literal.string(pattern))
    try:
        rendered = node.sql(dialect=sqlglot_dialect)
        reparsed = parse_one(rendered, dialect=sqlglot_dialect)
    # Any generator or parser failure is a refusal, not a crash: the whole
    # point is to discover that this dialect cannot carry this regex.
    except Exception:
        return False
    return any(literal.this == pattern for literal in reparsed.find_all(exp.Literal))


def unsupported_dialects(pattern: str) -> tuple[str, ...]:
    """The names of registered dialects that cannot express ``pattern``,
    sorted. Empty means every shipped and extension dialect can carry it."""
    unsupported = [
        dialect.name
        for dialect in registered_dialects()
        if not dialect.supports(DialectFeature.REGEXP_EXTRACT)
        or not _expressible(pattern, _sqlglot_name(dialect))
    ]
    return tuple(sorted(unsupported))
