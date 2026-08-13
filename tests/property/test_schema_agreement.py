"""Schema/parser agreement, measured rather than assumed (RFC 0020 D10, §6).

Two validators over one grammar drift. The drift is invisible until it reaches
a user, and then it reads as bloomery being arbitrary: a proposal loop emits a
document the schema accepted, the parser refuses it, and nothing in either
artifact explains why. So the gap is *measured* here.

- **Every fixture validates.** The corpus is the documentation example set
  (RFC 0009), so a schema that refuses one of them is refusing the spelling the
  docs teach. This direction is total: no exceptions.
- **What the parser refuses, the schema should too** — for the mutation
  classes JSON Schema can express: an unknown key, a wrong scalar type, an
  out-of-enum value.
- **The converse is false on purpose** and is not asserted anywhere: parse
  validates shape and grammar only (RFC 0002 D4), so the schema is legitimately
  stricter wherever it carries a set the parser checks later. The schema is a
  pre-filter; the parser stays the authority (D10).

Where the two genuinely disagree — a float ``tolerance``, a free-string metric
``agg`` — the divergence is *named* at the bottom of this module rather than
tolerated silently.

Hypothesis drives the mutation direction over the whole corpus so the classes
are exercised against every document shape rather than one hand-picked pair.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from bloomery import SpecKind, all_spec_schemas, load_catalog, load_project
from bloomery.spec import Mapping
from bloomery.errors import SpecParseError

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.property

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: Version key → the kind it identifies. The catalog is loaded separately
#: (RFC 0002 D8) but is a spec kind like any other for schema purposes.
KIND_BY_VERSION_KEY = {
    "catalog_version": SpecKind.CATALOG,
    "spec_version": SpecKind.ENTITY_MODEL,
    "mapping_version": SpecKind.MAPPING,
    "marts_version": SpecKind.MARTS,
    "metrics_version": SpecKind.METRICS,
    "steps_version": SpecKind.STEPS,
}

VALIDATORS = {kind: Draft202012Validator(schema) for kind, schema in all_spec_schemas().items()}


def _documents() -> list[tuple[str, SpecKind, dict[str, Any]]]:
    """Every fixture document, paired with the kind its version key names."""
    found: list[tuple[str, SpecKind, dict[str, Any]]] = []
    for path in sorted(FIXTURES.rglob("*.yaml")):
        data: object = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):  # pragma: no cover — every fixture is a mapping
            continue
        document: dict[str, Any] = data
        kinds = [KIND_BY_VERSION_KEY[key] for key in document if key in KIND_BY_VERSION_KEY]
        assert len(kinds) == 1, f"{path} names {len(kinds)} spec kinds"
        found.append((path.relative_to(FIXTURES).as_posix(), kinds[0], document))
    return found


DOCUMENTS = _documents()


def test_the_corpus_is_not_empty() -> None:
    """Both properties below iterate the corpus, so an empty one would make
    them pass by finding nothing."""
    assert len(DOCUMENTS) > 20
    assert {kind for _name, kind, _doc in DOCUMENTS} == set(SpecKind)


@pytest.mark.parametrize(
    ("name", "kind", "document"), DOCUMENTS, ids=[name for name, _kind, _doc in DOCUMENTS]
)
def test_every_fixture_validates_against_its_schema(
    name: str, kind: SpecKind, document: dict[str, Any]
) -> None:
    errors = sorted(VALIDATORS[kind].iter_errors(document), key=str)
    assert not errors, f"{name}: " + "; ".join(
        f"{list(error.absolute_path)}: {error.message}" for error in errors[:3]
    )


# ....................... #
# The other direction: what the parser refuses, the schema should refuse too.
#
# **One-directional, deliberately.** The converse — schema refuses ⟹ parser
# refuses — is false by design and must not be asserted: parse validates shape
# and grammar only (RFC 0002 D4), so an invented transform name reaches the
# typecheck stage, while the schema carries the whitelist (D2) and refuses it
# at the door. That is the export earning its keep, not a disagreement. Each
# mutation therefore ``assume``s the parser refused before checking the schema
# did too; Hypothesis fails the run if that filter eats too many examples, so
# the properties cannot pass by discarding everything.

def _parses(kind: SpecKind, document: dict[str, Any]) -> bool:
    """Whether the parser accepts this document *as a document of its kind*.

    Cardinality complaints are not shape failures: ``load_project`` wants
    exactly one entity model, and feeding it a lone mapping fails for a reason
    the schema neither knows nor should. So a single document is parsed
    alongside a minimal entity model, and the catalog through its own loader.
    """
    text = yaml.safe_dump(document)
    try:
        if kind is SpecKind.CATALOG:
            load_catalog(text)
        elif kind is SpecKind.ENTITY_MODEL:
            load_project({"doc": text})
        else:
            load_project({"doc": text, "entity_model": _MINIMAL_ENTITY_MODEL})
    except SpecParseError:
        return False
    return True


_MINIMAL_ENTITY_MODEL = """\
spec_version: 1
entities:
  e:
    grain: one row per e
    key: [k]
    fields:
      k: {type: string, required: true}
"""


def _validates(kind: SpecKind, document: dict[str, Any]) -> bool:
    return VALIDATORS[kind].is_valid(document)


def _scalar_paths(node: object, prefix: tuple[str | int, ...] = ()) -> Iterator[tuple[object, ...]]:
    """Every path to a scalar leaf, for the mutation strategies to target."""
    if isinstance(node, dict):
        entries: dict[str, object] = node
        for key, value in entries.items():
            yield from _scalar_paths(value, (*prefix, key))
    elif isinstance(node, list):
        entries_list: list[object] = node
        for index, value in enumerate(entries_list):
            yield from _scalar_paths(value, (*prefix, index))
    elif prefix:
        yield prefix


def _at(document: object, path: tuple[object, ...]) -> object:
    node = document
    for step in path:
        node = node[step]  # type: ignore[index]
    return node


def _replaced(document: object, path: tuple[object, ...], value: object) -> object:
    """``document`` with ``path`` set to ``value``, copied rather than mutated."""
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(document, dict):
        entries: dict[str, object] = dict(document)
        entries[str(head)] = _replaced(entries[str(head)], rest, value)
        return entries
    entries_list: list[object] = list(document)  # type: ignore[call-overload]
    index = int(str(head))
    entries_list[index] = _replaced(entries_list[index], rest, value)
    return entries_list


CORPUS = st.sampled_from(DOCUMENTS)

#: Slow by construction — each example runs a YAML round-trip, a full parse and
#: a schema validation over a real fixture. The count is what a property tier
#: can afford per run, not a claim that 40 is exhaustive.
SETTINGS = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@given(entry=CORPUS, key=st.text(min_size=1, max_size=8, alphabet="abcdefghij"))
@SETTINGS
def test_an_unknown_top_level_key_is_refused_by_both(
    entry: tuple[str, SpecKind, dict[str, Any]], key: str
) -> None:
    """``extra="forbid"`` on the model, ``additionalProperties: false`` on the
    schema — the one place the two are guaranteed to agree, and the mutation a
    machine author hits most (an invented key)."""
    _name, kind, document = entry
    assume(key not in document)
    mutated = {**document, key: "x"}
    assert not _parses(kind, mutated)
    assert not _validates(kind, mutated)


@given(entry=CORPUS, seed=st.integers(min_value=0, max_value=2**16))
@SETTINGS
def test_a_string_replaced_by_a_mapping_is_refused_by_both(
    entry: tuple[str, SpecKind, dict[str, Any]], seed: int
) -> None:
    """Wrong-type mutation. A mapping where a scalar belongs is expressible in
    JSON Schema for every field bloomery declares, so this direction must
    hold — and it is the class a generator produces by nesting one level too
    deep."""
    _name, kind, document = entry
    paths = [path for path in _scalar_paths(document) if isinstance(_at(document, path), str)]
    assume(paths)
    path = paths[seed % len(paths)]
    mutated = _replaced(document, path, {"unexpected": "mapping"})
    assert isinstance(mutated, dict)
    # A single-key mapping *is* an authored transform step, so replacing a
    # chain entry produces a well-formed document naming an unknown transform —
    # accepted at parse, refused at typecheck (RFC 0002 D4).
    assume(not _parses(kind, mutated))
    assert not _validates(kind, mutated), path


@given(entry=CORPUS, seed=st.integers(min_value=0, max_value=2**16))
@SETTINGS
def test_an_out_of_enum_value_is_refused_by_both(
    entry: tuple[str, SpecKind, dict[str, Any]], seed: int
) -> None:
    """The class RFC 0020 D2 exists for: a value outside a closed set. If the
    schema left the set open this passes the schema and fails the parser, which
    is exactly the round-trip a constrained decoder is supposed to save."""
    _name, kind, document = entry
    paths = [
        path
        for path in _scalar_paths(document)
        if isinstance(_at(document, path), str) and str(path[-1]) in _CLOSED_KEYS
    ]
    assume(paths)
    path = paths[seed % len(paths)]
    mutated = _replaced(document, path, "not_a_member_of_this_set")
    assert isinstance(mutated, dict)
    assert not _parses(kind, mutated), path
    assert not _validates(kind, mutated), path


#: Property names whose values are closed sets in every kind that declares
#: them. Named rather than discovered from the schema: discovering them *from
#: the schema* would make the test agree with whatever the schema says, which
#: is the one thing it must not do.
#:
#: ``agg`` is deliberately absent — see
#: :func:`test_agg_is_closed_on_a_mart_and_free_on_a_metric`.
_CLOSED_KEYS = frozenset(
    {"scd", "cardinality", "materialization", "on_fail", "rule", "additivity", "unit"}
)


# ....................... #
# Recorded divergences (D10): where the two validators genuinely disagree.


def test_the_schema_accepts_a_float_tolerance_the_parser_refuses() -> None:
    """The one measured gap, recorded rather than tolerated silently.

    ``Reconcile.tolerance`` is a ``Decimal`` with a ``mode="before"`` validator
    refusing Python ``float`` (RFC 0016: an unquoted YAML number would reach
    emission as a binary approximation of what the author wrote). JSON Schema
    has one numeric type and cannot tell ``0.01`` from ``1``, and narrowing the
    schema to strings would be *wrong* — ``tolerance: 0`` is an int and parses
    fine. So the schema is the looser of the two here, which is the safe
    direction for a pre-filter: it never rejects a document bloomery accepts.
    """
    document = {
        "spec_version": 1,
        "entities": {
            "e": {"grain": "g", "key": ["k"], "fields": {"k": {"type": "string", "required": True}}}
        },
        "reconcile": [{"name": "r", "left": "a", "right": "b", "tolerance": 0.01, "on_fail": "flag"}],
    }
    assert _validates(SpecKind.ENTITY_MODEL, document)
    assert not _parses(SpecKind.ENTITY_MODEL, document)
    # The int spelling parses, which is why the schema cannot simply forbid
    # numbers here.
    assert _parses(SpecKind.ENTITY_MODEL, {**document, "reconcile": [
        {"name": "r", "left": "a", "right": "b", "tolerance": 0, "on_fail": "flag"}
    ]})


def test_the_schema_accepts_every_authored_transform_spelling() -> None:
    """The divergence RFC 0020 §5.1 had to repair rather than record.

    ``TransformStep`` normalizes three authored spellings into one model, and
    Pydantic documents only the model. Left alone, the schema would refuse
    ``transform: [to_string]`` — the form every fixture, doc page and the
    quickstart use.
    """
    for chain in ([{"to_string": []}], ["to_string"], [{"name": "to_string", "args": []}]):
        document = {
            "mapping_version": 1,
            "source": "s",
            "target": "e",
            "key": {"k": {"from": "$.id", "transform": chain}},
        }
        assert _validates(SpecKind.MAPPING, document), chain
        assert _parses(SpecKind.MAPPING, document), chain


def test_agg_is_closed_on_a_mart_and_free_on_a_metric() -> None:
    """A closed set that is closed in one kind and open in another.

    ``Mart.measures``' aggregate is ``Literal["avg", "count", "max", "min",
    "sum"]``; ``Metric.agg`` is a bare ``str | None``. The export mirrors the
    models faithfully, so RFC 0020 D2's "every closed set appears as an enum"
    is met *where the model closes the set* and cannot be met where it does
    not — narrowing ``Metric.agg`` here would be the schema disagreeing with
    the parser, which is the failure this module measures.

    An out-of-vocabulary ``agg`` on a metric is accepted at parse and is inert
    downstream: the MetricFlow manifest for ``agg: count`` and
    ``agg: bogus_agg`` is byte-identical, so nothing wrong is emitted and
    nothing says the key was ignored. Narrowing the model is an RFC 0002
    change, not one this wave may make silently; pinned here so the asymmetry
    is a recorded measurement rather than a hole nobody looked into.
    """
    metric_document = {
        "metrics_version": 1,
        "metrics": {"m": {"grain": "e", "additivity": "additive", "agg": "bogus", "expr": "k"}},
    }
    assert _validates(SpecKind.METRICS, metric_document)
    assert _parses(SpecKind.METRICS, metric_document)

    mart_document = {
        "marts_version": 1,
        "marts": {"m": {"grain": "e", "base": "e", "measures": {"k": {"agg": "bogus"}}}},
    }
    assert not _validates(SpecKind.MARTS, mart_document)
    assert not _parses(SpecKind.MARTS, mart_document)


@pytest.mark.parametrize(
    "chain",
    [
        pytest.param([{}], id="neither-name-nor-step"),
        pytest.param([{"name": "to_string", "step": "extract_domain@1"}], id="both"),
    ],
)
def test_a_transform_step_that_is_neither_or_both_is_refused_by_both(
    chain: list[dict[str, Any]],
) -> None:
    """The shape the mutation strategies structurally cannot reach.

    ``TransformStep``'s fields all carry defaults, so Pydantic writes nothing
    required and the generated object accepted an empty step and a step
    claiming to be a transform *and* a step reference — both of which the model
    validator refuses (RFC 0017 D51). Neither is a mutation of a real fixture:
    the strategies above replace and add, and this is an *absence*. Review
    found it; this is what would find it again.
    """
    document = {
        "mapping_version": 1,
        "source": "s",
        "target": "e",
        "key": {"k": {"from": "$.id", "transform": chain}},
    }
    assert not _parses(SpecKind.MAPPING, document), chain
    assert not _validates(SpecKind.MAPPING, document), chain


def test_the_schema_refuses_a_boolean_transform_argument_the_parser_coerces() -> None:
    """One measured divergence, of the ``tolerance`` shape and from the other
    direction (RFC 0020 D10).

    ``TransformStep.args`` is ``str | int``, and Pydantic's lax mode coerces a
    bool into it: ``{round: [true]}`` parses and arrives as the **integer 1**,
    while JSON Schema types a boolean as itself and refuses it.

    An integral float is *not* a divergence, which is worth pinning because it
    looks like one: JSON Schema's ``integer`` accepts ``1.0`` (a number with
    zero fractional part), exactly as Pydantic does, and both refuse ``1.5``.

    Stricter-schema is the safe direction here — a constrained generator simply
    never writes ``true`` where an argument belongs. Narrowing ``args`` to
    reject it is a change to the *spec language*, an RFC 0002/0004 question,
    not one this wave settles by tightening an export.
    """
    for spelling in (True, False):
        document = {
            "mapping_version": 1,
            "source": "s",
            "target": "e",
            "key": {"k": {"from": "$.id", "transform": [{"round": [spelling]}]}},
        }
        assert _parses(SpecKind.MAPPING, document), spelling
        assert not _validates(SpecKind.MAPPING, document), spelling

    for agreed in (1, 1.0):
        document = {
            "mapping_version": 1,
            "source": "s",
            "target": "e",
            "key": {"k": {"from": "$.id", "transform": [{"round": [agreed]}]}},
        }
        assert _parses(SpecKind.MAPPING, document), agreed
        assert _validates(SpecKind.MAPPING, document), agreed

    parsed = Mapping.model_validate(
        {
            "mapping_version": 1,
            "source": "s",
            "target": "e",
            "key": {"k": {"from": "$.id", "transform": [{"round": [True]}]}},
        }
    )
    # The sharper half, which the schema cannot express and the parser does not
    # announce: `true` does not stay a bool, it becomes 1.
    assert parsed.key["k"].transform[0].args == (1,)


def test_the_schema_is_stricter_about_an_explicitly_null_step() -> None:
    """The over-strictness the one-of encoding introduces, measured not hidden.

    JSON Schema's ``required`` asks whether a *key* is present; the model asks
    whether ``step`` has a value. So ``{name: to_string, step: null}`` parses
    and the schema refuses it. Nothing documents that spelling and no fixture
    writes it, so the encoding stays the readable one — but the gap is a fact
    rather than an assumption.
    """
    document = {
        "mapping_version": 1,
        "source": "s",
        "target": "e",
        "key": {"k": {"from": "$.id", "transform": [{"name": "to_string", "step": None}]}},
    }
    assert _parses(SpecKind.MAPPING, document)
    assert not _validates(SpecKind.MAPPING, document)


def test_an_invented_transform_is_refused_by_the_schema() -> None:
    """RFC 0020 D2's payoff. Transform-name existence is a *typecheck*-stage
    refusal (RFC 0002 D4), so the parser accepts this document and only a later
    stage refuses it. The schema refuses it up front, which is what makes a
    constrained decoder unable to write it at all."""
    document = {
        "mapping_version": 1,
        "source": "s",
        "target": "e",
        "key": {"k": {"from": "$.id", "transform": ["to_striiing"]}},
    }
    assert not _validates(SpecKind.MAPPING, document)
    assert _parses(SpecKind.MAPPING, document)
