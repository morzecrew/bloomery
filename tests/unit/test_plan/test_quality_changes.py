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
| reconcile added                          | ADDITIVE  | no       | no     |
| reconcile removed / changed              | RESTATING | no       | no     |
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


def test_adding_a_quarantine_block_reports_only_its_retention() -> None:
    old, new = entity(), entity(quarantine=QuarantineIR(retention="90d"))
    change = _one(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert (change.old, change.new) == (None, "90d")


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
