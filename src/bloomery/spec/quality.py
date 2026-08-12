"""The data-quality spec surface (RFC 0016 §5.3).

Cleansing is declared, never coded: a **closed** rule catalogue attaches to
mapping fields and to entities, every rule carrying an explicit disposition
(``flag | quarantine | fail | repair`` — no global default, deliberately no
``drop``, and ``repair`` only since D87 gave it a recipe contract, RFC 0016
D2/D17/D87). Alongside the rules sit the two
entity-level blocks — ``dedupe:`` and ``quarantine:`` — and the
document-level ``reconcile:`` list.

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
from typing import Annotated, ClassVar, Literal, NoReturn, Self, cast

from pydantic import AfterValidator, Discriminator, Field, StringConstraints, model_validator

from bloomery.spec.common import JsonPath, ParameterValue, SpecModel, StepUse

__all__ = [
    "PORTABLE_REGEX_REJECTED",
    "RETENTION_PATTERN",
    "RULE_NAME_PATTERN",
    "CODEPOINT_ITEM_PATTERN",
    "CharsetRule",
    "CodepointItem",
    "Coverage",
    "CoercibleRule",
    "Dedupe",
    "DedupeKeepName",
    "EntityQualityRule",
    "ExpressionRule",
    "FieldQualityRule",
    "InEnumRule",
    "InSetRule",
    "LengthRule",
    "NormalizeRule",
    "NotNullRule",
    "NormalFormName",
    "OnFailName",
    "OnMissingName",
    "PatternRule",
    "EXACT_DECIMAL",
    "PortableRegex",
    "Quarantine",
    "Repair",
    "QualityRule",
    "RangeBound",
    "RangeRule",
    "Reconcile",
    "ReferentialRule",
    "RetentionDuration",
    "RuleName",
    "UniqueRule",
]

# ....................... #
# Vocabularies and grammars

#: The disposition vocabulary (RFC 0016 §5.1, D2): explicit per rule, never a
#: global default. No ``drop`` — quarantine is drop plus recoverability, and
#: deletion happens through retention, with a paper trail. ``repair`` was
#: deferred out of v1 on a repair-recipe contract (D17) and joined the
#: vocabulary when RFC 0017's step registry supplied one (D87); it never stands
#: alone, always beside a ``repair:`` block naming the recipe and the
#: disposition for a row the recipe did not fix.
OnFailName = Literal["flag", "quarantine", "fail", "repair"]

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

#: The Unicode normal form a ``normalize`` rule may name (RFC 0016 D86). One
#: value, and the reason is portability rather than taste: Postgres and Trino
#: spell all four forms (``NORMALIZE(x, NFKC)``), DuckDB has ``nfc_normalize``
#: and nothing else. Admitting ``nfkc`` here would mean a rule that compiles
#: everywhere and runs on two engines out of three — the failure mode RFC 0008
#: D3 exists to prevent. Widening a closed vocabulary later is
#: backward-compatible; narrowing one is not.
NormalFormName = Literal["nfc"]

#: A ``charset`` member: one codepoint (``U+200B``) or an inclusive range
#: (``U+0020-U+007E``). Uppercase hex, four to six digits, canonical spelling
#: only — ``u+200b`` and ``U+200B`` naming one character two ways would make
#: two specs with identical meaning produce different IR bytes.
#:
#: Codepoints rather than the characters themselves, and that is the whole
#: point of the rule: every character a ``charset`` set is written to catch is
#: invisible, so a literal one in a YAML file is unreadable in review and
#: indistinguishable from a space in a diff.
CODEPOINT_ITEM_PATTERN = r"^U\+[0-9A-F]{4,6}(-U\+[0-9A-F]{4,6})?$"

RuleName = Annotated[str, StringConstraints(pattern=RULE_NAME_PATTERN)]
RetentionDuration = Annotated[str, StringConstraints(pattern=RETENTION_PATTERN)]
CodepointItem = Annotated[str, StringConstraints(pattern=CODEPOINT_ITEM_PATTERN)]

# ....................... #
# The portable regex subset (RFC 0016 §5.3, D5) — an allowlist scanner
#
# The subset is defined by what the scanner *accepts*; everything else,
# including anything unrecognized, is refused. That direction is the whole
# point: a denylist accepts every construct nobody thought of, and the ones
# nobody thought of (backreferences, atomic groups, possessive quantifiers,
# ``\A``/``\Z``) abort the run on RE2 engines rather than compiling into
# something wrong. Loosening a refusal later is backward-compatible;
# tightening one is not (RFC 0010 §9), so the subset starts small.
#
# What "portable" is a claim about: DuckDB and Trino run RE2, Postgres runs
# POSIX ARE. The accepted constructs mean the same thing on all three, with
# two divergences stated rather than pretended away:
#
# - ``.`` excludes newline under RE2 and includes it under ARE. Accepted
#   anyway: the divergence needs an embedded newline in the data to show, and
#   the alternative is refusing the one construct authors reach for most.
# - ``\d``/``\w``/``\s`` are ASCII under RE2 and locale-defined under ARE
#   (``[[:alnum:]_]`` and friends), so ``\w`` can admit non-ASCII letters on
#   Postgres. Accepted with the caveat recorded here and in the docs.
#
# Their negations ``\D``/``\W``/``\S`` are accepted **outside** a character
# class only: ARE makes them an error *inside* brackets, where RE2 allows
# them, and an error is a divergence like any other.

#: Group constructs outside the subset, keyed by the ``(?`` prefix that
#: introduces them, longest prefix first, with a catch-all ``(?`` last so the
#: table is closed: a group form nobody listed is still refused, by name.
PORTABLE_REGEX_REJECTED: tuple[tuple[str, str], ...] = (
    ("(?P<", "named group"),
    ("(?P=", "named backreference"),
    ("(?<=", "lookbehind"),
    ("(?<!", "negative lookbehind"),
    ("(?<", "named group"),
    ("(?'", "named group"),
    ("(?=", "lookahead"),
    ("(?!", "negative lookahead"),
    ("(?>", "atomic group"),
    ("(?#", "inline comment"),
    ("(?(", "conditional group"),
    ("(?a", "inline flag"),
    ("(?i", "inline flag"),
    ("(?L", "inline flag"),
    ("(?m", "inline flag"),
    ("(?s", "inline flag"),
    ("(?u", "inline flag"),
    ("(?x", "inline flag"),
    ("(?-", "inline flag"),
    ("(?", "unrecognized group construct"),
)

#: Escapes standing for themselves: the subset's punctuation, plus ``\t``,
#: ``\n``, ``\r``, which RE2 and ARE spell identically.
_ESCAPED_LITERALS = frozenset("\\.^$|?*+()[]{}-/tnr")

#: Named refusals for the escapes an author is most likely to try. Anything
#: not here and not in :data:`_ESCAPED_LITERALS` (nor ``dDwWsS``) is an
#: "unrecognized escape" — the scanner never falls through to acceptance.
_ESCAPE_REFUSALS: tuple[tuple[str, str], ...] = (
    ("AZz", "text-anchor escape"),
    ("bB", "word-boundary escape"),
    ("G", "match-start escape"),
    ("0123456789", "backreference"),
    ("pP", "Unicode property class"),
    ("xuUN", "character-code escape"),
)

#: ``{n}``, ``{n,}``, ``{n,m}`` — the portable repetition forms.
_REPETITION = re.compile(r"\{(\d+)(,(\d+)?)?\}")

_SUBSET = (
    "the subset is literals, character classes, \\d/\\w/\\s and their negations, "
    "the anchors ^ and $, the quantifiers * + ? {n} {n,} {n,m}, alternation, and "
    "non-capturing groups (?:…)"
)


def _refuse(construct: str, text: str, why: str) -> NoReturn:
    """One refusal, naming the construct, its text, and the reason."""
    msg = (
        f"{construct} ({text!r}) is outside the portable regex subset "
        f"(RFC 0016 §5.3): {why} — {_SUBSET}"
    )
    raise ValueError(msg)


def _refuse_escape(char: str, *, in_class: bool) -> NoReturn:
    if in_class and char in "DWS":
        _refuse(
            "negated shorthand class inside a character class",
            f"\\{char}",
            "Postgres ARE rejects it inside brackets where RE2 accepts it, so the "
            f"same pattern is an error on one engine and a match on another; write [^\\{char.lower()}]",
        )
    for chars, label in _ESCAPE_REFUSALS:
        if char in chars:
            _refuse(label, f"\\{char}", "no RE2 engine and no POSIX ARE agree on it")
    _refuse(
        "unrecognized escape",
        f"\\{char}",
        "the subset is closed, so an escape it does not name is refused",
    )


def _scan_class(pattern: str, start: int) -> int:
    """Scan the character class opening at ``pattern[start]``; return the
    index just past its closing ``]``."""
    index = start + 1
    if pattern[index : index + 1] == "^":
        index += 1
    if pattern[index : index + 1] == "]":
        _refuse("empty character class", "[]", "write \\] for a literal bracket")
    while index < len(pattern):
        char = pattern[index]
        if char == "]":
            return index + 1
        if char == "\\":
            following = pattern[index + 1 : index + 2]
            if not following:
                _refuse("trailing backslash", "\\", "it escapes nothing")
            if following not in _ESCAPED_LITERALS and following not in "dws":
                _refuse_escape(following, in_class=True)
            index += 2
            continue
        if char == "[":
            following = pattern[index + 1 : index + 2]
            if following == ":":
                _refuse(
                    "POSIX character class",
                    pattern[index : pattern.find(":]", index) + 2] or "[[:",
                    "its membership is locale-defined on Postgres and fixed on RE2",
                )
            if following == ".":
                _refuse("POSIX collating element", "[.", "no RE2 engine implements it")
            if following == "=":
                _refuse("POSIX equivalence class", "[=", "no RE2 engine implements it")
            _refuse(
                "unescaped '[' inside a character class", "[", "write \\[ for a literal bracket"
            )
        index += 1
    _refuse("unterminated character class", pattern[start:], "no ']' closes it")


def _scan_portable(pattern: str) -> None:
    """Refuse everything the portable subset does not name.

    One left-to-right pass, so the refusal names the *first* offending
    construct rather than whatever a denylist happened to substring-match.
    Anchoring (below) is checked in the same pass: ``^`` is legal only at the
    start of a top-level alternative, ``$`` only at its end, and every
    alternative must have both.
    """
    index = 0
    depth = 0
    quantifiable = False  # the previous token can carry a quantifier
    quantifier: str | None = None  # the previous token *was* a quantifier
    branch_start = True  # at the start of a top-level alternative
    opened = False  # this alternative has its '^'
    closed = False  # ... and its '$', with nothing after it
    # One flag per open group: does its body carry an unbounded quantifier?
    # Popped when the group closes, so the quantifier applied *to* the group
    # can be judged against what it would be repeating (RFC 0016 D96).
    group_bodies: list[bool] = []
    just_closed_unbounded: bool | None = None  # the group that just closed, if any

    while index < len(pattern):
        char = pattern[index]
        if closed and char != "|":
            _refuse("misplaced anchor", "$", "'$' ends its alternative, and this one continues")

        if char == "^":
            if depth or not branch_start:
                _refuse(
                    "misplaced anchor",
                    "^",
                    "'^' opens a top-level alternative; anchors inside groups anchor nothing",
                )
            opened, branch_start, quantifiable, quantifier = True, False, False, None
        elif char == "$":
            if depth:
                _refuse(
                    "misplaced anchor",
                    "$",
                    "'$' closes a top-level alternative; anchors inside groups anchor nothing",
                )
            closed, branch_start, quantifiable, quantifier = True, False, False, None
        elif char == "|":
            if depth == 0:
                if not (opened and closed):
                    _refuse_unanchored(pattern)
                opened, closed, branch_start = False, False, True
            quantifiable, quantifier = False, None
        elif char == "(":
            if pattern.startswith("(?:", index):
                depth, index = depth + 1, index + 2
                group_bodies.append(False)
                quantifiable, quantifier, branch_start = False, None, False
                just_closed_unbounded = None
            else:
                for prefix, label in PORTABLE_REGEX_REJECTED:
                    if pattern.startswith(prefix, index):
                        _refuse(label, prefix, "it does not mean the same thing on every dialect")
                _refuse(
                    "capturing group",
                    "(",
                    "a rule is a boolean match and captures nothing, and numbered groups are "
                    "what backreferences read; write (?:…)",
                )
        elif char == ")":
            if depth == 0:
                _refuse("unbalanced ')'", ")", "no '(?:' opened it; write \\) for a literal")
            depth -= 1
            just_closed_unbounded = group_bodies.pop() if group_bodies else False
            quantifiable, quantifier, branch_start = True, None, False
        elif char == "[":
            index = _scan_class(pattern, index) - 1
            quantifiable, quantifier, branch_start = True, None, False
        elif char == "]":
            _refuse("unescaped ']'", "]", "no class opened it; write \\] for a literal bracket")
        elif char in "*+?":
            if quantifier is not None:
                label = {
                    "?": "lazy quantifier",
                    "+": "possessive quantifier",
                    "*": "double quantifier",
                }[char]
                _refuse(label, quantifier + char, "RE2 and ARE disagree about it or refuse it")
            if not quantifiable:
                _refuse("quantifier with nothing to repeat", char, "no atom precedes it")
            if char in "*+":
                if just_closed_unbounded:
                    _refuse_nested_repetition(pattern)
                for level in range(len(group_bodies)):
                    group_bodies[level] = True
            quantifier, quantifiable, branch_start = char, False, False
            just_closed_unbounded = None
        elif char == "{":
            match = _REPETITION.match(pattern, index)
            if match is None:
                _refuse("literal '{'", "{", "write \\{ for a literal brace, or {n}/{n,}/{n,m}")
            if quantifier is not None:
                _refuse("double quantifier", quantifier + match.group(0), "one quantifier per atom")
            if not quantifiable:
                _refuse("quantifier with nothing to repeat", match.group(0), "no atom precedes it")
            low, high = match.group(1), match.group(3)
            if high is not None and int(high) < int(low):
                _refuse("inverted repetition", match.group(0), "the minimum exceeds the maximum")
            unbounded = match.group(2) is not None and high is None
            if unbounded:
                if just_closed_unbounded:
                    _refuse_nested_repetition(pattern)
                for level in range(len(group_bodies)):
                    group_bodies[level] = True
            quantifier, quantifiable, branch_start = match.group(0), False, False
            just_closed_unbounded = None
            index = match.end() - 1
        elif char == "}":
            _refuse("unescaped '}'", "}", "no repetition opened it; write \\} for a literal brace")
        elif char == "\\":
            following = pattern[index + 1 : index + 2]
            if not following:
                _refuse("trailing backslash", "\\", "it escapes nothing")
            if following not in _ESCAPED_LITERALS and following not in "dDwWsS":
                _refuse_escape(following, in_class=False)
            quantifiable, quantifier, branch_start = True, None, False
            index += 1
        else:  # '.' and every ordinary literal
            quantifiable, quantifier, branch_start = True, None, False
            just_closed_unbounded = None
        index += 1

    if depth:
        _refuse("unbalanced '('", "(?:", "no ')' closes it")
    if not (opened and closed):
        _refuse_unanchored(pattern)


def _refuse_nested_repetition(pattern: str) -> NoReturn:
    """An unbounded quantifier repeating a group that already repeats
    (RFC 0016 D96).

    ``^(?:a+)+$`` and friends are the standard catastrophic-backtracking
    family: the two quantifiers can split the same input exponentially many
    ways, so a non-matching subject makes the engine try all of them. Measured
    on a backtracking matcher, ``^(?:a+)+$`` against 23 characters already
    takes tens of milliseconds and doubles with each one added.

    Refused at the spec layer rather than left to the engine, because only one
    of the three targets is exposed and the exposure is invisible from the
    spec: DuckDB (RE2) and Trino (RE2J) match in linear time and would shrug,
    while **Postgres** backtracks and hangs the model. A rule that is fine on
    two engines and a denial of service on the third is exactly the
    "silently means something else on another dialect" failure the portable
    subset already exists to prevent — this is the same argument applied to
    cost rather than to meaning.

    Capturing groups were already refused, so ``(?:…)`` is the only spelling
    that reaches here.
    """
    _refuse(
        "nested unbounded repetition",
        pattern,
        "an unbounded quantifier repeating a group that itself repeats without bound is the "
        "catastrophic-backtracking shape: on Postgres it is a denial of service, while RE2 "
        "engines shrug, so the rule would pass review on DuckDB and hang production. Fix: "
        "bound one of the two ('(?:a+){1,8}'), or write the inner repetition alone ('a+')",
    )


def _refuse_unanchored(pattern: str) -> NoReturn:
    msg = (
        f"pattern {pattern!r} is not anchored (RFC 0016 §5.3): a `pattern` rule matches the "
        "whole value, and every SQL regex predicate matches a substring unless the pattern "
        "says otherwise — unanchored, '[0-9]{5}' accepts 'abc12345xyz'. Write the anchors "
        "yourself, one pair per top-level alternative: '^[0-9]{5}$', '^a$|^b$'"
    )
    raise ValueError(msg)


def _portable_regex(pattern: str) -> str:
    """Accept only the portable subset, anchored; then let Python's engine
    have the last word on well-formedness.

    The scanner is the portability check — it is where the RE2/ARE knowledge
    lives, because no amount of *rendering* a pattern proves an engine will
    accept it (:mod:`bloomery.quality.pattern` says the same from the other
    side). ``re.compile`` stays behind it as a second opinion on shapes the
    scanner deliberately does not model, such as a reversed class range.
    """
    _scan_portable(pattern)
    try:
        re.compile(pattern)
    except re.error as exc:
        msg = f"invalid regular expression: {exc}"
        raise ValueError(msg) from None
    return pattern


PortableRegex = Annotated[str, AfterValidator(_portable_regex)]


# ....................... #
# Exact numeric bounds (RFC 0003 D5, RFC 0015 D5)

#: An exact decimal literal: optional sign, digits, optional fraction. No
#: exponent — ``1e10`` renders as a double literal, and no float ever reaches
#: an emission path (RFC 0003 D5). No ``NaN``/``Infinity`` — ``Decimal``
#: parses both, and ``amount < nan`` fails open.
#: An exact decimal bound: optional sign, digits, optional fraction, no
#: exponent (D57). Public because :mod:`bloomery.plan.diff` reads bounds
#: back out of the IR to order them, and must split numeric from temporal
#: exactly where this grammar does — two spellings of one grammar is how
#: they drift.
EXACT_DECIMAL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")

#: The ISO temporal carrier: ``str`` bounds also exist for dates and
#: timestamps (RFC 0015 D5), which lower to string literals compared in the
#: column's own type.
_ISO_TEMPORAL = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?$"
)


def _exact_bound(value: int | Decimal | str) -> int | Decimal | str:
    """A bound that survives to SQL as written.

    The IR carries bounds as ``str(value)`` and the lowering renders numeric
    text as a number literal, so the check is on the *rendered* text: exact
    decimal, or ISO temporal, or refused. Everything a float would smuggle in
    — ``nan``, ``inf``, ``1e10`` — is refused here, at parse, because it is
    decidable from the spec alone (RFC 0016 D13). A non-finite ``Decimal``
    never reaches this function: pydantic's own numeric validation refuses it
    one layer earlier, so the non-finite branch below exists for the *string*
    spellings, which stay strings precisely because ``Decimal`` refused them.
    """
    text = str(value)
    if EXACT_DECIMAL.match(text) or (isinstance(value, str) and _ISO_TEMPORAL.match(text)):
        return value
    lowered = text.lower().lstrip("+-")
    if lowered.startswith(("nan", "snan", "inf")):
        msg = (
            f"range bound {text!r} is non-finite: `amount < nan` is never TRUE on some engines "
            "and always TRUE on others (RFC 0015 D5). Fix: write a real bound"
        )
        raise ValueError(msg)
    if "e" in lowered:
        msg = (
            f"range bound {text!r} carries an exponent, which renders as a double literal, and "
            "floats never reach an emission path (RFC 0003 D5). Fix: write the number in full, "
            'e.g. "10000000000"'
        )
        raise ValueError(msg)
    msg = (
        f"range bound {text!r} is neither an exact decimal nor an ISO date/timestamp. Bounds are "
        "int, Decimal, or a string carrying one exactly (RFC 0015 D5) — the string form exists "
        "for decimals YAML would round to a float and for ISO temporals, nothing else"
    )
    raise ValueError(msg)


RangeBound = Annotated[int | Decimal | str, AfterValidator(_exact_bound)]


# ....................... #
# Field-level rules (RFC 0016 §5.3) — the closed catalogue


class Repair(SpecModel):
    """The repair-recipe contract D17 gated the disposition on (RFC 0016 D87).

    ``via`` names a registered Tier 1 ``sql_macro`` as ``ref@version``, which
    settles §10's open question — *inline vs catalog-referenced* — in favour of
    referenced, and not by preference: D1 holds that specs reference
    implementations and never contain them, and RFC 0017's registry is where a
    referenced implementation already lives, with a version, a declared
    signature, a ``runtime_lock`` and a trust-then-verify contract. An inline
    recipe would have been a second, weaker copy of all of that, reachable only
    from here.

    ``fallback`` is the disposition for a row the recipe did **not** fix, and
    it is required for the same reason ``on_fail`` is (D2): a repair that
    silently kept a still-broken value would be the ``drop`` this RFC refuses,
    wearing a friendlier name. It cannot itself be ``repair`` — a second
    attempt at the same value with the same recipe returns the same answer.
    """

    via: StepUse
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    fallback: Literal["flag", "quarantine", "fail"]


class QualityRule(SpecModel):
    """Base of every disposition-carrying rule: ``on_fail`` is **required**,
    never inherited from a project-wide default (RFC 0016 D2). The implicit
    ``coercible`` rule's ``quarantine`` default applies to the rule nobody
    wrote; a rule an author *did* write states its own disposition."""

    #: Whether ``on_fail: repair`` is meaningful for this kind (RFC 0016 D87).
    #: ``False`` where the rule has no repairable value in hand: ``coercible``
    #: fires *because* the projection is already NULL, ``unique`` is a property
    #: of a population rather than of a value, and a row rule has no column to
    #: rewrite.
    repairable: ClassVar[bool] = True

    on_fail: OnFailName
    repair: Repair | None = None

    @model_validator(mode="after")
    def _repair_accompanies_its_disposition(self) -> Self:
        if (self.on_fail == "repair") != (self.repair is not None):
            msg = (
                "on_fail: repair and a repair: block are one declaration — the disposition "
                "names no recipe on its own, and a recipe with any other disposition would "
                "never run (RFC 0016 D87)"
            )
            raise ValueError(msg)
        if self.repair is not None and not type(self).repairable:
            msg = (
                f"a {getattr(self, 'rule', 'row')!r} rule cannot carry on_fail: repair — it has "
                "no repairable value in hand when it fires (RFC 0016 D87). Fix the value earlier "
                "instead: a sql_macro spliced into the mapping runs before any rule sees it"
            )
            raise ValueError(msg)
        return self


class CoercibleRule(QualityRule):
    """``{rule: coercible}`` — the implicit, always-present rule made explicit
    to override its ``quarantine`` default (RFC 0016 §5.2, D3). Transform
    chains produce a value or a coercion-failure marker; this disposes of the
    marker. It absorbs the retired ``Mapping.on_unmapped_enum``."""

    rule: Literal["coercible"]
    # The marker means "the projection is NULL although every source it reads
    # was not", so by the time this fires the castable text is gone and a
    # recipe would be handed the NULL. Fixing a value *before* it is coerced is
    # what a Tier 1 macro in the mapping is for (RFC 0017 D50).
    repairable: ClassVar[bool] = False


class NotNullRule(QualityRule):
    """``{rule: not_null}`` — one of the two rules that own nulls (RFC 0016
    D19): every other rule's violation predicate stays silent on ``UNKNOWN``."""

    rule: Literal["not_null"]


class RangeRule(QualityRule):
    """``{rule: range, min: …, max: …}`` — at least one bound; bounds are
    ``int``/``Decimal``/``str``, never ``float`` (RFC 0003 D5), and the
    ``str`` carrier is exact: an exact decimal or an ISO temporal, never
    ``nan``/``inf`` and never an exponent (:func:`_exact_bound`). Two bounds
    may carry different dispositions, so they are two rules (§5.3's worked
    example: ``min: 0`` quarantines, ``max: 1000000`` flags)."""

    rule: Literal["range"]
    min: RangeBound | None = None
    max: RangeBound | None = None

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


class NormalizeRule(QualityRule):
    """``{rule: normalize, form: nfc}`` — the value must **already be** in the
    named Unicode normal form (RFC 0016 D86).

    A rule, not a transform, and deliberately so: normalizing silently would
    rewrite the value a source delivered, and RFC 0016 D1 holds that specs
    describe rather than repair. What this says is "``café`` spelled with a
    combining acute is not the same bytes as ``café`` spelled precomposed, and
    I want to know" — which is what dedupe, ``unique`` and every join already
    believe, while a human reading the two rows sees one value.
    """

    rule: Literal["normalize"]
    form: NormalFormName


class CharsetRule(QualityRule):
    """``{rule: charset, allow: [...]}`` or ``{rule: charset, forbid: [...]}``
    — exactly one, each a list of ``U+`` codepoints or inclusive ranges
    (RFC 0016 D86).

    This is the half of D26 that a *confusables table* was supposed to answer,
    and the table is deliberately not what this is. A confusables table is
    versioned Unicode data: embedding it would make the disposition of a row
    depend on which Unicode revision the compiler happened to ship, which is
    an ambient input by another name (RFC 0003). Declaring the admissible
    characters instead keeps the knowledge where D1 puts it — in the spec —
    and it is *stronger* for the case that motivated it: an allow-list of the
    script a column is actually written in catches a Cyrillic homoglyph, a
    fullwidth digit and an Arabic-Indic digit alike, none of which any
    denylist enumerates completely.

    ``forbid`` is the complementary shape, for the class that is genuinely
    small and closed: the invisible formatting characters (zero-width space,
    bidi controls, soft hyphen, BOM).

    Neither is expressible as a ``pattern``: the portable regex subset (D5)
    forbids exactly the codepoint-class constructs this would need, because
    such a class means one thing under RE2 and another under Postgres ARE.
    A literal *set* is not a regex at all, and lowers through ``TRANSLATE``.
    """

    rule: Literal["charset"]
    allow: tuple[CodepointItem, ...] | None = Field(default=None, min_length=1)
    forbid: tuple[CodepointItem, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_side(self) -> Self:
        if (self.allow is None) == (self.forbid is None):
            msg = (
                "a charset rule declares exactly one of allow: / forbid: — the two are "
                "opposite readings of one set, and declaring both states a policy twice "
                "with nothing making the halves agree"
            )
            raise ValueError(msg)
        return self


class UniqueRule(QualityRule):
    """``{rule: unique}`` — evaluated **per partition slice** in both full and
    incremental runs (RFC 0016 D5); cross-partition duplicates are key-based
    dedupe's job in every mode, and sampling is rejected outright."""

    rule: Literal["unique"]
    # A property of a population, not of a value: no rewrite of one row's
    # column can make a duplicate unique, and the predicate is a window
    # besides.
    repairable: ClassVar[bool] = False


FieldQualityRule = Annotated[
    CoercibleRule
    | NotNullRule
    | RangeRule
    | LengthRule
    | PatternRule
    | InEnumRule
    | InSetRule
    | NormalizeRule
    | CharsetRule
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
    # A row rule names no column, so there is nothing for a recipe to rewrite.
    repairable: ClassVar[bool] = False

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


class Coverage(SpecModel):
    """One cross-entity **coverage** check (RFC 0016 §10 → D90) — §10's "every
    customer has ≥1 order", made declarable.

    §10 guessed "probably reconcile-style". It is not: a ``reconcile`` compares
    two *values* and alerts when they differ beyond a tolerance, while this
    asserts *existence* — there is no right-hand value on the referenced entity
    to compare against, and ``right: 1`` is not a shape the reconcile grammar
    admits or should.

    It is a property of a declared **relationship**, which is what makes it
    expressible at all: ``referential`` already asks whether every *dependent*
    row has a parent, and this asks the mirror question — whether every
    *referenced* row has at least ``min`` dependents. Both read the same two
    relations through the same ``via`` pairs.

    **Why it is an audit and not a disposition-carrying rule.** A childless
    customer is a perfectly well-formed row; what is "wrong" is another table's
    contents. Routing it would need the referenced entity's model to read the
    dependent one — and the dependent one already reads the referenced one
    through this very relationship, so the pair that most wants this check is
    exactly the pair whose models would form a cycle. The audit is attached to
    the **dependent** side instead, which already depends on the referenced
    side, so the check adds no edge the relationship did not already imply.
    """

    name: RuleName
    relationship: str
    #: The minimum number of dependent rows each referenced row must have.
    #: ``1`` is §10's case; higher values state "every order has at least two
    #: lines" without a second surface.
    min: int = Field(default=1, ge=1)
    #: ``fail`` blocks the run, ``flag`` reports beside it — the two readings
    #: ``reconcile.on_fail`` carries (D38). ``quarantine`` and ``repair`` are
    #: absent: an audit attached to the dependent side cannot route a row of
    #: the referenced one, and pretending otherwise would be the silent
    #: degradation RFC 0008 D3 refuses.
    on_fail: Literal["flag", "fail"]


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
    #: Narrower than a rule's ``OnFailName`` (RFC 0016 D92). A reconcile
    #: compares two *aggregates*, so there is no row to divert: ``quarantine``
    #: has nothing to route and ``repair`` has no recipe surface to carry one.
    #: Both used to parse — ``repair`` lowered to ``OnFail.REPAIR`` with no
    #: recipe and no fallback, went non-blocking, and wrote "repair" into the
    #: quality mart's disposition column as if it meant something.
    on_fail: Literal["flag", "fail"]

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
