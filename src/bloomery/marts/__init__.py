"""Mart flattening (RFC 0010): the wide-mart gold layer resolved at IR
build — spec in, wide schema out, pure. Validation violations are
``GuardrailError`` leaves batched by the guardrail stage (RFC 0006 §5.1);
this package never raises."""

from bloomery.marts.flatten import (
    DATE_BUCKETS,
    HAS_QUALITY_FLAGS,
    MartLowering,
    lower_marts,
)
from bloomery.marts.rollup import RollupLowering, lower_rollups

# ----------------------- #

__all__ = [
    "DATE_BUCKETS",
    "HAS_QUALITY_FLAGS",
    "MartLowering",
    "RollupLowering",
    "lower_marts",
    "lower_rollups",
]
