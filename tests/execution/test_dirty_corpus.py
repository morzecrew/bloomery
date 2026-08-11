"""The dirty corpus, executed (RFC 0016 §6 — the execution row).

§6 states the doctrine this module exists to obey: assert survivors **and
quarantine contents**, because "a test that only checks what passed cannot tell
'correctly quarantined' from 'silently dropped'". So every assertion here reads
:func:`support.dirty.dispositions`, which reads *both* sides of the two-way
split and reports a row's rule names either way.

The corpus's ``_expected`` column is the assertion table. It records the
disposition under the documented **default rule set**, and
``tests/fixtures/dirty_corpus/`` declares exactly that rule set — which is what
turns a curated CSV into a regression suite rather than a comment.

Two documented departures from "assert ``_expected`` for every row", both from
the corpus's own README:

- ``_expected = dialect_divergent`` marks rows whose disposition is a property
  of the *engine*, not of the data (DuckDB accepts an exponent in a DECIMAL
  cast and trims before casting; other engines do neither). §6 assigns them to
  the dialect matrix, so this module asserts only that the outcome is
  *recorded consistently* on both sides of the split — never a single answer.
- ``unicode.csv`` used to be the second: its ``flag`` marks encode "contains an
  invisible or deceptive character", which no v1 rule expressed. D86's
  ``normalize`` and ``charset`` rules closed that down to **two rows**, named
  and argued for in :data:`UNDECIDABLE_UNICODE` — and neither is a gap a bigger
  character set would close, because what is wrong with each is a fact about
  *context* or *position* rather than about the value's characters.
"""

from __future__ import annotations

from collections.abc import Iterator

import duckdb
import pytest
from support.compiling import compile_fixture
from support.dirty import (
    DIALECT_DIVERGENT,
    FIXTURE,
    FLAGGED,
    KEPT,
    QUARANTINED,
    audits_of,
    build_corpus,
    cases,
    dispositions,
    expected,
)
from support.execution import audit_body

pytestmark = pytest.mark.execution


@pytest.fixture(scope="module")
def corpus_run() -> Iterator[duckdb.DuckDBPyConnection]:
    """One dirty run for the whole module: seed, compile, materialize.

    Module-scoped and read-only — twelve entity models, twelve reject models
    and the gold layer are the same artifacts for every assertion below, and
    rebuilding them per test would buy nothing but wall clock.
    """
    connection = build_corpus()
    yield connection
    connection.close()


#: ``entity → corpus file``. Every family in the corpus appears exactly once,
#: except ``extremes.csv``, which fans out by its own ``raw_kind`` column
#: because a single entity cannot declare ``raw_value`` decimal here and
#: timestamp there.
FAMILIES: dict[str, str] = {
    "dirty_number": "numerics.csv",
    "dirty_date": "dates.csv",
    "dirty_status": "enums.csv",
    "dirty_ref": "refs.csv",
    "dirty_name": "unicode.csv",
    "dirty_decimal_extreme": "extremes.csv",
    "dirty_integer_extreme": "extremes.csv",
    "dirty_timestamp_extreme": "extremes.csv",
    "dirty_text_extreme": "extremes.csv",
}

#: The unicode specimens no v1 rule decides, with the reason each is beyond a
#: rule's reach — ``{case: why}``. D26 recorded the whole family as
#: unassertable; D86's ``normalize`` and ``charset`` rules left exactly these
#: two, and neither is a gap a *bigger character set* would close.
#:
#: Named here rather than dropped from :data:`FAMILIES`, so the exclusion is
#: reviewable, has to be argued for, and shrinks visibly in a diff.
UNDECIDABLE_UNICODE: dict[str, str] = {
    # `emoji_zwj_sequence` needs U+200D and `zero_width_joiner` must not have
    # it. Same codepoint, opposite verdicts: what separates them is what sits
    # on either side, which is not a property of the character.
    "zero_width_joiner": "the joiner's legitimacy is contextual, not a set membership",
    # A combining acute with no base character. The value is well-formed, in
    # NFC, and holds no forbidden character — what is wrong with it is *where*
    # the mark sits, which neither a normal form nor a character set can see.
    "combining_mark_alone": "a mark with no base is a positional property, not a value one",
}

#: ``_expected``'s own vocabulary for "the row survives with its fk rewritten
#: to the reserved member". It folds onto ``flag``, because that is what the
#: lowering does with it: the row is kept and the rule's firing is recorded —
#: never quarantined, which would divert the very row the reserved member
#: exists to keep (:func:`~bloomery.quality.disposition`).
UNKNOWN_MEMBER = "unknown_member"


def _observed(entity: str, conn: duckdb.DuckDBPyConnection, corpus_file: str) -> dict[str, str]:
    """``{_case: observed disposition}`` for the rows of ``corpus_file`` that
    this entity was actually seeded with."""
    landed = dispositions(conn, entity)
    return {
        case: landed[row_id][0] for row_id, case in cases(corpus_file).items() if row_id in landed
    }


@pytest.mark.parametrize(("entity", "corpus_file"), sorted(FAMILIES.items()))
def test_every_specimen_lands_where_the_corpus_says(
    corpus_run: duckdb.DuckDBPyConnection, entity: str, corpus_file: str
) -> None:
    """The corpus's ``_expected`` column, asserted row by row.

    ``unknown_member`` is folded onto ``flag`` because that is what the
    lowering does with it (D19/§5.4): the row is kept, its fk rewritten, and
    the rule's firing recorded — never quarantined, which would divert the very
    row the reserved member exists to keep.
    """
    declared = expected(corpus_file)
    observed = _observed(entity, corpus_run, corpus_file)
    assert observed, f"{entity} was seeded with no row of {corpus_file}"
    for case, disposition in sorted(observed.items()):
        wanted = declared[case]
        if wanted == DIALECT_DIVERGENT:
            continue  # asserted for consistency below, never for an answer
        if corpus_file == "unicode.csv" and case in UNDECIDABLE_UNICODE:
            continue  # the two rows nothing in the catalogue reaches
        if wanted == UNKNOWN_MEMBER:
            wanted = FLAGGED
        assert disposition == wanted, f"{corpus_file}:{case}"


def test_uncastable_numerics_quarantine_carrying_the_coercible_rule(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """The reject side, named: every quarantined numeric records
    ``amount_coercible``, so the reject row is a readable account of *why* the
    row is not in the entity (§5.6) rather than a row that merely vanished."""
    landed = dispositions(corpus_run, "dirty_number")
    declared = expected("numerics.csv")
    quarantined = {
        case: landed[row_id][1]
        for row_id, case in cases("numerics.csv").items()
        if declared[case] == QUARANTINED
    }
    assert quarantined  # the family exists at all
    for case, rules in sorted(quarantined.items()):
        assert "amount_coercible" in rules, f"numerics.csv:{case}"


def test_uncastable_dates_quarantine_carrying_the_coercible_rule(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """``leap_second`` is the specimen that makes the declared type matter: it
    casts cleanly to DATE on DuckDB (which truncates) and not to TIMESTAMP, so
    a date-typed field would silently admit a row the corpus quarantines."""
    landed = dispositions(corpus_run, "dirty_date")
    row_ids = cases("dates.csv")
    declared = expected("dates.csv")
    for row_id, case in sorted(row_ids.items()):
        if declared[case] != QUARANTINED:
            continue
        assert "observed_at_coercible" in landed[row_id][1], f"dates.csv:{case}"


def test_enum_outliers_quarantine_on_in_enum_not_on_coercion(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """The retired ``on_unmapped_enum`` policy, replaced (§5.2, D3): an
    unmapped enum value simply fails ``in_enum`` and takes that rule's
    disposition. ``in_set`` fires alongside on the untouched text — a second
    reason recorded on the same reject row (D18), not a second reject row."""
    landed = dispositions(corpus_run, "dirty_status")
    declared = expected("enums.csv")
    for row_id, case in sorted(cases("enums.csv").items()):
        disposition, rules = landed[row_id]
        if declared[case] == KEPT:
            assert (disposition, rules) == (KEPT, ()), f"enums.csv:{case}"
            continue
        assert disposition == QUARANTINED, f"enums.csv:{case}"
        assert "status_in_enum" in rules, f"enums.csv:{case}"
        assert "status_text_in_set" in rules, f"enums.csv:{case}"
        assert "status_coercible" not in rules  # membership, not coercion


def test_the_widening_candidates_are_quarantined_and_therefore_replayable(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """``valid_but_unmapped`` and its twin are real upstream statuses the spec
    does not yet know — RFC 0016 calls enum widening "the normal path, not the
    exception". Here they sit in the reject table with their raw payload
    intact, which is the precondition for the replay walkthrough
    (``test_quarantine_replay``); the misspelling beside them must stay
    quarantined *after* the widening, so it is pinned here too."""
    landed = dispositions(corpus_run, "dirty_status")
    by_case = {case: row_id for row_id, case in cases("enums.csv").items()}
    for case in ("valid_but_unmapped", "valid_but_unmapped_2", "misspelling"):
        assert landed[by_case[case]][0] == QUARANTINED
    raw = dict(
        corpus_run.execute(
            "SELECT raw ->> '$._case', raw ->> '$.raw_status' FROM silver.dirty_status__reject"
        ).fetchall()
    )
    assert raw["valid_but_unmapped"] == "authorized"
    assert raw["valid_but_unmapped_2"] == "partially_refunded"


def test_referential_orphans_keep_their_row_and_gain_the_reserved_member(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """``on_missing: unknown_member`` keeps aggregates correct (§5.3): the row
    stays, its fk becomes ``'__unknown__'``, and the rule name lands in
    ``_quality_flags``. The NULL fk beside it is **not** an orphan (D19) — the
    correction of Document 5's bare ``COALESCE`` sketch — and the row that
    points at a parent which quarantines on its own rules *is* one, because
    ``referential`` reads the referenced **silver** entity, after cleansing."""
    by_row_id = cases("refs.csv")
    rows = {
        by_row_id[str(row_id)]: (customer_ref, parent_ref, tuple(flags or ()))
        for row_id, customer_ref, parent_ref, flags in corpus_run.execute(
            "SELECT _source_row_id, customer_ref, parent_ref, _quality_flags FROM silver.dirty_ref"
        ).fetchall()
    }
    assert rows["valid_ref"] == ("C-100", None, ())
    assert rows["null_fk"] == (None, None, ())  # a NULL fk is not an orphan
    assert rows["orphan_fk"][0] == "__unknown__"
    assert rows["orphan_fk"][2] == ("ref_of_customer_referential",)
    # Non-null, empty, no parent — an orphan, and the pair that pins the
    # empty-string-vs-null boundary §6 names in the dialect list.
    assert rows["empty_string_fk"][0] == "__unknown__"
    # The parent exists in bronze and fails its own rules, so it never reaches
    # silver: an orphan *after* cleansing, the ordering-sensitive case.
    assert rows["fk_to_quarantined_parent"][0] == "__unknown__"
    assert rows["fk_to_own_entity_reject"][1] == "__unknown__"
    # Orphanhood does not cascade: this points at a row that survived with only
    # its own fk rewritten.
    assert rows["chained_ref_to_rewritten_row"] == ("C-100", "ORD-2007", ())
    # A source value colliding with the reserved member — accepted and
    # documented (D6), never silently typed around.
    assert rows["fk_collides_with_reserved_member"][0] == "__unknown__"


#: The customer fks of ``refs.csv`` with no surviving referenced row, and the
#: parent fks likewise — read off the file's own notes, so the numbers below
#: are the corpus's statement rather than the run's.
_ORPHANED_CUSTOMER_FKS = (
    "empty_string_fk",
    "fk_case_variant",
    "fk_collides_with_reserved_member",
    "fk_to_quarantined_parent",
    "fk_whitespace_variant",
    "orphan_fk",
)
_ORPHANED_PARENT_FKS = ("fk_to_own_entity_reject", "self_reference_orphan")

#: The one row of the corpus whose synthesized payload is uncastable, and so
#: the only one the ``on_fail: fail`` rule fires on.
_BLOCKING_ROW = "quarantining_parent_row"


def _routed(corpus_run: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, tuple[str, ...]]]:
    by_row_id = cases("refs.csv")
    return {
        by_row_id[row_id]: landed
        for row_id, landed in dispositions(corpus_run, "dirty_ref_routed").items()
    }


def test_referential_at_quarantine_diverts_the_orphan_instead_of_rewriting_it(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """§5.4's second ``referential`` row: the same LEFT JOIN probe, but the
    orphaned *dependent* row diverts to its own reject table with the rule name
    in ``failed_rules``.

    Judged over the same specimens ``unknown_member`` keeps, which is the point
    — the disposition is the only thing that differs, so the two entities
    together say what a disposition *does* rather than merely that each one
    compiles. The NULL fk is still not an orphan under any of them (D19).
    """
    routed = _routed(corpus_run)
    diverted = tuple(
        sorted(case for case, (verdict, _) in routed.items() if verdict == QUARANTINED)
    )
    assert diverted == tuple(sorted((*_ORPHANED_CUSTOMER_FKS, _BLOCKING_ROW)))
    for case in _ORPHANED_CUSTOMER_FKS:
        assert routed[case][1] == ("routed_of_customer_referential",), case
    assert routed["null_fk"] == (KEPT, ())
    assert routed["valid_ref"] == (KEPT, ())


def test_referential_at_flag_keeps_the_orphan_and_records_the_rule(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """§5.4's third ``referential`` row: the row is kept unchanged — fk not
    rewritten, not diverted — and the rule name joins the single flag pass.
    ``flag`` is the disposition that says "I want to know", and the difference
    from ``unknown_member`` is observable only in the *stored fk*, so that is
    what this asserts alongside the flag."""
    routed = _routed(corpus_run)
    for case in _ORPHANED_PARENT_FKS:
        assert routed[case] == (FLAGGED, ("routed_of_parent_referential",)), case
    stored = dict(
        corpus_run.execute(
            "SELECT _source_row_id, parent_ref FROM silver.dirty_ref_routed"
        ).fetchall()
    )
    by_case = {case: row_id for row_id, case in cases("refs.csv").items()}
    # Flagged, never rewritten: the reserved member belongs to `unknown_member`
    # alone, and a `flag` disposition that quietly rewrote the key would make
    # the two dispositions indistinguishable downstream.
    assert stored[by_case["self_reference_orphan"]] == "ORD-9999"


def test_a_fail_rule_blocks_the_run_even_on_a_row_the_split_diverted(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """D18's severity order and D32's audit scope, on live corpus data.

    Until ``dirty_ref_routed`` existed the corpus carried no ``on_fail: fail``
    rule at all, so the disposition that *stops a pipeline* was the one the
    dirty-data regression suite said nothing about. The specimen is chosen so
    the two claims cannot be confused: ``quarantining_parent_row``'s amount is
    uncastable, so the implicit ``coercible`` rule diverts it **and** the
    blocking rule fires on it. An audit over the built model would see only the
    rows the split kept and report nothing, silently letting a quarantine
    disposition beat a fail one.
    """
    artifact = audits_of(compile_fixture(FIXTURE))["dirty_ref_routed_amount_not_null"]
    body = audit_body(artifact, "silver.dirty_ref_routed")
    reported = tuple(
        cases("refs.csv")[str(row_id)]
        for (row_id,) in corpus_run.execute(f"SELECT _source_row_id FROM ({body})").fetchall()
    )
    assert reported == (_BLOCKING_ROW,)
    # The same row is in the reject table, and its account names both rules.
    routed = _routed(corpus_run)
    assert routed[_BLOCKING_ROW] == (QUARANTINED, ("amount_coercible", "amount_not_null"))


def test_the_conservation_audit_is_skipped_where_routing_reads_a_sibling(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """D29's scope limit, as a property of a fixture that actually builds.

    ``dirty_ref_routed`` routes on a ``referential`` rule, whose predicate
    reads a sibling silver entity — and a SQLMesh AUDIT body may not address
    one, because model references inside it are not rewritten to the physical
    snapshot. So this entity gets no conservation audit while every other
    quarantining entity does. Asserted rather than left implicit: a skip nobody
    checks is indistinguishable from an audit that was never generated.
    """
    del corpus_run
    names = set(audits_of(compile_fixture(FIXTURE)))
    assert "dirty_ref_routed_conservation" not in names
    assert "dirty_ref_conservation" in names
    # …and the entity is still audited for the metadata contract (D21), which
    # reads nothing but itself.
    assert "dirty_ref_routed_ingestion_metadata" in names


def test_unicode_rows_are_flagged_never_dropped(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """The invariant the disposition model actually promises (§5.1, D2): there
    is no ``drop``. Every unicode specimen is accounted for on one side of the
    split, and only the row the declared ``pattern`` rule refuses is diverted.

    This is the assertion that held the family together while D26 was open and
    the dispositions themselves were unassertable. It stays after D86 closed
    that, because it says something the row-by-row check does not: whatever a
    rule decides, a flagged row is *kept*, and no specimen leaves the pipeline
    by a third door.
    """
    landed = dispositions(corpus_run, "dirty_name")
    row_ids = cases("unicode.csv")
    assert set(row_ids) == set(landed), "a unicode specimen reached neither side of the split"
    quarantined = {
        row_ids[row_id]
        for row_id, (disposition, _rules) in landed.items()
        if disposition == QUARANTINED
    }
    assert quarantined == {"lone_surrogate_escape"}


@pytest.mark.parametrize(
    ("case", "rule"),
    [
        # The empty STRING: `length` owns it, and `not_null` never sees it.
        ("empty_string_not_null", "name_length_min"),
        # Thirteen codepoints rendering as one grapheme — the upper bound any
        # `length` rule has to have an answer for.
        ("long_grapheme_cluster", "name_length_max"),
        # THE normalization specimen (D86): `café` decomposed. Byte-unequal to
        # the precomposed row beside it, canonically equal to it, and no other
        # rule in the catalogue can tell the two apart.
        ("nfd_form", "name_normalize"),
        # …and the same rule on the row whose base composes under NFC.
        ("long_grapheme_cluster", "name_normalize"),
        # The invisible half of the charset set: each of these renders exactly
        # like `ascii_control`, which is the clean row.
        ("zero_width_space", "name_charset"),
        ("rtl_mark", "name_charset"),
        ("bidi_override", "name_charset"),
        ("soft_hyphen", "name_charset"),
        ("nbsp", "name_charset"),
        ("leading_bom_in_field", "name_charset"),
        ("tab_in_field", "name_charset"),
        ("replacement_char", "name_charset"),
        # The confusable-script half — the rows a denylist of *blocks* reaches
        # and no enumeration of invisible characters ever would.
        ("homoglyph_cyrillic", "name_charset"),
        ("homoglyph_digits_fullwidth", "name_charset"),
        ("arabic_indic_digits", "name_charset"),
    ],
)
def test_the_unicode_rows_a_declared_rule_decides(
    corpus_run: duckdb.DuckDBPyConnection, case: str, rule: str
) -> None:
    landed = dispositions(corpus_run, "dirty_name")
    by_case = {name: row_id for row_id, name in cases("unicode.csv").items()}
    disposition, rules = landed[by_case[case]]
    assert disposition == FLAGGED
    assert rule in rules
    assert expected("unicode.csv")[case] == FLAGGED  # and the corpus agrees


def test_the_null_beside_the_empty_string_fires_nothing(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """D19, on live data: ``LENGTH(NULL)`` is NULL, so the comparison is
    ``UNKNOWN`` and ``length`` stays silent. The corpus pairs a NULL specimen
    against an empty-string one in five files precisely so a reader that
    collapses the two is caught here rather than in a dashboard."""
    landed = dispositions(corpus_run, "dirty_name")
    by_case = {name: row_id for row_id, name in cases("unicode.csv").items()}
    assert landed[by_case["empty_field"]] == (KEPT, ())
    # extremes.csv carries both sides in ONE row, and they belong to different
    # rules: `not_null` owns the NULL, `length` the empty string.
    extreme = dispositions(corpus_run, "dirty_text_extreme")
    extreme_cases = {name: row_id for row_id, name in cases("extremes.csv").items()}
    assert extreme[extreme_cases["empty_string_vs_null"]] == (QUARANTINED, ("value_length",))
    assert extreme[extreme_cases["zero_length_row"]] == (QUARANTINED, ("value_not_null",))


def test_dialect_divergent_rows_are_recorded_consistently_never_lost(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """§6's dialect-matrix row, honoured: these three specimens' dispositions
    are a property of the engine, so the assertion is that *whichever* side
    each lands on, it lands on exactly one and its rules match that side —
    never that it landed on a particular one."""
    landed = dispositions(corpus_run, "dirty_number")
    declared = expected("numerics.csv")
    divergent = {
        case: landed[row_id]
        for row_id, case in cases("numerics.csv").items()
        if declared[case] == DIALECT_DIVERGENT
    }
    assert set(divergent) == {"scientific_notation", "trailing_space", "leading_space"}
    for case, (disposition, rules) in sorted(divergent.items()):
        assert disposition in {KEPT, FLAGGED, QUARANTINED}, case
        # The recording matches the side: a quarantined row names the rule that
        # diverted it; a kept one cannot.
        assert ("amount_coercible" in rules) == (disposition == QUARANTINED), case


def test_reject_ids_are_stable_and_recomputable_from_the_row(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """``reject_id`` = sha256 over the length-prefixed utf-8 pair
    ``(source_relation, _source_row_id)`` (D21) — recomputable from the reject
    row itself, unique across the batch, and deliberately **not** a function of
    ``_load_id``, so a re-delivery lands on the same row rather than minting a
    new one per retry."""
    duplicates = corpus_run.execute(
        "SELECT reject_id FROM silver.dirty_number__reject GROUP BY 1 HAVING COUNT(*) > 1"
    ).fetchall()
    assert duplicates == []
    mismatched = corpus_run.execute(
        "SELECT reject_id FROM silver.dirty_number__reject WHERE reject_id <> SHA256("
        "  'S' || CAST(LENGTH(source_relation) AS TEXT) || ':' || source_relation ||"
        "  'S' || CAST(LENGTH(_source_row_id) AS TEXT) || ':' || _source_row_id)"
    ).fetchall()
    assert mismatched == []


def test_a_reject_row_records_every_failure_including_flag_level_ones(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """D18: a quarantined row's ``failed_rules`` is the *full* account, flag
    failures included — otherwise the reject table explains the diversion but
    not the row."""
    landed = dispositions(corpus_run, "dirty_number")
    by_case = {case: row_id for row_id, case in cases("numerics.csv").items()}
    disposition, rules = landed[by_case["comma_decimal"]]
    assert disposition == QUARANTINED
    # `amount_coercible` quarantined it; `amount_text_pattern` is a flag rule
    # that also fired, and it is recorded all the same.
    assert rules == ("amount_coercible", "amount_text_pattern")


def test_the_flagged_but_castable_row_survives_with_its_precision_loss_named(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """``scale_overflow_rounds`` and ``decimal_sub_ulp``: the cast does not
    fail, it *rounds*. Nothing quarantines, the value silently moves, and the
    only thing standing between that and a wrong dashboard is a flag."""
    numbers = dispositions(corpus_run, "dirty_number")
    by_case = {case: row_id for row_id, case in cases("numerics.csv").items()}
    assert numbers[by_case["scale_overflow_rounds"]] == (FLAGGED, ("amount_text_pattern",))
    extremes = dispositions(corpus_run, "dirty_decimal_extreme")
    extreme_cases = {case: row_id for row_id, case in cases("extremes.csv").items()}
    assert extremes[extreme_cases["decimal_sub_ulp"]] == (FLAGGED, ("value_text_pattern",))


def test_unique_fires_over_the_whole_table_slice_and_stays_silent_on_nulls(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """D5: an unpartitioned FULL entity's ``unique`` slice is the whole table.
    Fifteen ``dirty_ref_parent`` rows share an amount and every one is flagged;
    the sixteenth is NULL after a failed coercion and stays silent, which is
    the explicit ``col IS NOT NULL`` conjunct (D19) — SQL windows group NULLs
    together, so without it two null rows would count as duplicates."""
    flagged, total = corpus_run.execute(
        "SELECT COUNT(*) FILTER (WHERE LIST_CONTAINS(_quality_flags, 'amount_unique')), COUNT(*) "
        "FROM silver.dirty_ref_parent"
    ).fetchone() or (0, 0)
    assert (flagged, total) == (15, 15)
    rejected = corpus_run.execute(
        "SELECT failed_rules FROM silver.dirty_ref_parent__reject"
    ).fetchall()
    assert rejected == [(["amount_coercible"],)]  # the null row, and only coercible


def test_the_range_rule_diverts_the_row_that_casts_and_then_violates_the_bound(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """RFC 0016 §5.3's worked example (``range, min: 0, on_fail: quarantine``)
    on ``dirty_key.amount``, and the specimen D28 recorded the corpus as
    missing.

    Every *other* out-of-bounds value in the corpus is also uncastable, so
    ``coercible`` reaches it first and ``range`` stays ``UNKNOWN`` over the
    resulting NULL (D19). That left the corpus with no specimen for ``range``
    *routing* a row — the rule was live at execution only in the
    ``quality_precedence`` fixture, where it sits at ``fail`` and blocks the run
    rather than diverting anything. ``amount_below_range_min`` casts cleanly and
    then violates the bound, so this is where ``range`` and the two-way split
    meet.
    """
    # ``rows_failed`` only: on a *rule* row the population counts are
    # structurally zero (D34 moved them to the entity's accounting row), so
    # asserting one of them here would be a check that cannot fail.
    rows = corpus_run.execute(
        "SELECT rows_failed FROM gold.mart_data_quality WHERE rule = 'amount_range_min'"
    ).fetchall()
    assert rows == [(1,)]
    by_case = {case: row_id for row_id, case in cases("keys.csv").items()}
    diverted = corpus_run.execute(
        "SELECT _source_row_id, failed_rules FROM silver.dirty_key__reject "
        "WHERE LIST_CONTAINS(failed_rules, 'amount_range_min')"
    ).fetchall()
    assert diverted == [(by_case["amount_below_range_min"], ["amount_range_min"])]


def test_the_inclusive_edge_of_the_range_bound_is_kept(
    corpus_run: duckdb.DuckDBPyConnection,
) -> None:
    """The other half of the pair. ``min`` lowers to ``col < min``, so the bound
    itself is *in* bounds — and the two adjacent specimens one ulp apart are
    what makes an off-by-one in that comparison a test failure rather than a
    silently over-eager quarantine."""
    by_case = {case: row_id for row_id, case in cases("keys.csv").items()}
    landed = dispositions(corpus_run, "dirty_key")
    assert landed[by_case["amount_at_range_min"]] == (KEPT, ())
    assert landed[by_case["amount_below_range_min"]] == (QUARANTINED, ("amount_range_min",))
