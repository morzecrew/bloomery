"""Property tier for the grain model (RFC 0037 §6, D7).

Two invariants, over generated relationship graphs rather than over the
hand-built cases:

* **Nothing crosses a cardinality-expanding edge without a rule.** Every
  dependency the model admits has to be traceable to a declared relationship
  read in a direction D3 (`LOCKED`) permits. That is the property the whole
  sequence's value rests on: the strength of any proof RFC 0039 or RFC 0040
  builds is exactly the weakest fact admitted here, and a graph shape nobody
  wrote a case for is where a wrong admission would hide.
* **The walk does not see authored order.** ``ProjectIR`` promises sorted
  collections, and the closure sorts its own output — so permuting the input
  must change nothing at all, including the derivations.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bloomery.ir import Cardinality, ProjectIR
from bloomery.semantic import ColumnRef, DependencyBasis, closure, dependencies, grain_of
from support.grain_model import entity, relationship

pytestmark = pytest.mark.property

ENTITIES = ("alpha", "beta", "gamma", "delta")


def _entity(name: str):
    """Every entity carries a foreign-key column for every other one, so any
    generated pair of names has a ``via`` to join on."""

    return entity(
        name,
        (f"{name}_id",),
        (f"{name}_id", f"{name}_value", *(f"{other}_id" for other in ENTITIES if other != name)),
    )


edges = st.lists(
    st.tuples(
        st.sampled_from(ENTITIES),
        st.sampled_from(ENTITIES),
        st.sampled_from(list(Cardinality)),
    ).filter(lambda triple: triple[0] != triple[1]),
    min_size=1,
    max_size=6,
)


def _project(chosen: list[tuple[str, str, Cardinality]]) -> ProjectIR:
    return ProjectIR(
        entities=tuple(_entity(name) for name in ENTITIES),
        relationships=tuple(
            relationship(
                f"r{index}", left, right, cardinality, ((f"{right}_id", f"{right}_id"),)
            )
            for index, (left, right, cardinality) in enumerate(chosen)
        ),
    )


@settings(max_examples=100, deadline=None)
@given(chosen=edges)
def test_no_dependency_crosses_an_edge_in_a_direction_the_rules_do_not_admit(
    chosen: list[tuple[str, str, Cardinality]],
) -> None:
    project = _project(chosen)
    by_name = {rel.name: rel for rel in project.relationships}

    for dependency in dependencies(project).dependencies:
        if dependency.basis is DependencyBasis.ENTITY_KEY:
            assert dependency.via is None
            assert dependency.determinant.determinants[0].entity == dependency.dependent.entity
            continue

        rel = by_name[dependency.via]
        assert dependency.join
        # Which way this dependency reads the declared relationship.
        declared = dependency.join[0][0].entity == rel.from_entity
        reading, target = (
            (rel.from_entity, rel.to_entity) if declared else (rel.to_entity, rel.from_entity)
        )

        # The hop is the relationship's own columns, stated determinant-side
        # first — not merely *a* pair of columns on the right two entities.
        # Everything downstream compares routes on this, so a join that does
        # not match its relationship is an ambiguity check reading fiction.
        assert dependency.join == tuple(
            sorted(
                (ColumnRef(reading, b if not declared else a), ColumnRef(target, a if not declared else b))
                for a, b in rel.via
            )
        )
        assert dependency.dependent.entity == target
        assert dependency.determinant.determinants[0].entity == reading

        if rel.cardinality is Cardinality.ONE_TO_MANY:
            # Admitted inversely only — where it *is* a many_to_one.
            assert not declared
        elif rel.cardinality is Cardinality.MANY_TO_ONE:
            assert declared
        else:
            assert dependency.basis is DependencyBasis.ONE_TO_ONE


@settings(max_examples=50, deadline=None)
@given(chosen=edges, order=st.permutations(range(6)))
def test_authored_order_reaches_neither_the_dependencies_nor_the_closure(
    chosen: list[tuple[str, str, Cardinality]], order: list[int]
) -> None:
    baseline = _project(chosen)
    positions = [index for index in order if index < len(baseline.relationships)]
    permuted = ProjectIR(
        entities=tuple(reversed(baseline.entities)),
        relationships=tuple(baseline.relationships[index] for index in positions),
    )

    assert dependencies(permuted) == dependencies(baseline)
    for name in ENTITIES:
        grain = grain_of(name, (f"{name}_id",))
        assert closure(grain, dependencies(permuted)) == closure(grain, dependencies(baseline))
