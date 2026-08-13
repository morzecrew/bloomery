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

from bloomery.typing import LogicalType

__all__ = [
    "ColumnDescriptor",
    "Explanation",
    "MeasureExplanation",
    "QueryPlan",
]

type ColumnRole = Literal["dimension", "measure"]


@dataclass(frozen=True, slots=True)
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
    """

    name: str
    sql_alias: str
    type: LogicalType
    role: ColumnRole
    label: str | None = None


@dataclass(frozen=True, slots=True)
class MeasureExplanation:
    """How one requested measure was computed: its expression, declared
    additivity, and the lowering note (RFC 0011 D5 vocabulary)."""

    name: str
    expr: str
    additivity: str
    note: str


@dataclass(frozen=True, slots=True)
class Explanation:
    """The deterministic provenance record attached to every plan (D8)."""

    mart: str
    grain: str
    measures: tuple[MeasureExplanation, ...]
    filters: tuple[str, ...]
    policy_applied: bool

    def render(self) -> str:
        """The human-readable provenance block (RFC 0011 §5.6 shape)."""
        lines = [", ".join(measure.name for measure in self.measures)]
        lines.append(f"  mart:     {self.mart} (grain: {self.grain})")
        for measure in self.measures:
            lines.append(f"  measure:  {measure.name} = {measure.expr}")
            lines.append(f"            [{measure.note}]")
        rendered_filters = "; ".join(self.filters) if self.filters else "(none)"
        lines.append(f"  filters:  {rendered_filters}")
        lines.append(f"  policy:   {'applied' if self.policy_applied else 'not applied'}")
        return "\n".join(lines)


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
