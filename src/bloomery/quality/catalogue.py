"""The closed quality vocabulary (RFC 0016 D5/D6) and the fixed pipeline
order (D7) as data.

One module owns every name the rest of the package spells: rule kinds,
dispositions, ``referential.on_missing`` values, the generated column names,
the bronze ingestion-metadata contract, and the six pipeline stages. A
consumer that invents its own list is exactly how a rule ships lowered but
untested (RFC 0016 §6: the matrix is ``product(ALL_RULES, ALL_DISPOSITIONS)``
over *these* tuples).
"""

from __future__ import annotations

from bloomery.ir import OnFail

__all__ = [
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
]

#: The field-rule catalogue (RFC 0016 D5), sorted. ``coercible`` is implicit
#: and always present on a quality-carrying entity; the rest are authored.
FIELD_RULES: tuple[str, ...] = (
    "coercible",
    "in_enum",
    "in_set",
    "length",
    "not_null",
    "pattern",
    "range",
    "unique",
)

#: The row-rule catalogue (RFC 0016 D6), sorted — evaluated over the whole row
#: at stage 5, after the field rules.
ROW_RULES: tuple[str, ...] = ("expression", "referential")

#: Every rule kind, sorted. The unit matrix iterates this (RFC 0016 §6).
ALL_RULES: tuple[str, ...] = tuple(sorted((*FIELD_RULES, *ROW_RULES)))

#: The v1 disposition vocabulary in *severity* order, weakest first — the
#: reverse of RFC 0016 D18's precedence, which reads ``fail > quarantine >
#: flag``. Iterating weakest-first keeps the matrix output readable; the
#: precedence itself lives in :func:`bloomery.quality.predicates.disposition`.
ALL_DISPOSITIONS: tuple[OnFail, ...] = (OnFail.FLAG, OnFail.QUARANTINE, OnFail.FAIL)

#: ``referential.on_missing`` (RFC 0016 D6), sorted. ``fail`` is deliberately
#: absent — orphans are an expected, recoverable data condition.
ALL_ON_MISSING: tuple[str, ...] = ("flag", "quarantine", "unknown_member")

#: The reserved referential member (RFC 0016 §5.4). A *string*: there is
#: nowhere sound to put a sentinel in a non-string key, and a typed sentinel
#: like ``-1`` colliding with a legal key value is the silent wrongness this
#: project refuses.
UNKNOWN_MEMBER = "__unknown__"

#: The generated silver columns (RFC 0016 §5.5, D9/D23). Both are reserved
#: member names at spec parse, so an authored field can never collide.
FLAGS_COLUMN = "_quality_flags"
OK_COLUMN = "_quality_ok"

#: The bronze ingestion-metadata contract (RFC 0016 §5.6, D21), sorted. An
#: entity using ``quarantine`` or ``dedupe`` requires all three; absence is the
#: compile error ``IngestionMetadataMissing``, and the NOT NULL/uniqueness
#: properties — data facts no compiler can check — become a generated blocking
#: audit.
INGESTION_METADATA: tuple[str, ...] = ("_ingested_at", "_load_id", "_source_row_id")

#: The reject relation's suffix: one ``<entity>__reject`` per entity, never per
#: mapping (RFC 0016 §5.6, D10).
REJECT_SUFFIX = "__reject"

#: The fixed pipeline order (RFC 0016 §5.4, D7) — declared once, never
#: per-field, never configurable. Dedupe sits *before* the rules deliberately:
#: rules-first would silently replace a corrupt latest row with a stale-but-
#: clean older one, which is data loss disguised as data quality.
#:
#: Emission renders exactly this order — the extract/transform projection is
#: the innermost SELECT, ``dedupe`` its ``QUALIFY``, the field and row rules
#: the predicates of the layer above, and ``route`` the two-way split between
#: the entity model and ``<entity>__reject``.
PIPELINE_STAGES: tuple[str, ...] = (
    "extract",
    "transform",
    "dedupe",
    "field_rules",
    "row_rules",
    "route",
)


def payload_key(path: str) -> str:
    """The top-level bronze column a JSONPath-lite path reads.

    ``$.a`` and ``$.a.b`` both live in column ``a``: extraction lowers the
    first segment to a physical column and the rest to JSON extraction
    (RFC 0002 §5.5). The reject table's ``raw`` is keyed by this — it is the
    bronze *row* — and ``quarantine.redact`` is refused at the same
    granularity, so a redaction can never remove half of a column something
    reads.
    """
    return path.removeprefix("$.").split(".")[0]
