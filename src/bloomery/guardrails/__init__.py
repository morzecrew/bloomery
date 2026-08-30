"""The guardrail stage (RFC 0006): the compile-time refusals of
plausible-but-wrong arithmetic — unit coherence, tax basis, currency, grain
(fan-out), additivity, range sanity — batched into one ``GuardrailError``
aggregate, plus the two non-raising amendments (path-conflict shadows and
``assert:`` lowering). Compile errors, never warnings, no suppression knob
(RFC 0006 D1)."""

from bloomery.guardrails.stage import check_guardrails

# ----------------------- #

__all__ = [
    "check_guardrails",
]
