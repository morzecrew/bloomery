"""Every engine difference the differential is allowed to see (S-0092/D-3).

An engine difference is either a **written decision** or a defect, never a
tolerance. This table is the register of the written ones: an engine, a
transform, a predicate over the input, what the engine is held to instead — a
value, or a bound on its answer against the reference's — and the decision row
or ``path:line`` that makes it legitimate.

A disagreement no row names fails the differential, printing the input, the
engine's answer and the reference's. That is the whole point: without this
table a wide comparison silently widens with each engine quirk, and a genuine
regression hides inside the slack.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["DIFERENCES", "Difference", "difference_for"]


@dataclass(frozen=True)
class Difference:
    """One allowed engine difference.

    ``held_to`` takes the engine's answer and the reference's and decides
    whether the engine is within what this row licenses — for a value, the
    engine must equal it; for a bound, it must come close enough to the
    reference. It is consulted only once the exact comparison has already
    disagreed, so a row that happens to be satisfied by exactness costs
    nothing.
    """

    engine: str
    transform: str
    predicate: Callable[[Any], bool]
    held_to: Callable[[Any, Any], bool]
    justification: str


#: DuckDB answers ``''`` where the portable reading of an out-of-range
#: ``split_part`` is NULL (``nullifies=True``, and the comment above it says as
#: much). The engine is held to ``''`` exactly, not to a wideness — and only
#: over a **present** input: a NULL source is NULL on both sides, so licensing
#: it would let a regression that turns NULL into empty text pass as an
#: out-of-range difference.
_SPLIT_PART = Difference(
    engine="duckdb",
    transform="split_part",
    predicate=lambda source: source is not None,
    held_to=lambda produced, reference: produced == ("" if reference is None else reference),
    justification=(
        "src/bloomery/transforms/_builtins.py:264 — split_part declares "
        "nullifies=True on the portable NULL reading; DuckDB answers '' for an "
        "out-of-range index"
    ),
)


#: The same shape for ``regex_extract``, whose no-match answer is ``''`` on
#: DuckDB and NULL on Trino and PostgreSQL — over a present input only, for the
#: same reason as ``split_part`` above.
_REGEX_EXTRACT = Difference(
    engine="duckdb",
    transform="regex_extract",
    predicate=lambda source: source is not None,
    held_to=lambda produced, reference: produced == ("" if reference is None else reference),
    justification=(
        "src/bloomery/transforms/_builtins.py:285 — regex_extract declares "
        "nullifies=True on the portable NULL reading; DuckDB answers '' when "
        "the pattern does not match"
    ),
)


def _one_unit(produced: Any, reference: Any) -> bool:
    """Whether ``produced`` is within one unit in the last place of ``reference``."""
    if not isinstance(produced, Decimal) or not isinstance(reference, Decimal):
        return False
    exponent = reference.as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return abs(produced - reference) <= Decimal(1).scaleb(-scale)


#: DuckDB's ``/`` is float division, so ``divide`` cannot be exact there — the
#: divisor marker keeps the other ports exact and leaves DuckDB bounded by its
#: narrowing cast (S-0046/D-3, S-0046/what-fixed-looks-like; S-0092/D-8). The
#: engine is held to within one unit of the declared scale, never to a value.
_DIVIDE = Difference(
    engine="duckdb",
    transform="divide",
    predicate=lambda source: True,
    held_to=_one_unit,
    justification=(
        "src/bloomery/dialects/base.py:335 — _exact_division leaves DuckDB's "
        "float division bounded by the narrowing cast; S-0092/D-8 records the "
        "difference as a row rather than a tolerance"
    ),
)


#: Every allowed difference, in a stable order.
DIFERENCES: tuple[Difference, ...] = (
    _SPLIT_PART,
    _REGEX_EXTRACT,
    _DIVIDE,
)


def difference_for(engine: str, transform: str, source: Any) -> Difference | None:
    """The first row licensing an answer for this case, or ``None``."""
    for row in DIFERENCES:
        if row.engine == engine and row.transform == transform and row.predicate(source):
            return row
    return None