"""The RFC 0016 §5.7 amendment to ``plan()``: how the data-quality surface
classifies, and when a change opens a **replay** rather than just a backfill.

One test per branch of the matrix, because the matrix *is* the feature: the
whole reason cleansing lives in the spec is that "this change needs a
backfill" and "this change needs the reject table drained" become computed
facts instead of remembered ones.

| change                                   | class     | backfill | replay |
|------------------------------------------|-----------|----------|--------|
| rule added                               | RESTATING | yes      | no     |
| rule removed (was ``flag``)              | RESTATING | yes      | no     |
| rule removed (was ``quarantine``)        | RESTATING | yes      | **yes**|
| disposition ``flag`` → ``quarantine``    | RESTATING | yes      | no     |
| disposition ``quarantine`` → ``flag``    | RESTATING | yes      | **yes**|
| settings changed on a quarantining rule  | RESTATING | yes      | **yes**|
| settings changed on a flagging rule      | RESTATING | yes      | no     |
| ``dedupe`` added / removed / changed     | RESTATING | yes      | no     |
| ``quarantine.retention`` changed         | ADDITIVE  | no       | no     |
| ``quarantine.redact`` narrowed           | ADDITIVE  | no       | no     |
| ``quarantine.redact`` widened            | RESTATING | no       | no     |
| ``mapping_version`` bumped               | ADDITIVE  | no       | no     |
| reject ``raw`` payload widened           | ADDITIVE  | no       | no     |
| reject ``raw`` payload narrowed          | RESTATING | no       | no     |
| reconcile added                          | ADDITIVE  | no       | no     |
| reconcile removed / changed              | RESTATING | no       | no     |

A ``redact:`` **swap** is both a widening and a narrowing and reports as both
(D59); the last three rows are the reject table's own stored schema and report
only where a reject table exists on both sides of the change (D60).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from support.plan_ir import entity, project, quality_rule

from bloomery import plan
from bloomery.ir import DedupeIR, EntityIR, OnFail, QuarantineIR, ReconcileIR
from bloomery.plan import Change, ChangeClass

pytestmark = pytest.mark.unit

FLAG_RULE = quality_rule(name="amount_positive", on_fail=OnFail.FLAG)
QUARANTINE_RULE = quality_rule(name="amount_positive", on_fail=OnFail.QUARANTINE)


def _plan_of(old_entity: EntityIR, new_entity: EntityIR) -> tuple[Change, ...]:
    return plan(project(entities=(old_entity,)), project(entities=(new_entity,))).changes


def _one(old_entity: EntityIR, new_entity: EntityIR) -> Change:
    (change,) = _plan_of(old_entity, new_entity)
    return change


def _scopes(old_entity: EntityIR, new_entity: EntityIR) -> tuple[tuple[str, ...], tuple[str, ...]]:
    result = plan(project(entities=(old_entity,)), project(entities=(new_entity,)))
    return result.backfill_scope.entities, result.replay_scope.entities


# ....................... #
# Rules: add / remove / change


def test_adding_a_rule_restates_and_backfills_but_never_replays() -> None:
    """A new rule can only *remove* rows from the entity going forward; it
    cannot make an already-quarantined row pass."""
    change = _one(entity(), entity(quality=(QUARANTINE_RULE,)))
    assert change.change_class is ChangeClass.RESTATING
    assert change.subject == "quality:amount_positive"
    assert change.detail == "quality rule added (range)"
    assert change.new == "quarantine"
    assert _scopes(entity(), entity(quality=(QUARANTINE_RULE,))) == (("order_item",), ())


def test_removing_a_quarantining_rule_opens_a_replay() -> None:
    """The rows it quarantined are in the reject table, not in bronze's
    incremental window — a backfill alone cannot bring them back (§5.7)."""
    old, new = entity(quality=(QUARANTINE_RULE,)), entity()
    change = _one(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert change.detail == "quality rule removed (range)"
    assert change.old == "quarantine"
    assert _scopes(old, new) == (("order_item",), ("order_item",))


def test_removing_a_flagging_rule_needs_no_replay() -> None:
    """Nothing sits in the reject table on a flag rule's account, so replaying
    would drain nothing: a scope naming entities with nothing to replay is a
    scope nobody can act on."""
    old, new = entity(quality=(FLAG_RULE,)), entity()
    assert _one(old, new).change_class is ChangeClass.RESTATING
    assert _scopes(old, new) == (("order_item",), ())


def test_tightening_a_disposition_backfills_without_replay() -> None:
    old, new = entity(quality=(FLAG_RULE,)), entity(quality=(QUARANTINE_RULE,))
    change = _one(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert change.detail == "quality rule changed (disposition)"
    assert (change.old, change.new) == ("flag", "quarantine")
    assert _scopes(old, new) == (("order_item",), ())


def test_relaxing_a_disposition_opens_a_replay() -> None:
    """RFC 0016 §5.7's named case: ``quarantine → flag`` needs a quarantine
    replay, not just a backfill."""
    old, new = entity(quality=(QUARANTINE_RULE,)), entity(quality=(FLAG_RULE,))
    change = _one(old, new)
    assert change.detail == "quality rule changed (disposition)"
    assert (change.old, change.new) == ("quarantine", "flag")
    assert _scopes(old, new) == (("order_item",), ("order_item",))


def test_widening_a_bound_on_a_quarantining_rule_opens_a_replay() -> None:
    """A widened bound is the same situation as a relaxed disposition: rows the
    *old* rule quarantined now pass, and they are only in the reject table."""
    old = entity(quality=(QUARANTINE_RULE,))
    new = entity(quality=(quality_rule(name="amount_positive", params=(("min", "-100"),)),))
    change = _one(old, new)
    assert change.detail == "quality rule changed (settings)"
    assert _scopes(old, new) == (("order_item",), ("order_item",))


def test_narrowing_a_bound_on_a_quarantining_rule_needs_no_replay() -> None:
    """A tightening restates and backfills but frees nothing (D52): every row
    the old rule diverted, the new one diverts too. Naming the entity anyway
    hands a replay runner rows that the run will only quarantine again."""
    old = entity(quality=(QUARANTINE_RULE,))
    new = entity(quality=(quality_rule(name="amount_positive", params=(("min", "5"),)),))
    assert _one(old, new).detail == "quality rule changed (settings)"
    assert _scopes(old, new) == (("order_item",), ())


def test_relaxing_to_fail_needs_no_replay() -> None:
    """``quarantine → fail`` leaves ``quarantine`` but *tightens*: the rows in
    the reject table still violate the rule, and replaying them now halts the
    pipeline on the new blocking audit rather than freeing anything."""
    old = entity(quality=(QUARANTINE_RULE,))
    new = entity(quality=(quality_rule(name="amount_positive", on_fail=OnFail.FAIL),))
    change = _one(old, new)
    assert (change.old, change.new) == ("quarantine", "fail")
    assert _scopes(old, new) == (("order_item",), ())


def test_moving_to_fail_while_widening_the_bound_still_replays() -> None:
    """The rows the widened bound now admits can only come back through the
    reject table, whatever the disposition of the ones that still fail."""
    old = entity(quality=(QUARANTINE_RULE,))
    new = entity(
        quality=(
            quality_rule(name="amount_positive", on_fail=OnFail.FAIL, params=(("min", "-100"),)),
        )
    )
    assert _scopes(old, new) == (("order_item",), ("order_item",))


def _in_enum(*values: str, on_fail: OnFail = OnFail.QUARANTINE) -> EntityIR:
    return entity(
        quality=(
            quality_rule(
                name="status_in_enum",
                kind="in_enum",
                column_name="status",
                on_fail=on_fail,
                params=tuple((f"value_{i:04d}", value) for i, value in enumerate(values)),
            ),
        )
    )


def test_widening_an_admissible_set_replays_and_narrowing_does_not() -> None:
    """A membership rule is the one shape where relaxation is plainly readable:
    the new set either contains the old one or it does not."""
    narrow, wide = _in_enum("paid", "pending"), _in_enum("paid", "pending", "refunded")
    assert _scopes(narrow, wide) == (("order_item",), ("order_item",))
    assert _scopes(wide, narrow) == (("order_item",), ())


def test_an_opaque_settings_change_on_a_quarantining_rule_still_replays() -> None:
    """A regex is not orderable, so widening and narrowing are indistinguishable
    from the params (D52). The undecidable case reports the replay: a scope with
    nothing to drain is noise, a stranded row is data loss."""
    old = entity(
        quality=(
            quality_rule(
                name="sku_pattern", kind="pattern", column_name="sku", params=(("regex", "^A+$"),)
            ),
        )
    )
    new = entity(
        quality=(
            quality_rule(
                name="sku_pattern", kind="pattern", column_name="sku", params=(("regex", "^B+$"),)
            ),
        )
    )
    assert _scopes(old, new) == (("order_item",), ("order_item",))


def test_changing_settings_on_a_flagging_rule_needs_no_replay() -> None:
    old = entity(quality=(FLAG_RULE,))
    new = entity(
        quality=(
            quality_rule(name="amount_positive", on_fail=OnFail.FLAG, params=(("min", "-100"),)),
        )
    )
    assert _one(old, new).detail == "quality rule changed (settings)"
    assert _scopes(old, new) == (("order_item",), ())


REFERENTIAL_PARAMS = (
    ("relationship", "item_of_order"),
    ("to_entity", "order"),
    ("via_0000", "a=b"),
)


def _referential(on_missing: str) -> EntityIR:
    return entity(
        quality=(
            quality_rule(
                name="item_of_order_referential",
                kind="referential",
                column_name=None,
                on_fail=None,
                params=(*REFERENTIAL_PARAMS, ("on_missing", on_missing)),
            ),
        )
    )


@pytest.mark.parametrize(
    ("old_missing", "new_missing", "replay"),
    [
        # ``unknown_member`` and ``flag`` both keep the row, so the shipped
        # ``disposition()`` mapped them to the same ``OnFail`` and the differ
        # saw nothing at all — while the emitted SQL gains or loses its
        # ``'__unknown__'`` CASE and every stored fk restates.
        ("unknown_member", "flag", ()),
        ("flag", "unknown_member", ()),
        # Diverting starts: nothing sits in the reject table on this rule's
        # account yet, so there is nothing to replay.
        ("unknown_member", "quarantine", ()),
        ("flag", "quarantine", ()),
        # Diverting stops: the rows it diverted are only in the reject table.
        ("quarantine", "unknown_member", ("order_item",)),
        ("quarantine", "flag", ("order_item",)),
    ],
)
def test_every_referential_disposition_change_restates(
    old_missing: str, new_missing: str, replay: tuple[str, ...]
) -> None:
    """``referential`` carries ``on_missing``, not ``on_fail``, and D11 wants
    disposition changes classified in **both** directions — so the diff
    compares ``on_missing`` itself rather than the ``OnFail`` it collapses to."""
    old, new = _referential(old_missing), _referential(new_missing)
    change = _one(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert change.detail == "quality rule changed (disposition)"
    assert (change.old, change.new) == (old_missing, new_missing)
    assert _scopes(old, new) == (("order_item",), replay)


def test_an_unchanged_rule_produces_nothing() -> None:
    assert _plan_of(entity(quality=(QUARANTINE_RULE,)), entity(quality=(QUARANTINE_RULE,))) == ()


# ....................... #
# dedupe


DEDUPE = DedupeIR(keep="latest_by", field="_ingested_at", tie_break=("_load_id",))


@pytest.mark.parametrize(
    ("old_dedupe", "new_dedupe", "facets"),
    [
        (None, DEDUPE, "keep, field, tie_break"),
        (DEDUPE, None, "keep, field, tie_break"),
        (DEDUPE, DedupeIR(keep="latest_by", field="_loaded_at", tie_break=("_load_id",)), "field"),
        (DEDUPE, DedupeIR(keep="latest_by", field="_ingested_at", tie_break=()), "tie_break"),
    ],
)
def test_dedupe_changes_restate_and_backfill(
    old_dedupe: DedupeIR | None, new_dedupe: DedupeIR | None, facets: str
) -> None:
    """Dedupe decides which row wins per key, so changing it changes stored
    history. It never replays: the reject table is rebuilt by the backfill."""
    old, new = entity(dedupe=old_dedupe), entity(dedupe=new_dedupe)
    change = _one(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert change.subject == "dedupe:order_item"
    assert change.detail == f"dedupe changed ({facets})"
    assert _scopes(old, new) == (("order_item",), ())


# ....................... #
# quarantine: retention and redaction


def test_retention_change_is_additive_policy() -> None:
    old = entity(quarantine=QuarantineIR(retention="90d"))
    new = entity(quarantine=QuarantineIR(retention="30d"))
    change = _one(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert change.subject == "quarantine:order_item"
    assert (change.old, change.new) == ("90d", "30d")
    assert _scopes(old, new) == ((), ())


def test_widening_redact_restates_without_backfill_or_replay() -> None:
    """It destroys payload going forward, so reject rows written from now on
    mean something different — but neither a backfill nor a replay can restore
    a path the write path is removing."""
    old = entity(quarantine=QuarantineIR(retention="90d"))
    new = entity(quarantine=QuarantineIR(retention="90d", redact=("$.note",)))
    change = _one(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert "redact widened ($.note)" in change.detail
    assert _scopes(old, new) == ((), ())


def test_narrowing_redact_is_additive() -> None:
    old = entity(quarantine=QuarantineIR(retention="90d", redact=("$.note",)))
    new = entity(quarantine=QuarantineIR(retention="90d"))
    change = _one(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert "redact narrowed ($.note)" in change.detail


def test_swapping_a_redact_path_reports_both_directions() -> None:
    """A swap is a widening **and** a narrowing. The widening alone is the
    dangerous half, but the narrowing is a PII-governance fact (§5.6): a path
    that used to be scrubbed is now written into the reject table's ``raw``,
    and a caller told only "payload is being destroyed" never learns it."""
    old = entity(quarantine=QuarantineIR(retention="90d", redact=("$.a",)))
    new = entity(quarantine=QuarantineIR(retention="90d", redact=("$.b",)))
    changes = _plan_of(old, new)
    assert [(change.change_class, change.detail.split(" — ")[0]) for change in changes] == [
        (ChangeClass.ADDITIVE, "quarantine redact narrowed ($.a)"),
        (ChangeClass.RESTATING, "quarantine redact widened ($.b)"),
    ]
    assert _scopes(old, new) == ((), ())


def test_adding_a_quarantine_block_reports_only_its_retention() -> None:
    old, new = entity(), entity(quarantine=QuarantineIR(retention="90d"))
    change = _one(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert (change.old, change.new) == (None, "90d")


# ....................... #
# The reject table's stored schema: mapping_version and the `raw` payload (D60)


def _quarantined(*, mapping_version: int = 1, unmapped: tuple[str, ...] = ()) -> EntityIR:
    return entity(
        quarantine=QuarantineIR(retention="90d"),
        mapping_version=mapping_version,
        unmapped=unmapped,
    )


def test_bumping_mapping_version_is_an_additive_reject_stamp() -> None:
    """``mapping_version`` is a stored column of the reject schema (§5.6), so
    the emitted ``<entity>__reject`` model changes — but it is a provenance
    stamp, and a stored row still correctly records the version that rejected
    it."""
    old, new = _quarantined(), _quarantined(mapping_version=2)
    change = _one(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert change.subject == "quarantine:order_item"
    assert change.detail == "mapping_version changed (reject provenance stamp)"
    assert (change.old, change.new) == ("1", "2")
    assert _scopes(old, new) == ((), ())


def test_acknowledging_an_unmapped_path_widens_the_reject_payload() -> None:
    """``unmapped:`` decides which bronze columns ``raw`` carries, so adding
    one widens the payload: more is kept from now on, nothing stored changes."""
    old, new = _quarantined(), _quarantined(unmapped=("$.note",))
    change = _one(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert change.subject == "quarantine:order_item"
    assert "reject payload widened (note)" in change.detail
    assert _scopes(old, new) == ((), ())


def test_dropping_an_unmapped_path_narrows_the_reject_payload_and_restates() -> None:
    """The mirror of a widened ``redact:``: reject rows written from now on
    carry less than the stored ones, and neither a backfill nor a replay can
    restore a column the write path no longer projects."""
    old, new = _quarantined(unmapped=("$.note",)), _quarantined()
    change = _one(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert "reject payload narrowed (note)" in change.detail
    assert _scopes(old, new) == ((), ())


def test_unmapped_is_diffed_at_bronze_column_granularity() -> None:
    """``raw`` is keyed by top-level bronze column, so ``$.a.b`` → ``$.a.c``
    emits the identical model — reporting it would be a change nobody can act
    on (the D52 discipline)."""
    old, new = _quarantined(unmapped=("$.a.b",)), _quarantined(unmapped=("$.a.c",))
    assert _plan_of(old, new) == ()


def test_reject_schema_facts_are_silent_without_a_quarantine_block() -> None:
    """No quarantine policy, no reject model — neither field reaches an
    artifact, so neither is a change a caller can act on."""
    assert _plan_of(entity(), entity(mapping_version=7, unmapped=("$.note",))) == ()


# ....................... #
# reconcile (project-level: never an entity backfill)


def _check(name: str = "totals_match", *, tolerance: str = "0.01") -> ReconcileIR:
    return ReconcileIR(
        name=name,
        left="sum(order_item.amount) by order_id",
        right="order.total",
        tolerance=Decimal(tolerance),
        on_fail=OnFail.FLAG,
    )


def test_adding_a_reconcile_check_is_additive() -> None:
    """ADDITIVE rather than RESTATING, and deliberately: RFC 0007 D2's
    initial-deploy property says ``plan(None, ir)`` is all-ADDITIVE, and an
    initial deploy adds every reconcile check there is."""
    result = plan(project(), project(reconcile=(_check(),)))
    (change,) = result.changes
    assert change.change_class is ChangeClass.ADDITIVE
    assert (change.entity, change.subject) == (None, "reconcile:totals_match")
    assert result.backfill_scope.entities == ()


def test_changing_a_reconcile_check_restates_at_the_check() -> None:
    result = plan(project(reconcile=(_check(),)), project(reconcile=(_check(tolerance="1.00"),)))
    (change,) = result.changes
    assert change.change_class is ChangeClass.RESTATING
    assert change.subject == "reconcile:totals_match"
    # It routes no row and invalidates no entity.
    assert result.backfill_scope.entities == ()
    assert result.backfill_scope.restates_history
    assert result.replay_scope.entities == ()


def test_removing_a_reconcile_check_restates() -> None:
    result = plan(project(reconcile=(_check(),)), project())
    (change,) = result.changes
    assert change.change_class is ChangeClass.RESTATING
    assert change.detail == "reconcile check removed"
    assert result.backfill_scope.entities == ()


def test_removing_the_quarantine_block_is_breaking_not_a_retention_edit() -> None:
    """Reading the removal as a retention change to ``""`` called it "policy
    only". It is not: the ``<entity>__reject`` model stops being emitted and
    every unresolved row in it goes with it. RFC 0016 D2 buys quarantine over
    drop *for* recoverability and §5.6 names retention as the only deleter —
    this deletes reject rows by removing the table, and the plan has to say
    so before someone applies it."""
    old = entity(
        quality=(
            quality_rule(
                name="amount_range_min",
                kind="range",
                column_name="amount",
                on_fail=OnFail.QUARANTINE,
                params=(("min", "0"),),
            ),
        ),
        quarantine=QuarantineIR(retention="90d"),
    )
    new = entity()
    changes = _plan_of(old, new)
    removal = next(c for c in changes if c.subject == "quarantine:order_item")
    assert removal.change_class is ChangeClass.BREAKING
    assert (removal.old, removal.new) == ("90d", None)
    assert "no longer emitted" in removal.detail
    # The replay scope stays: with the BREAKING change beside it, it stops
    # being a dangling instruction and becomes "drain this before applying".
    _backfill, replay = _scopes(old, new)
    assert replay == ("order_item",)


def test_a_narrowed_set_does_not_replay_when_a_type_marker_shares_a_value() -> None:
    """D62 gives an ``in_set`` holding any int a ``numeric_NNNN`` marker per
    member whose *value* is the string ``"true"``/``"false"``. Flattening every
    param value into one membership set mixed those in with the literals, so
    narrowing a set that contains the literal ``"false"`` left the flattened
    set unchanged — a tightening reported as a relaxation, replaying rows that
    a narrowing cannot free."""
    def _in_set(*params: tuple[str, str]) -> EntityIR:
        return entity(
            quality=(
                quality_rule(
                    name="kind_in_set",
                    kind="in_set",
                    column_name="kind",
                    on_fail=OnFail.QUARANTINE,
                    params=params,
                ),
            )
        )

    # [1, "true", "false"] -> [1, "true"], spelled as the lowering spells it.
    old = _in_set(
        ("numeric_0000", "true"),
        ("numeric_0001", "false"),
        ("numeric_0002", "false"),
        ("value_0000", "1"),
        ("value_0001", "true"),
        ("value_0002", "false"),
    )
    new = _in_set(
        ("numeric_0000", "true"),
        ("numeric_0001", "false"),
        ("value_0000", "1"),
        ("value_0001", "true"),
    )
    _backfill, replay = _scopes(old, new)
    assert replay == ()


def test_a_widened_set_still_replays_with_the_markers_present() -> None:
    """The other direction, so the fix above cannot be "never replay"."""
    def _in_set(*params: tuple[str, str]) -> EntityIR:
        return entity(
            quality=(
                quality_rule(
                    name="kind_in_set",
                    kind="in_set",
                    column_name="kind",
                    on_fail=OnFail.QUARANTINE,
                    params=params,
                ),
            )
        )

    old = _in_set(("numeric_0000", "true"), ("value_0000", "1"))
    new = _in_set(("numeric_0000", "true"), ("numeric_0001", "false"), ("value_0000", "1"), ("value_0001", "x"))
    _backfill, replay = _scopes(old, new)
    assert replay == ("order_item",)


# ....................... #
# A swap admits previously-rejected rows although it relaxes nothing (D81)


def _bounded(minimum: str | None, maximum: str | None) -> EntityIR:
    params = tuple(
        (name, value)
        for name, value in (("min", minimum), ("max", maximum))
        if value is not None
    )
    return entity(
        quality=(
            quality_rule(
                name="amount_range",
                kind="range",
                column_name="amount",
                on_fail=OnFail.QUARANTINE,
                params=params,
            ),
        )
    )


def test_swapping_a_set_member_replays_although_it_is_not_a_widening() -> None:
    """`["a"] → ["b"]` is a widening and a narrowing at once, so the superset
    reading answered "not relaxed" and named no scope — while every row
    quarantined on `b` had become admissible and stayed in the reject table
    with nothing pointing at it. Replay asks whether the new rule admits
    something the old one rejected, which a swap plainly does."""
    assert _scopes(_in_enum("a"), _in_enum("b")) == (("order_item",), ("order_item",))


def test_a_partial_set_swap_replays_too() -> None:
    """The realistic shape: one member retired, one introduced."""
    assert _scopes(_in_enum("a", "b"), _in_enum("b", "c")) == (
        ("order_item",),
        ("order_item",),
    )


def test_shifting_an_interval_replays_although_it_widens_neither_end() -> None:
    """`0..10 → 5..20` drops no floor and so failed the old floor-*and*-ceiling
    conjunction — leaving a row quarantined at 15, squarely inside the new
    interval, stranded."""
    assert _scopes(_bounded("0", "10"), _bounded("5", "20")) == (
        ("order_item",),
        ("order_item",),
    )


def test_shifting_an_interval_the_other_way_replays_on_the_dropped_floor() -> None:
    assert _scopes(_bounded("5", "20"), _bounded("0", "10")) == (
        ("order_item",),
        ("order_item",),
    )


def test_a_strictly_tightened_interval_still_does_not_replay() -> None:
    """The control the `or` must not break: nothing outside the old interval
    is admitted, so no quarantined row can come back."""
    assert _scopes(_bounded("0", "20"), _bounded("5", "10")) == (("order_item",), ())


def test_raising_only_the_ceiling_replays_and_raising_only_the_floor_does_not() -> None:
    """One end moving is enough to free rows, or to free none."""
    assert _scopes(_bounded("0", "10"), _bounded("0", "20")) == (
        ("order_item",),
        ("order_item",),
    )
    assert _scopes(_bounded("0", "10"), _bounded("5", "10")) == (("order_item",), ())


# ....................... #
# Temporal range bounds are ordered, not read as undecidable (D57 × D81)


def test_a_tightened_timestamp_range_does_not_replay() -> None:
    """RFC 0016 D57 permits ISO date/timestamp `range` bounds — the string
    carrier exists for them. Parsing every bound as `Decimal` raised on those,
    which the caller read as "undecidable" and therefore replayable, so a pure
    temporal *tightening* scheduled a MERGE that can free nothing. Under
    `quarantine → fail` that is worse than noise: it feeds the replay runner
    rows that trip the new blocking audit."""
    wide = _bounded("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    tight = _bounded("2021-01-01T00:00:00Z", "2029-01-01T00:00:00Z")
    assert _scopes(wide, tight) == (("order_item",), ())


def test_a_widened_timestamp_range_replays() -> None:
    wide = _bounded("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    tight = _bounded("2021-01-01T00:00:00Z", "2029-01-01T00:00:00Z")
    assert _scopes(tight, wide) == (("order_item",), ("order_item",))


def test_a_shifted_timestamp_range_replays() -> None:
    """The D81 swap, in the temporal carrier."""
    old = _bounded("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z")
    new = _bounded("2025-01-01T00:00:00Z", "2035-01-01T00:00:00Z")
    assert _scopes(old, new) == (("order_item",), ("order_item",))


def test_date_only_bounds_order_too() -> None:
    assert _scopes(_bounded("2020-01-01", "2030-01-01"), _bounded("2021-01-01", "2029-01-01")) == (
        ("order_item",),
        (),
    )


def test_an_offset_bound_is_ordered_by_instant_not_by_text() -> None:
    """ISO text is not lexicographically ordered, which is why the bounds are
    parsed rather than compared as strings. `2020-01-01T05:00:00+06:00` is the
    *earlier* instant than `2020-01-01T00:00:00Z` (it is 2019-12-31T23:00Z)
    while sorting after it as text — so the two readings disagree here, in
    both directions."""
    utc, offset = "2020-01-01T00:00:00Z", "2020-01-01T05:00:00+06:00"
    ceiling = "2030-01-01T00:00:00Z"
    # The floor moves earlier: a widening, which a text comparison would miss.
    assert _scopes(_bounded(utc, ceiling), _bounded(offset, ceiling)) == (
        ("order_item",),
        ("order_item",),
    )
    # ...and back: the floor moves later, a tightening a text comparison would
    # have called a widening and replayed for nothing.
    assert _scopes(_bounded(offset, ceiling), _bounded(utc, ceiling)) == (("order_item",), ())


def test_bounds_of_different_kinds_are_undecidable_and_replay() -> None:
    """A naive bound and an aware one cannot be compared at all (Python
    refuses), and a decimal cannot be compared to a timestamp. Undecidable
    reports the replay — the conservative direction, per D52."""
    naive = _bounded("2020-01-01T00:00:00", "2030-01-01T00:00:00")
    aware = _bounded("2021-01-01T00:00:00Z", "2029-01-01T00:00:00Z")
    assert _scopes(naive, aware) == (("order_item",), ("order_item",))
    assert _scopes(_bounded("0", "10"), _bounded("2021-01-01", "2029-01-01")) == (
        ("order_item",),
        ("order_item",),
    )


def test_an_unparseable_bound_is_undecidable_and_replays() -> None:
    """The spec layer refuses these at parse, so this is the belt-and-braces
    branch — but it is reachable through a hand-built IR, and the `pragma: no
    cover` that used to sit on it was simply false once D57 admitted temporal
    bounds."""
    assert _scopes(_bounded("0", "10"), _bounded("0", "not-a-bound")) == (
        ("order_item",),
        ("order_item",),
    )
