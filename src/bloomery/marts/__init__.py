"""Mart flattening (RFC 0010): the wide-mart gold layer resolved at IR
build — spec in, wide schema out, pure. Validation violations are
``GuardrailError`` leaves batched by the guardrail stage (RFC 0006 §5.1);
this package never raises."""

from bloomery.marts.flatten import DATE_BUCKETS, MartLowering, lower_marts

__all__ = [
    "DATE_BUCKETS",
    "MartLowering",
    "lower_marts",
]
