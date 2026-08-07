"""``RowPolicy`` — the row-level scoping value object (RFC 0011 D7,
RFC 0013 D9).

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
(RFC 0013 §5.9d).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.planner.request import FilterExpr

if TYPE_CHECKING:
    from bloomery.planner.request import FilterOp, JsonScalar

__all__ = [
    "RowPolicy",
]


@dataclass(frozen=True, slots=True)
class RowPolicy:
    """One row-level scoping filter: ``dimension op value``.

    ``value`` may be a single scalar or a tuple of scalars for the
    multi-value operators (``in``, ``not_in``, ``between``). Construction
    validates the same structural rules as :class:`FilterExpr` — a malformed
    policy fails immediately, never at plan time.
    """

    dimension: str
    op: FilterOp
    value: JsonScalar | tuple[JsonScalar, ...]

    def __post_init__(self) -> None:
        self.as_filter()  # structural validation rides FilterExpr's

    def as_filter(self) -> FilterExpr:
        """The policy as the :class:`FilterExpr` the filter pipeline renders."""
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        return FilterExpr(dimension=self.dimension, op=self.op, values=values)
