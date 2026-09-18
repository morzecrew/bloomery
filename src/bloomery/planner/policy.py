"""``RowPolicy`` — the row-level scoping value object (S-0028/D-7,
S-0030/D-9, vocabulary per S-0032/D-11).

A policy is a *typed filter* — dimension, operator, value — not a predicate
string and not an identity, session, or security context: deciding whose
policy applies is upstream work this package must not know about (hard
invariant #3). The planner takes the value as a parameter, resolves its
dimension against the covering mart like any other filter, renders it
through the exact same literal-escaping pipeline
(:mod:`bloomery.planner.filters`), and prepends it to the user filters —
never string-appended, never templated with raw input. The mandatory
``test_row_policy_survives_every_path`` suite asserts, on the parsed AST,
that the rendered predicate reaches every scan of the mart relation
(S-0030/what-is-superseded-and-the-boundary-that-makes-it-reversible (§5.9d)).

Migration note (S-0032/D-11): ``as_filter()`` renamed to ``as_clause()``
and the operator space narrowed with :class:`~bloomery.planner.request.Op` —
a ``between``/``contains`` policy has no post-migration form. A policy stays
a *single* predicate: callers with range policies compose the range into the
request filters instead, or declare a gte-only/lte-only policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from bloomery.planner.request import Op, Predicate, Scalar

# ----------------------- #

__all__ = [
    "RowPolicy",
]


@dataclass(frozen=True, slots=True)
class RowPolicy:
    """One row-level scoping filter: ``dimension op value``.

    ``value`` may be a single scalar or a tuple of scalars for the
    multi-value operators (``in``, ``not_in``, ``like``, ``ilike``).
    Construction validates the same structural rules as :class:`Predicate` —
    a malformed policy fails immediately, never at plan time.
    """

    dimension: str
    op: Op
    value: Scalar | tuple[Scalar, ...]

    # ....................... #

    def __post_init__(self) -> None:
        self.as_clause()  # structural validation rides Predicate's

    # ....................... #

    def as_clause(self) -> Predicate:
        """The policy as the :class:`Predicate` the filter pipeline renders
        (S-0032/D-11 — renames the pre-vocabulary ``as_filter``)."""
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        return Predicate(dimension=self.dimension, op=self.op, values=values)
