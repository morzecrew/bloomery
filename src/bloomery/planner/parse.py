"""The JSON front door (RFC 0015 §5.2, D-Q4): a public, pure,
dependency-free parser from the Mongo-flavoured filter/sort/pagination
grammar into the typed request vocabulary of
:mod:`bloomery.planner.request`. The typed constructors remain the primary
path — this module is a convenience over the same types, not a second
representation.

**Normalize before refusing** (D-Q4): a large share of expressions that
*look* unsupported are supported after normalization —

1. negations push to leaves via De Morgan;
2. negated leaves invert through the complement table (``$not $eq`` →
   ``ne``, ``$not $gt`` → ``lte``, ``$not $null: true`` → ``is_null
   false``, …); a leaf with no complement (``like``/``ilike``) refuses with
   :class:`~bloomery.errors.UnsupportedNegation`;
3. the tree distributes to CNF with the clause cap (default 64) enforced
   **during** distribution — the moment the partial clause count exceeds
   the cap, distribution short-circuits with
   :class:`~bloomery.errors.FilterTooComplex`; the full expansion is never
   materialized (capping after materializing would make the parser itself
   the DoS vector the cap exists to remove);
4. each resulting predicate validates through the
   :class:`~bloomery.planner.request.Predicate` constructor.

The parser is total on *depth* too: input nesting beyond
:data:`MAX_NESTING_DEPTH` refuses with the same
:class:`~bloomery.errors.FilterTooComplex` complexity refusal **before**
recursing further — no input depth can raise ``RecursionError``.

Refusals come only from the closed §5.3 list: every reason code the three
parse functions can raise is in :data:`KNOWN_UNSUPPORTED`, drift-guarded by
test. Grammar errors outside the vocabulary (an unknown ``$op``, a
malformed document) are plain :class:`~bloomery.errors.InvalidRequest` —
malformed input is not a reviewed refusal.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

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
from bloomery.planner.request import AnyOf, Op, OrderSpec, Predicate

if TYPE_CHECKING:
    from bloomery.planner.request import Clause, Scalar

__all__ = [
    "DEFAULT_CLAUSE_CAP",
    "KNOWN_UNSUPPORTED",
    "MAX_NESTING_DEPTH",
    "parse_filter_json",
    "parse_page_json",
    "parse_sort_json",
]

#: The CNF clause cap (RFC 0015 D-Q4): counts **clauses** only — predicates
#: per clause are bounded by the input's leaf count, so no separate
#: predicate cap is needed.
DEFAULT_CLAUSE_CAP: Final[int] = 64

#: The input nesting-depth cap: ``_tree`` refuses a deeper document with
#: :class:`FilterTooComplex` before recursing further, keeping the parser
#: total for any input depth (no ``RecursionError`` can escape). Guarding
#: construction bounds ``_push_not``/``_distribute`` too — they recurse
#: over the tree ``_tree`` built, so their depth never exceeds this cap.
MAX_NESTING_DEPTH: Final[int] = 64

#: Every reason code the three parse functions can raise (RFC 0015 D9): the
#: union across :func:`parse_filter_json`, :func:`parse_sort_json`, and
#: :func:`parse_page_json` — which is why ``unsupported_sort_nulls`` and
#: ``unsupported_pagination`` legitimately sit here even though the filter
#: parser never raises them. The adapter-owned codes
#: (``unsupported_field_compare``, ``unsupported_quantifier``) are
#: deliberately absent — the two sets are disjoint. A drift-guard test
#: asserts exact equality against the actually-raisable union.
KNOWN_UNSUPPORTED: Final[frozenset[str]] = frozenset(
    {
        "unsupported_set_relation",
        "unsupported_hierarchy",
        "unsupported_text_operator",
        "filter_too_complex",
        "unsupported_negation",
        "invalid_literal",
        "unsupported_sort_nulls",
        "unsupported_pagination",
    }
)

_OPERATORS: Final[dict[str, Op]] = {
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

#: The complement table (RFC 0015 §5.2 step 2). ``is_null`` complements by
#: flipping its bool operand; ``like``/``ilike`` have no complement.
_COMPLEMENTS: Final[dict[Op, Op]] = {
    Op.EQ: Op.NE,
    Op.NE: Op.EQ,
    Op.GT: Op.LTE,
    Op.GTE: Op.LT,
    Op.LT: Op.GTE,
    Op.LTE: Op.GT,
    Op.IN: Op.NOT_IN,
    Op.NOT_IN: Op.IN,
}

#: Reviewed refusals for upstream operators bloomery deliberately does not
#: adopt (RFC 0015 §5.3) — refused with their closed-list error types.
_REFUSED_OPERATORS: Final[dict[str, type[UnsupportedFilter]]] = {
    "$superset": UnsupportedSetRelation,
    "$subset": UnsupportedSetRelation,
    "$disjoint": UnsupportedSetRelation,
    "$overlaps": UnsupportedSetRelation,
    "$descendant_of": UnsupportedHierarchy,
    "$ancestor_of": UnsupportedHierarchy,
    "$regex": UnsupportedTextOperator,
    "$empty": UnsupportedTextOperator,
}

#: Absent-vs-explicit-null sentinel for the sort ``nulls`` key: an omitted
#: key takes the canonical default, while an explicit ``"nulls": null`` is
#: a malformed placement (``InvalidRequest``) — the two must not collapse.
_ABSENT: Final = object()

_REFUSAL_REASONS: Final[dict[str, str]] = {
    "$superset": "marts are flattened and scalar — no array columns exist to relate",
    "$subset": "marts are flattened and scalar — no array columns exist to relate",
    "$disjoint": "marts are flattened and scalar — no array columns exist to relate",
    "$overlaps": "marts are flattened and scalar — no array columns exist to relate",
    "$descendant_of": "model hierarchy as flattened level columns on the mart",
    "$ancestor_of": "model hierarchy as flattened level columns on the mart",
    "$regex": "dialect-divergent and unbounded — use like/ilike",
    "$empty": "ambiguous across types — write eq '' or is_null true explicitly",
}


# ....................... #
# The internal boolean tree (never escapes this module)


@dataclass(frozen=True, slots=True)
class _Leaf:
    field: str
    op: Op
    values: tuple[object, ...]
    negated: bool = False

    def render(self) -> str:
        prefix = "not " if self.negated else ""
        return f"{prefix}{self.field} {self.op.value} {list(self.values)!r}"


# Only ``_Leaf`` carries a ``render`` — the sole renderable form is the
# normalized leaf inside an ``UnsupportedNegation`` message; combinator
# nodes never reach an error message, so they render nothing.


@dataclass(frozen=True, slots=True)
class _And:
    children: tuple[_Node, ...]


@dataclass(frozen=True, slots=True)
class _Or:
    children: tuple[_Node, ...]


@dataclass(frozen=True, slots=True)
class _Not:
    child: _Node


type _Node = _Leaf | _And | _Or | _Not


# ....................... #
# Grammar → tree


def _check_operand(value: object, *, where: str) -> object:
    """One JSON scalar operand. Floats normalize downstream (``Predicate``
    construction, RFC 0015 D5); the non-finite check is made here too so
    the refusal carries the parse-stage source and reason."""
    if isinstance(value, float) and not math.isfinite(value):
        msg = f"{where} carries non-finite {value!r} — fails open if permitted (RFC 0015 D5)"
        raise InvalidLiteral(msg)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    msg = f"{where} carries a non-scalar value of type {type(value).__name__!r}"
    raise InvalidRequest(msg)


def _leaf(field: str, spelling: str, operand: object) -> _Node:
    """One ``{field: {$op: operand}}`` entry as a leaf (or a refusal)."""
    where = f"filter on {field!r} ({spelling})"
    if spelling in _REFUSED_OPERATORS:
        error_type = _REFUSED_OPERATORS[spelling]
        msg = f"{where}: {_REFUSAL_REASONS[spelling]}"
        raise error_type(msg, source_path=field)
    op = _OPERATORS.get(spelling)
    if op is None:
        known = sorted(_OPERATORS)
        raise InvalidRequest(f"{where}: unknown operator; known: {known}")
    if op is Op.IS_NULL:
        if not isinstance(operand, bool):
            raise InvalidRequest(f"{where} takes exactly one bool operand")
        return _Leaf(field, op, (operand,))
    if op in (Op.IN, Op.NOT_IN):
        if not isinstance(operand, list):
            raise InvalidRequest(f"{where} takes an array operand")
        members = cast("list[object]", operand)
        values = tuple(_check_operand(v, where=where) for v in members)
        if any(v is None for v in values):
            raise InvalidRequest(f"{where} may not hold null — use $null instead")
        return _Leaf(field, op, values)
    if op in (Op.LIKE, Op.ILIKE):
        patterns: tuple[object, ...] = (
            tuple(cast("list[object]", operand)) if isinstance(operand, list) else (operand,)
        )
        return _Leaf(field, op, patterns)  # pattern validation rides Predicate
    checked = _check_operand(operand, where=where)
    if checked is None:  # {$eq: null} ≡ is_null true; {$neq: null} ≡ is_null false
        if op is Op.EQ:
            return _Leaf(field, Op.IS_NULL, (True,))
        if op is Op.NE:
            return _Leaf(field, Op.IS_NULL, (False,))
        raise InvalidRequest(f"{where} may not compare against null — use $null")
    return _Leaf(field, op, (checked,))


def _field_entry(field: str, spec: object) -> _Node:
    """One field-map entry: scalar = ``$eq`` shortcut, array = ``$in``
    shortcut, null = ``is_null true``, mapping = operator map (implicit
    AND across its operators)."""
    if field.startswith("$"):
        msg = f"unknown combinator {field!r}; known: ['$and', '$not', '$or']"
        raise InvalidRequest(msg)
    if spec is None:
        return _Leaf(field, Op.IS_NULL, (True,))
    if isinstance(spec, list):
        return _leaf(field, "$in", cast("list[object]", spec))
    if isinstance(spec, dict):
        op_map = cast("dict[object, object]", spec)
        if not op_map:
            raise InvalidRequest(f"filter on {field!r} is an empty operator map")
        nodes: list[_Node] = []
        for spelling, operand in op_map.items():
            if not isinstance(spelling, str):
                msg = f"filter on {field!r}: operator keys are strings, got {spelling!r}"
                raise InvalidRequest(msg)
            nodes.append(_leaf(field, spelling, operand))
        return nodes[0] if len(nodes) == 1 else _And(tuple(nodes))
    return _leaf(field, "$eq", spec)


def _tree(payload: object, *, depth: int = 0) -> _Node:
    """One filter document as a boolean tree — combinators and field maps
    may mix in one mapping (implicit AND across the keys). ``depth`` guards
    totality: nesting beyond :data:`MAX_NESTING_DEPTH` refuses **before**
    recursing further, so no input depth can raise ``RecursionError``."""
    if depth > MAX_NESTING_DEPTH:
        msg = (
            f"filter document nesting exceeded the depth cap ({MAX_NESTING_DEPTH} "
            "combinator levels) — refused before normalization; this is the "
            "nesting-depth cap, distinct from the CNF clause cap (RFC 0015 §5.2)"
        )
        raise FilterTooComplex(msg, normalized=f">{MAX_NESTING_DEPTH} levels deep")
    if not isinstance(payload, dict):
        msg = f"a filter document is a mapping, got {type(payload).__name__!r}"
        raise InvalidRequest(msg)
    document = cast("dict[object, object]", payload)
    if not document:
        raise InvalidRequest("a filter document may not be empty")
    nodes: list[_Node] = []
    for key, value in document.items():
        if not isinstance(key, str):
            msg = f"filter keys are strings, got {type(key).__name__!r}"
            raise InvalidRequest(msg)
        if key in ("$and", "$or"):
            if not isinstance(value, list) or not value:
                raise InvalidRequest(f"{key} takes a non-empty array of documents")
            children = tuple(_tree(child, depth=depth + 1) for child in cast("list[object]", value))
            nodes.append(_And(children) if key == "$and" else _Or(children))
        elif key == "$not":
            nodes.append(_Not(_tree(value, depth=depth + 1)))
        else:
            nodes.append(_field_entry(key, value))
    return nodes[0] if len(nodes) == 1 else _And(tuple(nodes))


# ....................... #
# Normalization (RFC 0015 §5.2): De Morgan → complement → capped CNF


def _push_not(node: _Node, *, negate: bool) -> _Node:
    """Steps 1–2: negations to the leaves via De Morgan, then inverted
    through the complement table; a non-invertible negated leaf refuses."""
    match node:
        case _Not(child):
            return _push_not(child, negate=not negate)
        case _And(children):
            pushed = tuple(_push_not(child, negate=negate) for child in children)
            return _Or(pushed) if negate else _And(pushed)
        case _Or(children):
            pushed = tuple(_push_not(child, negate=negate) for child in children)
            return _And(pushed) if negate else _Or(pushed)
        case _Leaf() as leaf:
            if not negate:
                return leaf
            if leaf.op is Op.IS_NULL:
                flipped = not leaf.values[0]
                return _Leaf(leaf.field, Op.IS_NULL, (flipped,))
            complement = _COMPLEMENTS.get(leaf.op)
            if complement is None:
                normalized = _Leaf(leaf.field, leaf.op, leaf.values, negated=True)
                msg = (
                    f"negated {leaf.op.value} on {leaf.field!r} has no complement "
                    "operator — not_like is added only on demonstrated need "
                    f"(RFC 0015 §5.3); normalized form: {normalized.render()}"
                )
                raise UnsupportedNegation(
                    msg, source_path=leaf.field, normalized=normalized.render()
                )
            return _Leaf(leaf.field, complement, leaf.values)


def _distribute(node: _Node, *, cap: int) -> list[tuple[_Leaf, ...]]:
    """Step 3: CNF distribution — a list of clauses, each a disjunction of
    leaves — with the cap enforced **during** distribution: the moment a
    partial count exceeds ``cap``, refuse; the expansion is never
    materialized (RFC 0015 D-Q4)."""

    def too_complex(count: int) -> FilterTooComplex:
        msg = (
            f"CNF distribution exceeded the clause cap ({cap}) at {count} partial "
            "clauses — refused during distribution, before materializing (RFC 0015 §5.2)"
        )
        return FilterTooComplex(msg, normalized=f">{cap} clauses")

    match node:
        case _Leaf() as leaf:
            if cap < 1:  # a single leaf is already one clause — the cap
                raise too_complex(1)  # binds here too (cap 0 admits nothing)
            return [(leaf,)]
        case _And(children):
            clauses: list[tuple[_Leaf, ...]] = []
            for child in children:
                for clause in _distribute(child, cap=cap):
                    clauses.append(clause)
                    if len(clauses) > cap:
                        raise too_complex(len(clauses))
            return clauses
        case _Or(children):
            product: list[tuple[_Leaf, ...]] = [()]
            for child in children:
                child_clauses = _distribute(child, cap=cap)
                next_product: list[tuple[_Leaf, ...]] = []
                for partial in product:
                    for clause in child_clauses:
                        next_product.append(partial + clause)
                        if len(next_product) > cap:
                            raise too_complex(len(next_product))
                product = next_product
            return product
        case _Not():  # pragma: no cover — _push_not eliminated every _Not
            raise InvalidRequest("internal: negation survived normalization")


# ....................... #
# The three public parse functions


def _require_mapping(payload: object, *, what: str) -> Mapping[str, object]:
    """Defensive boundary check — untyped callers hand us raw JSON. A
    non-mapping payload is malformed input (``InvalidRequest``), never a
    reviewed refusal; only well-formed mappings reach the refusal logic."""
    if not isinstance(payload, Mapping):
        msg = f"{what} is a mapping, got {type(payload).__name__!r}"
        raise InvalidRequest(msg)
    return cast("Mapping[str, object]", payload)


def parse_filter_json(
    payload: Mapping[str, object], *, clause_cap: int = DEFAULT_CLAUSE_CAP
) -> tuple[Clause, ...]:
    """Parse a Mongo-flavoured filter document into clauses.

    Grammar: ``{"$and": [...]}``, ``{"$or": [...]}``, ``{"$not": {...}}``,
    and a field map ``{field: scalar | {op: value} | [array]}`` using the
    operators in :class:`Op` (spellings ``$eq $neq $gt $gte $lt $lte $in
    $nin $null $like $ilike``). Scalars are the ``$eq`` shortcut; arrays are
    the ``$in`` shortcut; null is ``is_null: true``. Normalizes per RFC 0015
    D-Q4 (De Morgan → complement inversion → CNF capped during
    distribution), then validates each predicate. Nesting beyond
    :data:`MAX_NESTING_DEPTH` refuses with
    :class:`~bloomery.errors.FilterTooComplex` — the parser is total for
    any input depth. Raises
    :class:`~bloomery.errors.UnsupportedFilter` with a stable ``.reason`` —
    see :data:`KNOWN_UNSUPPORTED`.
    """
    document = dict(_require_mapping(payload, what="a filter document"))
    tree = _push_not(_tree(document), negate=False)
    clauses: list[Clause] = []
    for disjunction in _distribute(tree, cap=clause_cap):
        predicates = tuple(
            # Predicate re-validates every value at construction — the cast
            # only bridges the untyped JSON boundary to the typed vocabulary.
            Predicate(
                dimension=leaf.field,
                op=leaf.op,
                values=cast("tuple[Scalar, ...]", leaf.values),
            )
            for leaf in disjunction
        )
        clauses.append(predicates[0] if len(predicates) == 1 else AnyOf(predicates))
    return tuple(clauses)


def parse_sort_json(payload: Mapping[str, object]) -> tuple[OrderSpec, ...]:
    """Parse a sort document — ``{field: "asc" | "desc" | {"dir": …,
    "nulls": …}}`` — into :class:`OrderSpec` terms, in document order.

    A ``nulls`` placement equal to the canonical default (``first`` for
    asc, ``last`` for desc) is redundant and dropped; a well-formed
    non-default placement refuses with
    :class:`~bloomery.errors.UnsupportedSortNulls` (RFC 0015 D-Q6 —
    accepting-and-dropping a meaningful placement is worse than refusing).
    A **present** ``nulls`` key must hold exactly ``"first"`` or ``"last"``:
    a wrong type, an explicit ``null``, or an unknown word is malformed
    input (:class:`~bloomery.errors.InvalidRequest`), not a reviewed
    refusal. Omitting the key is the canonical default.
    """
    document = _require_mapping(payload, what="a sort document")
    specs: list[OrderSpec] = []
    # The declared key type is a promise untyped callers may break — widen
    # and check (the same discipline ``_tree`` applies to filter keys).
    for field, value in cast("Mapping[object, object]", document).items():
        if not isinstance(field, str):
            msg = f"sort keys are strings, got {type(field).__name__!r}"
            raise InvalidRequest(msg)
        direction: object
        nulls: object
        if isinstance(value, str):
            direction, nulls = value, _ABSENT
        elif isinstance(value, dict):
            spec_map = cast("dict[object, object]", value)
            unknown = sorted(str(key) for key in set(spec_map) - {"dir", "nulls"})
            if unknown:
                raise InvalidRequest(f"sort on {field!r} has unknown keys {unknown}")
            direction = spec_map.get("dir", "asc")
            # The sentinel keeps an omitted key (canonical default) distinct
            # from an explicit `"nulls": null`, which is malformed input.
            nulls = spec_map.get("nulls", _ABSENT)
        else:
            msg = f"sort on {field!r} must be 'asc', 'desc', or a dir/nulls mapping"
            raise InvalidRequest(msg)
        if direction not in ("asc", "desc"):
            msg = f"sort direction for {field!r} must be 'asc' or 'desc', got {direction!r}"
            raise InvalidRequest(msg)
        literal_direction: Literal["asc", "desc"] = "asc" if direction == "asc" else "desc"
        canonical = "first" if literal_direction == "asc" else "last"
        if nulls is not _ABSENT:
            # A present key must carry a well-formed placement: a wrong type,
            # an explicit null, or an unknown word is malformed input, never
            # a reviewed vocabulary refusal. Only a well-formed placement
            # reaches the D-Q6 refusal below.
            if nulls not in ("first", "last"):
                msg = (
                    f"sort on {field!r} sets nulls to {nulls!r} — a nulls "
                    "placement is 'first' or 'last' (omit the key for the "
                    "canonical default)"
                )
                raise InvalidRequest(msg)
            if nulls != canonical:
                msg = (
                    f"sort on {field!r} places nulls {nulls!r}, but the backend renders "
                    f"the canonical default only ({canonical!r} for {literal_direction!r}) — "
                    "refused rather than silently dropped (RFC 0015 D-Q6)"
                )
                raise UnsupportedSortNulls(msg, source_path=field)
        specs.append(OrderSpec(field=field, direction=literal_direction))
    return tuple(specs)


def parse_page_json(payload: Mapping[str, object]) -> int | None:
    """Parse a pagination document — ``{"limit": …, "offset": …}`` — into
    the request ``limit``.

    Pagination is limit-only (RFC 0015 D-Q7): a non-zero ``offset`` or a
    cursor key (``after``/``before``) refuses with
    :class:`~bloomery.errors.UnsupportedPagination` — paging aggregates
    belongs to the serving layer. Malformed payloads (a non-mapping
    document, a non-int ``limit``/``offset``) are
    :class:`~bloomery.errors.InvalidRequest` — only well-formed
    ``{limit/offset/after/before}`` shapes reach the reviewed refusals.
    """
    document = _require_mapping(payload, what="a pagination document")
    cursors = sorted(key for key in ("after", "before") if key in document)
    if cursors:
        msg = (
            f"cursor pagination ({cursors}) is refused — pagination is limit-only; "
            "page a materialization at the serving layer (RFC 0015 D-Q7)"
        )
        raise UnsupportedPagination(msg)
    unknown = sorted(str(key) for key in set(document) - {"limit", "offset"})
    if unknown:
        raise InvalidRequest(f"pagination has unknown keys {unknown}")
    offset = document.get("offset")
    if offset is not None:
        if isinstance(offset, bool) or not isinstance(offset, int):
            msg = f"offset must be an int, got {type(offset).__name__!r}"
            raise InvalidRequest(msg)
        if offset != 0:
            msg = (
                f"offset {offset!r} is refused — pagination is limit-only; page a "
                "materialization at the serving layer (RFC 0015 D-Q7)"
            )
            raise UnsupportedPagination(msg)
    limit = document.get("limit")
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise InvalidRequest(f"limit must be an int, got {type(limit).__name__!r}")
    if limit < 1:
        raise InvalidRequest(f"limit must be >= 1, got {limit}")
    return limit
