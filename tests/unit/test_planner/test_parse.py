"""The JSON front door (RFC 0015 §5.2–§5.3): grammar happy paths, the
negation-complement table, every bloomery-owned refusal with its stable
``.reason`` (and ``.normalized`` where the refusal happens after
normalization), and the ``KNOWN_UNSUPPORTED`` drift guard — the export
equals the union of codes the three parse functions actually raise."""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pytest

import bloomery.planner.parse as parse_module
from bloomery.errors import (
    FilterTooComplex,
    InvalidLiteral,
    InvalidRequest,
    UnsupportedFilter,
    UnsupportedHierarchy,
    UnsupportedNegation,
    UnsupportedPagination,
    UnsupportedSetRelation,
    UnsupportedSortNulls,
    UnsupportedTextOperator,
)
from bloomery.planner import (
    KNOWN_UNSUPPORTED,
    AnyOf,
    Op,
    OrderSpec,
    Predicate,
    parse_filter_json,
    parse_page_json,
    parse_sort_json,
)
from bloomery.planner.parse import MAX_NESTING_DEPTH

pytestmark = pytest.mark.unit


# ....................... #
# Grammar happy paths (RFC 0015 D10)


def test_scalar_is_the_eq_shortcut() -> None:
    assert parse_filter_json({"region": "EU"}) == (Predicate("region", Op.EQ, ("EU",)),)


def test_array_is_the_in_shortcut() -> None:
    assert parse_filter_json({"carrier": ["DHL", "UPS"]}) == (
        Predicate("carrier", Op.IN, ("DHL", "UPS")),
    )


def test_null_is_is_null_true() -> None:
    assert parse_filter_json({"region": None}) == (Predicate("region", Op.IS_NULL, (True,)),)


def test_operator_map_spellings() -> None:
    clauses = parse_filter_json(
        {
            "a": {"$eq": 1},
            "b": {"$neq": 2},
            "c": {"$gt": 3},
            "d": {"$gte": 4},
            "e": {"$lt": 5},
            "f": {"$lte": 6},
            "g": {"$in": [7, 8]},
            "h": {"$nin": [9]},
            "i": {"$null": False},
            "j": {"$like": "%x%"},
            "k": {"$ilike": ["%y%", "%z%"]},
        }
    )
    assert clauses == (
        Predicate("a", Op.EQ, (1,)),
        Predicate("b", Op.NE, (2,)),
        Predicate("c", Op.GT, (3,)),
        Predicate("d", Op.GTE, (4,)),
        Predicate("e", Op.LT, (5,)),
        Predicate("f", Op.LTE, (6,)),
        Predicate("g", Op.IN, (7, 8)),
        Predicate("h", Op.NOT_IN, (9,)),
        Predicate("i", Op.IS_NULL, (False,)),
        Predicate("j", Op.LIKE, ("%x%",)),
        Predicate("k", Op.ILIKE, ("%y%", "%z%")),
    )


def test_multi_operator_map_is_implicit_and() -> None:
    assert parse_filter_json({"amount": {"$gte": 10, "$lte": 20}}) == (
        Predicate("amount", Op.GTE, (10,)),
        Predicate("amount", Op.LTE, (20,)),
    )


def test_and_combinator_flattens_to_clauses() -> None:
    clauses = parse_filter_json({"$and": [{"a": 1}, {"b": 2}]})
    assert clauses == (Predicate("a", Op.EQ, (1,)), Predicate("b", Op.EQ, (2,)))


def test_or_combinator_becomes_one_any_of() -> None:
    clauses = parse_filter_json({"$or": [{"region": "EU"}, {"region": "UK"}]})
    assert clauses == (
        AnyOf((Predicate("region", Op.EQ, ("EU",)), Predicate("region", Op.EQ, ("UK",)))),
    )


def test_mixed_dimension_any_of_is_legal() -> None:
    # RFC 0015 decision 14: AnyOf groups may span different dimensions.
    (clause,) = parse_filter_json({"$or": [{"region": "EU"}, {"carrier": "DHL"}]})
    assert isinstance(clause, AnyOf)
    assert {p.dimension for p in clause.predicates} == {"carrier", "region"}


def test_combinators_and_field_maps_mix_with_implicit_and() -> None:
    clauses = parse_filter_json(
        {"carrier": {"$in": ["DHL", "UPS"]}, "$or": [{"region": "EU"}, {"region": "UK"}]}
    )
    assert clauses == (
        Predicate("carrier", Op.IN, ("DHL", "UPS")),
        AnyOf((Predicate("region", Op.EQ, ("EU",)), Predicate("region", Op.EQ, ("UK",)))),
    )


def test_json_floats_normalize_through_the_boundary() -> None:
    from decimal import Decimal

    (clause,) = parse_filter_json({"amount": {"$gt": 0.5}})
    assert isinstance(clause, Predicate)
    assert clause.values == (Decimal("0.5"),)


def test_eq_null_and_neq_null_map_to_is_null() -> None:
    assert parse_filter_json({"a": {"$eq": None}}) == (Predicate("a", Op.IS_NULL, (True,)),)
    assert parse_filter_json({"a": {"$neq": None}}) == (Predicate("a", Op.IS_NULL, (False,)),)


# ....................... #
# The negation-complement table (RFC 0015 §5.2 step 2)


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"$not": {"a": {"$eq": 1}}}, Predicate("a", Op.NE, (1,))),
        ({"$not": {"a": {"$neq": 1}}}, Predicate("a", Op.EQ, (1,))),
        ({"$not": {"a": {"$gt": 1}}}, Predicate("a", Op.LTE, (1,))),
        ({"$not": {"a": {"$gte": 1}}}, Predicate("a", Op.LT, (1,))),
        ({"$not": {"a": {"$lt": 1}}}, Predicate("a", Op.GTE, (1,))),
        ({"$not": {"a": {"$lte": 1}}}, Predicate("a", Op.GT, (1,))),
        ({"$not": {"a": {"$in": [1, 2]}}}, Predicate("a", Op.NOT_IN, (1, 2))),
        ({"$not": {"a": {"$nin": [1]}}}, Predicate("a", Op.IN, (1,))),
        ({"$not": {"a": {"$null": True}}}, Predicate("a", Op.IS_NULL, (False,))),
        ({"$not": {"a": {"$null": False}}}, Predicate("a", Op.IS_NULL, (True,))),
    ],
)
def test_negation_complement_table(document: dict[str, Any], expected: Predicate) -> None:
    assert parse_filter_json(document) == (expected,)


def test_double_negation_cancels() -> None:
    assert parse_filter_json({"$not": {"$not": {"a": 1}}}) == (Predicate("a", Op.EQ, (1,)),)


def test_de_morgan_pushes_not_over_and() -> None:
    # not(a=1 AND b=2) → (a≠1 OR b≠2) — one AnyOf clause.
    assert parse_filter_json({"$not": {"$and": [{"a": 1}, {"b": 2}]}}) == (
        AnyOf((Predicate("a", Op.NE, (1,)), Predicate("b", Op.NE, (2,)))),
    )


def test_de_morgan_pushes_not_over_or() -> None:
    # not(a=1 OR b=2) → a≠1 AND b≠2 — two clauses.
    assert parse_filter_json({"$not": {"$or": [{"a": 1}, {"b": 2}]}}) == (
        Predicate("a", Op.NE, (1,)),
        Predicate("b", Op.NE, (2,)),
    )


def test_cnf_distributes_or_over_and() -> None:
    # (a=1 AND b=2) OR c=3 → (a=1 OR c=3) AND (b=2 OR c=3).
    assert parse_filter_json({"$or": [{"$and": [{"a": 1}, {"b": 2}]}, {"c": 3}]}) == (
        AnyOf((Predicate("a", Op.EQ, (1,)), Predicate("c", Op.EQ, (3,)))),
        AnyOf((Predicate("b", Op.EQ, (2,)), Predicate("c", Op.EQ, (3,)))),
    )


# ....................... #
# The closed refusal list (RFC 0015 §5.3) — right type, .reason, .normalized


@pytest.mark.parametrize(
    ("spelling", "error_type", "reason"),
    [
        ("$superset", UnsupportedSetRelation, "unsupported_set_relation"),
        ("$subset", UnsupportedSetRelation, "unsupported_set_relation"),
        ("$disjoint", UnsupportedSetRelation, "unsupported_set_relation"),
        ("$overlaps", UnsupportedSetRelation, "unsupported_set_relation"),
        ("$descendant_of", UnsupportedHierarchy, "unsupported_hierarchy"),
        ("$ancestor_of", UnsupportedHierarchy, "unsupported_hierarchy"),
        ("$regex", UnsupportedTextOperator, "unsupported_text_operator"),
        ("$empty", UnsupportedTextOperator, "unsupported_text_operator"),
    ],
)
def test_refused_upstream_operators(
    spelling: str, error_type: type[UnsupportedFilter], reason: str
) -> None:
    with pytest.raises(error_type) as excinfo:
        parse_filter_json({"field": {spelling: ["x"]}})
    assert excinfo.value.reason == reason
    assert excinfo.value.source_path == "field"
    assert spelling in str(excinfo.value)


def test_non_invertible_negation_refuses_with_the_normalized_form() -> None:
    with pytest.raises(UnsupportedNegation) as excinfo:
        parse_filter_json({"$not": {"name": {"$like": "%x%"}}})
    assert excinfo.value.reason == "unsupported_negation"
    assert excinfo.value.normalized is not None
    assert "not name like" in excinfo.value.normalized
    assert excinfo.value.normalized in str(excinfo.value)


def test_deep_negated_ilike_refuses_after_de_morgan() -> None:
    # The negation reaches the leaf only after De Morgan pushes it down.
    with pytest.raises(UnsupportedNegation):
        parse_filter_json({"$not": {"$and": [{"a": 1}, {"b": {"$ilike": "%x%"}}]}})


def test_clause_cap_short_circuits_during_distribution() -> None:
    # 2^7 = 128 > 64 clauses; the refusal happens mid-distribution.
    document = {"$or": [{"$and": [{f"a{i}": 1}, {f"b{i}": 2}]} for i in range(7)]}
    with pytest.raises(FilterTooComplex) as excinfo:
        parse_filter_json(document)
    assert excinfo.value.reason == "filter_too_complex"
    assert excinfo.value.normalized == ">64 clauses"


def test_clause_cap_is_configurable() -> None:
    document = {"$or": [{"$and": [{"a": 1}, {"b": 2}]}, {"c": 3}]}  # 2 clauses
    assert len(parse_filter_json(document, clause_cap=2)) == 2
    with pytest.raises(FilterTooComplex):
        parse_filter_json(document, clause_cap=1)


def test_clause_cap_zero_refuses_even_a_single_leaf() -> None:
    # The cap binds on the leaf path too: cap 0 admits nothing.
    assert len(parse_filter_json({"a": 1}, clause_cap=1)) == 1
    with pytest.raises(FilterTooComplex) as excinfo:
        parse_filter_json({"a": 1}, clause_cap=0)
    assert excinfo.value.reason == "filter_too_complex"


def test_nesting_depth_cap_boundary_is_exact() -> None:
    """Depth MAX_NESTING_DEPTH parses; one level deeper refuses with the
    FilterTooComplex depth-cap refusal, named distinctly from the clause
    cap."""
    document: dict[str, Any] = {"a": 1}
    for _ in range(MAX_NESTING_DEPTH):
        document = {"$and": [document]}
    assert parse_filter_json(document) == (Predicate("a", Op.EQ, (1,)),)
    with pytest.raises(FilterTooComplex) as excinfo:
        parse_filter_json({"$not": document})
    assert excinfo.value.reason == "filter_too_complex"
    assert "depth cap" in str(excinfo.value)
    assert excinfo.value.normalized == f">{MAX_NESTING_DEPTH} levels deep"


def test_non_finite_json_number_is_invalid_literal() -> None:
    with pytest.raises(InvalidLiteral) as excinfo:
        parse_filter_json({"amount": {"$lt": float("nan")}})
    assert excinfo.value.reason == "invalid_literal"


def test_invalid_like_pattern_is_invalid_literal() -> None:
    with pytest.raises(InvalidLiteral, match="unpaired escape"):
        parse_filter_json({"name": {"$like": "broken\\"}})


def test_no_nesting_refusal_exists() -> None:
    """RFC 0015 decision 14: after normalization every boolean tree reaches
    AND-of-AnyOf — no dedicated nesting refusal type exists. Depth beyond
    MAX_NESTING_DEPTH refuses as the FilterTooComplex *complexity* refusal
    (parser totality), not a vocabulary gap."""
    document: dict[str, Any] = {"leaf": 1}
    for index in range(12):
        document = {"$and": [{"$or": [document, {f"d{index}": index}]}]}
    clauses = parse_filter_json(document)
    assert clauses  # representable — and nothing named "nesting" can raise
    assert not hasattr(parse_module, "UnsupportedNesting")


# ....................... #
# Grammar errors outside the closed list stay InvalidRequest


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"$and": []},
        {"$or": "not-a-list"},
        {"$and": [5]},  # a combinator child must itself be a document
        {"$xor": [{"a": 1}]},
        {"a": {}},
        {"a": {"$boom": 1}},
        {"a": {"$in": "not-a-list"}},
        {"a": {"$in": [1, None]}},
        {"a": {"$null": "yes"}},
        {"a": {"$gt": None}},
        {"a": {"$gt": {"nested": 1}}},  # non-scalar operand
        {"a": {1: 2}},  # operator keys are strings
        {1: "x"},  # filter keys are strings
        "not-a-mapping",
    ],
)
def test_malformed_documents_are_invalid_requests(document: object) -> None:
    with pytest.raises(InvalidRequest) as excinfo:
        parse_filter_json(document)  # type: ignore[arg-type]
    assert not isinstance(excinfo.value, UnsupportedFilter)  # not a reviewed refusal


# ....................... #
# parse_sort_json (RFC 0015 D-Q6)


def test_sort_directions_parse_in_document_order() -> None:
    assert parse_sort_json({"revenue": "desc", "store": "asc"}) == (
        OrderSpec("revenue", "desc"),
        OrderSpec("store", "asc"),
    )


def test_sort_spec_form_with_default_nulls_is_dropped() -> None:
    assert parse_sort_json(
        {"revenue": {"dir": "desc", "nulls": "last"}, "store": {"dir": "asc", "nulls": "first"}}
    ) == (OrderSpec("revenue", "desc"), OrderSpec("store", "asc"))


@pytest.mark.parametrize(
    "spec", [{"dir": "asc", "nulls": "last"}, {"dir": "desc", "nulls": "first"}]
)
def test_non_default_nulls_placement_is_refused(spec: dict[str, str]) -> None:
    with pytest.raises(UnsupportedSortNulls) as excinfo:
        parse_sort_json({"revenue": spec})
    assert excinfo.value.reason == "unsupported_sort_nulls"


@pytest.mark.parametrize("spec", ["ascending", {"dir": "up"}, {"order": "asc"}, 1])
def test_malformed_sort_is_invalid_request(spec: object) -> None:
    with pytest.raises(InvalidRequest):
        parse_sort_json({"revenue": spec})


@pytest.mark.parametrize("payload", [["revenue"], "revenue", 1])
def test_non_mapping_sort_payload_is_invalid_request(payload: object) -> None:
    with pytest.raises(InvalidRequest, match="a sort document is a mapping") as excinfo:
        parse_sort_json(payload)  # type: ignore[arg-type]
    assert not isinstance(excinfo.value, UnsupportedFilter)


def test_non_string_sort_keys_are_invalid_request() -> None:
    with pytest.raises(InvalidRequest, match="sort keys are strings"):
        parse_sort_json({1: "asc"})  # type: ignore[dict-item]


# ....................... #
# parse_page_json (RFC 0015 D-Q7)


def test_limit_only_pagination_parses() -> None:
    assert parse_page_json({"limit": 100}) == 100
    assert parse_page_json({"limit": 100, "offset": 0}) == 100
    assert parse_page_json({"limit": None}) is None
    assert parse_page_json({}) is None


def test_non_zero_offset_is_refused() -> None:
    with pytest.raises(UnsupportedPagination) as excinfo:
        parse_page_json({"limit": 100, "offset": 100})
    assert excinfo.value.reason == "unsupported_pagination"


@pytest.mark.parametrize("payload", [{"after": "tok"}, {"before": "tok"}])
def test_cursor_pagination_is_refused(payload: dict[str, str]) -> None:
    with pytest.raises(UnsupportedPagination) as excinfo:
        parse_page_json(payload)
    assert excinfo.value.reason == "unsupported_pagination"


@pytest.mark.parametrize("payload", [{"limit": 0}, {"limit": "ten"}, {"limit": True}, {"pp": 1}])
def test_malformed_pagination_is_invalid_request(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidRequest):
        parse_page_json(payload)


@pytest.mark.parametrize("payload", [[{"limit": 1}], "after", 1])
def test_non_mapping_pagination_payload_is_invalid_request(payload: object) -> None:
    # "after" as a *string payload* must be malformed input, never the
    # cursor refusal — only well-formed mappings reach the reviewed refusals.
    with pytest.raises(InvalidRequest, match="a pagination document is a mapping") as excinfo:
        parse_page_json(payload)  # type: ignore[arg-type]
    assert not isinstance(excinfo.value, UnsupportedFilter)


@pytest.mark.parametrize("offset", [True, False, "5"])
def test_non_int_offset_is_invalid_request_not_a_refusal(offset: object) -> None:
    # bool is excluded exactly as limit does it: True/False are malformed,
    # not offset-pagination requests (and False is not a zero offset).
    with pytest.raises(InvalidRequest, match="offset must be an int") as excinfo:
        parse_page_json({"offset": offset})
    assert not isinstance(excinfo.value, UnsupportedFilter)


# ....................... #
# The drift guard (RFC 0015 D9): export == the actually-raisable union


#: One adversarial document per raisable code, per function — parsing each
#: collects the reason codes the three functions *actually* raise.
_FILTER_CORPUS: list[dict[str, Any]] = [
    {"a": {"$superset": [1]}},
    {"a": {"$descendant_of": "x"}},
    {"a": {"$regex": "x+"}},
    {"a": {"$empty": True}},
    {"$or": [{"$and": [{f"a{i}": 1}, {f"b{i}": 2}]} for i in range(7)]},
    {"$not": {"a": {"$like": "%x%"}}},
    {"a": {"$gt": float("inf")}},
    {"a": {"$like": "broken\\"}},
]

_SORT_CORPUS: list[dict[str, Any]] = [{"f": {"dir": "asc", "nulls": "last"}}]

_PAGE_CORPUS: list[dict[str, Any]] = [{"offset": 5}, {"after": "tok"}]


def _raised_reasons() -> set[str]:
    reasons: set[str] = set()
    for document in _FILTER_CORPUS:
        with pytest.raises(UnsupportedFilter) as excinfo:
            parse_filter_json(document)
        reasons.add(excinfo.value.reason)
    for sort_doc in _SORT_CORPUS:
        with pytest.raises(UnsupportedFilter) as excinfo:
            parse_sort_json(sort_doc)
        reasons.add(excinfo.value.reason)
    for page_doc in _PAGE_CORPUS:
        with pytest.raises(UnsupportedFilter) as excinfo:
            parse_page_json(page_doc)
        reasons.add(excinfo.value.reason)
    return reasons


def test_known_unsupported_equals_the_raisable_union() -> None:
    """The corpus half of the drift guard: every exported code is provoked
    from one of the three functions, and nothing outside the export is."""
    assert _raised_reasons() == KNOWN_UNSUPPORTED


def test_known_unsupported_matches_the_raise_sites_in_source() -> None:
    """The introspection half (RFC 0015 D9): every UnsupportedFilter leaf
    *referenced* in the source of the parse path — ``parse.py`` plus the
    ``Predicate`` construction it delegates pattern/scalar validation to —
    maps to exactly the exported codes. Import aliases are not ``ast.Name``
    nodes, so only actual use sites (raises, constructor returns, the
    refusal table) count; a new raisable leaf without an export (or an
    export nothing can raise) fails here."""
    import bloomery.errors as errors_module
    import bloomery.planner.request as request_module

    leaves_by_name = {
        name: leaf
        for name, leaf in vars(errors_module).items()
        if isinstance(leaf, type)
        and issubclass(leaf, UnsupportedFilter)
        and leaf is not UnsupportedFilter
    }
    referenced: set[str] = set()
    for module in (parse_module, request_module):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in leaves_by_name:
                referenced.add(leaves_by_name[node.id].reason)
    assert referenced == KNOWN_UNSUPPORTED


def test_adapter_codes_are_not_in_the_export() -> None:
    # RFC 0015 D9: the two reason-code sets are disjoint.
    assert "unsupported_field_compare" not in KNOWN_UNSUPPORTED
    assert "unsupported_quantifier" not in KNOWN_UNSUPPORTED
