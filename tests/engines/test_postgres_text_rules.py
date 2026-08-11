"""Engine tier (RFC 0009 §5.2 tier 5): ``normalize`` and ``charset`` on real
PostgreSQL (RFC 0016 D86).

Both rules rest on a claim about *engines*, not about SQL: that Postgres spells
``NORMALIZE(x, NFC)`` the way the dialect-neutral node renders, and that its
``TRANSLATE`` deletes a character when the ``to`` argument is shorter. Neither
is decidable by rendering, and D83's finding was precisely a dialect that
declared two capabilities and had neither — so both are asserted against the
engine, at the port, with the *same predicate the emitter emits*.

Trino was verified the same way against ``trinodb/trino:483`` and agrees on
every row below; it has no permanent tier here only because the repository
carries no Trino client dependency (RFC 0009's outstanding work).

Opt-in (Docker required); excluded from ``just test``.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from bloomery.dialects import get_dialect
from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import violation

pytestmark = pytest.mark.engine("postgres")

_PORT = get_dialect("postgres")

#: ``café`` decomposed and precomposed; ``Acme``/``Corp`` with and without a
#: zero-width space between them. Escapes, not literals: a specimen that looks
#: identical to its control in a diff cannot be reviewed.
NFD_CAFE = "cafe\u0301"
NFC_CAFE = "caf\u00e9"
ZWSP_NAME = "Acme\u200bCorp"
CLEAN_NAME = "AcmeCorp"

#: ``(value, normalize fires, forbid fires, allow fires)`` — the allow set is
#: printable ASCII, so it fires on anything the other two see and on ``café``
#: besides.
ROWS: list[tuple[str | None, bool | None, bool | None, bool | None]] = [
    (NFD_CAFE, True, False, True),
    (NFC_CAFE, False, False, True),
    (ZWSP_NAME, False, True, True),
    (CLEAN_NAME, False, False, False),
    # D19, on the engine: every one of these stays UNKNOWN over a null.
    (None, None, None, None),
]


def _normalize_rule() -> QualityRuleIR:
    return QualityRuleIR(
        name="name_normalize",
        kind="normalize",
        column="name",
        on_fail=OnFail.FLAG,
        params=(("form", "nfc"),),
    )


def _charset_rule(side: str, item: str) -> QualityRuleIR:
    return QualityRuleIR(
        name=f"name_charset_{side}",
        kind="charset",
        column="name",
        on_fail=OnFail.FLAG,
        params=((f"{side}_0000", item),),
    )


@pytest.fixture(scope="module")
def text_db() -> Iterator[psycopg.Connection]:
    with PostgresContainer("postgres:16-alpine", driver=None) as container:
        conn = psycopg.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        # A real table, not a VALUES list folded at plan time — the D84 trap:
        # Postgres evaluates a constant subquery during planning, so a
        # predicate probed over one is not the predicate a row meets.
        conn.execute("CREATE TABLE names (ord int, name text)")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO names VALUES (%s, %s)",
                [(index, row[0]) for index, row in enumerate(ROWS)],
            )
        conn.commit()
        yield conn
        conn.close()


def _verdicts(conn: psycopg.Connection, rule: QualityRuleIR) -> list[bool | None]:
    predicate = _PORT.render(violation(rule))
    rows = conn.execute(f"SELECT ord, ({predicate}) FROM names ORDER BY ord").fetchall()
    return [fired for _ord, fired in rows]


def test_normalize_fires_on_the_decomposed_spelling_and_nothing_else(
    text_db: psycopg.Connection,
) -> None:
    """The claim that ``NORMALIZE(x, NFC)`` is Postgres' spelling, checked by
    running it rather than by reading a manual."""
    assert _verdicts(text_db, _normalize_rule()) == [row[1] for row in ROWS]


def test_charset_forbid_fires_on_the_value_holding_the_member(
    text_db: psycopg.Connection,
) -> None:
    """``TRANSLATE(x, members, '')`` deleting rather than substituting is the
    whole construction; a Postgres that padded instead would make the predicate
    silently never fire."""
    assert _verdicts(text_db, _charset_rule("forbid", "U+200B")) == [row[2] for row in ROWS]


def test_charset_allow_fires_on_anything_outside_the_set(text_db: psycopg.Connection) -> None:
    assert _verdicts(text_db, _charset_rule("allow", "U+0020-U+007E")) == [row[3] for row in ROWS]


def test_the_two_readings_disagree_on_the_same_set(text_db: psycopg.Connection) -> None:
    """One ``TRANSLATE`` serves both, so they must be opposites on the engine
    too — not merely in the AST."""
    allowed = _verdicts(text_db, _charset_rule("allow", "U+0041-U+007A"))
    forbidden = _verdicts(text_db, _charset_rule("forbid", "U+0041-U+007A"))
    clean = ROWS.index((CLEAN_NAME, False, False, False))
    assert (allowed[clean], forbidden[clean]) == (False, True)
