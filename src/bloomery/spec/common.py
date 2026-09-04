"""Shared spec-layer plumbing (RFC 0002 §5.1–§5.3, §5.6).

Hosts the strict :class:`SpecModel` base, the source-path conversion from
Pydantic ``loc`` tuples to dotted/bracketed authored-document addresses, the
shared grammars (type strings, partition specs, JSONPath-lite) and shared
sub-models (:class:`RatioSpec`, :class:`SemiAdditivePolicy`), and the strict
YAML loader that rejects duplicate keys (RFC 0002 D5).

Only :mod:`bloomery.errors` may be imported from here — the spec layer knows
nothing internal but errors (import-linter contract).
"""

from __future__ import annotations

from collections.abc import Hashable
from collections.abc import Mapping as AbcMapping
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from pydantic import ValidationError as PydanticValidationError

from bloomery.errors import BloomeryError, SpecParseError

# ----------------------- #

__all__ = [
    "JSONPATH_PATTERN",
    "PARTITION_SPEC_PATTERN",
    "RESERVED_MEMBER_NAMES",
    "RESERVED_MEMBER_REASONS",
    "TYPE_STRING_PATTERN",
    "AdditivityName",
    "CardinalityName",
    "CurrencyCode",
    "DimensionName",
    "JsonPath",
    "MaterializationName",
    "MemberName",
    "IDENTIFIER_PATTERN",
    "RELATION_NAME_PATTERN",
    "RelationName",
    "ParameterValue",
    "PartitionSpecString",
    "RatioSpec",
    "SemiAdditivePolicy",
    "SpecModel",
    "StepUse",
    "TypeString",
    "USE_PATTERN",
    "flatten_collected",
    "load_yaml_mapping",
    "source_path_from_loc",
    "validate_document",
]

# ....................... #
# Grammars (RFC 0002 §5.5) — shape-only; semantics live downstream.

#: The closed logical-type grammar (RFC 0004 §5.1). The spec layer validates the
#: grammar only; ``bloomery.typing.parse_type`` consumes the same pattern.
TYPE_STRING_PATTERN = (
    r"^(?:string|int|bool|date|timestamp|variant|decimal\((\d{1,3}), ?(\d{1,3})\))$"
)

#: Iceberg-style partition entries: a bare column or ``fn(column)`` with
#: ``fn ∈ {days, months, years, hours}`` (RFC 0002 §5.5).
PARTITION_SPEC_PATTERN = (
    r"^(?:(days|months|years|hours)\(([A-Za-z_][A-Za-z0-9_]*)\)|[A-Za-z_][A-Za-z0-9_]*)$"
)

#: JSONPath-lite: ``$.a.b`` dotted paths only (RFC 0002 §5.5).
JSONPATH_PATTERN = r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"

#: Names the compiler generates, so neither an authored member (a field, a
#: metric, a date role) nor an authored relation (an entity, a mart) may claim
#: one — the generated column would collide silently. ``metric_time`` is
#: MetricFlow's canonical query-time dimension (RFC 0002 D10, RFC 0013 R4); the
#: rest are the data-quality columns and the bronze ingestion-metadata contract
#: (RFC 0016 §5.5, §5.6, D9/D21/D23). Each carries the reason its message
#: quotes: a bare "reserved" tells an author nothing about which layer owns it.
#:
#: **Adding to this dict is the one change that can stop a document loading
#: without minting a new spec version** — the exception the stability reference
#: states and bounds. It is admissible because the outcome is binary: the
#: document loads unchanged, or it is refused with a message naming the name,
#: the owning layer and the fix. A reserved name can never reinterpret a
#: document, which is what a version bump exists to prevent. Two obligations
#: come with that: the reason string below is part of the contract rather than
#: a comment, and every addition is a ``CHANGELOG.md`` entry under *Changed*.
RESERVED_MEMBER_REASONS: dict[str, str] = {
    "metric_time": "RFC 0013 R4: the canonical query-time dimension",
    "_quality_flags": "RFC 0016 D9: the generated silver quality-flag column",
    "_quality_ok": "RFC 0016 D9: generated from _quality_flags",
    "_quality_repairs": "RFC 0016 D87: the generated repair marker",
    "_load_id": "RFC 0016 D21: bronze ingestion metadata",
    "_ingested_at": "RFC 0016 D21: bronze ingestion metadata",
    "_source_row_id": "RFC 0016 D21: the stable source-row identity",
    # Reserved unconditionally, not only on merged entities (RFC 0024 D18): a
    # name that is legal until a second mapping arrives is a trap laid for the
    # change that adds one.
    "_source": "RFC 0024 D7: the generated union-merge provenance column",
    "has_quality_flags": "RFC 0016 D9: the generated mart dimension",
}

#: The reserved names, sorted — the message vocabulary lives in
#: :data:`RESERVED_MEMBER_REASONS`, which is public for the same reason the
#: reason strings are contract: a second surface refusing these names has to
#: give the *same* account of why, and the only way to guarantee that is to
#: read this one.
RESERVED_MEMBER_NAMES = tuple(sorted(RESERVED_MEMBER_REASONS))


def _reject_reserved(name: str, *, rename: str) -> str:
    """Refuse a reserved name, telling the author what to rename.

    ``rename`` is not decoration. The stability reference makes a newly
    reserved name the one change that may refuse a ``spec_version: 1``
    document without minting a version, and it is admissible *because* the
    refusal is actionable — so a message naming a surface the author is not
    using undoes the argument. One validator served both annotations and said
    "field/dimension/role" to everyone, so an **entity** called
    ``metric_time`` was told to rename a field it does not have. Only
    ``metric_time`` and ``has_quality_flags`` reach that path: the other seven
    reserved names begin with ``_`` and :data:`RELATION_NAME_PATTERN` refuses
    them before this runs.
    """
    reason = RESERVED_MEMBER_REASONS.get(name)

    if reason is not None:
        msg = f"{name!r} is a reserved name ({reason}); pick a different {rename} name"
        raise ValueError(msg)

    return name


# ....................... #


def _reject_reserved_member(name: str) -> str:
    #: Every surface :data:`MemberName` guards: entity and mapping fields,
    #: metrics, and a mart's role-playing date dimension.
    return _reject_reserved(name, rename="field/metric/dimension-role")


# ....................... #


def _reject_reserved_relation(name: str) -> str:
    #: :data:`RelationName`'s two surfaces (RFC 0002 D14).
    return _reject_reserved(name, rename="entity/mart")


# ....................... #


TypeString = Annotated[str, StringConstraints(pattern=TYPE_STRING_PATTERN)]
PartitionSpecString = Annotated[str, StringConstraints(pattern=PARTITION_SPEC_PATTERN)]
JsonPath = Annotated[str, StringConstraints(pattern=JSONPATH_PATTERN)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
MemberName = Annotated[str, AfterValidator(_reject_reserved_member)]

#: A bare lower-snake identifier — the shape a name must have to be safe in a
#: context that does not quote it. Two such contexts exist, and they are
#: deliberately the *only* two: the SQLMesh ``MODEL (...)`` envelope, which is
#: Jinja over pre-rendered strings (:data:`RelationName`, RFC 0002 D14), and a
#: metric filter's dimension reference, which is Jinja on MetricFlow and
#: ``{member}`` templating on Cube (:data:`DimensionName`, RFC 0034 D8).
#:
#: One constant because it is one rule. Both names below travel outside
#: SQLGlot's quoting, so both need it; a second spelling of the same pattern is
#: how the two would come to differ about what an identifier is.
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]*$"

#: A name that becomes a **relation** — an entity or a mart (RFC 0002 D14).
#:
#: Stricter than :data:`MemberName` because it travels further. A field name
#: reaches SQL through SQLGlot, which quotes and escapes it; a relation name
#: also reaches the SQLMesh ``MODEL (...)`` envelope, which is Jinja over
#: pre-rendered strings and quotes nothing — so an entity named
#: ``t"; DROP TABLE x --`` put those characters into the model definition
#: verbatim. The pattern is the fix rather than escaping at the envelope: a
#: relation name has no business carrying anything but identifier characters,
#: and ``StepRef`` is pinned the same way for the same reason.
RELATION_NAME_PATTERN = IDENTIFIER_PATTERN
RelationName = Annotated[
    str, StringConstraints(pattern=RELATION_NAME_PATTERN), AfterValidator(_reject_reserved_relation)
]

#: A member name *referenced from a place that does not quote it* — today, the
#: dimension of a metric filter (RFC 0034 D8).
#:
#: :data:`MemberName` is deliberately unpatterned, on the reasoning quoted
#: above: a field name reaches SQL through SQLGlot, which quotes it. A metric
#: filter breaks that premise — the name is interpolated into
#: ``{{ Dimension('<entity>__<name>') }}`` on MetricFlow and ``{CUBE}.<name>``
#: on Cube, and neither is SQLGlot. A field named ``evil') }} = 1 OR 1=1 --``
#: therefore closed the template and made the filter match every row: a metric
#: declared as a restricted subset silently returning the whole population.
#:
#: The pattern rather than per-target escaping, for the same reason D13 refuses
#: template braces in a *value*: two escaping rules that can disagree is worse
#: than one refusal both targets inherit. Filtering on a column whose name is
#: not a bare identifier is the narrow thing this gives up.
DimensionName = Annotated[
    str, StringConstraints(pattern=IDENTIFIER_PATTERN), AfterValidator(_reject_reserved_member)
]

AdditivityName = Literal["additive", "semi_additive", "non_additive"]
CardinalityName = Literal["many_to_one", "one_to_one", "one_to_many"]
MaterializationName = Literal["full", "incremental_by_key", "incremental_by_partition"]

# ....................... #
# Base model (RFC 0002 §5.2)


class SpecModel(BaseModel):
    """Base of every spec model: strict (unknown keys are hard errors), frozen
    (a parsed spec is immutable), whitespace-stripped strings."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


# ....................... #


class RatioSpec(SpecModel):
    """Additive decomposition of a non-additive metric (RFC 0002 D9, RFC 0011 D5)."""

    numerator: str
    denominator: str


# ....................... #


class SemiAdditivePolicy(SpecModel):
    """Typed semi-additive policy (RFC 0002 §5.5): the dimension the metric is
    not additive over, and the rule applied along it."""

    over: str
    rule: Literal["last", "first", "avg", "min", "max"]


# ....................... #
# Source paths (RFC 0002 §5.3)


# ....................... #


def source_path_from_loc(document: str, loc: tuple[int | str, ...]) -> str:
    """Convert a Pydantic ``loc`` tuple into a document-prefixed source path.

    Dict keys join with ``.``, list indices render as ``[n]``, and the document
    name prefixes the path: ``mappings/shopify: fields.unit_price.from``.
    Pydantic's ``[key]`` marker (a failing dict *key*) is dropped — the path
    already ends at the key itself.
    """
    parts: list[str] = []

    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif item == "[key]":
            continue
        else:
            parts.append(f".{item}" if parts else str(item))

    if not parts:
        return document

    return f"{document}: {''.join(parts)}"


# ....................... #


def _with_document_identity(
    model_cls: type[SpecModel],
    data: object,
    *,
    document: str,
) -> tuple[object, SpecParseError | None]:
    """Bind ``document`` on a mapping's data; leave every other kind alone.

    An authored ``document:`` is **refused rather than overwritten**
    (RFC 0032 D3): the field is a fact about where the document was read from,
    and a document asserting its own filename is a second source of truth that
    can disagree with the first. Silently discarding the author's value would
    make that disagreement invisible, which is the failure the refusal exists
    to prevent.

    Refused here rather than by ``extra="forbid"``, which cannot see it: once
    ``document`` is a declared field of :class:`~bloomery.spec.mapping.Mapping`
    it is a *known* key, so the shape check that refuses every other unknown
    key would accept this one.

    **The refusal is returned, not raised**, so that it joins the document's
    other shape failures instead of pre-empting them (RFC 0002 D6). Raising
    here would report the authored key and hide every other error in the same
    document, which is the one-at-a-time fixing that batching exists to
    prevent — and the caller has the author's value bound to a real field by
    then, so it must be a refusal rather than a value either way.
    """
    from bloomery.spec.mapping import Mapping

    if model_cls is not Mapping or not isinstance(data, AbcMapping):
        return data, None

    if "document" in data:
        msg = (
            "'document' is not part of the mapping vocabulary — it is the name this "
            "document was loaded under, which bloomery supplies (RFC 0032 D3)"
        )
        # The authored value is dropped and the loader's bound in its place, so
        # the rest of the document still validates and reports its own errors.
        refusal = SpecParseError(msg, source_path=source_path_from_loc(document, ("document",)))

        return {**data, "document": document}, refusal  # pyright: ignore[reportUnknownVariableType]

    return {**data, "document": document}, None  # pyright: ignore[reportUnknownVariableType]


# ....................... #


def validate_document[ModelT: SpecModel](
    model_cls: type[ModelT], data: object, *, document: str
) -> ModelT:
    """Validate one parsed YAML document against a spec model.

    Pydantic's ``ValidationError`` never escapes (RFC 0002 D3): every failure
    is converted to a :class:`SpecParseError` with a document-prefixed source
    path, and multiple failures in one document are batched into a single
    aggregate error listing every path (RFC 0002 D6).

    ``document`` also **binds a mapping's identity** (RFC 0032 D1/D3). It is
    already the name this document is known by — it prefixes every refusal
    raised here — so a :class:`~bloomery.spec.mapping.Mapping` takes its
    ``document`` field from the same argument rather than from a second one
    that could disagree. Bound here rather than in ``load_project`` because
    this is the one gate every parsed document passes: a caller validating a
    mapping directly gets an identity too, instead of a
    ``document: Field required`` from a model it has no way to complete.
    """

    data, identity_refusal = _with_document_identity(model_cls, data, document=document)

    try:
        validated = model_cls.model_validate(data)
    except PydanticValidationError as exc:
        collected = (
            *((identity_refusal,) if identity_refusal is not None else ()),
            *(
                SpecParseError(
                    str(err["msg"]),
                    source_path=source_path_from_loc(document, tuple(err["loc"])),
                )
                for err in exc.errors()
            ),
        )
        if len(collected) == 1:
            raise collected[0] from None
        raise SpecParseError.from_collected(collected) from None

    if identity_refusal is not None:
        raise identity_refusal

    return validated


# ....................... #
# YAML parsing (RFC 0002 §5.6)


# ....................... #


#: The caps below exist because the spec path is the one that takes files from
#: other teams, and the filter parser already promises its half ("adversarial
#: nesting yields FilterTooComplex, never a RecursionError"). Each was sized
#: from the failure it prevents, not from what a spec needs — real documents
#: sit orders of magnitude below all three.
#:
#: Depth: PyYAML's composer recurses per nesting level, so ~1000 levels is a
#: raw ``RecursionError`` out of ``yaml.load`` (measured). 120 stays far under
#: the interpreter limit while no hand-written spec nests a tenth of it.
_MAX_DEPTH = 120

#: Aliases: PyYAML composes an alias as a *shared* node, so a billion-laughs
#: document loads cheaply here — and then costs whoever walks the result. A
#: 399-byte document was measured expanding to 10^8 leaves for its first
#: consumer (validation, in this package). The budget bounds the document's
#: *expanded* node count — every node counted once per path from the root —
#: relative to its distinct nodes, so a dense but alias-free document is
#: never refused for its honest size while a bomb's ratio is astronomical:
#: legitimate anchor reuse measures well under 2×.
_ALIAS_EXPANSION_FACTOR = 10
_ALIAS_EXPANSION_FLOOR = 10_000

#: Size: parse cost and every later cost scale with the document, so refuse
#: the pathological ones with a reason instead of an OOM kill. Five million
#: characters is ~three orders of magnitude above the largest fixture.
_MAX_SPEC_CHARS = 5_000_000


class _RecursiveAlias(Exception):
    """A node reachable from itself — an alias inside its own anchor."""

    def __init__(self, node: yaml.Node) -> None:
        super().__init__()
        self.node = node


def _children(node: yaml.Node) -> list[yaml.Node] | None:
    """A collection node's children, or ``None`` for a scalar."""
    if isinstance(node, yaml.SequenceNode):
        return list(cast("list[yaml.Node]", node.value))
    if isinstance(node, yaml.MappingNode):
        pairs = cast("list[tuple[yaml.Node, yaml.Node]]", node.value)
        return [child for pair in pairs for child in pair]
    return None


def _expanded_size(root: yaml.Node, memo: dict[int, int]) -> int:
    """The document's expanded node count — every node counted once per path
    from the root, which is exactly the cost a consumer walking the
    constructed value pays.

    Iterative post-order with a proper subtree memo, so an aliased subtree is
    measured once however many times it is named, and the whole computation
    costs the *distinct* nodes — never the expansion it bounds. A node found
    on its own path (an alias inside its own anchor) raises
    :class:`_RecursiveAlias`: the constructed value would be a cyclic
    structure no consumer can walk at all. Iterative for the same reason the
    depth cap exists: a walker that recursed would fall to the nesting it is
    part of bounding.
    """
    in_progress: set[int] = set()
    stack: list[tuple[yaml.Node, bool]] = [(root, False)]
    while stack:
        current, children_done = stack.pop()
        if children_done:
            in_progress.discard(id(current))
            done_children = _children(current) or []
            memo[id(current)] = 1 + sum(memo[id(child)] for child in done_children)
            continue
        if id(current) in memo:
            continue
        if id(current) in in_progress:
            raise _RecursiveAlias(current)
        children = _children(current)
        if children is None:
            memo[id(current)] = 1
            continue
        in_progress.add(id(current))
        stack.append((current, True))
        stack.extend((child, False) for child in children)
    return memo[id(root)]


class _StrictSafeLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that rejects duplicate mapping keys and caps
    adversarial shape.

    PyYAML's default silently keeps the last value — exactly the silent
    failure the spec layer exists to prevent (RFC 0002 D5). The two structural
    caps (nesting depth, alias expansion) turn the two quiet
    resource-exhaustion shapes into refusals with the limit named; the module
    constants above record the measurements behind them.
    """

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._depth = 0

    # ....................... #

    def compose_node(self, parent: yaml.Node | None, index: int | None) -> yaml.Node | None:
        self._depth += 1
        if self._depth > _MAX_DEPTH:
            event = self.peek_event()  # type: ignore[no-untyped-call]  # types-PyYAML leaves it untyped
            mark = cast("yaml.error.Mark", event.start_mark)  # pyright: ignore[reportUnknownMemberType]
            raise yaml.MarkedYAMLError(
                problem=(
                    f"nested more than {_MAX_DEPTH} levels deep — a spec document does"
                    " not nest this far, and deeper would exhaust the parser"
                ),
                problem_mark=mark,
            )
        try:
            # The stub narrows `index` to int; PyYAML itself passes None for
            # the document root, hence the wider parameter and the cast here.
            return super().compose_node(parent, cast("int", index))
        finally:
            self._depth -= 1

    # ....................... #

    def get_single_node(self) -> yaml.Node | None:
        """The composed document, measured before anything constructs it.

        Accounting runs here — once, on the finished node graph — rather than
        per alias during composition, because an alias *inside its own anchor*
        resolves to a node whose children are not composed yet: a per-alias
        walk sees an empty shell, undercounts it, and lets a cyclic document
        through to construct a recursive Python value no consumer can walk
        (measured: ``a: &x {b: *x}`` loaded and made ``d["a"]["b"] is
        d["a"]`` true). On the finished graph the cycle is visible and the
        weights are final.
        """
        root = super().get_single_node()
        if root is None:
            return root
        memo: dict[int, int] = {}
        try:
            expanded = _expanded_size(root, memo)
        except _RecursiveAlias as cycle:
            raise yaml.MarkedYAMLError(
                problem=(
                    "an alias refers to a node inside its own anchor — the"
                    " document would construct a recursive value no consumer"
                    " can read; name a completed anchor instead"
                ),
                problem_mark=cycle.node.start_mark,
            ) from None
        budget = max(_ALIAS_EXPANSION_FACTOR * len(memo), _ALIAS_EXPANSION_FLOOR)
        if expanded > budget:
            raise yaml.MarkedYAMLError(
                problem=(
                    f"aliases expand this document to {expanded:,} nodes from"
                    f" {len(memo):,} written ones, over the {budget:,} allowed —"
                    " write the repeated content out, or split the document"
                ),
                problem_mark=root.start_mark,
            )
        return root

    # ....................... #

    def _construct_key(self, node: yaml.Node) -> object:
        """``construct_object`` pinned to ``object`` — types-PyYAML leaves it untyped."""

        return cast(
            "object",
            self.construct_object(node, deep=True),  # pyright: ignore[reportUnknownMemberType]
        )

    # ....................... #

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[object] = set()

        for key_node, _value_node in node.value:
            key = self._construct_key(key_node)
            if isinstance(key, (dict, list)):  # unhashable — SafeLoader rejects later
                continue
            if key in seen:
                raise yaml.MarkedYAMLError(
                    problem=f"duplicate key {key!r}",
                    problem_mark=key_node.start_mark,
                )
            seen.add(key)

        return super().construct_mapping(node, deep=deep)


# ....................... #


def load_yaml_mapping(text: str, *, document: str) -> dict[str, object]:
    """Parse one YAML document into a mapping, strictly.

    Duplicate keys, YAML syntax errors, unsafe tags, and non-mapping roots are
    all :class:`SpecParseError` with the document name as source path. So are
    the three adversarial shapes — an oversized document, nesting past the
    parser's depth, aliases that expand a small document into a huge value —
    which is the same guarantee the filter parser makes for its input: a
    hostile document yields a refusal naming the limit, never a
    ``RecursionError`` and never memory exhaustion.
    """
    if len(text) > _MAX_SPEC_CHARS:
        raise SpecParseError(
            f"the document is {len(text):,} characters, over the"
            f" {_MAX_SPEC_CHARS:,} limit — split it into multiple spec files",
            source_path=document,
        )

    try:
        # SafeLoader subclass: only plain YAML types construct (RFC 0002 §5.6).
        data = yaml.load(text, Loader=_StrictSafeLoader)  # noqa: S506 — a SafeLoader subclass, see above
    except yaml.YAMLError as exc:
        raise SpecParseError(f"invalid YAML: {exc}", source_path=document) from exc

    if not isinstance(data, dict):
        raise SpecParseError(
            f"a spec document must be a YAML mapping, got {type(data).__name__}",
            source_path=document,
        )

    mapping = cast("dict[object, object]", data)
    bad_keys = [key for key in mapping if not isinstance(key, str)]

    if bad_keys:
        raise SpecParseError(
            f"spec document keys must be strings, got {bad_keys[0]!r}",
            source_path=document,
        )

    return {str(key): value for key, value in mapping.items()}


# ....................... #


def flatten_collected(errors: list[BloomeryError]) -> tuple[BloomeryError, ...]:
    """Flatten already-aggregated errors into one flat collected tuple."""
    flat: list[BloomeryError] = []

    for err in errors:
        if err.collected:
            flat.extend(err.collected)
        else:
            flat.append(err)

    return tuple(flat)


# ....................... #
# Naming and binding a step (RFC 0017 §5.2)
#
# Defined here rather than in ``spec.steps`` — which re-exports both, so every
# shipped import path is unchanged — because two documents name a step and
# ``spec.steps`` imports one of them: ``quality.Repair.via`` references a
# ``sql_macro`` (RFC 0016 D87) while ``spec.steps`` reads ``quality``'s
# ``ExpressionRule`` for a step output's rules. Whichever way that pair is
# written it is a cycle, so the two primitives move below both.


# ....................... #


#: ``ref@version`` — the only way a spec names a step.
USE_PATTERN = r"^[a-z][a-z0-9_]*@[1-9][0-9]*$"

StepUse = Annotated[str, StringConstraints(pattern=USE_PATTERN)]

#: A parameter value a call site may set. ``float`` is deliberately absent
#: (RFC 0003 D5) — a decimal arrives as ``Decimal``, and a YAML float would
#: reach emission as a binary approximation of what the author wrote.
ParameterValue = str | int | bool | Decimal
