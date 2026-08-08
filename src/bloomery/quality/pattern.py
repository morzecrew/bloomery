"""What a target dialect can do with a ``pattern`` rule (RFC 0016 §5.3, D5).

Read this module for what it **is not**, first. It does not validate regex
*semantics* per dialect, and nothing that runs at compile time can: bloomery
never executes SQL (D10), and the only authority on whether DuckDB's RE2
accepts ``\\A`` is DuckDB. Rendering a pattern through SQLGlot and reading it
back proves the *literal* travelled; it proves nothing about the engine's
regex engine, which is why a denylist plus a round-trip once accepted
backreferences, atomic groups, possessive quantifiers and ``\\A``/``\\Z`` —
every one of which aborts the run on DuckDB (§11, D53).

The flavour knowledge lives one layer up instead, in
:data:`~bloomery.spec.quality.PortableRegex`: a closed **allowlist** scanner
over the constructs RE2 (DuckDB, Trino) and POSIX ARE (Postgres) agree on.
Static, stated, and refusing everything it does not name.

What is left here is real, and narrow — two mechanical questions about a
*dialect*, not about a regex:

1. does the dialect declare :attr:`DialectFeature.REGEXP_EXTRACT`? A dialect
   with no regex surface could never run the rule;
2. does a ``REGEXP_LIKE`` carrying this pattern survive rendering and
   re-parsing through that dialect with the literal intact? That is literal
   *transport* — it catches a dialect name SQLGlot cannot resolve at all, and
   a generator that would mangle the pattern text on its way into SQL.

Either is a compile-time :class:`~bloomery.errors.GuardrailError` naming the
dialect (§5.3 states the refusal without minting a named leaf, as it does for
the non-string ``unknown_member`` fk in §5.4 — the five named leaves of §5.9
are the complete new-error list).
"""

from __future__ import annotations

from typing import Final

from sqlglot import exp, parse_one

from bloomery.dialects import DialectFeature, DialectPort, SQLGlotDialect, get_dialect

__all__ = [
    "PATTERN_TARGET_DIALECTS",
    "unsupported_dialects",
]

#: The dialects a `pattern` rule is checked against by default: the ports
#: bloomery ships, named as a constant rather than read from the registry
#: (RFC 0016 D56). ``registered_dialects()`` is process-global and mutable —
#: an extension dialect registered by an unrelated import could decide
#: whether an existing project compiles, which is precisely the ambient
#: dependency RFC 0003 forbids. A caller that targets an extension dialect
#: passes it explicitly to :func:`unsupported_dialects`.
PATTERN_TARGET_DIALECTS: Final[tuple[str, ...]] = ("duckdb", "postgres", "trino")


def _sqlglot_name(dialect: DialectPort) -> str:
    """The SQLGlot generator an extension port renders through. Extension
    dialects that are not :class:`SQLGlotDialect` subclasses are probed under
    their own name — SQLGlot resolves it or the round-trip refuses."""
    if isinstance(dialect, SQLGlotDialect):
        return dialect.sqlglot_dialect
    return dialect.name


def _transports_literal(pattern: str, sqlglot_dialect: str) -> bool:
    """Whether ``pattern`` survives a render/re-parse round-trip intact.

    A transport check, not a semantics check: it answers "does this dialect
    exist for SQLGlot, and does the pattern text reach the SQL unchanged",
    never "will the engine's regex engine accept it".
    """
    node = exp.RegexpLike(this=exp.column("_probe"), expression=exp.Literal.string(pattern))
    try:
        rendered = node.sql(dialect=sqlglot_dialect)
        reparsed = parse_one(rendered, dialect=sqlglot_dialect)
    # Any generator or parser failure is a refusal, not a crash: the whole
    # point is to discover that this dialect cannot carry this regex.
    except Exception:
        return False
    return any(literal.this == pattern for literal in reparsed.find_all(exp.Literal))


def unsupported_dialects(
    pattern: str, dialects: tuple[DialectPort, ...] | None = None
) -> tuple[str, ...]:
    """The names of ``dialects`` that cannot carry ``pattern``, sorted.

    ``dialects`` defaults to the shipped ports named by
    :data:`PATTERN_TARGET_DIALECTS` — never the mutable registry, so the
    verdict is a function of the pattern and the bloomery version alone. Empty
    means every checked dialect declares a regex surface and transports the
    literal; it is **not** a statement that every engine's regex engine
    accepts the pattern (see the module docstring — the spec layer's allowlist
    is what carries that claim).
    """
    checked = (
        tuple(get_dialect(name) for name in PATTERN_TARGET_DIALECTS)
        if dialects is None
        else dialects
    )
    unsupported = [
        dialect.name
        for dialect in checked
        if not dialect.supports(DialectFeature.REGEXP_EXTRACT)
        or not _transports_literal(pattern, _sqlglot_name(dialect))
    ]
    return tuple(sorted(unsupported))
