"""Data-quality guardrails (RFC 0016 §5.9): every leaf triggers on the model
it is about, stays silent on the model it is not, and batches into the **one**
aggregate the stage raises (RFC 0006 D2).

Each check gets a trigger *and* a non-trigger: a guardrail that never fires is
a guardrail nobody notices is broken, and one that always fires is worse.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from bloomery import build_project_ir, load_project
from bloomery import dialects as dialects_module
from bloomery.dialects import DialectFeature, SQLGlotDialect, register_dialect
from bloomery.quality import pattern as pattern_module
from bloomery.errors import (
    AssertLoweringError,
    DedupeDispositionConflict,
    DedupeTieBreakMissing,
    GuardrailError,
    IngestionMetadataMissing,
    QuarantineRetentionMissing,
    RedactionConflict,
)
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``pattern`` validation reads the process-global dialect registry."""
    monkeypatch.setattr(dialects_module, "_overlay", {})
    yield


METADATA = '["$._load_id", "$._ingested_at", "$._source_row_id"]'


def _project(
    *,
    entity_extra: str = "",
    field_quality: str = "",
    unmapped: str = METADATA,
    fields: str = "      amount: {type: string}\n",
) -> dict[str, str]:
    return {
        "entity_model": f"""
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {{type: string, required: true}}
{fields}{entity_extra}
""",
        "mapping": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [to_string]}}
fields:
  amount:
    from: "$.amount"
    transform: [to_string]
{field_quality}
unmapped: {unmapped}
""",
    }


def _leaves(documents: dict[str, str]) -> list[type[GuardrailError]]:
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(documents))
    return [type(leaf) for leaf in excinfo.value.collected]


def _message(documents: dict[str, str]) -> str:
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(documents))
    return str(excinfo.value)


# ....................... #
# The shipped fixture is the non-trigger for all of them


def test_the_quality_fixture_compiles_clean() -> None:
    project, catalog = load_fixture("semi_additive_inventory")
    assert build_project_ir(project, catalog).entities[0].quality


def test_a_quality_free_project_is_untouched_by_these_checks() -> None:
    project, catalog = load_fixture("minimal")
    assert build_project_ir(project, catalog).entities[0].quality == ()


# ....................... #
# DedupeTieBreakMissing (§5.3, D6)


DEDUPE_NO_TIE_BREAK = "    dedupe: {keep: latest_by, field: _ingested_at}\n"
DEDUPE_OK = "    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}\n"


def test_dedupe_without_tie_break_is_refused() -> None:
    documents = _project(entity_extra=DEDUPE_NO_TIE_BREAK)
    assert _leaves(documents) == [DedupeTieBreakMissing]
    message = _message(documents)
    assert "without tie_break" in message
    assert "nondeterministic model violates the core invariant" in message


def test_dedupe_with_tie_break_is_accepted() -> None:
    build_project_ir(load_project(_project(entity_extra=DEDUPE_OK)))


# ....................... #
# dedupe columns must exist (§5.4, D47)


def test_dedupe_ordering_by_an_undeclared_column_is_refused() -> None:
    """``ORDER BY typo_col DESC`` is a run-time binder failure, and the whole
    point of the guardrail stage is that a spec typo never reaches an engine."""
    documents = _project(
        entity_extra="    dedupe: {keep: latest_by, field: typo_col, tie_break: [_load_id]}\n"
    )
    message = _message(documents)
    assert "dedupe.field reads 'typo_col'" in message
    # The declared columns are named, so the author does not go hunting.
    assert "amount" in message
    assert "_ingested_at" in message


def test_dedupe_tie_breaking_by_an_undeclared_column_is_refused() -> None:
    documents = _project(
        entity_extra="    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [nope]}\n"
    )
    assert "dedupe.tie_break reads 'nope'" in _message(documents)


def test_dedupe_may_order_by_the_ingestion_metadata_columns() -> None:
    """They are legal targets although no mapping *field* declares them: they
    are the ingestion metadata contract (§5.6, D21), not mapped fields."""
    build_project_ir(
        load_project(
            _project(
                entity_extra=(
                    "    dedupe: {keep: latest_by, field: _ingested_at, "
                    "tie_break: [_load_id, _source_row_id]}\n"
                )
            )
        )
    )


def test_dedupe_may_order_by_a_declared_field() -> None:
    build_project_ir(
        load_project(
            _project(
                entity_extra=(
                    "    dedupe: {keep: latest_by, field: amount, tie_break: [order_id]}\n"
                )
            )
        )
    )


# ....................... #
# DedupeDispositionConflict (§5.4, D6)


CONFLICT = """      - {rule: coercible, on_fail: quarantine}
"""


def test_a_weaker_coercible_on_a_dedupe_field_is_refused() -> None:
    documents = _project(
        entity_extra=(
            "    dedupe: {keep: latest_by, field: amount, tie_break: [_load_id]}\n"
            "    quarantine: {retention: 30d}\n"
        ),
        field_quality=f"    quality:\n{CONFLICT}",
    )
    assert DedupeDispositionConflict in _leaves(documents)
    message = _message(documents)
    # The message names both sides: the field and the dedupe clause reading it.
    assert "field 'amount'" in message
    assert "dedupe.field reads 'amount'" in message
    assert "coercible is forced to 'fail'" in message


def test_a_fail_coercible_on_a_dedupe_field_is_accepted() -> None:
    build_project_ir(
        load_project(
            _project(
                entity_extra=(
                    "    dedupe: {keep: latest_by, field: amount, tie_break: [_load_id]}\n"
                    "    quarantine: {retention: 30d}\n"
                ),
                field_quality="    quality:\n      - {rule: coercible, on_fail: fail}\n",
            )
        )
    )


# ....................... #
# QuarantineRetentionMissing (§5.6, D10)


def test_a_quarantine_disposition_without_retention_is_refused() -> None:
    documents = _project(field_quality="    quality:\n      - {rule: not_null, on_fail: flag}\n")
    assert QuarantineRetentionMissing in _leaves(documents)
    message = _message(documents)
    # The implicit coercible rule is the one carrying the quarantine default,
    # so the message says so rather than leaving the author hunting.
    assert "implicit coercible rule carries the quarantine default" in message
    assert "amount_coercible" in message


def test_declaring_the_quarantine_block_satisfies_it() -> None:
    build_project_ir(
        load_project(
            _project(
                entity_extra="    quarantine: {retention: 30d}\n",
                field_quality="    quality:\n      - {rule: not_null, on_fail: flag}\n",
            )
        )
    )


def test_flag_only_rules_still_need_it_because_coercible_is_implicit() -> None:
    """Recorded so the behaviour is deliberate rather than surprising: an
    entity whose *authored* rules are all ``flag`` still has the implicit
    ``coercible`` rule at ``quarantine`` (§5.2) — and key fields carry it too,
    with no spec surface to override them, so a quality-carrying entity always
    owes a ``quarantine:`` block."""
    assert QuarantineRetentionMissing in _leaves(
        _project(field_quality="    quality:\n      - {rule: not_null, on_fail: flag}\n")
    )


def test_an_entity_with_no_quality_surface_owes_no_retention() -> None:
    """The check reads dispositions, not the opt-in flag: an entity that never
    joined the quality system has none, so it is silently fine."""
    build_project_ir(load_project(_project()))


# ....................... #
# IngestionMetadataMissing (§5.6, D21)


def test_dedupe_without_the_metadata_contract_is_refused() -> None:
    documents = _project(entity_extra=DEDUPE_OK, unmapped="[]")
    assert IngestionMetadataMissing in _leaves(documents)
    message = _message(documents)
    assert "must supply the ingestion metadata contract" in message
    assert "'oms__orders'" in message
    assert "_source_row_id" in message


def test_quarantine_without_the_metadata_contract_is_refused() -> None:
    documents = _project(entity_extra="    quarantine: {retention: 30d}\n", unmapped="[]")
    assert IngestionMetadataMissing in _leaves(documents)


def test_acknowledging_the_metadata_in_unmapped_satisfies_it() -> None:
    build_project_ir(load_project(_project(entity_extra=DEDUPE_OK)))


def test_an_entity_using_neither_never_needs_the_metadata() -> None:
    build_project_ir(load_project(_project(unmapped="[]")))


# ....................... #
# RedactionConflict (§5.6, D10)


def test_redacting_a_mapped_path_is_refused() -> None:
    documents = _project(entity_extra='    quarantine: {retention: 30d, redact: ["$.amount"]}\n')
    assert RedactionConflict in _leaves(documents)
    message = _message(documents)
    # Both sides named: the redact path and the mapping that reads it.
    assert "$.amount" in message
    assert "mapping[oms__orders->order]" in message
    assert "replay re-runs the current mapping against raw" in message


def test_redaction_is_refused_at_column_granularity() -> None:
    """``raw`` is the bronze *row*, so redaction removes a whole column — the
    refusal has to match that granularity or the removal would silently take
    a sibling path the mapping reads."""
    documents = {
        "entity_model": """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    quarantine: {retention: 30d, redact: ["$.payload.ssn"]}
    fields:
      order_id: {type: string, required: true}
      note: {type: string}
""",
        "mapping": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [to_string]}}
fields:
  note: {{from: "$.payload.note", transform: [to_string]}}
unmapped: {METADATA}
""",
    }
    assert RedactionConflict in _leaves(documents)


def test_redacting_an_unmapped_path_is_accepted() -> None:
    build_project_ir(
        load_project(
            _project(
                entity_extra='    quarantine: {retention: 30d, redact: ["$.ssn"]}\n',
                unmapped='["$._load_id", "$._ingested_at", "$._source_row_id", "$.ssn"]',
            )
        )
    )


# ....................... #
# pattern portability (§5.3, D5) and unknown_member on a non-string fk (§5.4)


PATTERN_QUALITY = '    quality:\n      - {rule: pattern, regex: "^[0-9]+$", on_fail: flag}\n'


def test_a_pattern_a_target_dialect_cannot_express_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoRegexDialect(SQLGlotDialect):
        name: str = "noregex"
        sqlglot_dialect: str = "duckdb"
        features = frozenset(DialectFeature) - {DialectFeature.REGEXP_EXTRACT}

    # The checked set is the shipped ports, not the registry (RFC 0016 D56) —
    # registering a dialect no longer changes a verdict, so the target set is
    # what a test has to move to reach this refusal.
    register_dialect(NoRegexDialect())
    monkeypatch.setattr(pattern_module, "PATTERN_TARGET_DIALECTS", ("noregex",))
    documents = _project(
        entity_extra="    quarantine: {retention: 30d}\n", field_quality=PATTERN_QUALITY
    )
    message = _message(documents)
    assert "cannot be expressed on dialect(s) noregex" in message
    assert "silently means something else" in message


def test_a_portable_pattern_is_accepted() -> None:
    build_project_ir(
        load_project(
            _project(
                entity_extra="    quarantine: {retention: 30d}\n", field_quality=PATTERN_QUALITY
            )
        )
    )


UNKNOWN_MEMBER_PROJECT = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {{type: {key_type}, required: true}}
  order_item:
    grain: one row per line
    key: [line_id]
    quarantine: {{retention: 30d}}
    quality:
      - {{rule: referential, via: item_of_order, on_missing: unknown_member}}
    fields:
      line_id: {{type: string, required: true}}
      order_id: {{type: {key_type}}}
relationships:
  - name: item_of_order
    from: order_item
    to: order
    via: {{order_id: order_id}}
    cardinality: many_to_one
"""

UNKNOWN_MEMBER_MAPPINGS = {
    "mapping_order": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [{{to_int: []}}]}}
unmapped: {METADATA}
""",
    "mapping_item": f"""
mapping_version: 1
source: oms__lines
target: order_item
key:
  line_id: {{from: "$.id", transform: [to_string]}}
fields:
  order_id: {{from: "$.order_id", transform: [{{to_int: []}}]}}
unmapped: {METADATA}
""",
}


def test_unknown_member_on_a_non_string_fk_is_refused() -> None:
    documents = {
        "entity_model": UNKNOWN_MEMBER_PROJECT.format(key_type="int"),
        **UNKNOWN_MEMBER_MAPPINGS,
    }
    message = _message(documents)
    assert "the reserved member is the string '__unknown__'" in message
    assert "use on_missing: quarantine or flag" in message


def test_unknown_member_on_a_string_fk_is_accepted() -> None:
    documents = {
        "entity_model": UNKNOWN_MEMBER_PROJECT.format(key_type="string"),
        "mapping_order": UNKNOWN_MEMBER_MAPPINGS["mapping_order"].replace(
            "[{to_int: []}]", "[to_string]"
        ),
        "mapping_item": UNKNOWN_MEMBER_MAPPINGS["mapping_item"].replace(
            "[{to_int: []}]", "[to_string]"
        ),
    }
    build_project_ir(load_project(documents))


# ....................... #
# unknown_member on a composite key (§5.4, D48)


COMPOSITE_PROJECT = """
spec_version: 1
entities:
  parent:
    grain: one row per parent
    key: [a_id, b_id]
    fields:
      a_id: {{type: string, required: true}}
      b_id: {{type: {b_type}, required: true}}
  child:
    grain: one row per child
    key: [child_id]
    quarantine: {{retention: 30d}}
    quality:
      - {{rule: referential, via: child_of_parent, on_missing: {on_missing}}}
    fields:
      child_id: {{type: string, required: true}}
      a_id: {{type: string}}
      b_id: {{type: {b_type}}}
relationships:
  - name: child_of_parent
    from: child
    to: parent
    via: {{a_id: a_id, b_id: b_id}}
    cardinality: many_to_one
"""


def _composite(*, b_type: str, on_missing: str) -> dict[str, str]:
    cast = "[to_string]" if b_type == "string" else "[{to_int: []}]"
    return {
        "entity_model": COMPOSITE_PROJECT.format(b_type=b_type, on_missing=on_missing),
        "mapping_parent": f"""
mapping_version: 1
source: src__parent
target: parent
key:
  a_id: {{from: "$.a", transform: [to_string]}}
  b_id: {{from: "$.b", transform: {cast}}}
unmapped: {METADATA}
""",
        "mapping_child": f"""
mapping_version: 1
source: src__child
target: child
key:
  child_id: {{from: "$.id", transform: [to_string]}}
fields:
  a_id: {{from: "$.a", transform: [to_string]}}
  b_id: {{from: "$.b", transform: {cast}}}
unmapped: {METADATA}
""",
    }


def test_unknown_member_on_a_composite_key_is_refused() -> None:
    """The rewrite can only put ``'__unknown__'`` in one column, so a composite
    fk would get a half-sentinel key matching no reserved row — refused whole
    rather than emitted wrong (D48). A non-string second column sorting after a
    string first one used to escape the §5.4 type refusal entirely."""
    message = _message(_composite(b_type="int", on_missing="unknown_member"))
    assert "composite" in message
    assert "a_id, b_id" in message
    assert "use on_missing: quarantine or flag" in message


def test_a_composite_key_referential_is_fine_under_the_other_dispositions() -> None:
    """The refusal is about the *rewrite*, which only ``unknown_member`` does."""
    build_project_ir(load_project(_composite(b_type="int", on_missing="quarantine")))


def test_a_string_composite_key_is_refused_too() -> None:
    """Every column being a string does not help: the rewrite still writes one."""
    assert "composite" in _message(_composite(b_type="string", on_missing="unknown_member"))


# ....................... #
# referential resolution: via must name a relationship this entity owns


VIA_PROJECT = """
spec_version: 1
entities:
  cust:
    grain: one row per customer
    key: [cust_id]
    fields:
      cust_id: {{type: string, required: true}}
      parent_cust_id: {{type: string}}
  oi:
    grain: one row per line
    key: [line_id]
    quarantine: {{retention: 30d}}
    quality:
      - {{rule: referential, via: {via}, on_missing: flag}}
    fields:
      line_id: {{type: string, required: true}}
      cust_id: {{type: string}}
relationships:
  - name: cust_self
    from: cust
    to: cust
    via: {{parent_cust_id: cust_id}}
    cardinality: many_to_one
  - name: oi_of_cust
    from: oi
    to: cust
    via: {{cust_id: cust_id}}
    cardinality: many_to_one
"""

VIA_MAPPINGS = {
    "mapping_cust": f"""
mapping_version: 1
source: crm__cust
target: cust
key:
  cust_id: {{from: "$.id", transform: [to_string]}}
fields:
  parent_cust_id: {{from: "$.parent", transform: [to_string]}}
unmapped: {METADATA}
""",
    "mapping_oi": f"""
mapping_version: 1
source: oms__lines
target: oi
key:
  line_id: {{from: "$.id", transform: [to_string]}}
fields:
  cust_id: {{from: "$.cust_id", transform: [to_string]}}
unmapped: {METADATA}
""",
}


def _via(via: str) -> dict[str, str]:
    return {"entity_model": VIA_PROJECT.format(via=via), **VIA_MAPPINGS}


def test_a_referential_rule_naming_no_relationship_is_refused(  # F6
) -> None:
    """It used to be a raw ``KeyError`` out of the lowering — not a
    ``BloomeryError``, so it never reached the batched aggregate at all."""
    message = _message(_via("no_such_rel"))
    assert "names no relationship 'no_such_rel'" in message
    # Both the unknown name and the declared ones, so the fix is one edit away.
    assert "cust_self, oi_of_cust" in message


def test_a_referential_rule_via_another_entitys_relationship_is_refused() -> None:
    """``cust_self`` runs ``cust → cust``; declaring it on ``oi`` compiled
    clean and emitted a LEFT JOIN on a column ``oi`` never projects."""
    message = _message(_via("cust_self"))
    assert "relationship 'cust_self' runs from 'cust'" in message
    assert "not from 'oi'" in message


def test_a_referential_rule_via_the_entitys_own_relationship_is_accepted() -> None:
    build_project_ir(load_project(_via("oi_of_cust")))


# ....................... #
# referential onto the entity itself (§5.4, D24)


SELF_REFERENTIAL_PROJECT = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    quarantine: {{retention: 30d}}
    quality:
      - {{rule: referential, via: {via}, on_missing: flag}}
    fields:
      order_id: {{type: string, required: true}}
      parent_order_id: {{type: string}}
  order_parent:
    grain: one row per order, as the parent side
    key: [order_id]
    fields:
      order_id: {{type: string, required: true}}
relationships:
  - name: order_of_parent_self
    from: order
    to: order
    via: {{parent_order_id: order_id}}
    cardinality: many_to_one
  - name: order_of_parent
    from: order
    to: order_parent
    via: {{parent_order_id: order_id}}
    cardinality: many_to_one
"""

SELF_REFERENTIAL_MAPPINGS = {
    "mapping_order": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [to_string]}}
fields:
  parent_order_id: {{from: "$.parent_id", transform: [to_string]}}
unmapped: {METADATA}
""",
    "mapping_parent": f"""
mapping_version: 1
source: oms__orders
target: order_parent
key:
  order_id: {{from: "$.id", transform: [to_string]}}
unmapped: {METADATA}
""",
}


def test_a_referential_rule_onto_the_entity_itself_is_refused() -> None:
    documents = {
        "entity_model": SELF_REFERENTIAL_PROJECT.format(via="order_of_parent_self"),
        **SELF_REFERENTIAL_MAPPINGS,
    }
    message = _message(documents)
    assert "a model cannot join the table it is being built from" in message
    assert "model the referenced side as a separate entity" in message


def test_a_referential_rule_onto_a_sibling_entity_is_accepted() -> None:
    """The alternative the refusal names: the same parent relation modeled as
    its own entity, built from the same source."""
    documents = {
        "entity_model": SELF_REFERENTIAL_PROJECT.format(via="order_of_parent"),
        **SELF_REFERENTIAL_MAPPINGS,
    }
    build_project_ir(load_project(documents))


# ....................... #
# One aggregate (RFC 0006 D2)


def test_quality_leaves_batch_with_the_shipped_violations_in_one_aggregate() -> None:
    """A data-quality refusal and an ``assert:`` refusal are reported
    together, sorted by ``(source_path, type name)`` — an author fixes a spec
    in one round-trip, not one error at a time."""
    documents = _project(
        entity_extra=DEDUPE_NO_TIE_BREAK,
        # A numeric bound on a string field can never run — RFC 0006 D8.
        fields="      amount: {type: string, assert: {min: 0}}\n",
        unmapped="[]",
    )
    leaves = _leaves(documents)
    assert set(leaves) == {DedupeTieBreakMissing, IngestionMetadataMissing, AssertLoweringError}
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(documents))
    collected = excinfo.value.collected
    keys = [(leaf.source_path or "", type(leaf).__name__) for leaf in collected]
    assert keys == sorted(keys)
    assert str(excinfo.value).startswith(f"{len(collected)} error(s):")
