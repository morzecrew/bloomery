"""The dialect port and registry (S-0025/ports, S-0025/D-8): physical type mapping,
feature queries, registry collision/unknown-name behavior."""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import typing

import pytest
from sqlglot import exp

from bloomery.dialects import (
    DialectFeature,
    DialectPort,
    DuckDBDialect,
    PostgresDialect,
    SQLGlotDialect,
    TrinoDialect,
    get_dialect,
    register_dialect,
)
from bloomery.dialects.base import DIALECT_PORT_MEMBERS, strip_iso_text
from bloomery.errors import EmitError, UnsupportedByTarget
from bloomery.ir.lower import canon
from bloomery.quality.pattern import unsupported_dialects
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import DecimalType, StringType

pytestmark = pytest.mark.unit

dialects_module = importlib.import_module("bloomery.dialects")


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(dialects_module, "_overlay", {})
    yield


class _Custom(SQLGlotDialect):
    name = "custom"
    sqlglot_dialect = "postgres"


def test_get_dialect_returns_the_default() -> None:
    assert isinstance(get_dialect("duckdb"), DuckDBDialect)


def test_unknown_dialect_lists_known_names() -> None:
    expected = (
        r"unknown dialect 'sqlite': known dialects are "
        r"\['bigquery', 'databricks', 'duckdb', 'postgres', 'trino'\]"
    )
    with pytest.raises(EmitError, match=expected):
        get_dialect("sqlite")


def test_register_dialect_overlay() -> None:
    register_dialect(_Custom())
    assert get_dialect("custom").name == "custom"


def test_register_dialect_collision_is_an_error() -> None:
    with pytest.raises(EmitError, match="'duckdb' is already registered"):
        register_dialect(DuckDBDialect())


def test_an_incomplete_port_is_refused_at_registration() -> None:
    """`DialectPort` is a Protocol, so it is satisfied *structurally* and never
    inherited: a port can pass a type checker and still omit a member, and the
    first anyone hears of it is an `AttributeError` from inside emission —
    naming an attribute rather than a contract, at a point the caller cannot
    act on.

    The member that prompted this is `begin_transaction`, added so the replay
    macro opens a transaction its engine spells; but the check is over every
    member, because the next one added would otherwise reintroduce the same
    gap.
    """

    class _Incomplete:
        name = "incomplete"

        def render(self, node: object) -> str:  # pragma: no cover — never reached
            return ""

    with pytest.raises(EmitError, match="does not implement begin_transaction"):
        register_dialect(_Incomplete())  # type: ignore[arg-type]

    with pytest.raises(EmitError, match="unknown dialect 'incomplete'"):
        get_dialect("incomplete")


def _protocol_members(protocol: type) -> frozenset[str]:
    """The members a `Protocol` declares, on every supported Python.

    `typing.get_protocol_members` is the public spelling and is 3.13+; this
    project's floor is 3.12, where the same set is on `__protocol_attrs__`.
    Falling back to the dunder keeps the drift check below running on **all
    three** supported versions, which a `skipif` would not: a check that does
    not run on the floor is one the floor can drift past.

    Neither present is a hard failure rather than a skip. A skip that becomes
    permanent is a hole nobody sees, and this is the only thing standing between
    `DIALECT_PORT_MEMBERS` and the class it claims to mirror.
    """
    public = getattr(typing, "get_protocol_members", None)

    if public is not None:
        return frozenset(public(protocol))  # type: ignore[arg-type]

    members = getattr(protocol, "__protocol_attrs__", None)
    assert members is not None, (
        "no way to read a Protocol's members on this interpreter — the drift check "
        "below cannot run, and silently skipping it is what it exists to prevent"
    )
    return frozenset(members)


def test_the_declared_port_members_are_the_protocols() -> None:
    """The list existing and being wrong is worse than no list.

    `DIALECT_PORT_MEMBERS` is data because `register_dialect` has to iterate it
    at run time, and a hand-kept copy of a class's shape drifts the first time
    someone adds a member. This is what stops that — and it is the reason the
    tuple is safe to trust rather than a second place to remember.
    """
    assert frozenset(DIALECT_PORT_MEMBERS) == _protocol_members(DialectPort)


def test_pattern_check_does_not_consult_the_mutable_registry() -> None:
    """S-0033/D-56: registering a dialect must not change any verdict the
    compile stage reaches. A port that refuses every regex would flip
    ``unsupported_dialects`` if the check read the registry — it does not."""

    class _NoRegex(SQLGlotDialect):
        name = "noregex"
        sqlglot_dialect = "duckdb"

        def supports(self, feature: DialectFeature) -> bool:
            return feature is not DialectFeature.REGEXP_EXTRACT

    before = unsupported_dialects("^ok$")
    register_dialect(_NoRegex())
    assert unsupported_dialects("^ok$") == before == ()
    # ...and the explicit-argument hatch is what *does* see it. The caller
    # names its own port rather than enumerating the registry, which is the
    # only shape D56 offers — see `bloomery.dialects`.
    assert unsupported_dialects("^ok$", dialects=(_NoRegex(),)) == ("noregex",)


def test_base_render_is_deterministic() -> None:
    node = exp.cast(exp.column("x"), exp.DataType.build("TEXT"))
    assert _Custom().render(node) == _Custom().render(node)


def test_base_supports_all_declared_features() -> None:
    dialect = _Custom()
    for feature in DialectFeature:
        assert dialect.supports(feature)


def test_base_physical_types() -> None:
    dialect = _Custom()
    assert dialect.physical_type(StringType()) == "TEXT"
    assert dialect.physical_type(DecimalType(12, 4)) == "DECIMAL(12, 4)"


@pytest.mark.parametrize(
    "dialect",
    [DuckDBDialect(), PostgresDialect(), TrinoDialect()],
    ids=lambda dialect: dialect.name,
)
def test_every_shipped_dialect_has_arrays(dialect: DialectPort) -> None:
    # S-0033/D-9: array support is an *engine* property, recorded as a
    # DialectFeature — SQLMesh-on-DuckDB and dbt-on-DuckDB share it (the
    # S-0025/D-1 split). All three shipped engines have a first-class array
    # type (DuckDB STRING[], Postgres TEXT[], Trino ARRAY(VARCHAR)), so none
    # takes the delimited fallback.
    assert dialect.supports(DialectFeature.ARRAY)


def test_array_is_a_dialect_feature() -> None:
    # S-0033/D-9's deliberate divergence from Document 5 §5.3: array support
    # is an engine property, recorded on the dialect port. (The target-side
    # Feature vocabulary it diverged from has since been removed outright —
    # nothing ever consulted it.)
    assert "array" in {feature.value for feature in DialectFeature}


def test_a_port_that_never_strips_the_iso_marker_is_refused() -> None:
    """The default is neither identity nor silence (S-0044).

    A port registered through `register_dialect` that inherits the base render
    and never decides what its engine needs would otherwise emit
    `BLM_ISO_TEXT(x)` — an undefined function that fails at *plan* time with the
    engine's own message. Defaulting to identity instead would be worse still:
    an engine whose cast rejects the `T` separator would return NULL for good
    data, which is the defect S-0044 exists to close.

    So the base renderer refuses, at emit, naming the one call to make.
    """

    class _Forgetful(SQLGlotDialect):
        name = "forgetful"
        sqlglot_dialect = "duckdb"

    node = exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )
    with pytest.raises(UnsupportedByTarget) as excinfo:
        _Forgetful().render(node)
    message = str(excinfo.value)
    assert "'forgetful'" in message
    assert "strip_iso_text" in message
    # The reason, not only the rule: a port author has to know why identity is
    # not a safe default.
    assert "silently NULL" in message


def test_a_port_that_strips_the_marker_renders_normally() -> None:
    """The companion: without it, deleting the guard's trigger would look like
    a pass."""

    class _Careful(SQLGlotDialect):
        name = "careful"
        sqlglot_dialect = "duckdb"

        def render(self, node: exp.Expression) -> str:
            return super().render(strip_iso_text(node.copy(), lambda text: text))

    node = exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )
    assert _Careful().render(node) == (
        "CAST(CASE\n"
        "  WHEN SUBSTRING(CAST(x AS TEXT), 11) LIKE '%+%'\n"
        "  OR SUBSTRING(CAST(x AS TEXT), 11) LIKE '%-%'\n"
        "  THEN NULL\n"
        "  ELSE x\n"
        "END AS TIMESTAMP)"
    )


@pytest.mark.parametrize(
    ("dialect", "window"),
    [
        (DuckDBDialect(), "SUBSTRING(CAST(_ingested_at AS TEXT), 11)"),
        (PostgresDialect(), "SUBSTRING(CAST(_ingested_at AS VARCHAR) FROM 11)"),
        (TrinoDialect(), "SUBSTR(CAST(_ingested_at AS VARCHAR), 11)"),
    ],
    ids=lambda value: getattr(value, "name", "window"),
)
def test_the_offset_guard_reads_its_operand_as_text_on_every_port(
    dialect: DialectPort, window: str
) -> None:
    """S-0052's guard takes its window over an explicit cast, on all three.

    The marked operand is text in a transform chain by `parse_ts`'s declared
    input type — but on S-0033/D-21's metadata audit the marker sits on a
    **bronze column**, which is whatever the project landed. Measured: none of
    the three engines plans `SUBSTRING(<timestamp>, 11)`, so a guard reading
    the operand raw would refuse to *compile* the audit instead of refusing the
    value, on the one column no `coercible` rule can reach. It is the same
    totality the Trino port already bought with the cast before its `replace`,
    and the guard has to buy it too or the port's is undone one node above.
    """
    node = exp.TryCast(
        this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("_ingested_at")]),
        to=exp.DataType.build("TIMESTAMP"),
    )
    # The window's own operand, not merely some cast in the expression: Trino's
    # `replace` spelling casts too, and asserting on that would pass here while
    # the window still read a raw timestamp.
    assert window in dialect.render(node)


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        (DuckDBDialect(), "REGEXP_EXTRACT(sku, 'sku-([0-9]+)', 1)"),
        # PostgreSQL has no `regexp_extract`; `regexp_substr`'s sixth argument
        # is the capture group (S-0046/what-was-measured (§2.3)).
        (PostgresDialect(), "REGEXP_SUBSTR(sku, 'sku-([0-9]+)', 1, 1, '', 1)"),
        (TrinoDialect(), "REGEXP_EXTRACT(sku, 'sku-([0-9]+)', 1)"),
    ],
    ids=lambda value: value.name if isinstance(value, SQLGlotDialect) else "sql",
)
def test_the_capture_group_survives_the_canonical_round_trip(
    dialect: DialectPort, expected: str
) -> None:
    """Every port *renders* ``{regex_extract: [pattern, N]}`` with group N.

    ``regex_extract`` builds :class:`sqlglot.exp.RegexpExtract` with ``group``
    set, which renders correctly — but the IR keeps canonical text and
    re-parses at emit (S-0020/D-2), and ``REGEXP_EXTRACT(x, p, 1)`` re-parses
    with the third argument bound to ``position``. SQLGlot's duckdb and trino
    generators then **drop it**, warning to a stderr nothing reads, so the
    transform returned group 0 — the whole match — on both engines that can run
    it. Measured before the fix: ``REGEXP_EXTRACT('sku-42', 'sku-([0-9]+)')``
    is ``'sku-42'`` on DuckDB where the three-argument form is ``'42'``.

    This asserts the rendering, not the run, and the three expectations are no
    longer the same string: PostgreSQL defines no ``regexp_extract``, so
    S-0046/what-was-measured (§2.3) gave it ``regexp_substr``, whose sixth argument is the group.
    Pinning all three is what keeps the restoration port-independent — the
    spelling PostgreSQL got still had to carry the group, and this is the test
    that said so before it existed.

    No fixture used ``regex_extract``, so no golden showed it; the
    declared-vs-produced battery found it (S-0045/D-5).
    """
    built = DEFAULT_REGISTRY["regex_extract"].builder(exp.column("sku"), "sku-([0-9]+)", 1)
    assert dialect.render(canon(built).ast()) == expected


def test_a_capture_group_the_author_set_is_never_overwritten() -> None:
    """The rewrite fills in a group the round trip lost; it does not decide one
    for a tree that already carries it."""
    node = exp.RegexpExtract(
        this=exp.column("sku"),
        expression=exp.Literal.string("sku-([0-9]+)"),
        position=exp.Literal.number(1),
        group=exp.Literal.number(2),
    )
    assert DuckDBDialect().render(node) == "REGEXP_EXTRACT(sku, 'sku-([0-9]+)', 2)"


def test_restoring_the_capture_group_does_not_mutate_the_input() -> None:
    """The port contract shares one neutral AST across every dialect, so a
    rewrite that edited in place would leave the next dialect rendering the
    previous one's tree — the trap :mod:`tests.unit.test_dialects.test_trino`
    already guards for zone interpretation."""
    node = exp.select(
        exp.alias_(
            canon(
                DEFAULT_REGISTRY["regex_extract"].builder(exp.column("sku"), "sku-([0-9]+)", 1)
            ).ast(),
            "n",
        )
    )
    before = node.sql()
    DuckDBDialect().render(node)
    assert node.sql() == before
    assert node.find(exp.RegexpExtract).args.get("group") is None  # still the demoted form


# ....................... #
# `utc_now` — the engine's instant as a zoneless UTC timestamp (S-0003/P-1)


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("duckdb", "CAST(TIMEZONE('UTC', CURRENT_TIMESTAMP) AS TIMESTAMP)"),
        ("postgres", "CAST(TIMEZONE('UTC', CURRENT_TIMESTAMP) AS TIMESTAMP)"),
        ("trino", "CAST(AT_TIMEZONE(CURRENT_TIMESTAMP, 'UTC') AS TIMESTAMP)"),
    ],
)
def test_utc_now_states_the_zone_on_every_port(dialect: str, expected: str) -> None:
    """`timestamp` is always UTC and zoneless here, and every engine's
    `CURRENT_TIMESTAMP` is zone-*aware* instead.

    The two wrong answers are both plausible. A bare `CURRENT_TIMESTAMP`
    written into a text column carries an offset — measured on DuckDB through
    dbt: `2026-09-17 19:18:21.796404+03`, which the D21 audit refuses. And
    `CAST(CURRENT_TIMESTAMP AS TIMESTAMP)` keeps the *session's* wall clock,
    which is the S-0045/what-was-measured defect in a shape that looks like the fix.

    Trino's spelling is different rather than cosmetically so: it has no
    `timezone(zone, ts)`, and `with_timezone` — the function the port's other
    UTC door uses — states the zone of a *zoneless* value and is a type error
    on an instant that already has one.
    """
    assert get_dialect(dialect).render(get_dialect(dialect).utc_now()) == expected


def test_utc_now_is_not_rewritten_by_the_ports_zone_door() -> None:
    """The ports rewrite every `exp.AtTimeZone` into their own door into the
    `timestamp` type, and that door is for a zoneless *local* value being told
    which clock it came off.

    Spelling `utc_now` as an `AtTimeZone` therefore double-converted on DuckDB
    and PostgreSQL — `CURRENT_TIMESTAMP AT TIME ZONE 'UTC' AT TIME ZONE 'UTC'`,
    zone-aware again — and handed Trino's `with_timezone` an instant. This is
    what pins the spelling as a function call rather than as that node.
    """
    for name in ("duckdb", "postgres", "trino"):
        assert "AT TIME ZONE" not in get_dialect(name).render(get_dialect(name).utc_now())
