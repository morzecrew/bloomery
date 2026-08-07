"""Parse properties (RFC 0015 §6): CNF normalization terminates and
respects the clause cap on adversarial nesting, and the parser is *total* —
any generated document either parses into clauses that are **semantically
equivalent** to the original (checked by evaluating both forms against
generated rows under SQL three-valued logic — structural comparison after
normalization would be circular) or refuses with a reason from
``KNOWN_UNSUPPORTED``. No nesting refusal type exists: arbitrarily deep
input either reaches AND-of-``AnyOf`` or refuses with the
``FilterTooComplex`` complexity refusal (the clause cap during
distribution, or the nesting-depth cap before normalization — never a
``RecursionError``) / ``UnsupportedNegation``."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from bloomery.errors import FilterTooComplex, UnsupportedFilter
from bloomery.planner import KNOWN_UNSUPPORTED, AnyOf, Op, Predicate, parse_filter_json
from bloomery.planner.request import Clause

pytestmark = pytest.mark.property

# ....................... #
# The grammar strategy: typed fields so evaluation is well-defined

_STR_VALUES = ["", "a", "abc", "DHL", "eu-west", "O'Neil", "100%"]
_INT_VALUES = [-3, 0, 1, 7, 100]

_pattern_tokens = st.sampled_from(["%", "_", "a", "b", "\\%", "\\_", "\\\\", "C", "'"])
_patterns = st.lists(_pattern_tokens, min_size=1, max_size=5).map("".join)

_str_leaf = st.one_of(
    st.builds(lambda v: {"s": v}, st.sampled_from(_STR_VALUES)),
    st.builds(lambda v: {"s": {"$eq": v}}, st.sampled_from(_STR_VALUES)),
    st.builds(lambda v: {"s": {"$neq": v}}, st.sampled_from(_STR_VALUES)),
    st.builds(
        lambda v: {"s": {"$in": v}},
        st.lists(st.sampled_from(_STR_VALUES), min_size=1, max_size=3),
    ),
    st.builds(
        lambda v: {"s": {"$nin": v}},
        st.lists(st.sampled_from(_STR_VALUES), min_size=1, max_size=3),
    ),
    st.builds(lambda v: {"s": {"$null": v}}, st.booleans()),
    st.builds(lambda p: {"s": {"$like": p}}, _patterns),
    st.builds(lambda p: {"s": {"$ilike": p}}, _patterns),
    st.builds(
        lambda ps: {"s": {"$like": ps}}, st.lists(_patterns, min_size=1, max_size=3)
    ),
)

_int_leaf = st.one_of(
    st.builds(lambda v: {"n": v}, st.sampled_from(_INT_VALUES)),
    *[
        st.builds(lambda v, op=op: {"n": {op: v}}, st.sampled_from(_INT_VALUES))
        for op in ("$eq", "$neq", "$gt", "$gte", "$lt", "$lte")
    ],
    st.builds(
        lambda v: {"n": {"$in": v}},
        st.lists(st.sampled_from(_INT_VALUES), min_size=1, max_size=3),
    ),
    st.builds(lambda v: {"n": {"$null": v}}, st.booleans()),
)

_bool_leaf = st.one_of(
    st.builds(lambda v: {"b": v}, st.booleans()),
    st.builds(lambda v: {"b": {"$null": v}}, st.booleans()),
)

_leaves = st.one_of(_str_leaf, _int_leaf, _bool_leaf)


def _combine(children: list[dict[str, Any]]) -> st.SearchStrategy[dict[str, Any]]:
    return st.sampled_from(
        [{"$and": children}, {"$or": children}, {"$not": children[0]}]
    )


_documents = st.recursive(
    _leaves,
    lambda inner: st.lists(inner, min_size=1, max_size=3).flatmap(_combine),
    max_leaves=12,
)


def _or_of_ands(width: int) -> dict[str, Any]:
    """An OR of ``width`` two-leaf ANDs — CNF distribution multiplies to
    ``2**width`` clauses, so widths above 6 exceed the 64-clause cap."""
    return {"$or": [{"$and": [{f"a{i}": 1}, {f"b{i}": 2}]} for i in range(width)]}


#: The generic corpus (max_leaves=12) almost never exceeds 64 clauses, which
#: left the refusal branch of the cap property dead — so the cap property
#: draws from this mix: generic documents plus distribution-explosive
#: OR-of-ANDs (widths 5–9 straddle the cap: 32 and 64 parse, 128+ refuse).
_adversarial_documents = st.one_of(
    _documents, st.integers(min_value=5, max_value=9).map(_or_of_ands)
)

_rows = st.fixed_dictionaries(
    {
        "s": st.one_of(st.none(), st.sampled_from(_STR_VALUES)),
        "n": st.one_of(st.none(), st.sampled_from(_INT_VALUES)),
        "b": st.one_of(st.none(), st.booleans()),
    }
)


# ....................... #
# The reference evaluator — SQL three-valued logic on both forms

type _Truth = bool | None  # Kleene: True / False / unknown


def _like_regex(pattern: str) -> re.Pattern[str]:
    """The RFC 0015 pattern language as a regex: ``%``/``_`` wildcards,
    ``\\`` escapes the next character, full-string match."""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            parts.append(re.escape(pattern[index + 1]))
            index += 2
        elif char == "%":
            parts.append("(?s:.*)")
            index += 1
        elif char == "_":
            parts.append("(?s:.)")
            index += 1
        else:
            parts.append(re.escape(char))
            index += 1
    return re.compile("".join(parts) + r"\Z")


def _eval_leaf(op: Op, value: object, operands: tuple[object, ...]) -> _Truth:
    """One predicate under SQL semantics: NULL operands make comparisons
    unknown; ``is_null`` is total."""
    if op is Op.IS_NULL:
        return (value is None) == operands[0]
    if value is None:
        return None
    if op is Op.EQ:
        return value == operands[0]
    if op is Op.NE:
        return value != operands[0]
    if op in (Op.GT, Op.GTE, Op.LT, Op.LTE):
        left, right = value, operands[0]
        assert not isinstance(left, str)
        assert not isinstance(right, str)
        if op is Op.GT:
            return left > right  # type: ignore[operator]
        if op is Op.GTE:
            return left >= right  # type: ignore[operator]
        if op is Op.LT:
            return left < right  # type: ignore[operator]
        return left <= right  # type: ignore[operator]
    if op is Op.IN:
        return value in operands
    if op is Op.NOT_IN:
        return value not in operands
    assert isinstance(value, str)
    if op is Op.LIKE:
        return any(_like_regex(str(p)).match(value) is not None for p in operands)
    assert op is Op.ILIKE
    return any(
        _like_regex(str(p).lower()).match(value.lower()) is not None for p in operands
    )


def _not(truth: _Truth) -> _Truth:
    return None if truth is None else not truth


def _all(truths: list[_Truth]) -> _Truth:
    if any(t is False for t in truths):
        return False
    if any(t is None for t in truths):
        return None
    return True


def _any(truths: list[_Truth]) -> _Truth:
    if any(t is True for t in truths):
        return True
    if any(t is None for t in truths):
        return None
    return False


_DOC_OPS = {
    "$eq": Op.EQ,
    "$neq": Op.NE,
    "$gt": Op.GT,
    "$gte": Op.GTE,
    "$lt": Op.LT,
    "$lte": Op.LTE,
    "$in": Op.IN,
    "$nin": Op.NOT_IN,
    "$null": Op.IS_NULL,
    "$like": Op.LIKE,
    "$ilike": Op.ILIKE,
}


def _eval_doc(document: dict[str, Any], row: dict[str, Any]) -> _Truth:
    """The original document, evaluated directly — the oracle the parsed
    clauses must agree with."""
    truths: list[_Truth] = []
    for key, spec in document.items():
        if key == "$and":
            truths.append(_all([_eval_doc(child, row) for child in spec]))
        elif key == "$or":
            truths.append(_any([_eval_doc(child, row) for child in spec]))
        elif key == "$not":
            truths.append(_not(_eval_doc(spec, row)))
        elif spec is None:
            truths.append(_eval_leaf(Op.IS_NULL, row[key], (True,)))
        elif isinstance(spec, list):
            truths.append(_eval_leaf(Op.IN, row[key], tuple(spec)))
        elif isinstance(spec, dict):
            for spelling, operand in spec.items():
                operands = tuple(operand) if isinstance(operand, list) else (operand,)
                truths.append(_eval_leaf(_DOC_OPS[spelling], row[key], operands))
        else:
            truths.append(_eval_leaf(Op.EQ, row[key], (spec,)))
    return _all(truths)


def _plain(value: object) -> object:
    """Clause values carry Decimal where JSON had numbers — compare in one
    domain (the generated corpus is int-only, so this is exact)."""
    return int(value) if isinstance(value, Decimal) else value


def _eval_predicate(predicate: Predicate, row: dict[str, Any]) -> _Truth:
    operands = tuple(_plain(v) for v in predicate.values)
    return _eval_leaf(predicate.op, row[predicate.dimension], operands)


def _eval_clauses(clauses: tuple[Clause, ...], row: dict[str, Any]) -> _Truth:
    truths: list[_Truth] = []
    for clause in clauses:
        if isinstance(clause, AnyOf):
            truths.append(_any([_eval_predicate(p, row) for p in clause.predicates]))
        else:
            truths.append(_eval_predicate(clause, row))
    return _all(truths)


# ....................... #
# The properties


@settings(max_examples=200, deadline=None)
@given(document=_documents, rows=st.lists(_rows, min_size=1, max_size=5))
def test_parse_is_total_and_semantically_equivalent(
    document: dict[str, Any], rows: list[dict[str, Any]]
) -> None:
    """RFC 0015 §6: any generated document parses or refuses with a
    KNOWN_UNSUPPORTED reason; on success, the clauses agree with the
    document on every generated row — under three-valued logic, so the
    complement table's NULL behavior is checked too."""
    try:
        clauses = parse_filter_json(document)
    except UnsupportedFilter as error:
        assert error.reason in KNOWN_UNSUPPORTED
        return
    for row in rows:
        assert _eval_clauses(clauses, row) == _eval_doc(document, row), (
            f"clauses {clauses} disagree with {document} on {row}"
        )


@settings(max_examples=200, deadline=None)
@given(document=_adversarial_documents)
def test_cnf_terminates_and_respects_the_cap(document: dict[str, Any]) -> None:
    """RFC 0015 §6: adversarial input either reaches AND-of-AnyOf within
    the cap or refuses with FilterTooComplex/UnsupportedNegation — never a
    nesting refusal, never a hang. The strategy mixes in explosive
    OR-of-ANDs so the refusal branch actually executes (hypothesis events
    record the split); the deterministic witnesses below pin both the cap
    and the depth refusals independently of generation luck."""
    try:
        clauses = parse_filter_json(document)
    except UnsupportedFilter as error:
        assert error.reason in {"filter_too_complex", "unsupported_negation"}
        event(f"refused: {error.reason}")
        return
    event("parsed")
    assert 0 < len(clauses) <= 64
    for clause in clauses:
        if isinstance(clause, AnyOf):
            assert all(isinstance(p, Predicate) for p in clause.predicates)


def test_the_cap_refusal_has_a_deterministic_witness() -> None:
    """The FilterTooComplex branch of the cap property, pinned: 2**7 = 128
    partial clauses exceed the 64 cap and refuse during distribution —
    deterministic, so a sabotaged cap constant fails here every run."""
    with pytest.raises(FilterTooComplex) as excinfo:
        parse_filter_json(_or_of_ands(7))
    assert excinfo.value.reason == "filter_too_complex"
    assert excinfo.value.normalized == ">64 clauses"


@pytest.mark.parametrize("combinator", ["$not", "$and"])
def test_depth_500_chains_refuse_typed_never_recursion_error(combinator: str) -> None:
    """The parser is total on depth: a 500-deep ``$not`` chain and a
    500-deep ``$and`` chain refuse with the typed FilterTooComplex
    depth-cap refusal — a ``RecursionError`` never escapes for any input
    depth."""
    document: dict[str, Any] = {"a": 1}
    for _ in range(500):
        document = {"$not": document} if combinator == "$not" else {"$and": [document]}
    with pytest.raises(FilterTooComplex) as excinfo:
        parse_filter_json(document)
    assert excinfo.value.reason == "filter_too_complex"
    assert "depth cap" in str(excinfo.value)  # named distinctly from the clause cap


@settings(max_examples=60, deadline=None)
@given(width=st.integers(min_value=1, max_value=9))
def test_the_cap_boundary_is_exact(width: int) -> None:
    """2^width clauses: within 64 parses, above 64 refuses — the cap counts
    clauses, enforced during distribution."""
    document = {
        "$or": [{"$and": [{f"a{i}": 1}, {f"b{i}": 2}]} for i in range(width)]
    }
    if 2**width <= 64:
        assert len(parse_filter_json(document)) == 2**width
    else:
        with pytest.raises(UnsupportedFilter) as excinfo:
            parse_filter_json(document)
        assert excinfo.value.reason == "filter_too_complex"
