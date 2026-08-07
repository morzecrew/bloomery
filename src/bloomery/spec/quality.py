"""The data-quality spec surface (RFC 0016 §5.3).

Cleansing is declared, never coded: a **closed** rule catalogue attaches to
mapping fields and to entities, every rule carrying an explicit disposition
(``flag | quarantine | fail`` — no global default, deliberately no ``drop``,
and no ``repair`` in v1, RFC 0016 D2/D17). Alongside the rules sit the three
entity-level blocks — ``dedupe:``, ``quarantine:`` — and the document-level
``reconcile:`` list.

Parse validates *shape and grammar* only (RFC 0002 D4), exactly as everywhere
else in this layer. Three deliberate non-checks, because RFC 0016 §5.9 makes
them **guardrails** (compile-stage, batched, one aggregate error) rather than
parse failures:

- a missing ``tie_break`` under ``keep: latest_by`` — ``DedupeTieBreakMissing``;
- a ``quarantine`` disposition with no ``quarantine:`` block —
  ``QuarantineRetentionMissing``;
- a ``redact:`` path intersecting a mapped ``from`` path — ``RedactionConflict``.

Rejecting them here would move a *model* error into the *document* stage and
lose the batched, cross-document message an author actually fixes from.
"""

from __future__ import annotations

import re
from collections.abc import Mapping as AbcMapping
from decimal import Decimal
from typing import Annotated, Literal, Self, cast

from pydantic import AfterValidator, Discriminator, Field, StringConstraints, model_validator

from bloomery.spec.common import JsonPath, SpecModel

__all__ = [
    "PORTABLE_REGEX_REJECTED",
    "RETENTION_PATTERN",
    "RULE_NAME_PATTERN",
    "CoercibleRule",
    "Dedupe",
    "DedupeKeepName",
    "EntityQualityRule",
    "ExpressionRule",
    "FieldQualityRule",
    "InEnumRule",
    "InSetRule",
    "LengthRule",
    "NotNullRule",
    "OnFailName",
    "OnMissingName",
    "PatternRule",
    "PortableRegex",
    "Quarantine",
    "QualityRule",
    "RangeRule",
    "Reconcile",
    "ReferentialRule",
    "RetentionDuration",
    "RuleName",
    "UniqueRule",
]

# ....................... #
# Vocabularies and grammars

#: The v1 disposition vocabulary (RFC 0016 §5.1, D2): explicit per rule, never
#: a global default. No ``drop`` — quarantine is drop plus recoverability; no
#: ``repair`` — deferred out of v1 on a repair-recipe contract (D17).
OnFailName = Literal["flag", "quarantine", "fail"]

#: ``referential.on_missing`` (RFC 0016 §5.3, D6). ``fail`` is deliberately
#: absent: orphans are an expected, recoverable data condition, and a pipeline
#: that stops on every orphan punishes the normal case — a pipeline-stopping
#: orphan gate is expressed as a ``reconcile`` check instead.
OnMissingName = Literal["unknown_member", "quarantine", "flag"]

#: ``dedupe.keep`` — a closed vocabulary that starts at one value: loosening a
#: refusal later is backward-compatible, tightening one is not (RFC 0010 §9).
DedupeKeepName = Literal["latest_by"]

#: Rule names are identifier-constrained at parse (RFC 0016 §5.5, D23) so that
#: neither ``_quality_flags`` shape — the array nor the comma-delimited string
#: fallback — ever needs escaping. The same constraint covers ``reconcile``
#: names, which reach the quality mart's ``rule`` dimension.
RULE_NAME_PATTERN = r"^[a-z0-9_]+$"

#: The closed retention grammar (RFC 0016 §5.6 requires ``retention:``, and
#: names ``90d``; the grammar itself is this RFC's to pin). A positive integer
#: with no leading zero, at most five digits, and exactly one unit suffix from
#: ``h`` (hours), ``d`` (days), ``w`` (weeks). Months and years are deliberately
#: absent — they are not fixed durations, and a retention window that means
#: something different in February is a legal problem, not a convenience;
#: minutes are absent because ``m`` would read as either.
RETENTION_PATTERN = r"^[1-9][0-9]{0,4}[hdw]$"

RuleName = Annotated[str, StringConstraints(pattern=RULE_NAME_PATTERN)]
RetentionDuration = Annotated[str, StringConstraints(pattern=RETENTION_PATTERN)]

#: Constructs outside the portable regex subset (RFC 0016 §5.3, D5), keyed by
#: the ``(?`` prefix that introduces them. Character classes, anchors, and
#: quantifiers are portable across DuckDB (RE2), Postgres (ARE), and Trino
#: (RE2); lookaround and named groups are not — RE2 has no lookaround at all,
#: and the named-group syntaxes disagree. A regex that works on DuckDB and
#: silently means something else on Trino is exactly the bug this project
#: exists to prevent. Full per-dialect validation via sqlglot is the lowering
#: phase's job; this is the subset check every dialect agrees on.
PORTABLE_REGEX_REJECTED: tuple[tuple[str, str], ...] = (
    ("(?=", "lookahead"),
    ("(?!", "negative lookahead"),
    ("(?<=", "lookbehind"),
    ("(?<!", "negative lookbehind"),
    ("(?P<", "named group"),
    ("(?P=", "named backreference"),
    ("(?<", "named group"),
)


def _first_unsupported(pattern: str) -> tuple[str, str] | None:
    """The first non-portable construct in ``pattern``, or ``None``.

    Scans the pattern rather than substring-searching it: an escaped ``\\(?=``
    is a literal paren, and ``[(?=]`` is a character class — neither is
    lookahead. Order in :data:`PORTABLE_REGEX_REJECTED` is significant, the
    longer ``(?<=``/``(?<!`` prefixes preceding the bare ``(?<``.
    """
    index = 0
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2  # the escaped character is a literal, whatever it is
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif pattern.startswith("(?", index):
            for prefix, label in PORTABLE_REGEX_REJECTED:
                if pattern.startswith(prefix, index):
                    return prefix, label
        index += 1
    return None


def _portable_regex(pattern: str) -> str:
    """Reject the non-portable subset, then the malformed."""
    found = _first_unsupported(pattern)
    if found is not None:
        prefix, label = found
        msg = (
            f"{label} ({prefix}) is outside the portable regex subset (RFC 0016 §5.3): "
            "character classes, anchors, and quantifiers only — no lookaround, no named "
            "groups, because they do not mean the same thing on every target dialect"
        )
        raise ValueError(msg)
    try:
        re.compile(pattern)
    except re.error as exc:
        msg = f"invalid regular expression: {exc}"
        raise ValueError(msg) from None
    return pattern


PortableRegex = Annotated[str, AfterValidator(_portable_regex)]


# ....................... #
# Field-level rules (RFC 0016 §5.3) — the closed catalogue


class QualityRule(SpecModel):
    """Base of every disposition-carrying rule: ``on_fail`` is **required**,
    never inherited from a project-wide default (RFC 0016 D2). The implicit
    ``coercible`` rule's ``quarantine`` default applies to the rule nobody
    wrote; a rule an author *did* write states its own disposition."""

    on_fail: OnFailName


class CoercibleRule(QualityRule):
    """``{rule: coercible}`` — the implicit, always-present rule made explicit
    to override its ``quarantine`` default (RFC 0016 §5.2, D3). Transform
    chains produce a value or a coercion-failure marker; this disposes of the
    marker. It absorbs the retired ``Mapping.on_unmapped_enum``."""

    rule: Literal["coercible"]


class NotNullRule(QualityRule):
    """``{rule: not_null}`` — one of the two rules that own nulls (RFC 0016
    D19): every other rule's violation predicate stays silent on ``UNKNOWN``."""

    rule: Literal["not_null"]


class RangeRule(QualityRule):
    """``{rule: range, min: …, max: …}`` — at least one bound; bounds are
    ``int``/``Decimal``/``str``, never ``float`` (RFC 0003 D5). Two bounds may
    carry different dispositions, so they are two rules (§5.3's worked
    example: ``min: 0`` quarantines, ``max: 1000000`` flags)."""

    rule: Literal["range"]
    min: int | Decimal | str | None = None
    max: int | Decimal | str | None = None

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> Self:
        if self.min is None and self.max is None:
            msg = "a range rule needs at least one of min / max"
            raise ValueError(msg)
        return self


class LengthRule(QualityRule):
    """``{rule: length, min: …, max: …}`` — at least one bound, both
    non-negative character counts."""

    rule: Literal["length"]
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> Self:
        if self.min is None and self.max is None:
            msg = "a length rule needs at least one of min / max"
            raise ValueError(msg)
        return self


class PatternRule(QualityRule):
    """``{rule: pattern, regex: …}`` — ``regex`` names the expression, keeping
    one word for one concept alongside the shipped ``assert: {regex: …}``
    (RFC 0006 D8). The portable subset is enforced here; per-dialect
    validation through sqlglot is the lowering phase's."""

    rule: Literal["pattern"]
    regex: PortableRegex


class InEnumRule(QualityRule):
    """``{rule: in_enum}`` — the value survived its ``enum_map`` chain
    unmapped. Parameterless by construction: the admissible set *is* the
    chain's mapping, and restating it here would let the two drift."""

    rule: Literal["in_enum"]


class InSetRule(QualityRule):
    """``{rule: in_set, values: [...]}`` — membership in a literal set
    declared inline; at least one value (an empty set fails every row)."""

    rule: Literal["in_set"]
    values: tuple[str | int, ...] = Field(min_length=1)


class UniqueRule(QualityRule):
    """``{rule: unique}`` — evaluated **per partition slice** in both full and
    incremental runs (RFC 0016 D5); cross-partition duplicates are key-based
    dedupe's job in every mode, and sampling is rejected outright."""

    rule: Literal["unique"]


FieldQualityRule = Annotated[
    CoercibleRule
    | NotNullRule
    | RangeRule
    | LengthRule
    | PatternRule
    | InEnumRule
    | InSetRule
    | UniqueRule,
    Discriminator("rule"),
]
"""The closed field-rule catalogue (RFC 0016 D5), discriminated on ``rule``.
New rules are RFC amendments, not config."""


# ....................... #
# Entity-level rules (RFC 0016 §5.3) — row rules


class ExpressionRule(QualityRule):
    """``{rule: expression, name: …, expr: …}`` — a boolean row predicate over
    the entity's own columns. ``name`` is authored because it reaches
    ``_quality_flags`` and the quality mart, where a generated name would be
    unreadable."""

    rule: Literal["expression"]
    name: RuleName
    expr: str


class ReferentialRule(SpecModel):
    """``{rule: referential, via: …, on_missing: …}`` — a declared
    relationship probed at the row-rule stage against the referenced *silver*
    entity (RFC 0016 §5.1).

    It carries ``on_missing``, not ``on_fail``: ``unknown_member`` is a
    disposition no other rule has (the row passes with its fk rewritten to the
    reserved ``'__unknown__'`` member, keeping aggregates correct), and
    ``fail`` is deliberately unavailable (D6).
    """

    rule: Literal["referential"]
    via: str
    on_missing: OnMissingName


EntityQualityRule = Annotated[ExpressionRule | ReferentialRule, Discriminator("rule")]
"""The closed row-rule catalogue (RFC 0016 D6), discriminated on ``rule``."""


# ....................... #
# Entity-level blocks


class Dedupe(SpecModel):
    """``dedupe: {keep: latest_by, field: …, tie_break: [...]}`` — partitions
    by the entity key and keeps one row per key (RFC 0016 §5.4).

    ``tie_break`` is optional *here* and mandatory *there*: its absence is the
    compile error ``DedupeTieBreakMissing`` (§5.3), a statement about the
    model rather than the document.
    """

    keep: DedupeKeepName
    field: str
    tie_break: tuple[str, ...] = ()


class Quarantine(SpecModel):
    """``quarantine: {retention: 90d, redact: [...]}`` — the per-entity reject
    table's policy (RFC 0016 §5.6).

    ``retention:`` is required whenever the block exists because reject rows
    hold raw source payloads, and therefore PII: "trivial now and a legal
    problem in eighteen months". ``redact:`` JSONPaths apply to ``raw`` and
    ``key_values`` at write time.
    """

    retention: RetentionDuration
    redact: tuple[JsonPath, ...] = ()


class Reconcile(SpecModel):
    """One ``reconcile:`` block — the check that catches a *correct formula
    over wrong data* (RFC 0016 §5.3), emitting its own model plus a
    non-blocking audit.

    ``tolerance`` is a quoted decimal: YAML's ``0.01`` is a float, and floats
    never enter the IR or an emission path (RFC 0003 D5).
    """

    name: RuleName
    left: str
    right: str
    tolerance: Decimal = Field(ge=0)
    on_fail: OnFailName

    @model_validator(mode="before")
    @classmethod
    def _reject_float_tolerance(cls, value: object) -> object:
        if not isinstance(value, AbcMapping):
            return value
        mapping = cast("AbcMapping[object, object]", value)
        if isinstance(mapping.get("tolerance"), float):
            msg = (
                "tolerance must be a quoted decimal string — an unquoted YAML number "
                'parses as a float, which the IR bans (RFC 0003 D5): use tolerance: "0.01"'
            )
            raise ValueError(msg)
        return mapping
