"""The planner's response types (RFC 0011 §5.2, §5.6 — D2/D8):
:class:`ColumnDescriptor`, :class:`QueryPlan`, and the deterministic
:class:`Explanation` with its :class:`MeasureExplanation` entries.

``QueryPlan.columns`` is the self-describing envelope — the caller gets
typed metadata without knowing the row shape in advance; never return bare
rows without it. ``fingerprint`` is ``sha256(sql)`` — the caller's result
cache key; the planner never executes and never sees a connection.

The :class:`Explanation` is generated from the plan, never from an LLM
(RFC 0011 D8): every number ships with how it was computed, and ``render()``
output is locked by tests — change it deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bloomery.semantic import SemanticPlan
from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
    "BranchSource",
    "ColumnDescriptor",
    "Explanation",
    "MeasureExplanation",
    "QueryPlan",
]

type ColumnRole = Literal["dimension", "measure"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ColumnDescriptor:
    """One output column: what the caller asked for, and what the SQL returns.

    ``name`` is the caller's vocabulary — role-qualified for date-role
    dimensions at the effective grain (``ordered_month``), and never a
    MetricFlow dunder (RFC 0013 D7). ``sql_alias`` is the alias the emitted
    SQL actually projects, which for a dimension is entity-qualified and
    grain-suffixed: ``store`` comes back as ``order__store`` and
    ``ordered_month`` as ``order__ordered_day__month``. Measures agree on both.

    The two exist because they differ (RFC 0009 D24, closed by RFC 0018 D4).
    Binding a result set positionally works and always did; binding it by
    ``name`` silently found nothing, because no column in the SQL is called
    that. Bind by ``sql_alias``; render ``name``. :class:`Explanation`
    continues to speak ``name``, since an explanation is for a reader.

    **Constructed by keyword only.** ``sql_alias`` was inserted second rather
    than appended, which reads better and would silently misassign every field
    of a four-argument positional call — `name`, then the type into
    ``sql_alias``, the role into ``type``, the label into ``role``, with no
    error. Keyword-only makes that call fail immediately instead. Appending the
    field with a default was the alternative and is worse: the only available
    default is ``name``, which is the defect D4 exists to remove, restored
    silently for anyone who does not pass the argument.
    """

    name: str
    sql_alias: str
    type: LogicalType
    role: ColumnRole
    label: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class MeasureExplanation:
    """How one requested measure was computed: its expression, declared
    additivity, and the lowering note (RFC 0011 D5 vocabulary)."""

    name: str
    expr: str
    additivity: str
    note: str


# ....................... #


@dataclass(frozen=True, slots=True)
class BranchSource:
    """One branch of a composed plan: the relation it aggregated, and the
    grain it did so from (RFC 0041 D15)."""

    mart: str
    grain: str


# ....................... #


@dataclass(frozen=True, slots=True)
class Explanation:
    """The deterministic provenance record attached to every plan (D8)."""

    mart: str
    grain: str
    measures: tuple[MeasureExplanation, ...]
    filters: tuple[str, ...]
    policy_applied: bool
    #: Every branch a cross-mart request was answered from, sorted, or empty
    #: for the single-mart plans that are still the common case (RFC 0041
    #: D15). ``mart`` and ``grain`` above hold the first branch's, so a reader
    #: of the old two fields is told about one of several rather than
    #: something that is not true of any.
    branches: tuple[BranchSource, ...] = ()

    # ....................... #

    def render(self) -> str:
        """The human-readable provenance block (RFC 0011 §5.6 shape)."""
        lines = [", ".join(measure.name for measure in self.measures)]

        if self.branches:
            for branch in self.branches:
                lines.append(f"  branch:   {branch.mart} (grain: {branch.grain})")
        else:
            lines.append(f"  mart:     {self.mart} (grain: {self.grain})")

        for measure in self.measures:
            lines.append(f"  measure:  {measure.name} = {measure.expr}")
            lines.append(f"            [{measure.note}]")

        rendered_filters = "; ".join(self.filters) if self.filters else "(none)"
        lines.append(f"  filters:  {rendered_filters}")
        lines.append(f"  policy:   {'applied' if self.policy_applied else 'not applied'}")

        return "\n".join(lines)


# ....................... #


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """SQL text plus metadata — the planner's whole product (RFC 0011 D2).

    ``mart`` is the serving mart's logical name; ``warnings`` carries
    non-fatal notices (limit clamping, ignored ``time_grain``);
    ``fingerprint`` is the sha256 hex digest of ``sql``.
    """

    sql: str
    columns: tuple[ColumnDescriptor, ...]
    mart: str
    warnings: tuple[str, ...]
    explanation: Explanation
    fingerprint: str
    #: What bloomery decided to compute, before any target saw the request
    #: (RFC 0040). Beside the SQL rather than under or instead of it, which is
    #: D7 closed as "beside" at P1: `sql`, `columns` and `explanation` are
    #: shipped surfaces that every golden pins, and D5 makes P1 a
    #: re-expression with no capability change — bundling an output change into
    #: that phase would cost §8's parity suite its only reference point
    #: (logs/T-0021.md, D-118).
    #:
    #: Present for every request but one shape (RFC 0066 P1-P3). It was absent
    #: for four — a computed metric, a semi-additive measure, a cumulative one,
    #: and metrics restricted differently — and those now carry a plan.
    #:
    #: **Still optional, and RFC 0066 D1 wanted it required.** What blocks it is
    #: a `derived:` input carrying an `offset_window` or `offset_to_grain`:
    #: §5.2 says that shape composes from two same-mart branches differing in a
    #: filter, and it does not. MetricFlow builds it by joining to the *time
    #: spine* — `gold.dim_date` — at a shifted date, with a `FULL OUTER JOIN`,
    #: and neither the spine nor a shifted join key is anything this plan's
    #: nodes can state (logs/T-0037.md). Refusing the shape instead would
    #: breach D2, which is why the field stayed as it is rather than the phase
    #: being finished a cheaper way.
    #:
    #: The second reason it was once optional — that a caller constructing a
    #: `QueryPlan` directly need not build one — had already stopped being
    #: true: the only two construction sites are in the planner itself.
    semantic: SemanticPlan | None = None
    #: Every mart this plan reads, sorted — one name for the single-mart case
    #: and one per branch for a composed one (RFC 0041 D15). ``mart`` keeps
    #: its meaning as the first of these, so a caller reading it gets a mart
    #: that really serves part of the answer rather than a name invented for
    #: the join.
    #:
    #: Defaulted and then filled, rather than required: a caller constructing
    #: a `QueryPlan` directly — the emitter tests do — would otherwise have to
    #: restate a name it already passed, and the two could disagree.
    marts: tuple[str, ...] = ()

    # ....................... #

    def __post_init__(self) -> None:
        if not self.marts:
            object.__setattr__(self, "marts", (self.mart,))
