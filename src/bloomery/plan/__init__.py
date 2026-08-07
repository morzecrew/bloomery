"""The plan stage (RFC 0007): ``plan(old_ir | None, new_ir) -> Plan`` — a
pure structural diff of two :class:`~bloomery.ir.ProjectIR`s that classifies
every change (``ADDITIVE | WIDENING | RENAME | RESTATING | BREAKING``),
computes backfill scope and downstream metric impact from the IR's own
``depends_on`` edges, and enforces the expand/contract rule
(:class:`~bloomery.errors.ContractViolation` — the stage's only refusal)."""

from bloomery.plan.diff import plan
from bloomery.plan.model import BackfillScope, Change, ChangeClass, Plan

__all__ = [
    "BackfillScope",
    "Change",
    "ChangeClass",
    "Plan",
    "plan",
]
