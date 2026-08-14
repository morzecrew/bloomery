"""A demonstration identity resolver — the *body* the platform would own.

RFC 0021 §5.1 settles identity resolution as a Tier 3 step rather than a spec
kind, and the evidence for "settled" is a fixture that runs, not a paragraph.
This is the half of that fixture bloomery never sees: the step's own code,
which lives with the platform's registry and is imported by the generated
wrapper at run time.

**It is a demonstration, not a resolver.** The matching is naive on purpose —
exact email, then a normalized-name comparison, no blocking beyond that, no
tuning, no library. Its value is the *wiring* it makes real: two sources with
no shared key in, one canonical entity and a crosswalk out, both satisfying the
manifest's declared contract. A production step swaps this body and changes
nothing else, which is the property RFC 0017 exists to provide.

It lives under ``tests/support/`` for the reason :mod:`support.steps` gives
about manifests: ``fixtures/`` holds YAML spec projects only
(``tests/README.md``), and a step body is neither a spec nor bloomery's. RFC
0021 §5.1 sketched it under ``tests/fixtures/identity_resolution/registry/``,
which would have put Python inside the spec corpus and broken that rule.

**Deterministic by construction**, because the manifest declares
``determinism: pure`` and the fixture would otherwise be lying: canonical ids
are derived from the winning email or normalized name, never from a counter, a
clock or an iteration order, so the same rows in any order give the same ids.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "RESOLVED_AT",
    "canonical_id",
    "normalize_name",
    "resolve",
]

#: The resolution timestamp the demonstration stamps. A constant rather than a
#: clock: `determinism: pure` is a claim the fixture has to be able to keep,
#: and a step reading the wall clock produces a different `resolved_at` on
#: every backfill of the same window — the failure `runtime_lock` and the
#: determinism tier exist to catch (RFC 0017 D5).
RESOLVED_AT = pd.Timestamp("2026-01-01T00:00:00")

_PUNCTUATION = re.compile(r"[^a-z0-9]+")


def normalize_name(value: object) -> str:
    """A name reduced to what two spellings of one person share.

    NFKD-folded, lowercased, punctuation collapsed, tokens sorted — so
    ``"Ada Lovelace"``, ``"lovelace, ada"`` and ``"Ada  Lovelace"`` agree.
    Sorting the tokens is what makes surname-first and given-name-first
    orderings match, which is the single most common shape of the same person
    written twice.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    folded = unicodedata.normalize("NFKD", str(value)).casefold()
    stripped = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(sorted(token for token in _PUNCTUATION.split(stripped) if token))


def canonical_id(seed: str) -> str:
    """``cust_`` plus a short digest of the matching key.

    Derived from the key rather than assigned from a counter, so the id a row
    gets does not depend on the order rows arrived in — which is what makes
    two runs over the same data produce the same crosswalk, and what lets the
    consistency audit between the siblings mean anything.
    """
    return "cust_" + hashlib.sha256(seed.encode()).hexdigest()[:12]


def _rows(frame: pd.DataFrame) -> Iterable[Mapping[str, object]]:
    return frame.to_dict(orient="records")


def resolve(
    crm: pd.DataFrame, billing: pd.DataFrame, *, threshold: Decimal
) -> dict[str, pd.DataFrame]:
    """The step's entrypoint: two source frames in, two declared outputs out.

    The signature is the manifest's, keyword for keyword — the generated
    wrapper calls ``resolve(**inputs, **parameters)``, so a rename here is a
    run-time failure and not a compile-time one. That is the trade RFC 0017
    D4 accepts, and why the contract assertion runs on every execution.

    Matching, in order: an exact email match, then an exact normalized-name
    match. Everything else is its own person. Confidence is ``1.0`` for an
    email match and ``0.85`` for a name match, and ``threshold`` is what a
    second tenant turns up to refuse the second kind — the parameterize-never-
    fork rule, exercised rather than described.
    """
    by_key: dict[str, str] = {}
    xref: list[dict[str, object]] = []
    customers: dict[str, dict[str, object]] = {}

    for source in (crm, billing):
        for row in _rows(source):
            email = str(row.get("email") or "").strip()
            name_key = normalize_name(row.get("name"))
            # Email first: it is the stronger signal, and preferring it keeps
            # the outcome independent of which source is read first.
            key, method, confidence = (
                (f"email:{email}", "exact", Decimal("1.000"))
                if email
                else (f"name:{name_key}", "fuzzy", Decimal("0.850"))
            )
            if confidence < threshold:
                # Below the wiring's bar this row resolves to nobody. It still
                # appears in the crosswalk, with a NULL canonical_id: "we could
                # not resolve this" is a fact the warehouse should carry, and
                # dropping the row would make it look like the source never had
                # it. The consistency audit is three-valued for this reason.
                xref.append(
                    {
                        "source_system": row["source_system"],
                        "source_id": row["source_id"],
                        "canonical_id": None,
                        "method": "none",
                    }
                )
                continue
            identifier = by_key.setdefault(key, canonical_id(key))
            customers.setdefault(
                identifier,
                {
                    "canonical_id": identifier,
                    "confidence": confidence,
                    "resolved_at": RESOLVED_AT,
                },
            )
            xref.append(
                {
                    "source_system": row["source_system"],
                    "source_id": row["source_id"],
                    "canonical_id": identifier,
                    "method": method,
                }
            )

    return {
        "customer": pd.DataFrame(
            sorted(customers.values(), key=lambda each: str(each["canonical_id"])),
            columns=["canonical_id", "confidence", "resolved_at"],
        ),
        "customer_xref": pd.DataFrame(
            xref, columns=["source_system", "source_id", "canonical_id", "method"]
        ),
    }
