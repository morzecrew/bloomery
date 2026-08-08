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
from bloomery.ir import OnFail
from bloomery.errors import (
    AssertLoweringError,
    DedupeDispositionConflict,
    DedupeTieBreakMissing,
    GuardrailError,
    IngestionMetadataMissing,
    QuarantineRetentionMissing,
    RedactionConflict,
)
from support.compiling import fixture_sources, load_fixture

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
# referential onto the entity itself (§5.4, D27)


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


# ....................... #
# an authored rule name displacing a generated one (§5.3, D71)


_GENERATED_IN_SET = "    quality:\n      - {rule: in_set, values: [a, b], on_fail: flag}\n"


def _authored(name: str) -> str:
    return (
        "    quality:\n"
        f'      - {{rule: expression, name: {name}, expr: "amount IS NOT NULL", on_fail: flag}}\n'
        "    quarantine: {retention: 90d}\n"
    )


def test_an_authored_rule_name_that_would_displace_a_generated_one_is_refused() -> None:
    """Generated names are order-independent (D50) but were not *name*-
    independent: an authored ``expression`` rule named ``amount_in_set`` sorted
    ahead of the field's own generated ``amount_in_set`` and pushed it to
    ``amount_in_set_2``. The mart's ``rule`` dimension is a time series, so an
    unrelated edit silently moved a series key — the rule kept firing on the
    same rows under a name nothing in the spec spells."""
    documents = _project(field_quality=_GENERATED_IN_SET, entity_extra=_authored("amount_in_set"))
    message = _message(documents)
    assert "amount_in_set" in message
    assert "generated" in message


def test_an_authored_rule_name_of_its_own_is_accepted() -> None:
    documents = _project(field_quality=_GENERATED_IN_SET, entity_extra=_authored("amount_present"))
    ir = build_project_ir(load_project(documents))
    assert sorted(rule.name for rule in ir.entities[0].quality) == [
        "amount_coercible",
        "amount_in_set",
        "amount_present",
        "order_id_coercible",
    ]


# ....................... #
# Two referential rules through one relationship (RFC 0016 §5.4)


DOUBLE_VIA_PROJECT = VIA_PROJECT.replace(
    "      - {{rule: referential, via: {via}, on_missing: flag}}",
    "      - {{rule: referential, via: {via}, on_missing: flag}}\n"
    "      - {{rule: referential, via: {via}, on_missing: quarantine}}",
)


def test_two_referential_rules_through_one_relationship_are_refused() -> None:
    """Each lowers to a LEFT JOIN aliased ``_ref_<relationship>``, so two of
    them put two joins under one alias — DuckDB rejects the emitted model
    outright (``Ambiguous reference to table "_ref_oi_of_cust"``). Nothing
    caught it: the two rules differ in disposition, so name assignment just
    suffixed the second and both survived to emission."""
    documents = {
        "entity_model": DOUBLE_VIA_PROJECT.format(via="oi_of_cust"),
        **VIA_MAPPINGS,
    }
    message = _message(documents)
    assert "more than one referential rule through relationship 'oi_of_cust'" in message
    assert "two joins under one alias" in message


def test_one_referential_rule_per_relationship_is_accepted() -> None:
    """The non-trigger — the same project with the duplicate removed."""
    build_project_ir(load_project(_via("oi_of_cust")))


# ....................... #
# Chain-derived rules read the chain at a point that must be sound (§5.2)


def _chain(steps: str, rule: str) -> dict[str, str]:
    return _project(
        entity_extra="    quarantine: {retention: 30d}\n",
        field_quality=f"    quality:\n      - {rule}\n",
        fields="      amount: {type: string}\n",
    ) | {
        "mapping": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [to_string]}}
fields:
  amount:
    from: "$.amount"
    transform: {steps}
    quality:
      - {rule}
unmapped: {METADATA}
""",
    }


ENUM_RULE = "{rule: in_enum, on_fail: quarantine}"
ENUM_MAP = '{enum_map: [paid, paid, pending, pending]}'


def test_in_enum_with_a_transform_after_enum_map_is_refused() -> None:
    """The admissible set is read off the ``enum_map``; the predicate tests the
    column's *final* value. With ``upper`` after it, every correctly-mapped row
    lands as ``PAID`` against a set spelling ``paid`` — executed on DuckDB, the
    entity came out **empty** and all three rows sat in the reject table. The
    worst failure mode this feature has, and no fixture could see it: every
    ``enum_map`` in the corpus happens to be the last step."""
    message = _message(_chain(f"[to_string, {ENUM_MAP}, upper]", ENUM_RULE))
    assert "applies upper after enum_map" in message
    assert "quarantining every correctly-mapped row" in message


def test_in_enum_with_the_enum_map_last_is_accepted() -> None:
    build_project_ir(load_project(_chain(f"[to_string, {ENUM_MAP}]", ENUM_RULE)))


def test_in_enum_with_a_second_enum_map_after_the_first_is_accepted() -> None:
    """Another ``enum_map`` may follow: the union of both steps' targets still
    contains every value the chain can finally produce, so the set can only be
    too generous, never too strict — and too strict is what quarantines a good
    row."""
    second = "{enum_map: [paid, settled]}"
    build_project_ir(load_project(_chain(f"[to_string, {ENUM_MAP}, {second}]", ENUM_RULE)))


def test_an_authored_coercible_on_a_nulling_chain_is_refused() -> None:
    """``coercible`` reads "output NULL, source not" as a failed cast.
    ``nullif`` makes a value vanish on purpose, so the two are indistinguishable
    — and the row was quarantined for obeying the mapping it was given."""
    message = _message(_chain("[to_string, {nullif: 'N/A'}]", "{rule: coercible, on_fail: quarantine}"))
    assert "applies nullif" in message
    assert "returns NULL from a non-NULL input deliberately" in message


# ....................... #
# data_quality is the synthesized mart's name (RFC 0016 §5.8, D12)


QUALITY_MART_PROJECT = {
    "entity_model": f"""
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    quarantine: {{retention: 30d}}
    fields:
      order_id: {{type: string, required: true}}
      amount: {{type: int}}
""",
    "mapping": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [to_string]}}
fields:
  amount: {{from: "$.amount", transform: [to_int]}}
unmapped: {METADATA}
""",
    "marts": """
marts_version: 1
marts:
  data_quality:
    grain: order
    base: order
    measures: [amount]
""",
}


def test_an_authored_mart_named_data_quality_is_refused() -> None:
    """``is_quality_mart`` matches by name, so an authored ``data_quality``
    mart is *taken for* the synthesized one: SQLMesh emitted the quality mart
    twice at one path and the author's mart — its base, its grain, its
    measures — vanished with no diagnostic, while Cube wrote two different
    files to that path and the last writer won."""
    message = _message(QUALITY_MART_PROJECT)
    assert "collides with the name of the quality mart" in message
    assert "silently replaced" in message


def test_the_mart_name_is_reserved_even_without_any_quality() -> None:
    """Unconditional, for the reason its metric sibling gives: a name reserved
    only sometimes is a name nobody can rely on, and adding one ``quality:``
    block later must not break an unrelated mart."""
    documents = dict(QUALITY_MART_PROJECT)
    documents["entity_model"] = documents["entity_model"].replace(
        "    quarantine: {retention: 30d}\n", ""
    )
    assert "collides with the name of the quality mart" in _message(documents)


def test_only_the_reserved_name_earns_this_refusal() -> None:
    """The non-trigger, isolating the *name*: the same mart under another one
    still fails this project's other mart rules, and must not collect the
    reserved-name leaf among them."""
    documents = dict(QUALITY_MART_PROJECT)
    documents["marts"] = documents["marts"].replace("data_quality:", "order_totals:")
    assert "collides with the name of the quality mart" not in _message(documents)


# ....................... #
# A recipe's direct: path is a path the mapping reads (RFC 0006 D7 × D10)


def _direct(redact: str = "") -> tuple[dict[str, str], object]:
    """The shipped ``path_conflict`` fixture — the only one carrying a recipe
    ``direct:`` — given a quarantine block so replay exists at all."""
    sources = dict(fixture_sources("path_conflict"))
    sources["entity_model"] += (
        f"    quarantine: {{retention: 30d{redact}}}\n"
        "    quality:\n"
        "      - {rule: expression, name: qty_positive, expr: \"quantity > 0\", "
        "on_fail: quarantine}\n"
    )
    sources["mapping"] += f"unmapped: {METADATA}\n"
    _project, catalog = load_fixture("path_conflict")
    return sources, catalog


def test_redacting_a_recipes_direct_path_is_refused() -> None:
    """``direct:`` lowers to a real ``<field>__direct`` column that replay
    rebuilds from ``raw`` (RFC 0006 D7 × RFC 0016 D10), so it is a path the
    mapping *reads* — and ``_read_paths`` did not say so, which let redaction
    remove the very key replay depends on."""
    sources, catalog = _direct(', redact: ["$.price"]')
    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(sources), catalog)
    assert "$.price" in str(excinfo.value)


def test_a_direct_path_reaches_the_reject_payload() -> None:
    """The half the redaction refusal is *for*. The direct path was missing
    from the entity's source fields, so it never entered the reject table's
    ``raw`` — and replay rebuilt ``net_price__direct`` from a key that is not
    there, producing NULL for every replayed row and feeding that to the
    reconcile audit whose whole job is to compare it."""
    sources, catalog = _direct()
    ir = build_project_ir(load_project(sources), catalog)
    paths = {field.source_path for field in ir.entities[0].source.fields}
    assert "$.price" in paths


# ....................... #
# The dedupe order outranks the nulling-chain skip (RFC 0016 D80)


def _nulling_dedupe(rule: str = "") -> dict[str, str]:
    """An entity deduplicating by a field whose chain nulls deliberately."""
    return {
        "entity_model": f"""
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    dedupe: {{keep: latest_by, field: recency, tie_break: [_load_id]}}
    quarantine: {{retention: 30d}}
    fields:
      order_id: {{type: string, required: true}}
      recency: {{type: string}}
""",
        "mapping": f"""
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {{from: "$.id", transform: [to_string]}}
fields:
  recency:
    from: "$.recency"
    transform: [to_string, {{nullif: 'N/A'}}]
{rule}
unmapped: {METADATA}
""",
    }


def test_a_dedupe_column_keeps_its_forced_coercible_despite_a_nulling_chain() -> None:
    """D73 skips the implicit ``coercible`` where the chain nulls on purpose —
    but on a column the dedupe order reads, §5.4/D6 *forces* that rule to
    ``fail`` because an uncastable sort value leaves the order undefined.
    Letting the skip win deleted the rule and its blocking audit silently,
    trading a false positive for a nondeterministic entity, with no way for
    the author to restore it."""
    ir = build_project_ir(load_project(_nulling_dedupe()))
    rules = {(rule.name, rule.on_fail) for rule in ir.entities[0].quality}
    assert ("recency_coercible", OnFail.FAIL) in rules


def test_an_authored_coercible_on_a_nulling_dedupe_column_is_not_refused() -> None:
    """The other half: D6 demands ``on_fail: fail`` on a dedupe column, so
    refusing the authored rule there would leave the author no way to satisfy
    it — refused coming and going."""
    documents = _nulling_dedupe("    quality:\n      - {rule: coercible, on_fail: fail}\n")
    assert build_project_ir(load_project(documents)).entities[0].quality


def test_a_key_columns_nulling_chain_is_read_too() -> None:
    """``mapped_fields`` yields ``None`` for a key column, but ``KeyField``
    carries a transform chain. Reading ``None`` as "no chain" left the key
    with the very false positive the skip exists to prevent — and the worst
    version of it: a key has no ``quality:`` surface, so the author could
    neither declare the rule away nor be told why rows vanished."""
    documents = _nulling_dedupe()
    documents["mapping"] = documents["mapping"].replace(
        'order_id: {from: "$.id", transform: [to_string]}',
        "order_id: {from: \"$.id\", transform: [to_string, {nullif: 'N/A'}]}",
    )
    kinds = {rule.column for rule in build_project_ir(load_project(documents)).entities[0].quality}
    assert "order_id" not in kinds


# ....................... #
# in_enum needs an enum_map to read (RFC 0016 D49)


def test_in_enum_without_any_enum_map_is_refused() -> None:
    """The admissible set *is* the ``enum_map``, so with none in the chain the
    set is empty and the rule lowered to ``NOT status IN ()`` — invalid SQL on
    every dialect, and semantically a rule rejecting every row."""
    message = _message(_chain("[to_string]", ENUM_RULE))
    assert "has no enum_map step" in message
    assert "rejects every row" in message


def test_to_string_after_enum_map_is_accepted() -> None:
    """``to_string`` is the identity on the string ``enum_map`` produces, so it
    cannot move the value off the set — refusing it was a false positive."""
    build_project_ir(load_project(_chain(f"[to_string, {ENUM_MAP}, to_string]", ENUM_RULE)))
