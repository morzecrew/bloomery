"""The delta vocabulary: what about a definition moved (RFC 0064 §5.1).

:func:`~bloomery.timeline` reports *that* a node's definition differs between
two versions of a project. This module says **how**, in the vocabulary the
specs are written in — a grain that moved, a filter that gained a predicate, an
expression that was rewritten — and never as a text diff of emitted SQL (D1). A
reader who has to decide which textual differences are semantic is doing the
compiler's job.

**The table is keyed by record type and field name, and it is total.** §9's
first risk is a facet list that is a closed world and therefore wrong: a spec
field landing in no facet is silently unattributed, which is how a change comes
to be reported as no change at all. So there is no fall-through — an unmapped
field raises :class:`~bloomery.errors.InvariantViolated` — and
``test_every_field_of_every_comparable_record_has_a_facet`` enumerates every
field of every record :func:`~bloomery.resolve.timeline` can compare, so the
raise is unreachable rather than merely unlikely. That is this module's answer
to D6, which asked whether an unattributable field is a ``check`` refusal or a
warning: neither. A ``check`` refusal would reject an author's specs for a gap
in a table that ships with the compiler, and there is no warnings channel to
put it in — a test plus a loud invariant is the mechanical failure §10's third
question asks for (``logs/T-0045.md``).

**Identity is not definition.** ``name``, ``ref`` and ``id`` belong to no
facet: they are how a node is *matched* across versions, which is RFC 0062's
business, and a pure rename must attribute nothing (§6). They are excluded once
here rather than blanked per kind, so the rule has one statement.

**The comparison is one level deep.** A nested record maps by the field that
owns it — a rewritten ``derived:`` block is a ``body`` change and not a tour of
what inside it moved — which is the coarseness §5.1 already blesses for
``body``: reporting "the expression changed" honestly beats reporting a token
diff dressed as semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, TypeGuard, cast

from bloomery.errors import InvariantViolated

# Runtime imports, not `TYPE_CHECKING` ones: `Facet`, `FacetDelta` and
# `facets` are public, and RFC 0018 D10 requires a public annotation to resolve
# at run time — `tests/unit/test_signature_closure.py` calls `get_type_hints`
# on every export and a guarded name fails it.
from bloomery.ir import SourceColumnIR, SqlExpr
from bloomery.spec.catalog import CanonicalField
from bloomery.typing import LogicalType, render_type

# ----------------------- #

__all__ = [
    "Facet",
    "FacetDelta",
    "facets",
]


class Facet(StrEnum):
    """What a difference between two definitions is *about* (§5.1).

    §5.1's table names six, written for a metric. The comparison is not
    restricted to metrics — :func:`~bloomery.timeline` takes any node id, so
    the definitions reaching it span seven node kinds and ten record types —
    and the four members after the first six are what those kinds need. Adding
    them here rather than widening the meaning of `inputs` or `body` is the
    point: a facet that means several things reports nothing (``logs/T-0045.md``).
    """

    #: Which rows the definition describes — the grain itself, the key that
    #: identifies one, the dimensions a gold relation keeps.
    GRAIN = "grain"
    #: Which of those rows count. A metric's declared filter, and nothing else:
    #: a rule that *drops* a row is :attr:`QUALITY`, because an author changes
    #: the two for different reasons and reads them in different places.
    FILTER = "filter"
    #: What the value is expressed in — its logical type, its unit, its tax
    #: basis, its currency.
    UNIT = "unit"
    #: What the definition is wired to: the fields it reads, the measures a
    #: mart carries, the relations a step consumes and produces.
    INPUTS = "inputs"
    #: An expression changed. Deliberately coarse (§5.1): the facet says the
    #: body moved and makes no claim about what the move means.
    BODY = "body"
    #: How values combine — the aggregate, the additivity class, the
    #: semi-additive policy, the window, the ratio.
    ADDITIVITY = "additivity"
    #: Which rows survive a rule: quality rules, dedupe, quarantine, audits,
    #: mart asserts, and whether a column is required.
    QUALITY = "quality"
    #: How the relation is stored — materialization, partitioning, cost hint.
    STORAGE = "storage"
    #: What runs a step: its version, its determinism class, its runtime lock,
    #: its lineage class, its seed.
    RUNTIME = "runtime"
    #: Something a reader reads and no number depends on.
    METADATA = "metadata"


# ....................... #


@dataclass(frozen=True, slots=True)
class FacetDelta:
    """One facet of one definition, before and after.

    It carries the field as well as the facet because the facet is a
    *classification* and the field is the fact: three of ``MetricIR``'s fields
    are :attr:`Facet.ADDITIVITY`, and "the aggregate changed" and "the
    semi-additive policy changed" are not the same sentence.

    :attr:`old` and :attr:`new` are populated where a value is a thing a person
    can read — a scalar, an expression, a list of names — and are ``None``
    where it is not. A rendering that flattened a mart's whole column list into
    a string would be a text diff wearing a facet's name (D1), so the honest
    answer for a value with no compact spelling is to name the field and stop.
    """

    facet: Facet
    #: The IR field that moved, spelled as the record spells it.
    field: str
    #: The earlier value, rendered, or ``None`` — which means either "absent"
    #: or "has no compact spelling". The two are told apart by the other side
    #: and by :attr:`field`, not by this.
    old: str | None = None
    #: The later value, under the same rule.
    new: str | None = None


# ....................... #


#: Fields that name a node rather than define it. Identity is RFC 0062's
#: business and a pure rename must attribute nothing (§6), so these belong to
#: no facet and never reach the table below.
_IDENTITY: Final[frozenset[str]] = frozenset({"id", "name", "ref"})


#: ``(record type, field)`` to the facet it lands in — **total** over every
#: record :func:`~bloomery.resolve.timeline._definition` can return, and keyed
#: by the pair rather than by the field alone because one name means two things
#: across kinds: ``kind`` on an ``ExposureIR`` is what a consumer *is*, and on
#: a ``StepIR`` it is what executes it.
_FACETS: Final[dict[tuple[str, str], Facet]] = {
    # A metric: the record §5.1's table was written for.
    ("MetricIR", "grain"): Facet.GRAIN,
    ("MetricIR", "filter"): Facet.FILTER,
    ("MetricIR", "additivity"): Facet.ADDITIVITY,
    ("MetricIR", "agg"): Facet.ADDITIVITY,
    ("MetricIR", "ratio"): Facet.ADDITIVITY,
    ("MetricIR", "semi_additive"): Facet.ADDITIVITY,
    ("MetricIR", "cumulative"): Facet.ADDITIVITY,
    ("MetricIR", "expr"): Facet.BODY,
    ("MetricIR", "derived"): Facet.BODY,
    ("MetricIR", "depends_on"): Facet.INPUTS,
    ("MetricIR", "description"): Facet.METADATA,
    # A metric the IR could not reach: what is missing, and through what.
    ("UnreachableMetric", "missing"): Facet.INPUTS,
    ("UnreachableMetric", "via"): Facet.INPUTS,
    # A mart.
    ("MartIR", "grain"): Facet.GRAIN,
    ("MartIR", "dimensions"): Facet.GRAIN,
    ("MartIR", "base"): Facet.INPUTS,
    ("MartIR", "columns"): Facet.INPUTS,
    ("MartIR", "measures"): Facet.INPUTS,
    ("MartIR", "joins"): Facet.INPUTS,
    ("MartIR", "asserts"): Facet.QUALITY,
    ("MartIR", "materialization"): Facet.STORAGE,
    ("MartIR", "partition_by"): Facet.STORAGE,
    ("MartIR", "cost_hint"): Facet.STORAGE,
    # A rollup, which shares the mart's node prefix (RFC 0067 §5.1).
    ("RollupIR", "keep"): Facet.GRAIN,
    ("RollupIR", "of"): Facet.INPUTS,
    ("RollupIR", "measures"): Facet.INPUTS,
    ("RollupIR", "materialization"): Facet.STORAGE,
    ("RollupIR", "partition_by"): Facet.STORAGE,
    # A declared consumer.
    ("ExposureIR", "metrics"): Facet.INPUTS,
    ("ExposureIR", "marts"): Facet.INPUTS,
    ("ExposureIR", "kind"): Facet.METADATA,
    ("ExposureIR", "owner"): Facet.METADATA,
    ("ExposureIR", "url"): Facet.METADATA,
    # A step. `outputs` is `inputs` too: the facet is what the node is wired
    # to, and a step that stops producing a relation has moved the same fact
    # as one that stops reading it.
    ("StepIR", "inputs"): Facet.INPUTS,
    ("StepIR", "outputs"): Facet.INPUTS,
    ("StepIR", "parameters"): Facet.INPUTS,
    ("StepIR", "body"): Facet.BODY,
    ("StepIR", "entrypoint"): Facet.BODY,
    ("StepIR", "version"): Facet.RUNTIME,
    ("StepIR", "kind"): Facet.RUNTIME,
    ("StepIR", "determinism"): Facet.RUNTIME,
    ("StepIR", "runtime_lock"): Facet.RUNTIME,
    ("StepIR", "lineage"): Facet.RUNTIME,
    ("StepIR", "seed"): Facet.RUNTIME,
    # An entity, which reaches this table as the definition of a step's
    # produced relation rather than of a field (see `_entity_field`).
    ("EntityIR", "grain"): Facet.GRAIN,
    ("EntityIR", "key"): Facet.GRAIN,
    ("EntityIR", "scd"): Facet.GRAIN,
    ("EntityIR", "columns"): Facet.INPUTS,
    ("EntityIR", "sources"): Facet.INPUTS,
    ("EntityIR", "produced_by"): Facet.INPUTS,
    ("EntityIR", "audits"): Facet.QUALITY,
    ("EntityIR", "quality"): Facet.QUALITY,
    ("EntityIR", "dedupe"): Facet.QUALITY,
    ("EntityIR", "quarantine"): Facet.QUALITY,
    ("EntityIR", "materialization"): Facet.STORAGE,
    ("EntityIR", "partition_by"): Facet.STORAGE,
    # An entity field: the schema half.
    ("ColumnIR", "type"): Facet.UNIT,
    ("ColumnIR", "unit"): Facet.UNIT,
    ("ColumnIR", "tax_basis"): Facet.UNIT,
    ("ColumnIR", "canonical"): Facet.INPUTS,
    ("ColumnIR", "required"): Facet.QUALITY,
    ("ColumnIR", "description"): Facet.METADATA,
    ("ColumnIR", "renamed_from"): Facet.METADATA,
    # An entity field: the lowering half, one per source (RFC 0024 D26).
    ("SourceColumnIR", "expr"): Facet.BODY,
    ("SourceColumnIR", "recipe_id"): Facet.BODY,
    ("SourceColumnIR", "sources"): Facet.INPUTS,
    ("SourceColumnIR", "enum_values"): Facet.INPUTS,
    ("SourceColumnIR", "enum_spellings"): Facet.INPUTS,
    # A canonical field, the one spec model among these: the IR has no record
    # of one at all (`_definition`).
    ("CanonicalField", "type"): Facet.UNIT,
    ("CanonicalField", "unit"): Facet.UNIT,
    ("CanonicalField", "tax_basis"): Facet.UNIT,
    ("CanonicalField", "currency"): Facet.UNIT,
    ("CanonicalField", "entity"): Facet.INPUTS,
    ("CanonicalField", "recipes"): Facet.BODY,
    ("CanonicalField", "description"): Facet.METADATA,
}


# ....................... #


def _render(value: object) -> str | None:
    """A value as a person reads it, or ``None`` where it has no compact
    spelling.

    ``None`` is not a failure. A mart's ``columns`` is a tuple of records and
    any flattening of it is a text diff wearing a facet's name (D1), so the
    delta names the field and stops. What renders is what an author wrote in
    one place: a scalar, a type, an expression, a list of names, and a per
    source list of any of those.
    """

    match value:
        case None:
            return None
        case SqlExpr():
            return value.sql
        case str():
            # `StrEnum` lands here too, and `str()` is what makes the member
            # its declared spelling — `currency` rather than `Unit.CURRENCY`.
            return str(value)
        case bool() | int() | Decimal():
            return str(value)
        case _ if isinstance(value, LogicalType):
            # The one spelling a type has (RFC 0004): `render_type` is public
            # precisely so that three consumers cannot invent a fourth. Matched
            # by a guard rather than by `case LogicalType()`: it is a union
            # alias over seven classes, and a match pattern takes a class.
            return render_type(value)
        case ():
            # Nothing to spell. `""` would read as a value rather than as an
            # absence, and the two sides of a delta are compared by a reader
            # who has only these two strings.
            return None
        case tuple():
            return _render_tuple(cast("tuple[object, ...]", value))
        case _:
            return None


# ....................... #


def _render_tuple(value: tuple[object, ...]) -> str | None:
    """A non-empty tuple: a list of names, or a list of values keyed by the
    source relation they were lowered for."""

    if all(isinstance(one, str) for one in value):
        return ", ".join(str(one) for one in value)

    keyed = [one for one in value if _is_keyed(one)]

    if len(keyed) != len(value):
        return None

    # Rendered only when every value renders: half a list is worse than none,
    # because a reader cannot see which half is missing.
    rendered = [(key, _render(one)) for key, one in keyed]

    if any(one is None for _key, one in rendered):
        return None

    return "; ".join(f"{key}: {one}" for key, one in rendered)


# ....................... #


def _is_keyed(value: object) -> TypeGuard[tuple[str, object]]:
    """Whether ``value`` is a ``(key, value)`` pair this can render under its
    key — the shape :func:`_flatten` builds for a lowering."""

    if not isinstance(value, tuple):
        return False

    pair = cast("tuple[object, ...]", value)
    return len(pair) == 2 and isinstance(pair[0], str)


# ....................... #


def _record_fields(record: object) -> dict[str, tuple[str, object]]:
    """One record as ``field -> (record type, value)``, identity excluded.

    The type travels with the value because the table is keyed by the pair: a
    field name alone is ambiguous across kinds, and a new record inheriting
    another's classification by sharing a field name is exactly the silent
    mis-attribution §9 warns about.
    """

    name = type(record).__name__

    if isinstance(record, CanonicalField):
        return {
            field: (name, getattr(record, field))
            for field in CanonicalField.model_fields
            if field not in _IDENTITY
        }

    if is_dataclass(record) and not isinstance(record, type):
        return {
            field.name: (name, getattr(record, field.name))
            for field in fields(record)
            if field.name not in _IDENTITY
        }

    msg = f"no field table for a definition of type {name!r}"
    raise InvariantViolated(msg)


# ....................... #


def _flatten(definition: object) -> dict[str, tuple[str, object]]:
    """A definition as one flat field map, whatever shape it arrived in.

    Three shapes reach here, and flattening them to one removes every special
    case downstream — including the one that has no name: a node whose *kind
    of record* changed between two versions, a metric that stopped resolving
    and became an ``UnreachableMetric``. Two field maps compare whether or not
    they came from the same class.

    An entity field is the shape that needs the work: its schema is a
    ``ColumnIR`` and its expression is a ``SourceColumnIR`` **per source**
    (RFC 0024 D26), so the lowering's fields enter keyed by source relation.
    A source added to a merged entity therefore moves every lowered field at
    once, which is verbose and true — the alternative, comparing only the
    sources both sides share, would report a rewritten mapping and a dropped
    one identically.
    """

    if definition is None:
        return {}

    if isinstance(definition, tuple):
        # `_definition` returns `object`, and this is the one shape it builds
        # rather than looks up: the schema half and the lowering half of one
        # entity field (RFC 0024 D26).
        column, lowerings = cast(
            "tuple[object, tuple[tuple[str, SourceColumnIR], ...]]", definition
        )
        flat = _record_fields(column)
        for field in _lowered_fields(lowerings):
            flat[field] = (
                "SourceColumnIR",
                tuple((relation, getattr(lowered, field)) for relation, lowered in lowerings),
            )
        return flat

    return _record_fields(definition)


# ....................... #


def _lowered_fields(lowerings: tuple[tuple[str, SourceColumnIR], ...]) -> tuple[str, ...]:
    """The ``SourceColumnIR`` fields to compare, identity excluded — read off
    the records themselves so a field added there is compared without being
    listed twice."""

    for _relation, lowered in lowerings:
        return tuple(field.name for field in fields(lowered) if field.name not in _IDENTITY)
    return ()


# ....................... #


def facets(before: object, after: object) -> tuple[FacetDelta, ...]:
    """What moved between two definitions of one node (§5.1).

    Empty means the definitions agree on everything a facet covers — which,
    the table being total, means they agree. That is what makes this the test
    of whether a definition changed at all: a pure rename moves ``name`` and
    nothing else, ``name`` belongs to no facet, and the answer is empty (§6).

    Sorted by facet and then field, so a value built from two IRs is
    deterministic in the way everything else here is (RFC 0003 §5.3).

    Raises :class:`~bloomery.errors.InvariantViolated` for a field the table
    does not cover. Loud rather than silent, because the alternative is a
    change reported as no change (§9), and a test makes the raise unreachable.
    """

    old = _flatten(before)
    new = _flatten(after)
    deltas: list[FacetDelta] = []

    # Which record owns each field, over both sides at once. The two agree
    # wherever both carry a field, and where only one does the field belongs to
    # that side's record — the case a node whose record *kind* changed
    # produces, and the reason nothing below assumes one type.
    owners = {field: record for field, (record, _value) in (new | old).items()}

    for field in sorted(old.keys() | new.keys()):
        was = old.get(field)
        now = new.get(field)

        if was is not None and now is not None and was[1] == now[1]:
            continue

        deltas.append(
            FacetDelta(
                facet=_facet(owners[field], field),
                field=field,
                old=None if was is None else _render(was[1]),
                new=None if now is None else _render(now[1]),
            )
        )

    return tuple(sorted(deltas, key=lambda one: (one.facet.value, one.field)))


# ....................... #


def _facet(record: str, field: str) -> Facet:
    """The facet ``field`` lands in, or a refusal naming what is unmapped."""

    facet = _FACETS.get((record, field))

    if facet is None:
        msg = (
            f"{record}.{field} lands in no facet — RFC 0064 §9: a spec field "
            f"that no facet covers is reported as unchanged when it changed"
        )
        raise InvariantViolated(msg)

    return facet
