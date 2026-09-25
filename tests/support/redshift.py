"""The Redshift surrogate harness (S-0015): the fixture split the local lane
reads, built before there is a lane to read it.

Floci gives a Redshift-shaped control plane over a real PostgreSQL container,
and LocalStack emulates the AWS control plane and Data API. Both are the
*surrogate* rung — evidence, never the oracle (S-0012/D-1) — and a lane using
either marks itself

.. code-block:: python

    @pytest.mark.surrogate("redshift_postgres")

so a CI log never reads as "Redshift passed". LocalStack stays optional while
bloomery is a pure compiler (S-0015/D-5): it emulates surfaces the compiler does
not touch, so no lane is blocked on it.

**The split (S-0015/D-3).** Fixtures fall into two named classes, and the native
class never runs on the surrogate: PostgreSQL is not an oracle for ``SUPER``,
PartiQL, Redshift-only functions or Redshift's own type rules, so a green run
over a native fixture would be a claim the lane cannot make. Without the split
the lane's coverage number silently includes cases it cannot speak to, which is
how a partial lane comes to be read as a full one.

Nothing consumes this yet — the lane is phase 2. It is here because the split is
cheap before there are fixtures and expensive afterwards.

**Why the classification is derived rather than listed.** A hand-kept list of
native fixtures is right on the day it is written and silently wrong the day a
fixture gains a ``variant`` field or a ``quarantine:`` block — and the failure
is invisible, because a fixture that quietly moves into the compatible class
makes the lane look *better*. So the classes are computed from what the port
actually emits, against the port's own Redshift-only vocabulary below.
"""

from __future__ import annotations

from bloomery.errors import BloomeryError
from support.compiling import compile_fixture, spec_fixture_names

# ----------------------- #

#: The two classes, spelled as S-0015/D-3 spells them.
POSTGRES_COMPATIBLE = "postgres-compatible"
REDSHIFT_NATIVE = "redshift-native"

#: The surrogate marker a lane over :func:`surrogate_fixtures` carries.
SURROGATE = "redshift_postgres"

#: Redshift-only spellings :class:`~bloomery.dialects.redshift.RedshiftDialect`
#: emits, each one a construct PostgreSQL either does not define or reads
#: differently — so a fixture whose SQL contains any of them is `redshift-native`
#: and the surrogate is not its oracle:
#:
#: * ``SUPER``, ``JSON_PARSE``, ``CAN_JSON_PARSE``, ``OBJECT(`` — the ``SUPER``
#:   data model (S-0015/D-4). PostgreSQL has none of the three functions.
#: * ``CONVERT_TIMEZONE`` — Redshift's zone conversion, absent in PostgreSQL,
#:   which spells the same thing ``AT TIME ZONE`` and (per S-0025/D-3) means
#:   something else by it.
#: * ``REGEXP_SUBSTR`` with a match parameter — the same function name in both,
#:   with a different argument list and a different reading of the third
#:   argument, which is exactly the "plausible-looking spelling" class.
#: * ``SHA2`` — Redshift's text digest. PostgreSQL's ``sha256`` takes and
#:   returns ``bytea``, which is why the PostgreSQL port spells it differently.
#: * ``GETDATE`` — Redshift's session clock, no PostgreSQL equivalent.
NATIVE_SPELLINGS = (
    "CAN_JSON_PARSE",
    "CONVERT_TIMEZONE",
    "GETDATE",
    "JSON_PARSE",
    "OBJECT(",
    "REGEXP_SUBSTR",
    "SHA2(",
    "SUPER",
)

#: Divergences that are **not** discriminators and so must not be read as one.
#: Every fixture's DDL carries ``VARCHAR(MAX)`` — Redshift's ``string``, and a
#: type PostgreSQL does not parse at all. It is a property of the port rather
#: than of any fixture, so it cannot separate the classes; a lane on the
#: surrogate has to answer for it once, for every fixture alike. Named here so
#: that "postgres-compatible" is read as "no Redshift-only *construct*" and not
#: as "runs on PostgreSQL unchanged".
PORT_WIDE_DIVERGENCES = ("VARCHAR(MAX)",)


def classify(fixture_name: str) -> str | None:
    """Which class ``fixture_name`` is in, or ``None`` if it emits no SQL here.

    ``None`` is not a third class: it is a fixture the port never renders —
    either a refusal fixture, which is refused on every dialect and exists to
    be, or one this port declines (``dirty_corpus``, whose ``normalize`` rule
    needs a normalization function Redshift does not have). Neither has emitted
    SQL for a lane to run, so neither belongs in a class; returning ``None``
    keeps that visible instead of parking them in the compatible class, where
    they would inflate its count and never run.
    """

    try:
        artifacts = compile_fixture(fixture_name, dialect="redshift")
    except BloomeryError:
        return None

    sql = "\n".join(artifact.content for artifact in artifacts)
    native = any(spelling in sql for spelling in NATIVE_SPELLINGS)

    return REDSHIFT_NATIVE if native else POSTGRES_COMPATIBLE


def fixtures_by_class() -> dict[str, tuple[str, ...]]:
    """Every spec fixture the port renders, under its class name."""

    classified: dict[str, list[str]] = {POSTGRES_COMPATIBLE: [], REDSHIFT_NATIVE: []}

    for name in spec_fixture_names():
        name_class = classify(name)

        if name_class is not None:
            classified[name_class].append(name)

    return {key: tuple(names) for key, names in classified.items()}


def surrogate_fixtures() -> tuple[str, ...]:
    """The fixtures a lane on the PostgreSQL-backed surrogate may run.

    The compatible class and nothing else — this is the function that makes
    S-0015/D-3 a mechanism rather than a note, because a lane parametrized on it
    cannot reach a native fixture by forgetting to exclude one.
    """

    return fixtures_by_class()[POSTGRES_COMPATIBLE]
