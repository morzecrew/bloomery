"""``charset`` member sets: from ``U+`` items to the characters a predicate
compares against (RFC 0016 §5.3, D86).

The spec surface validates *spelling* — ``U+200B``, ``U+0020-U+007E``, and
nothing else (``CODEPOINT_ITEM_PATTERN``). What it cannot decide from a regex
is decided here, and every refusal is a property of the declaration alone, so
all three are compile-time :class:`~bloomery.errors.GuardrailError`\\ s in the
§5.9 sense rather than run-time dispositions.

Owned by ``quality/`` rather than ``spec/`` because both consumers live here:
:mod:`bloomery.quality.lower` checks a declaration while building the IR, and
:mod:`bloomery.quality.predicates` expands the same items into the ``TRANSLATE``
literal. Putting the expansion in the spec layer would have made the predicate
builders — which know nothing but the IR — import it upward.
"""

from __future__ import annotations

from typing import Final

from bloomery.errors import GuardrailError

# ----------------------- #

__all__ = [
    "MAX_CHARSET_SIZE",
    "expand_codepoints",
]

#: The largest character set a ``charset`` rule may expand to. The set becomes
#: a string *literal* inside every row's predicate, so an unbounded range
#: (``U+0000-U+10FFFF`` is a legal spelling) would put a megabyte of text into
#: the emitted SQL and a megabyte into the IR fingerprint. 1024 is far above
#: any real declaration — printable ASCII is 95, Latin-1 is 191, the invisible
#: class is a dozen — and far below the size at which the artifact stops being
#: reviewable, which is the property this protects.
MAX_CHARSET_SIZE: Final[int] = 1024

#: The UTF-16 surrogate block. These are not characters: no encoder can
#: represent one, so a set naming them describes a value that cannot reach the
#: column. The corpus carries the specimen (``unicode.csv``'s
#: ``lone_surrogate_escape``) precisely because what production delivers is the
#: six-character *escape sequence*, never the codepoint.
_SURROGATES: Final[range] = range(0xD800, 0xE000)


def _codepoint(text: str, *, item: str, where: str) -> int:
    value = int(text.removeprefix("U+"), 16)

    if value > 0x10FFFF:
        msg = (
            f"charset item {item!r} on {where} names {text}, which is past the last Unicode "
            "codepoint U+10FFFF"
        )
        raise GuardrailError(msg)

    return value


# ....................... #


def expand_codepoints(items: tuple[str, ...], *, where: str) -> str:
    """The declared items as one sorted, deduplicated character string.

    Sorted by codepoint and deduplicated so that two spellings of one set —
    ``[U+0041, U+0042]`` and ``[U+0041-U+0042]``, or the same character named
    twice — produce identical bytes. The IR carries the *items* (reviewable);
    this is what the predicate compares against.

    ``where`` names the rule for the error message; it never reaches output.

    The surrogate check is on the *span*, not on the endpoints, which is the
    only version of it that can fire: the block is 2048 codepoints wide, so a
    range crossing it always exceeds :data:`MAX_CHARSET_SIZE` first, and an
    endpoint-only check would leave the real refusal to depend on a size
    constant that has nothing to do with surrogates.
    """
    codepoints: set[int] = set()

    for item in items:
        low_text, _, high_text = item.partition("-")
        low = _codepoint(low_text, item=item, where=where)
        high = _codepoint(high_text, item=item, where=where) if high_text else low
        if high < low:
            msg = (
                f"charset item {item!r} on {where} runs backwards — its range ends before it "
                "begins. Write the lower codepoint first"
            )
            raise GuardrailError(msg)
        span = range(low, high + 1)
        if low < _SURROGATES.stop and _SURROGATES.start <= high:
            msg = (
                f"charset item {item!r} on {where} covers the surrogate block "
                "U+D800-U+DFFF. Surrogates are not characters — no UTF-8 value can contain "
                "one — so naming them describes something the column cannot hold. A lone "
                "surrogate arrives as its six-character escape sequence, which is made of "
                "ordinary characters; name those, or split the range around the block"
            )
            raise GuardrailError(msg)
        if len(span) > MAX_CHARSET_SIZE:
            msg = (
                f"charset item {item!r} on {where} covers {len(span)} codepoints, past the "
                f"{MAX_CHARSET_SIZE} a set may hold: the whole set becomes a string literal in "
                "every row's predicate and in the IR fingerprint"
            )
            raise GuardrailError(msg)
        codepoints.update(span)

    if len(codepoints) > MAX_CHARSET_SIZE:
        msg = (
            f"charset set on {where} expands to {len(codepoints)} characters, past the "
            f"{MAX_CHARSET_SIZE} a set may hold"
        )
        raise GuardrailError(msg)

    return "".join(chr(code) for code in sorted(codepoints))
