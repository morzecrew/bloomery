"""The declared-vs-produced type battery (RFC 0028 D5).

Every transform declares an output *logical* type
(:attr:`~bloomery.transforms.registry.TransformSpec.output_type`) and,
separately, constructs the AST that computes it
(:attr:`~bloomery.transforms.registry.TransformSpec.builder`). Nothing checked
that the second produces the first. ``to_utc`` declared ``timestamp`` and
produced a zone-*aware* value on all three ports for the whole life of the
project, and it took someone measuring by hand to notice (RFC 0028 §2).

This module is the case corpus, the comparison, and the register of
divergences that exist today. The tiers that own an engine run it: DuckDB in
tier 4, PostgreSQL and Trino in tier 5.

**Why the engine and not emit.** Compilation does no I/O (RFC 0003), so emit
has no engine to ask; the only static model available is SQLGlot's type
annotator, and it answers ``UNKNOWN`` for ``AtTimeZone`` on DuckDB — the exact
node this whole class of defect lived in — while answering confidently for
``CAST(… AS TIMESTAMP)``, which is bloomery's own claim read back to itself.
Worse, a type-shaped check invites a cast-shaped fix, and a cast is a converter
rather than an assertion: wrapping the old ``to_utc`` in ``CAST(… AS
TIMESTAMP)`` satisfies the declared type on every port while keeping the wrong
instant on two of them. The declaration and the engine are the two things that
have to agree, so the engine is where the check belongs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects.base import DialectPort
from bloomery.ir.lower import canon
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

#: Transforms whose AST deliberately reaches no engine, and why. ``convert``
#: builds the ``CONVERT_CURRENCY`` marker, which emit refuses (RFC 0023 D4)
#: precisely because no engine defines it — there is no produced type to
#: compare a declaration against.
UNRUNNABLE: dict[str, str] = {
    "convert": "builds the CONVERT_CURRENCY marker, refused at emit (RFC 0023 D4)",
}

DECIMAL = DecimalType(12, 4)


@dataclass(frozen=True, slots=True)
class Case:
    """One probe: a source column of type ``source`` holding ``value``, with
    ``transform`` applied over it."""

    transform: str
    source: LogicalType
    value: str
    args: tuple[str | int, ...] = ()
    #: Distinguishes two cases sharing a (transform, source) key — the two
    #: format branches of ``parse_ts``/``parse_date``, the two path depths of
    #: ``json_path``.
    label: str = ""

    @property
    def id(self) -> str:
        suffix = f"-{self.label}" if self.label else ""
        return f"{self.transform}-{spell(self.source)}{suffix}"

    @property
    def declared(self) -> LogicalType:
        return DEFAULT_REGISTRY[self.transform].output_type(self.source, self.args)

    def expression(self, column: str) -> Expression:
        """The AST as *emit* sees it, not as the builder returned it.

        The IR keeps canonical dialect-neutral **text** and re-parses at emit
        (RFC 0003 D2), and that round trip is not lossless in the ways that
        matter here: ``json_path``'s path literal only becomes an
        :class:`sqlglot.exp.JSONPath` — the node the PostgreSQL port rewrites
        — after re-parsing, and ``regex_extract``'s capture group comes back
        bound to a different argument entirely. Probing the builder's output
        directly would measure an expression no artifact contains.
        """
        built = DEFAULT_REGISTRY[self.transform].builder(exp.column(column), *self.args)
        return canon(built).ast()


def spell(t: LogicalType) -> str:
    if isinstance(t, DecimalType):
        return f"decimal({t.precision},{t.scale})"
    return type(t).__name__.removesuffix("Type").lower()


#: One case per (transform, input type) the typechecker accepts, plus a second
#: where one builder has two branches. Values are chosen so the transform has
#: something real to do: a `parse_date` over ``'value'`` would measure the
#: engine's error path rather than its type.
CASES: tuple[Case, ...] = (
    # ....................... string transforms
    Case("trim", StringType(), "  padded  "),
    Case("upper", StringType(), "value"),
    Case("lower", StringType(), "VALUE"),
    Case("split_part", StringType(), "a-b-c", ("-", 1)),
    Case("regex_extract", StringType(), "sku-42", ("sku-([0-9]+)", 1)),
    Case("strip_prefix", StringType(), "sku-42", ("sku-",)),
    Case("strip_suffix", StringType(), "42-eu", ("-eu",)),
    Case("concat", StringType(), "42", ("-eu",)),
    Case("enum_map", StringType(), "a", ("a", "alpha", "b", "beta")),
    # ....................... casts and parses
    Case("to_string", StringType(), "value"),
    Case("to_string", IntType(), "42"),
    Case("to_string", DECIMAL, "3.5"),
    Case("to_string", BoolType(), "true"),
    Case("to_string", DateType(), "2026-01-06"),
    Case("to_string", TimestampType(), "2026-01-06 23:30:00"),
    Case("to_string", VariantType(), '{"a": {"b": "x"}}'),
    Case("to_int", StringType(), "42"),
    Case("to_int", IntType(), "42"),
    Case("to_int", DECIMAL, "3.5"),
    Case("to_int", BoolType(), "true"),
    Case("to_decimal", StringType(), "3.5", (12, 4)),
    Case("to_decimal", IntType(), "42", (12, 4)),
    Case("to_decimal", DECIMAL, "3.5", (10, 2)),
    Case("to_bool", StringType(), "true"),
    Case("to_bool", IntType(), "1"),
    Case("to_bool", BoolType(), "true"),
    Case("parse_ts", StringType(), "2026-01-06T23:30:00", ("ISO8601",), "iso"),
    Case("parse_ts", StringType(), "2026-01-06 23:30:00", ("%Y-%m-%d %H:%M:%S",), "format"),
    Case("parse_date", StringType(), "2026-01-06", ("ISO8601",), "iso"),
    Case("parse_date", StringType(), "06/01/2026", ("%d/%m/%Y",), "format"),
    Case("to_utc", TimestampType(), "2026-01-06 23:30:00", ("Europe/Berlin",)),
    # ....................... null handling and JSON
    Case("coalesce", StringType(), "value", ("unknown",)),
    Case("coalesce", IntType(), "42", (0,)),
    Case("coalesce", DECIMAL, "3.5", (0,)),
    Case("coalesce", BoolType(), "true", ("false",)),
    Case("coalesce", DateType(), "2026-01-06", ("1970-01-01",)),
    Case("coalesce", TimestampType(), "2026-01-06 23:30:00", ("1970-01-01 00:00:00",)),
    Case("coalesce", VariantType(), '{"a": {"b": "x"}}', ("{}",)),
    Case("nullif", StringType(), "value", ("sentinel",)),
    Case("nullif", IntType(), "42", (0,)),
    Case("nullif", DECIMAL, "3.5", (0,)),
    Case("nullif", BoolType(), "true", ("false",)),
    Case("nullif", DateType(), "2026-01-06", ("1970-01-01",)),
    Case("nullif", TimestampType(), "2026-01-06 23:30:00", ("1970-01-01 00:00:00",)),
    Case("nullif", VariantType(), '{"a": {"b": "x"}}', ("{}",)),
    Case("json_path", VariantType(), '{"a": {"b": "x"}}', ("$.a.b",), "deep"),
    Case("json_path", VariantType(), '{"a": {"b": "x"}}', ("$.a",), "shallow"),
    Case("json_path", StringType(), '{"a": {"b": "x"}}', ("$.a.b",), "deep"),
    Case("json_path", StringType(), '{"a": {"b": "x"}}', ("$.a",), "shallow"),
    # ....................... arithmetic
    Case("multiply", DECIMAL, "3.5", (2,)),
    Case("divide", DECIMAL, "3.5", (2,)),
    Case("round", IntType(), "42", (0,)),
    Case("round", DECIMAL, "3.5", (2,)),
    Case("abs", IntType(), "-42"),
    Case("abs", DECIMAL, "-3.5"),
)

_COLUMN_OF = {case.id: f"c{index}" for index, case in enumerate(CASES)}


def uncovered() -> tuple[str, ...]:
    """(transform, input type) pairs the registry accepts and no case probes.

    The corpus is hand-written, so the one way it rots is a transform — or a
    widened input domain — arriving without a case. This is what makes that a
    failure rather than a quiet gap in coverage.
    """
    covered = {(case.transform, type(case.source)) for case in CASES}
    return tuple(
        f"{name}({kind.__name__.removesuffix('Type').lower()})"
        for name, spec in sorted(DEFAULT_REGISTRY.items())
        if name not in UNRUNNABLE
        for kind in spec.input_domain
        if (name, kind) not in covered
    )


_TIMESTAMP_FAMILY = frozenset(
    {
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPNTZ,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.TIMESTAMPLTZ,
    }
)


def canonical(spelling: str, *, dialect: str) -> str:
    """An engine's type spelling and a port's, made comparable.

    SQLGlot's type parser is the normalizer: it knows PostgreSQL's ``timestamp
    without time zone`` and the port's ``TIMESTAMP`` are one type, that
    ``numeric(12,4)`` is ``DECIMAL(12, 4)``, and that ``timestamp with time
    zone`` is neither. It renames; it never widens — the zone-aware and
    zoneless spellings stay distinct, which is the distinction the battery
    exists for.

    Timestamp precision is dropped, because bloomery's ``timestamp`` declares
    none: an engine's default (``timestamp(3)`` on Trino) is not a claim a port
    could be wrong about. Decimal precision is kept — ``decimal(12, 4)`` and
    ``decimal(38, 0)`` are different types, and a transform whose declared
    (p, s) is not the engine's is exactly the finding.
    """
    parsed = exp.DataType.build(spelling, dialect=dialect)
    if parsed.this in _TIMESTAMP_FAMILY:
        parsed.set("expressions", None)
    return parsed.sql(dialect=dialect)


def column_of(case: Case) -> str:
    return _COLUMN_OF[case.id]


def source_columns(port: DialectPort) -> tuple[tuple[str, str, str], ...]:
    """``(column name, physical type, literal)`` for the probe table.

    One column per case, so a case's source is a real column rather than a
    folded constant — the distinction that nearly mismeasured RFC 0016 D84,
    where PostgreSQL evaluated a guarded cast at plan time over a constant and
    raised where the column form returns NULL.
    """
    return tuple((column_of(case), port.physical_type(case.source), case.value) for case in CASES)


def probe_sql(case: Case, port: DialectPort, *, relation: str) -> str:
    """``SELECT <the transform, rendered for this port> AS probe FROM …``."""
    select = exp.select(exp.alias_(case.expression(column_of(case)), "probe")).from_(relation)
    return port.render(select)


def declared_type(case: Case, port: DialectPort) -> str:
    """What the transform says it produces, in this port's spelling."""
    return canonical(port.physical_type(case.declared), dialect=port.name)


@dataclass(frozen=True, slots=True)
class Divergence:
    """One (case, port) pair where the engine disagrees with the declaration.

    ``produced`` is the engine's canonical type, or ``error:<code>`` when the
    expression does not run at all — an engine-stable code (a PostgreSQL
    SQLSTATE, a Trino error name), never a message, so an engine upgrade
    rewording itself does not read as a behaviour change.
    """

    produced: str
    why: str


# ....................... #
# The divergences that exist today (RFC 0029)

_WIDENS = (
    "engine decimal arithmetic widens past the (p, s) RFC 0004 §5.4 tracks; the builder "
    "is never told the input type, so it cannot narrow the result back"
)
_UNCONSTRAINED = (
    "PostgreSQL drops the typmod through an expression, so the result is unconstrained "
    "numeric rather than the declared numeric(p, s)"
)
_FLOAT_DIVISION = (
    "`/` yields a binary float, which RFC 0003 D5 forbids in an emission path; "
    "SQLGlot's `typed` flag fixes it on PostgreSQL and Trino but does not survive the "
    "canonical-text round trip, and DuckDB has no exact decimal division at all"
)
_ROUND_KEEPS_INPUT = (
    "the engine's `round(x, d)` rounds the value and keeps the input type, where "
    "RFC 0004 §5.4 narrows the declared scale to d"
)
_PG_NO_CAST = "PostgreSQL refuses this cast between boolean and bigint; only int4 converts"
_PG_TO_TIMESTAMP_TZ = (
    "PostgreSQL's `to_timestamp(text, text)` returns `timestamptz` — the same defect "
    "RFC 0028 closed for `to_utc`, surviving in `parse_ts`'s explicit-format branch, "
    "which no fixture uses"
)
_TRINO_LITERAL_NOT_COERCED = (
    "Trino does not coerce a varchar literal to the column's type, so a spec-level "
    "sentinel or fallback that runs on DuckDB and PostgreSQL fails to plan here"
)

#: port name → case id → the divergence measured there.
#:
#: **Exact, not a floor.** The tiers assert set equality, so a divergence that
#: appears is a failure *and* one that disappears is too — a fix cannot land
#: without deleting its row, and a regression cannot hide behind a row that
#: happens to describe it. Every entry is scheduled in RFC 0029.
KNOWN: dict[str, dict[str, Divergence]] = {
    "duckdb": {
        "coalesce-decimal(12,4)": Divergence("DECIMAL(14, 4)", _WIDENS),
        "multiply-decimal(12,4)": Divergence("DECIMAL(18, 4)", _WIDENS),
        "round-decimal(12,4)": Divergence("DECIMAL(12, 2)", _WIDENS),
        "divide-decimal(12,4)": Divergence("DOUBLE", _FLOAT_DIVISION),
    },
    "postgres": {
        "coalesce-decimal(12,4)": Divergence("DECIMAL", _UNCONSTRAINED),
        "multiply-decimal(12,4)": Divergence("DECIMAL", _UNCONSTRAINED),
        "round-decimal(12,4)": Divergence("DECIMAL", _UNCONSTRAINED),
        "abs-decimal(12,4)": Divergence("DECIMAL", _UNCONSTRAINED),
        "round-int": Divergence(
            "DECIMAL",
            "PostgreSQL has no `round(bigint, int)`, so the argument is promoted to "
            "numeric and the result is numeric where `round` declares the input type "
            "unchanged",
        ),
        "divide-decimal(12,4)": Divergence("DOUBLE PRECISION", _FLOAT_DIVISION),
        "to_int-bool": Divergence("error:42846", _PG_NO_CAST),
        "to_bool-int": Divergence("error:42846", _PG_NO_CAST),
    },
    "trino": {
        "coalesce-decimal(12,4)": Divergence("DECIMAL(14, 4)", _WIDENS),
        "multiply-decimal(12,4)": Divergence("DECIMAL(22, 4)", _WIDENS),
        "round-decimal(12,4)": Divergence("DECIMAL(13, 4)", _ROUND_KEEPS_INPUT),
        "divide-decimal(12,4)": Divergence("DOUBLE", _FLOAT_DIVISION),
        "coalesce-bool": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "coalesce-date": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "coalesce-timestamp": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "coalesce-variant": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "nullif-bool": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "nullif-date": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "nullif-timestamp": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
        "nullif-variant": Divergence("error:TYPE_MISMATCH", _TRINO_LITERAL_NOT_COERCED),
    },
}


def measure(
    port: DialectPort, probe: Callable[[str], str], *, relation: str = "probe"
) -> dict[str, str]:
    """Run every case and return ``case id -> produced`` for the ones that
    disagree with the declaration.

    ``probe`` runs one ``SELECT`` and returns the engine's type for its single
    column, canonicalized — or ``error:<code>`` if the engine refused it.
    """
    observed: dict[str, str] = {}
    for case in CASES:
        produced = probe(probe_sql(case, port, relation=relation))
        if produced != declared_type(case, port):
            observed[case.id] = produced
    return observed


def assert_matches_known(observed: dict[str, str], *, port: str) -> None:
    """The measured divergences are exactly the registered ones."""
    registered = {case_id: entry.produced for case_id, entry in KNOWN[port].items()}
    appeared = {k: v for k, v in observed.items() if registered.get(k) != v}
    vanished = {k: v for k, v in registered.items() if observed.get(k) != v}
    assert not appeared and not vanished, (
        f"{port}: declared and produced types disagree in ways the register does not "
        f"describe.\n  new or changed: {appeared or '{}'}\n  registered but not "
        f"measured (a fix landed — delete the row): {vanished or '{}'}"
    )
