"""The data-quality lowering package (RFC 0016) — the run-time half of the
compiler's quality story.

The boundary this package lives on is normative (RFC 0016 §5.9, D13): a
**guardrail** says the *model* is wrong and is decided at compile time from
the spec alone (``bloomery/guardrails/``); a **quality rule** says the *data*
is wrong and is decided per row at run time. Nothing decidable from the spec
alone belongs here — this package only ever *lowers*: spec blocks to IR nodes,
IR nodes to dialect-neutral SQLGlot ASTs. It does no I/O, executes nothing,
and (like every compile-path module) never sees a clock.

Modules:

- :mod:`~bloomery.quality.catalogue` — the closed vocabulary and the fixed
  pipeline order as data;
- :mod:`~bloomery.quality.predicates` — one violation predicate per rule kind,
  under the three-valued-logic invariant (D19) documented at its top;
- :mod:`~bloomery.quality.flags` — the ``_quality_flags``/``failed_rules``
  physical contract (D23) and its single-pass construction;
- :mod:`~bloomery.quality.dedupe` — the ``QUALIFY ROW_NUMBER`` total order
  (D20), shared by the pipeline and the replay merge;
- :mod:`~bloomery.quality.reject` — ``reject_id`` as canon bytes in SQL (D21);
- :mod:`~bloomery.quality.pattern` — per-dialect ``pattern`` validation;
- :mod:`~bloomery.quality.lower` — spec → IR.
"""

from bloomery.quality.catalogue import (
    ALL_DISPOSITIONS,
    ALL_ON_MISSING,
    ALL_RULES,
    FIELD_RULES,
    FLAGS_COLUMN,
    INGESTION_METADATA,
    OK_COLUMN,
    PIPELINE_STAGES,
    REJECT_SUFFIX,
    ROW_RULES,
    UNKNOWN_MEMBER,
    payload_key,
)
from bloomery.quality.dedupe import (
    ROW_ID_COLUMN,
    dedupe_order,
    dedupe_row_number,
    dedupe_sort_columns,
    with_dedupe_qualify,
)
from bloomery.quality.flags import (
    DELIMITER,
    FLAG_ARRAY_TYPE,
    empty_flags,
    flags_expression,
    quality_ok,
)
from bloomery.quality.lower import (
    field_sources,
    lower_dedupe,
    lower_quality,
    lower_quarantine,
    lower_reconcile,
    mapped_fields,
    opts_in,
)
from bloomery.quality.pattern import unsupported_dialects
from bloomery.quality.predicates import (
    conjunction,
    disjunction,
    disposition,
    failed_rule_names,
    grouped,
    indexed_params,
    params_of,
    qualify_columns,
    ref_alias,
    source_alias,
    unknown_member_case,
    violation,
    worst,
)
from bloomery.quality.reject import REJECT_COLUMNS, canon_literal, canon_prefixed, reject_id

__all__ = [
    # catalogue
    "ALL_DISPOSITIONS",
    "ALL_ON_MISSING",
    "ALL_RULES",
    "FIELD_RULES",
    "FLAGS_COLUMN",
    "INGESTION_METADATA",
    "OK_COLUMN",
    "PIPELINE_STAGES",
    "REJECT_SUFFIX",
    "ROW_RULES",
    "UNKNOWN_MEMBER",
    "payload_key",
    # dedupe
    "ROW_ID_COLUMN",
    "dedupe_order",
    "dedupe_row_number",
    "dedupe_sort_columns",
    "with_dedupe_qualify",
    # flags (D23)
    "DELIMITER",
    "FLAG_ARRAY_TYPE",
    "empty_flags",
    "flags_expression",
    "quality_ok",
    # lowering
    "field_sources",
    "lower_dedupe",
    "lower_quality",
    "lower_quarantine",
    "lower_reconcile",
    "mapped_fields",
    "opts_in",
    # pattern portability
    "unsupported_dialects",
    # predicates
    "conjunction",
    "disjunction",
    "disposition",
    "failed_rule_names",
    "grouped",
    "indexed_params",
    "params_of",
    "qualify_columns",
    "ref_alias",
    "source_alias",
    "unknown_member_case",
    "violation",
    "worst",
    # reject
    "REJECT_COLUMNS",
    "canon_literal",
    "canon_prefixed",
    "reject_id",
]
