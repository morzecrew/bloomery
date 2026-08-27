"""The edge-label vocabulary is closed, and guarded from both sides
(RFC 0031 §5.3, §6, D6; ``logs/T-0005.md`` D-021).

``_EDGE_SHAPES`` is the closed set of ``(label family, src kind, dst kind)``
triples the two builders in ``resolve/graph.py`` can emit. Two guards hold it
true, and **neither alone is enough**:

- the **corpus** guard compiles every fixture and asserts what it emits is a
  *subset*. It cannot see a shape no fixture exercises, which is exactly how
  RFC 0031's first draft lost both ``step → step`` forms and the whole
  ``step:<ref@version>`` label.
- the **source** guard reads every ``Edge(...)`` construction in that module
  and asserts the same subset relation. It sees shapes nothing exercises,
  which is the half the corpus cannot do.

Subset rather than equality, in both directions: a triple in the constant that
no builder reaches would be a stale row worth catching, but the corpus reaching
fewer than the builders is the normal, permanent state of this tree.
"""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from pathlib import Path

import pytest

from bloomery import load_catalog, load_project
from bloomery.cli import io
from bloomery.resolve import graph as graph_module
from bloomery.resolve.graph import (
    _EDGE_SHAPES,  # pyright: ignore[reportPrivateUsage]
    NodeKind,
    build_graph,
)
from bloomery.resolve.metrics import effective_metrics
from support.compiling import spec_fixture_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures"

#: The node constructors in ``resolve/graph.py``, and the kind each returns.
#: Read from the module's own functions rather than guessed, so a renamed
#: constructor fails here instead of silently shrinking the walk's coverage.
CONSTRUCTOR_KINDS = {
    "source_column_node": NodeKind.SOURCE_COLUMN,
    "entity_field_node": NodeKind.ENTITY_FIELD,
    "canonical_field_node": NodeKind.CANONICAL_FIELD,
    "metric_node": NodeKind.METRIC,
    "step_node": NodeKind.STEP,
}


def test_every_named_constructor_exists_and_returns_its_kind() -> None:
    """The map above is a claim about the module, so it is checked.

    Without this the source guard could quietly stop resolving a renamed
    constructor and report a smaller, still-passing set.
    """
    for name, kind in CONSTRUCTOR_KINDS.items():
        builder = getattr(graph_module, name)
        signature = inspect.signature(builder)
        arguments = ["x"] * len(signature.parameters)
        assert builder(*arguments).kind is kind


# ....................... #
# Guard one: the corpus is a subset


def loadable_projects() -> list[tuple[str, object, object]]:
    """Every spec fixture, loaded — with **no exception handling**.

    An earlier version swallowed load failures and moved on, guarded by a
    "at least 20 fixtures" floor. That floor cannot tell twenty-two from
    twenty, so a resolver regression would have shrunk this sweep silently and
    left the guard green over the survivors.
    """
    projects = []
    for name in spec_fixture_names():
        sources, catalog_text = io.read_spec_directory(str(FIXTURES / name))
        catalog = load_catalog(catalog_text) if catalog_text else None
        projects.append((name, load_project(sources), catalog))
    return projects


def test_the_corpus_emits_only_declared_shapes() -> None:
    projects = loadable_projects()
    assert [name for name, _p, _c in projects] == list(spec_fixture_names())

    emitted: set[tuple[str, NodeKind, NodeKind]] = set()
    for _name, project, catalog in projects:
        built = build_graph(project, catalog, effective_metrics(project, catalog))  # type: ignore[arg-type]
        emitted |= {
            (edge.label.split(":")[0], edge.src.kind, edge.dst.kind) for edge in built.edges
        }

    assert emitted <= _EDGE_SHAPES, f"undeclared shapes in the corpus: {emitted - _EDGE_SHAPES}"


def test_the_corpus_does_not_reach_every_declared_shape() -> None:
    """A control, and the reason the guard above is a subset rather than an
    equality.

    If this ever fails, the corpus has grown to cover everything and the
    subset relation could tighten — which would be good news, and is a
    deliberate decision rather than something to discover by a green run.
    """
    emitted: set[tuple[str, NodeKind, NodeKind]] = set()
    for _name, project, catalog in loadable_projects():
        built = build_graph(project, catalog, effective_metrics(project, catalog))  # type: ignore[arg-type]
        emitted |= {
            (edge.label.split(":")[0], edge.src.kind, edge.dst.kind) for edge in built.edges
        }
    unreached = _EDGE_SHAPES - emitted
    assert unreached, "the corpus now reaches every declared shape"
    assert unreached == {
        ("step", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        ("step_input", NodeKind.STEP, NodeKind.STEP),
    }


# ....................... #
# Guard two: the source is a subset — the half the corpus cannot see


class EdgeShapeReader(ast.NodeVisitor):
    """Every ``Edge(...)`` construction in one module, as shape triples.

    **This couples to the source's form**, not its behaviour: a ``label=``
    keyword whose value is a literal, an f-string or a name bound to one, and
    ``src=``/``dst=`` whose values are constructor calls or names bound to
    them. That is the price of seeing a shape no fixture exercises, and it is
    stated here so whoever refactors ``_step_edges`` and breaks this knows why.

    An unreadable construction is **reported, never skipped** — a guard that
    silently ignores what it cannot parse passes for the wrong reason.
    """

    def __init__(self) -> None:
        self.shapes: set[tuple[str, NodeKind, NodeKind]] = set()
        self.unreadable: list[str] = []
        self._bindings: dict[str, ast.expr] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        outer = self._bindings
        self._bindings = dict(outer)
        for statement in ast.walk(node):
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                if isinstance(target, ast.Name):
                    self._bindings[target.id] = statement.value
        self.generic_visit(node)
        self._bindings = outer

    def _kind(self, expression: ast.expr, depth: int = 0) -> NodeKind | None:
        if depth > 4:
            return None
        if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
            return CONSTRUCTOR_KINDS.get(expression.func.id)
        if isinstance(expression, ast.Name):
            bound = self._bindings.get(expression.id)
            return self._kind(bound, depth + 1) if bound is not None else None
        return None

    def _families(self, expression: ast.expr, depth: int = 0) -> list[str] | None:
        if depth > 4:
            return None
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            return [expression.value.split(":")[0]]
        if isinstance(expression, ast.JoinedStr):
            head = expression.values[0]
            if isinstance(head, ast.Constant) and isinstance(head.value, str):
                return [head.value.split(":")[0]]
            return None
        if isinstance(expression, ast.IfExp):
            body = self._families(expression.body, depth + 1)
            orelse = self._families(expression.orelse, depth + 1)
            return None if body is None or orelse is None else body + orelse
        if isinstance(expression, ast.Name):
            bound = self._bindings.get(expression.id)
            return self._families(bound, depth + 1) if bound is not None else None
        return None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id == "Edge":
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            where = f"line {node.lineno}"
            src = self._kind(keywords["src"]) if "src" in keywords else None
            dst = self._kind(keywords["dst"]) if "dst" in keywords else None
            families = self._families(keywords["label"]) if "label" in keywords else None
            if src is None or dst is None or families is None:
                self.unreadable.append(f"{where}: src={src} dst={dst} families={families}")
            else:
                self.shapes |= {(family, src, dst) for family in families}
        self.generic_visit(node)


def read_graph_module_shapes() -> EdgeShapeReader:
    source = Path(inspect.getsourcefile(graph_module) or "").read_text(encoding="utf-8")
    reader = EdgeShapeReader()
    reader.visit(ast.parse(source))
    return reader


def test_every_edge_construction_in_the_source_is_readable() -> None:
    """The guard's own precondition. An `Edge(...)` this cannot parse means the
    check below is narrower than it claims, so it fails rather than passing on
    a smaller set."""
    reader = read_graph_module_shapes()
    assert not reader.unreadable, f"unreadable Edge(...) constructions: {reader.unreadable}"


def test_the_source_builds_only_declared_shapes() -> None:
    """The half the corpus cannot do: a row added to a builder and not to
    ``_EDGE_SHAPES`` fails here even when no fixture reaches it."""
    reader = read_graph_module_shapes()

    assert reader.shapes, "no Edge(...) constructions found — the reader stopped working"
    assert reader.shapes <= _EDGE_SHAPES, (
        f"builders emit shapes the vocabulary does not declare: {reader.shapes - _EDGE_SHAPES}"
    )


def test_the_source_reaches_the_shapes_the_corpus_cannot() -> None:
    """The two entries a corpus-derived table lost, asserted present.

    This is the regression test for the *method*, not for a row: it fails if
    someone re-derives the vocabulary from fixtures.
    """
    reader = read_graph_module_shapes()

    assert ("step_input", NodeKind.STEP, NodeKind.STEP) in reader.shapes
    assert ("step", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD) in reader.shapes


def test_no_declared_shape_is_stale() -> None:
    """Every triple in the constant is reachable from some builder.

    The constant is hand-maintained, so it can drift the other way too — a row
    kept after the construction that produced it was deleted.
    """
    reader = read_graph_module_shapes()
    assert _EDGE_SHAPES <= reader.shapes, f"declared but unbuilt: {_EDGE_SHAPES - reader.shapes}"


# ....................... #
# The suffixes a family comparison cannot see


def test_recipe_suffixes_name_a_recipe_the_catalog_defines() -> None:
    checked = Counter[str]()
    for name, project, catalog in loadable_projects():
        if catalog is None:
            continue
        built = build_graph(project, catalog, effective_metrics(project, catalog))  # type: ignore[arg-type]
        declared = {
            recipe.id
            for field in catalog.canonical_fields.values()  # type: ignore[attr-defined]
            for recipe in field.recipes
        }
        for edge in built.edges:
            if edge.label.startswith("recipe:"):
                suffix = edge.label.split(":", 1)[1]
                assert suffix in declared, f"{name}: recipe {suffix!r} is not in the catalog"
                checked[name] += 1
    assert sum(checked.values()) > 0, "no recipe edge in the corpus — this guard proved nothing"


def test_step_suffixes_name_a_macro_with_a_ref_and_a_version() -> None:
    """The other half of §6's suffix rule.

    No fixture declares a `sql_macro` field, so the corpus proves nothing here —
    which is the point, and why the shape is asserted against a project built
    for it. The suffix is a `StepUse`, `ref@version`, and a bare ref would make
    the label ambiguous across two versions of one macro.
    """
    from bloomery import load_project  # noqa: PLC0415 — local to keep the module's imports about the corpus

    from tests.unit.test_resolve.test_edge_shapes_offcorpus import (  # noqa: PLC0415
        ENTITY_MODEL,
        MACRO_MAPPING,
    )

    project = load_project({"entity_model": ENTITY_MODEL, "mapping_c": MACRO_MAPPING})
    built = build_graph(project, None, ())

    suffixes = {
        edge.label.split(":", 1)[1] for edge in built.edges if edge.label.startswith("step:")
    }
    assert suffixes, "the macro project emitted no step: edge"
    for suffix in suffixes:
        ref, sep, version = suffix.partition("@")
        assert sep and ref and version, f"step suffix {suffix!r} is not ref@version"


def test_no_corpus_edge_carries_a_step_suffix() -> None:
    """The premise the test above rests on, asserted rather than assumed.

    If a fixture ever declares a macro field this becomes false, and the corpus
    guard should then be the one validating suffixes.
    """
    for _name, project, catalog in loadable_projects():
        built = build_graph(project, catalog, effective_metrics(project, catalog))  # type: ignore[arg-type]
        assert not [e for e in built.edges if e.label.startswith("step:")]

