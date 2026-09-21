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

Scoped to the single-document kinds (S-0010/D-6's pooled-name problem is a
later phase), but nothing here is entity-model specific.
"""

from __future__ import annotations

import re
from typing import Any

from hypothesis import strategies as st

__all__ = ["NAMES", "from_spec_schema"]

#: The shared name pool. Small on purpose: these are the only strings that ever
#: land in an identifier-shaped position, so a ``key:`` entry, a ``fields:``
#: key, a relationship endpoint and a ``via`` pair all draw from the same three
#: names and agree often enough for documents to reach past the parser. Widen
#: it and the reach fraction falls off a cliff.
NAMES = ("a", "b", "c")

#: Upper bound on every generated array and open-keyed object. The pipeline
#: runs per example, so breadth is paid for on every one of them; three is
#: enough for a duplicate, a cycle, or a dangling reference to appear.
_MAX_SIZE = 3

_NAME_KEYS = frozenset({"key", "from", "to", "entity", "relationship", "column", "name"})


def from_spec_schema(schema: dict[str, Any]) -> st.SearchStrategy[dict[str, Any]]:
    """A strategy over documents the exported ``schema`` accepts.

    Not every draw validates — ``patternProperties`` without an
    ``additionalProperties`` sibling admits keys no pattern describes, and the
    strategy generates those too rather than pretending the export is closed
    where it is not. Callers filter with the schema itself.
    """
    return _build(schema, schema).map(dict)


def _build(node: dict[str, Any], root: dict[str, Any]) -> st.SearchStrategy[Any]:
    """The recursive core: one strategy per schema node, ``root`` for ``$ref``."""
    if ref := node.get("$ref"):
        return st.deferred(lambda: _build(_resolve(ref, root), root))
    if "const" in node:
        return st.just(node["const"])
    if enum := node.get("enum"):
        return st.sampled_from(enum)
    if branches := node.get("anyOf") or node.get("oneOf"):
        return st.one_of([_build(branch, root) for branch in branches])

    kind = node.get("type")
    if kind is None:
        # A field the export left unconstrained (``seeds``). Anything at all
        # validates, so the interesting draw is the one an author writes.
        return st.none()
    if kind == "object":
        return _objects(node, root)
    if kind == "array":
        return st.lists(
            _build(node.get("items", {}), root),
            min_size=node.get("minItems", 0),
            max_size=_MAX_SIZE,
        )
    if kind == "string":
        return _strings(node)
    if kind == "integer":
        return st.integers(min_value=node.get("minimum", 0), max_value=node.get("maximum", 8))
    if kind == "number":
        return st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)
    if kind == "boolean":
        return st.booleans()
    if kind == "null":
        return st.none()
    raise NotImplementedError(f"schema type {kind!r} is outside the exported subset")


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise NotImplementedError(f"$ref {ref!r} is outside the exported subset")
    definition: dict[str, Any] = root["$defs"][ref.removeprefix(prefix)]
    return definition


def _objects(node: dict[str, Any], root: dict[str, Any]) -> st.SearchStrategy[Any]:
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
                key: _build(value, root)
                for key, value in properties.items()
                if key in required
            },
            optional={
                key: _build(value, root)
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
        st.sampled_from(NAMES), _build(values, root), min_size=1, max_size=_MAX_SIZE
    )


def _strings(node: dict[str, Any]) -> st.SearchStrategy[str]:
    """Strings, pooled where they name something and free where they do not.

    A ``pattern`` that :data:`NAMES` satisfies (every identifier pattern in the
    export) draws from the pool; one it does not (``type``'s closed spelling
    list, the numeric-string bounds) goes through ``from_regex``, which is the
    only way to hit ``decimal(9, 2)`` at all.
    """
    pattern = node.get("pattern")
    if pattern is None:
        return st.sampled_from(NAMES)
    compiled = re.compile(pattern)
    pooled = [name for name in NAMES if compiled.fullmatch(name)]
    if pooled:
        return st.sampled_from(pooled)
    return st.from_regex(pattern, fullmatch=True)
