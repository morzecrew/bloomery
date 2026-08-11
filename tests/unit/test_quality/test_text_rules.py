"""``normalize`` and ``charset`` — the two rules D86 added to close D26.

The matrix in :mod:`test_predicates` already executes both at every
disposition. What is left here is what a single specimen cannot say: the
``allow`` reading of ``charset`` (the matrix carries the ``forbid`` one), the
declarations both rules refuse, and the two per-dialect facts each depends on.

Every character these rules exist to catch is invisible, so **every literal in
this module is written as an escape**. A test whose specimen and control are
indistinguishable in a diff cannot be reviewed, which is the same reason the
spec surface takes ``U+`` codepoints rather than the characters themselves.
"""

from __future__ import annotations

import duckdb
import pydantic
import pytest
from sqlglot import exp, parse_one
from support.compiling import compile_fixture
from support.quality_rules import rule_of_kind

from bloomery.dialects import DialectFeature, SQLGlotDialect, get_dialect, register_dialect
from bloomery.errors import GuardrailError, UnsupportedByTarget
from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import violation
from bloomery.quality.charset import MAX_CHARSET_SIZE, expand_codepoints
from bloomery.spec.quality import CharsetRule, NormalizeRule

pytestmark = pytest.mark.unit

_PORT = get_dialect("duckdb")

#: ``Acme`` and ``Corp`` joined by a zero-width space, and the same string
#: without one. They render identically.
ZWSP_NAME = "Acme\u200bCorp"
CLEAN_NAME = "AcmeCorp"

#: ``café`` decomposed and precomposed. Likewise indistinguishable.
NFD_CAFE = "cafe\u0301"
NFC_CAFE = "caf\u00e9"


def _charset_rule(side: str, items: tuple[str, ...]) -> QualityRuleIR:
    return QualityRuleIR(
        name="name_charset",
        kind="charset",
        column="name",
        on_fail=OnFail.FLAG,
        params=tuple((f"{side}_{index:04d}", item) for index, item in enumerate(items)),
    )


def _fires(rule: QualityRuleIR, value: str | None) -> bool | None:
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(
            f"SELECT ({_PORT.render(violation(rule))}) FROM (SELECT ? AS name)", [value]
        ).fetchone()
    assert result is not None
    return result[0]


# ....................... #
# charset: the allow reading


@pytest.mark.parametrize(
    ("value", "fires"),
    [
        (CLEAN_NAME, False),
        # One character outside printable ASCII is enough — and it is the one
        # nobody sees.
        (ZWSP_NAME, True),
        # The homoglyph case an allow-list answers and no denylist enumerates:
        # Cyrillic А, с and е drawn as Latin ones.
        ("\u0410\u0441m\u0435 Corp", True),
        (NFC_CAFE, True),
    ],
)
def test_allow_fires_on_any_character_outside_the_set(value: str, *, fires: bool) -> None:
    """``allow`` is the reading that catches what a set was never written to
    anticipate: it does not enumerate the bad characters, it enumerates the
    good ones."""
    rule = _charset_rule("allow", ("U+0020-U+007E",))
    assert _fires(rule, value) is fires


def test_allow_stays_unknown_on_a_null_value() -> None:
    """D19: ``TRANSLATE(NULL, …)`` is NULL and ``LENGTH(NULL)`` is NULL, so the
    comparison is ``UNKNOWN`` — ``not_null`` owns nulls, not this."""
    assert _fires(_charset_rule("allow", ("U+0020-U+007E",)), None) is None


def test_forbid_stays_unknown_on_a_null_value() -> None:
    assert _fires(_charset_rule("forbid", ("U+200B",)), None) is None


def test_the_two_readings_are_opposites_over_the_same_set() -> None:
    """The construction is one ``TRANSLATE`` either way, so the readings must
    not merely both work — they must disagree, on the same value, in the same
    direction."""
    ascii_set = ("U+0041-U+005A", "U+0061-U+007A")
    assert _fires(_charset_rule("allow", ascii_set), CLEAN_NAME) is False
    assert _fires(_charset_rule("forbid", ascii_set), CLEAN_NAME) is True


# ....................... #
# The declarations both rules refuse


def test_a_charset_rule_declaring_neither_side_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError, match="exactly one of allow"):
        CharsetRule(rule="charset", on_fail="flag")


def test_a_charset_rule_declaring_both_sides_is_refused() -> None:
    """Not a merge and not a precedence: a set read both ways states one policy
    twice, with nothing making the halves agree."""
    with pytest.raises(pydantic.ValidationError, match="exactly one of allow"):
        CharsetRule(rule="charset", on_fail="flag", allow=("U+0041",), forbid=("U+200B",))


@pytest.mark.parametrize(
    "item",
    [
        "u+200b",  # lowercase — one character, two spellings, two IR bytes
        "U+20",  # too short to be a codepoint
        "\u200b",  # the character itself, which is the whole thing being avoided
        "U+200B-",  # a range with no end
        "0x200B",  # a different notation
    ],
)
def test_a_codepoint_spelled_any_other_way_is_refused_at_parse(item: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        CharsetRule(rule="charset", on_fail="flag", forbid=(item,))


def test_a_normal_form_outside_the_portable_one_is_refused_at_parse() -> None:
    """Postgres and Trino spell all four forms; DuckDB has ``nfc_normalize``
    and nothing else, so admitting ``nfkc`` would mean a rule that compiles
    everywhere and runs on two engines out of three."""
    with pytest.raises(pydantic.ValidationError):
        NormalizeRule(rule="normalize", on_fail="flag", form="nfkc")


def test_a_backwards_range_is_refused() -> None:
    with pytest.raises(GuardrailError, match="runs backwards"):
        expand_codepoints(("U+007E-U+0020",), where="rule 'name_charset'")


def test_a_surrogate_named_on_its_own_is_refused() -> None:
    """No UTF-8 value can contain one, so a set naming it can never match. The
    corpus's specimen is the six-character *escape sequence*, which is made of
    ordinary characters."""
    with pytest.raises(GuardrailError, match="surrogate block"):
        expand_codepoints(("U+D800",), where="rule 'name_charset'")


def test_a_range_crossing_the_surrogate_block_is_refused_for_being_surrogates() -> None:
    """Not for being large. The block is 2048 codepoints wide, so such a range
    also exceeds ``MAX_CHARSET_SIZE`` — and a refusal that happened to arrive
    from a size constant would silently become an acceptance the day that
    constant grew."""
    with pytest.raises(GuardrailError, match="surrogate block"):
        expand_codepoints(("U+D7FF-U+E000",), where="rule 'name_charset'")


def test_a_codepoint_past_the_last_one_is_refused() -> None:
    with pytest.raises(GuardrailError, match="U\\+10FFFF"):
        expand_codepoints(("U+110000",), where="rule 'name_charset'")


def test_an_oversized_range_is_refused_before_it_reaches_a_literal() -> None:
    """The set becomes a string literal in every row's predicate and in the IR
    fingerprint, and ``U+0100-U+1FFF`` is a perfectly ordinary thing to write.

    Deliberately a range that stays below the surrogate block: ``U+0000-U+10FFFF``
    would be refused for crossing it, and would prove nothing about the cap.
    """
    with pytest.raises(GuardrailError, match="past the"):
        expand_codepoints(("U+0100-U+1FFF",), where="rule 'name_charset'")


def test_many_small_items_are_capped_the_same_way() -> None:
    """The per-item check cannot see the total, so the set is measured after
    expansion too — otherwise two half-sized ranges would slip past."""
    halves = ("U+0100-U+04FF", "U+0500-U+08FF")
    # Each half is exactly at the cap, so neither trips the per-item check…
    for half in halves:
        assert len(expand_codepoints((half,), where="rule 'name_charset'")) == MAX_CHARSET_SIZE
    # …and together they are twice it.
    with pytest.raises(GuardrailError, match="past the"):
        expand_codepoints(halves, where="rule 'name_charset'")


def test_the_expansion_is_sorted_and_deduplicated() -> None:
    """Two spellings of one set must produce identical bytes, or the same
    policy written two ways would move every fingerprint."""
    assert expand_codepoints(("U+0041-U+0042",), where="r") == expand_codepoints(
        ("U+0042", "U+0041", "U+0041"), where="r"
    )


# ....................... #
# The two per-dialect facts


def test_duckdb_renders_the_only_normalization_it_has() -> None:
    """DuckDB has ``nfc_normalize`` and no ``NORMALIZE``, and SQLGlot's duckdb
    generator renders :class:`sqlglot.exp.Normalize` verbatim rather than
    refusing it — so the untouched AST emits a call the engine has never heard
    of. Asserted at the port, because that is the seam the rewrite lives in."""
    rendered = _PORT.render(violation(rule_of_kind("normalize")))
    assert "NFC_NORMALIZE" in rendered
    assert "NORMALIZE(" not in rendered.replace("NFC_NORMALIZE(", "")


def test_the_neutral_node_is_what_postgres_and_trino_want() -> None:
    """The other half of the same statement: those two spell it exactly as the
    dialect-neutral node renders, so only DuckDB needs the rewrite."""
    for name in ("postgres", "trino"):
        rendered = get_dialect(name).render(violation(rule_of_kind("normalize")))
        assert "NORMALIZE(name, NFC)" in rendered.replace("amount", "name")


def test_the_rewrite_does_not_mutate_the_shared_ast() -> None:
    """The port contract shares one AST across dialects, so a rewrite that
    mutated in place would leave DuckDB's spelling in Postgres' output."""
    node = violation(rule_of_kind("normalize"))
    _PORT.render(node)
    assert node.find(exp.Normalize) is not None


def test_charset_renders_identically_on_every_shipped_dialect() -> None:
    """``TRANSLATE`` is spelled the same everywhere — which is why the rule
    carries no ``DialectFeature`` of its own — and the members survive the
    round trip, invisible characters included."""
    rendered = {
        name: get_dialect(name).render(violation(rule_of_kind("charset")))
        for name in ("duckdb", "postgres", "trino")
    }
    assert len(set(rendered.values())) == 1
    for name, sql in rendered.items():
        literal = parse_one(f"SELECT {sql}", read=name).find(exp.Literal)
        assert literal is not None
        assert literal.this == "\u200b", name


class NoNormalizeDialect(SQLGlotDialect):
    """DuckDB in every respect but the one under test."""

    name: str = "nonormalize"
    sqlglot_dialect: str = "duckdb"
    features = frozenset(DialectFeature) - {DialectFeature.UNICODE_NORMALIZE}


def test_a_dialect_without_normalization_refuses_the_rule_rather_than_emitting_it() -> None:
    """RFC 0008 D3: fail loud, never approximate. There is no weaker reading of
    ``normalize`` to fall back to — the comparison against a normal form is the
    entire rule — and SQLGlot emits ``NORMALIZE(...)`` for any generator, so an
    unrefused rule would render cleanly and fail at run time on a function the
    engine does not define."""
    register_dialect(NoNormalizeDialect())
    with pytest.raises(UnsupportedByTarget, match="dirty_name.*no normalization function"):
        compile_fixture("dirty_corpus", dialect="nonormalize")


def test_every_shipped_dialect_declares_the_normalization_capability() -> None:
    """Declared *and* true: D83's finding was a dialect that announced two
    features and had neither, so the flag is checked against a port that
    actually renders something the engine defines."""
    for name in ("duckdb", "postgres", "trino"):
        assert get_dialect(name).supports(DialectFeature.UNICODE_NORMALIZE)
