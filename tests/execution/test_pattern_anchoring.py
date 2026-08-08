"""The portable regex subset, executed (RFC 0016 §5.3, D53/D54).

The subset check is a *static* claim about what DuckDB (RE2), Trino (RE2) and
Postgres (ARE) will accept, and a static claim about an engine is only worth
what an engine says. So this module asks DuckDB directly, from both ends:

- an **anchored** pattern — the only form the spec surface accepts — must fire
  on a value that merely *contains* a match. §5.3 says patterns are anchored;
  before D54 nothing enforced it, and `[0-9]{5}` accepted `abc12345xyz`;
- every construct the allowlist refuses must be a construct DuckDB **aborts**
  on, not one it quietly reinterprets. That is the pairing that keeps the
  refusal list honest rather than superstitious.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest

from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import violation
from bloomery.spec.quality import PatternRule

pytestmark = pytest.mark.execution

#: Constructs the denylist waved through, each verified to abort on DuckDB.
ABORTING = (
    r"(a)\1",  # backreference
    "(?>abc)",  # atomic group
    "a*+",  # possessive quantifier
    r"\A\d+\Z",  # text anchors
)


@pytest.fixture(scope="module")
def connection() -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect()
    yield con
    con.close()


def _fires(connection: duckdb.DuckDBPyConnection, regex: str, value: str) -> bool:
    """The rule's violation predicate, lowered and executed against ``value``.

    Built from a :class:`QualityRuleIR` and rendered through the same
    :func:`violation` the models are emitted from — this is the shipped SQL
    semantics, not a re-implementation of them.
    """
    rule = QualityRuleIR(
        name="code_pattern",
        kind="pattern",
        column="code",
        on_fail=OnFail.FLAG,
        params=(("regex", regex),),
    )
    predicate = violation(rule).sql(dialect="duckdb")
    row = connection.execute(f"SELECT {predicate} FROM (SELECT ? AS code)", [value]).fetchone()
    assert row is not None
    return bool(row[0])


def test_an_anchored_pattern_rejects_a_substring_match(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    regex = PatternRule(rule="pattern", regex="^[0-9]{5}$", on_fail="flag").regex
    assert _fires(connection, regex, "abc12345xyz") is True  # violated: not the whole value
    assert _fires(connection, regex, "12345") is False


def test_the_unanchored_form_is_unreachable_and_would_have_matched(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    # what the spec surface now refuses ...
    with pytest.raises(ValueError, match="not anchored"):
        PatternRule(rule="pattern", regex="[0-9]{5}", on_fail="flag")
    # ... and why: unanchored, the emitted predicate accepts the substring
    assert _fires(connection, "[0-9]{5}", "abc12345xyz") is False


@pytest.mark.parametrize("regex", ABORTING)
def test_a_refused_construct_is_one_duckdb_aborts_on(
    connection: duckdb.DuckDBPyConnection, regex: str
) -> None:
    with pytest.raises(ValueError, match="portable regex subset"):
        PatternRule(rule="pattern", regex=f"^{regex}$", on_fail="flag")
    with pytest.raises(duckdb.Error):
        connection.execute("SELECT regexp_matches('abc12345xyz', ?)", [regex]).fetchone()


@pytest.mark.parametrize(
    ("regex", "value", "violated"),
    [
        (r"^-?[0-9]+(?:\.[0-9]{1,9})?$", "-12.50", False),
        (r"^-?[0-9]+(?:\.[0-9]{1,9})?$", "12.5e3", True),
        (r"^[a-z\d_-]{1,8}$", "ok_1-2", False),
        (r"^[^\\]*$", "back\\slash", True),
        ("^(?:AA|BB)$", "BB", False),
        ("^(?:AA|BB)$", "AABB", True),
    ],
)
def test_the_accepted_subset_means_on_duckdb_what_the_scanner_promises(
    connection: duckdb.DuckDBPyConnection, regex: str, value: str, violated: bool
) -> None:
    accepted = PatternRule(rule="pattern", regex=regex, on_fail="flag").regex
    assert _fires(connection, accepted, value) is violated
