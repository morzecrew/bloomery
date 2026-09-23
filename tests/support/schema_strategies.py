"""A Hypothesis strategy over the JSON Schema subset bloomery exports.

Hand-written rather than ``hypothesis-jsonschema``, which S-0010/D-3 leaves to
execution: the deciding number is the fraction of generated documents that
reach the resolver, and a generic generator over these schemas spends nearly
all of it at the door. The reason is :data:`NAMES`. A document only parses when
the name an ``key:`` entry spells is a name ``fields:`` declares, and the name a
relationship spells is a name ``entities:`` declares — so every string this
module generates for an identifier-shaped position is drawn from one small
shared pool, and collisions happen by construction instead of by luck. That
bias is the whole strategy; a dependency that does not know which strings are
names cannot have it.

The subset is what pydantic's ``model_json_schema`` emits and nothing more:
``$ref`` into ``$defs``, ``anyOf``/``oneOf``, ``const``, ``enum``,
``patternProperties``, ``additionalProperties`` as a schema, and the scalar
types with ``pattern``/``minimum``/``minItems``. Anything outside it raises
rather than generating quietly — a keyword the export grows and this module
ignores would otherwise narrow the generated space silently.

Nothing here is kind-specific: :func:`from_spec_schema` takes any of the
exported schemas, and :func:`project_documents` draws a whole project's worth
of documents from one pool so that the cross-document references resolve
(S-0010/D-6).
"""

from __future__ import annotations

import re
from typing import Any

from hypothesis import strategies as st

__all__ = ["NAMES", "from_spec_schema", "project_documents"]

#: The shared name pool. Small on purpose: these are the only strings that ever
#: land in an identifier-shaped position, so a ``key:`` entry, a ``fields:``
#: key, a relationship endpoint and a ``via`` pair all draw from the same three
#: names and agree often enough for documents to reach past the parser.
#:
#: Three is a middle point, measured rather than guessed — over 200 projects
#: drawn from a pool of this width shared as a constant, 62 of 181 valid draws
#: got past the parser and 32 compiled; at one name, 92 of 192 and 55; at
#: eight, 45 of 168 and 29. So a narrower pool does buy reach, and it buys it
#: by making the space degenerate: with one name every entity, field and mart
#: is called ``a``, and a dangling reference or a two-entity join cannot be
#: generated at all. Three keeps both, which is why widening is what costs
#: (S-0010/D-6 — the pool is worth what it constrains).
NAMES = ("a", "b", "c")

#: Upper bound on every generated array and open-keyed object. The pipeline
#: runs per example, so breadth is paid for on every one of them; three is
#: enough for a duplicate, a cycle, or a dangling reference to appear.
_MAX_SIZE = 3

_NAME_KEYS = frozenset({"key", "from", "to", "entity", "relationship", "column", "name"})


def from_spec_schema(
    schema: dict[str, Any], names: tuple[str, ...] = NAMES
) -> st.SearchStrategy[dict[str, Any]]:
    """A strategy over documents the exported ``schema`` accepts.

    Not every draw validates — ``patternProperties`` without an
    ``additionalProperties`` sibling admits keys no pattern describes, and the
    strategy generates those too rather than pretending the export is closed
    where it is not. Callers filter with the schema itself.

    ``names`` is the pool identifier-shaped positions draw from, defaulting to
    :data:`NAMES`. It is a parameter rather than only a constant so that the
    cost of the pool is measurable: the same strategy over a wider pool is the
    comparison D-6's "constrains more than it buys" needs.
    """
    return _build(schema, schema, names).map(dict)


def project_documents(
    schemas: dict[str, dict[str, Any]],
    names: tuple[str, ...] = NAMES,
    omit: frozenset[str] = frozenset(),
) -> st.SearchStrategy[dict[str, dict[str, Any]]]:
    """A strategy over whole projects: document name → document (S-0010/D-6).

    ``schemas`` maps each project kind's name to its exported schema — the
    caller's job, because which kinds form a project is
    :func:`~bloomery.load_project`'s business and not this module's. The key is
    used as the document name, which is what ``load_project`` takes for a
    source-path prefix. ``omit`` drops top-level keys from every drawn
    document, for a key the schema declares and the parser refuses outright.

    Every kind but ``entity_model`` is optional, so a draw is any of the
    subsets a project may be: the entity model alone (the phase-1 shape), all
    of them together, or anything between. Cardinality is what
    ``load_project`` admits — at most one of each — so nothing here draws two
    marts documents.

    **The pool is drawn, not fixed.** The entity model comes first, and the
    names it *actually declared* — its entity keys and their field keys — are
    the pool every other document in the same draw uses. A pool shared as a
    module constant is not enough: with three names in it and one entity
    declared, a ``mapping`` naming an entity from the constant hits the
    declared one a third of the time, and measured that way a three-document
    project reached past ``resolve`` 4 times in 195 (against 0 in 222 when each
    document drew from a pool of its own). Harvesting instead makes the
    reference resolve by construction rather than by luck, which is what D-6's
    "stateful across a project's documents" buys.
    """

    def shaped(kind: str, pool: tuple[str, ...]) -> st.SearchStrategy[dict[str, Any]]:
        return from_spec_schema(schemas[kind], pool).map(
            lambda document: {key: value for key, value in document.items() if key not in omit}
        )

    def rest(entity_model: dict[str, Any]) -> st.SearchStrategy[dict[str, dict[str, Any]]]:
        pool = _declared_names(entity_model) or names
        return st.fixed_dictionaries(
            {"entity_model": st.just(entity_model)},
            optional={kind: shaped(kind, pool) for kind in schemas if kind != "entity_model"},
        )

    return shaped("entity_model", names).flatmap(rest)


def _declared_names(entity_model: dict[str, Any]) -> tuple[str, ...]:
    """The names an entity model declares: its entities and their fields.

    Both, because the two are what the other kinds reference — a mart's
    ``base`` is an entity and its measures are fields — and the export's open
    maps mean either may be drawn as something no author would write (an empty
    key, a mapping where a body belongs), which is dropped here rather than
    handed on as a pool member nothing can resolve.
    """
    pool: set[str] = set()
    entities = entity_model.get("entities")
    if not isinstance(entities, dict):
        return ()
    for name, body in entities.items():
        if isinstance(name, str) and name:
            pool.add(name)
        if isinstance(body, dict) and isinstance(fields := body.get("fields"), dict):
            pool.update(field for field in fields if isinstance(field, str) and field)
    return tuple(sorted(pool))


def _build(
    node: dict[str, Any], root: dict[str, Any], names: tuple[str, ...]
) -> st.SearchStrategy[Any]:
    """The recursive core: one strategy per schema node, ``root`` for ``$ref``."""
    if ref := node.get("$ref"):
        return st.deferred(lambda: _build(_resolve(ref, root), root, names))
    if "const" in node:
        return st.just(node["const"])
    if enum := node.get("enum"):
        return st.sampled_from(enum)
    if branches := node.get("anyOf") or node.get("oneOf"):
        if "type" in node or "properties" in node:
            # A *constraint* rather than a union: the node types itself and the
            # branches only add `required`/`minItems` on top (``Imports`` and
            # ``Exports``, which demand at least one non-empty group). Building
            # a bare branch here drew from a node with no `type` at all, which
            # fell through to `st.none()` and made every generated imports
            # document schema-invalid.
            return st.one_of([_build(_merged(node, branch), root, names) for branch in branches])
        return st.one_of([_build(branch, root, names) for branch in branches])

    kind = node.get("type")
    if kind is None:
        # A field the export left unconstrained (``seeds``). Anything at all
        # validates, so the interesting draw is the one an author writes.
        return st.none()
    if kind == "object":
        return _objects(node, root, names)
    if kind == "array":
        return st.lists(
            _build(node.get("items", {}), root, names),
            min_size=node.get("minItems", 0),
            max_size=_MAX_SIZE,
        )
    if kind == "string":
        return _strings(node, names)
    if kind == "integer":
        return st.integers(min_value=node.get("minimum", 0), max_value=node.get("maximum", 8))
    if kind == "number":
        return st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)
    if kind == "boolean":
        return st.booleans()
    if kind == "null":
        return st.none()
    raise NotImplementedError(f"schema type {kind!r} is outside the exported subset")


def _merged(node: dict[str, Any], branch: dict[str, Any]) -> dict[str, Any]:
    """``node`` with one ``anyOf`` branch folded in, the branch winning.

    Shallow per-property, which is all the export needs: a branch narrows a
    property the node already declares (``minItems: 1`` over an array that is
    typed above) and adds it to ``required``.
    """
    properties = dict(node.get("properties", {}))
    for key, narrowed in branch.get("properties", {}).items():
        properties[key] = {**properties.get(key, {}), **narrowed}
    merged = {key: value for key, value in node.items() if key not in ("anyOf", "oneOf")}
    return {
        **merged,
        "properties": properties,
        "required": sorted({*node.get("required", ()), *branch.get("required", ())}),
    }


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise NotImplementedError(f"$ref {ref!r} is outside the exported subset")
    definition: dict[str, Any] = root["$defs"][ref.removeprefix(prefix)]
    return definition


def _objects(
    node: dict[str, Any], root: dict[str, Any], names: tuple[str, ...]
) -> st.SearchStrategy[Any]:
    """Objects, in the three shapes the export uses.

    ``properties`` with ``required`` is the model case; ``patternProperties``
    and ``additionalProperties``-as-schema are the two open-keyed maps
    (``entities``, ``fields``), whose keys come from :data:`NAMES` so that the
    names other parts of the document spell can find them.
    """
    if properties := node.get("properties"):
        required = set(node.get("required", ()))
        return st.fixed_dictionaries(
            {
                key: _build(value, root, names)
                for key, value in properties.items()
                if key in required
            },
            optional={
                key: _build(value, root, names)
                for key, value in properties.items()
                if key not in required
            },
        )

    values = node.get("additionalProperties")
    if patterned := node.get("patternProperties"):
        # One pattern per open map in every kind bloomery exports; the pattern
        # itself is not applied to the drawn key, because NAMES already
        # satisfies the identifier patterns and the mismatch when it does not
        # is a divergence worth generating rather than hiding.
        values = next(iter(patterned.values()))
    if not isinstance(values, dict):
        return st.just({})
    return st.dictionaries(
        st.sampled_from(names), _build(values, root, names), min_size=1, max_size=_MAX_SIZE
    )


def _strings(node: dict[str, Any], names: tuple[str, ...]) -> st.SearchStrategy[str]:
    """Strings, pooled where they name something and free where they do not.

    A ``pattern`` that :data:`NAMES` satisfies (every identifier pattern in the
    export) draws from the pool; one it does not (``type``'s closed spelling
    list, the numeric-string bounds) goes through ``from_regex``, which is the
    only way to hit ``decimal(9, 2)`` at all.
    """
    pattern = node.get("pattern")
    if pattern is None:
        return st.sampled_from(names)
    compiled = re.compile(pattern)
    pooled = [name for name in names if compiled.fullmatch(name)]
    if pooled:
        return st.sampled_from(pooled)
    return st.from_regex(pattern, fullmatch=True)
