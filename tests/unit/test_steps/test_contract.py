"""The adversarial fake-step battery (RFC 0017 §6, Document 5 §8.7).

Every liar fails loudly, and each one is a *separate* specimen because the
point is not that bad steps fail — it is that each named failure mode is
caught by the check written for it. A battery where one over-broad assertion
catches everything would pass just as green while telling nobody which
guarantee actually holds.

This is the run-time half of trust-then-verify (§5.4, D4). The compile half
trusts ``produces``; without these tests that trust is a comment.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas", reason="the step contract is checked against dataframes")

from bloomery.errors import StepContractViolation  # noqa: E402
from bloomery.steps.contract import assert_step_contract  # noqa: E402

pytestmark = pytest.mark.unit

MANIFEST = {
    "ref": "resolve_customers",
    "version": 3,
    "outputs": {
        "customer": {
            "key": ["canonical_id"],
            "produces": {
                "canonical_id": {"type": "string", "required": True},
                "confidence": {"type": "decimal(4,3)", "required": False},
            },
        }
    },
}


def honest() -> dict[str, pd.DataFrame]:
    return {
        "customer": pd.DataFrame(
            {"canonical_id": ["c1", "c2"], "confidence": [0.9, 0.8]}
        )
    }


def test_an_honest_step_passes() -> None:
    """The control. Without it the battery would pass just as green against a
    checker that rejected everything."""
    assert_step_contract(honest(), MANIFEST)


# ....................... #
# §8.7: every liar, one at a time


def test_an_extra_column_is_caught() -> None:
    outputs = honest()
    outputs["customer"]["surprise"] = 1
    with pytest.raises(StepContractViolation, match="undeclared surprise"):
        assert_step_contract(outputs, MANIFEST)


def test_an_omitted_column_is_caught() -> None:
    outputs = {"customer": honest()["customer"].drop(columns=["confidence"])}
    with pytest.raises(StepContractViolation, match="missing confidence"):
        assert_step_contract(outputs, MANIFEST)


def test_a_wrong_type_is_caught() -> None:
    """A step returning numbers where text was promised. Downstream models
    were typechecked against the declaration, so this is the case where the
    lie propagates furthest if it is not caught here."""
    outputs = {"customer": pd.DataFrame({"canonical_id": [1, 2], "confidence": [0.9, 0.8]})}
    with pytest.raises(StepContractViolation, match="declared string but holds dtype"):
        assert_step_contract(outputs, MANIFEST)


def test_a_null_in_a_required_column_is_caught() -> None:
    outputs = {
        "customer": pd.DataFrame({"canonical_id": ["c1", None], "confidence": [0.9, 0.8]})
    }
    with pytest.raises(StepContractViolation, match="required but holds 1 null"):
        assert_step_contract(outputs, MANIFEST)


def test_duplicate_grain_keys_are_caught() -> None:
    """The check that makes ``grain`` mean something: a duplicated key is a
    fan-out waiting to multiply every number computed downstream."""
    outputs = {
        "customer": pd.DataFrame({"canonical_id": ["c1", "c1"], "confidence": [0.9, 0.8]})
    }
    with pytest.raises(StepContractViolation, match="grain is not unique: 1 duplicate"):
        assert_step_contract(outputs, MANIFEST)


def test_an_undeclared_output_table_is_caught() -> None:
    outputs = honest()
    outputs["ghost"] = pd.DataFrame({"x": [1]})
    with pytest.raises(StepContractViolation, match="does not declare"):
        assert_step_contract(outputs, MANIFEST)


def test_a_missing_output_table_is_caught() -> None:
    with pytest.raises(StepContractViolation, match="not returned by the step"):
        assert_step_contract({}, MANIFEST)


def test_something_that_is_not_a_dataframe_is_caught() -> None:
    with pytest.raises(StepContractViolation, match="expected a dataframe, got list"):
        assert_step_contract({"customer": [1, 2, 3]}, MANIFEST)


# ....................... #
# Deliberate permissiveness, stated rather than discovered


def test_object_dtype_satisfies_every_declared_type() -> None:
    """pandas uses ``object`` for strings, for ``Decimal``, and for any column
    holding nulls beside another type. An assertion that rejected it would
    fire on correct steps constantly — which is the fastest route to a
    mandatory check being disabled, so the permissiveness is deliberate."""
    from decimal import Decimal

    outputs = {
        "customer": pd.DataFrame(
            {"canonical_id": ["c1"], "confidence": [Decimal("0.9")]}
        )
    }
    assert_step_contract(outputs, MANIFEST)


def test_a_wider_int_still_satisfies_int() -> None:
    """Width is storage, not meaning: the check catches text-where-a-number
    was promised, and does not police ``int32`` versus ``int64``."""
    manifest = {
        "ref": "s",
        "outputs": {"o": {"key": ["n"], "produces": {"n": {"type": "int", "required": True}}}},
    }
    frame = pd.DataFrame({"n": pd.array([1, 2], dtype="int32")})
    assert_step_contract({"o": frame}, manifest)


def test_a_composite_key_is_checked_over_both_columns() -> None:
    manifest = {
        "ref": "s",
        "outputs": {
            "o": {
                "key": ["a", "b"],
                "produces": {"a": {"type": "string"}, "b": {"type": "string"}},
            }
        },
    }
    unique = pd.DataFrame({"a": ["x", "x"], "b": ["1", "2"]})
    assert_step_contract({"o": unique}, manifest)
    duplicated = pd.DataFrame({"a": ["x", "x"], "b": ["1", "1"]})
    with pytest.raises(StepContractViolation, match=r"key \(a, b\)"):
        assert_step_contract({"o": duplicated}, manifest)


def test_every_declared_output_is_checked_not_just_the_returned_one() -> None:
    """D16: with each output emitted as its own model, a step that lies about
    one of them should be caught wherever the run happens to start."""
    manifest = {
        "ref": "s",
        "outputs": {
            "a": {"key": ["k"], "produces": {"k": {"type": "string"}}},
            "b": {"key": ["k"], "produces": {"k": {"type": "string"}}},
        },
    }
    outputs = {
        "a": pd.DataFrame({"k": ["ok"]}),
        "b": pd.DataFrame({"k": ["dup"], "extra": [1]}),
    }
    with pytest.raises(StepContractViolation, match="output 'b'"):
        assert_step_contract(outputs, manifest)


def test_the_violation_names_the_step_and_the_output() -> None:
    """A run-time failure inside somebody's warehouse is only actionable if it
    says which step and which output — the message is the whole interface."""
    outputs = honest()
    outputs["customer"]["surprise"] = 1
    with pytest.raises(StepContractViolation) as excinfo:
        assert_step_contract(outputs, MANIFEST)
    message = str(excinfo.value)
    assert "resolve_customers" in message
    assert "'customer'" in message
    assert excinfo.value.source_path == "step: resolve_customers.customer"


def test_a_decimal_column_is_actually_type_checked() -> None:
    """`decimal` was missing from the kind table and its absence did not
    fail — it fell through `.get()` and skipped the check, so the RFC's own
    flagship column (`confidence: decimal(4,3)`) accepted a `datetime64`
    without complaint. Exactly the failure D21 records, one type short."""
    outputs = {
        "customer": pd.DataFrame(
            {"canonical_id": ["c1"], "confidence": pd.to_datetime(["2020-01-01"])}
        )
    }
    with pytest.raises(StepContractViolation, match="declared decimal"):
        assert_step_contract(outputs, MANIFEST)


def test_a_duplicated_column_label_is_a_violation_not_an_attribute_error() -> None:
    """pandas permits a repeated label, and every check here assumed it could
    not happen: the column set was compared as a *set*, so a frame carrying
    ``a`` twice matched a manifest declaring one ``a``; ``frame['a']`` then
    returned a DataFrame and the type check died with ``AttributeError:
    'DataFrame' object has no attribute 'dtype'`` — an opaque crash inside
    somebody's warehouse instead of the designed violation.
    """
    manifest = {
        "ref": "s",
        "outputs": {"o": {"key": ["a"], "produces": {"a": {"type": "string"}}}},
    }
    frame = pd.DataFrame([["x", "y"]], columns=["a", "a"])
    with pytest.raises(StepContractViolation, match="appears more than once"):
        assert_step_contract({"o": frame}, manifest)


def test_a_manifest_without_outputs_fails_loudly_rather_than_checking_nothing() -> None:
    """``manifest.get("outputs", {})`` made the whole assertion a no-op: no
    declared outputs, so nothing missing, nothing undeclared, and an empty
    loop — a mandatory check silently degraded to a pass, which is the exact
    failure mode D21 and D29 both record. The wrapper always embeds the key,
    so its absence is a generation defect that must surface as a crash.
    """
    with pytest.raises(KeyError):
        assert_step_contract({}, {"ref": "s"})


def test_a_type_the_checker_does_not_know_is_refused_not_skipped() -> None:
    """The generalisation of the bug above: an unknown base type must fail
    loudly rather than pass silently, so the next gap cannot hide."""
    manifest = {
        "ref": "s",
        "outputs": {"o": {"key": ["k"], "produces": {"k": {"type": "geography"}}}},
    }
    with pytest.raises(StepContractViolation, match="does not know how to verify"):
        assert_step_contract({"o": pd.DataFrame({"k": ["x"]})}, manifest)
