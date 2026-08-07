"""The total error hierarchy (RFC 0002 §5.4): every leaf is a
``BloomeryError``, carries ``source_path``, and the batched-stage aggregation
surface works."""

from __future__ import annotations

import pytest

import bloomery.errors as errors_mod
from bloomery.errors import (
    AdditivityViolation,
    AmbiguousDimension,
    AssertLoweringError,
    BloomeryError,
    CircularDerivation,
    ContractViolation,
    CurrencyMismatch,
    DedupeDispositionConflict,
    DedupeTieBreakMissing,
    EmitError,
    FanoutRisk,
    FilterTypeMismatch,
    GrainMismatch,
    GrainViolation,
    GuardrailError,
    IngestionMetadataMissing,
    InvalidRequest,
    MartMissingTimeDimension,
    MissingReference,
    NonAdditiveWithoutComponents,
    PlanError,
    PlannerError,
    QuarantineRetentionMissing,
    RedactionConflict,
    RenameTargetMissing,
    ResolutionError,
    SpecParseError,
    TaxBasisMismatch,
    TransformRegistrationError,
    TypeCheckError,
    UnitMismatch,
    UnknownMember,
    UnknownTransformError,
    UnreachableAtGrain,
    UnsupportedByTarget,
)

pytestmark = pytest.mark.unit

ALL_ERROR_CLASSES = [getattr(errors_mod, name) for name in errors_mod.__all__]


@pytest.mark.parametrize("cls", ALL_ERROR_CLASSES, ids=lambda cls: cls.__name__)
def test_every_class_is_a_bloomery_error(cls: type[BloomeryError]) -> None:
    assert issubclass(cls, BloomeryError)
    assert issubclass(cls, Exception)


@pytest.mark.parametrize("cls", ALL_ERROR_CLASSES, ids=lambda cls: cls.__name__)
def test_every_class_carries_source_path_and_message(cls: type[BloomeryError]) -> None:
    err = cls("boom", source_path="doc: a.b[0].c")
    assert str(err) == "boom"
    assert err.source_path == "doc: a.b[0].c"
    assert err.collected == ()


@pytest.mark.parametrize("cls", ALL_ERROR_CLASSES, ids=lambda cls: cls.__name__)
def test_source_path_defaults_to_none(cls: type[BloomeryError]) -> None:
    assert cls("boom").source_path is None


@pytest.mark.parametrize("cls", ALL_ERROR_CLASSES, ids=lambda cls: cls.__name__)
def test_every_class_has_a_stage_docstring(cls: type[BloomeryError]) -> None:
    assert cls.__doc__, f"{cls.__name__} must document which stage raises it"


@pytest.mark.parametrize(
    ("leaf", "parent"),
    [
        (SpecParseError, BloomeryError),
        (UnknownTransformError, BloomeryError),
        (TypeCheckError, BloomeryError),
        (TransformRegistrationError, BloomeryError),
        (CircularDerivation, ResolutionError),
        (MissingReference, ResolutionError),
        (UnitMismatch, GuardrailError),
        (TaxBasisMismatch, GuardrailError),
        (CurrencyMismatch, GuardrailError),
        (GrainMismatch, GuardrailError),
        (AdditivityViolation, GuardrailError),
        (AssertLoweringError, GuardrailError),
        (GrainViolation, GuardrailError),
        (FanoutRisk, GuardrailError),
        (NonAdditiveWithoutComponents, GuardrailError),
        (MartMissingTimeDimension, GuardrailError),
        # RFC 0016 §5.9: a guardrail says the *model* is wrong (compile
        # time, decidable from the spec alone); a quality rule says the
        # *data* is wrong (run time). These five are the former.
        (QuarantineRetentionMissing, GuardrailError),
        (DedupeTieBreakMissing, GuardrailError),
        (DedupeDispositionConflict, GuardrailError),
        (IngestionMetadataMissing, GuardrailError),
        (RedactionConflict, GuardrailError),
        (ContractViolation, PlanError),
        (RenameTargetMissing, PlanError),
        (UnsupportedByTarget, EmitError),
        (UnknownMember, PlannerError),
        (UnreachableAtGrain, PlannerError),
        (AmbiguousDimension, PlannerError),
        (InvalidRequest, PlannerError),
        (FilterTypeMismatch, PlannerError),
    ],
    ids=lambda item: item.__name__,
)
def test_stage_hierarchy(leaf: type[BloomeryError], parent: type[BloomeryError]) -> None:
    assert issubclass(leaf, parent)


def test_step_contract_violation_belongs_to_rfc_0017() -> None:
    # RFC 0016's guardrail leaves land here; the registered-step contract
    # error is RFC 0017's (M13), deliberately not declared early.
    assert not hasattr(errors_mod, "StepContractViolation")


def test_retired_incompatible_artifact_is_absent() -> None:
    # RFC 0014 retired IncompatibleArtifact: a version mismatch is a cache
    # miss by construction, never an error.
    assert not hasattr(errors_mod, "IncompatibleArtifact")


def test_from_collected_lists_every_path() -> None:
    parts = (
        UnitMismatch("currency + count", source_path="doc_a: fields.x"),
        GrainMismatch("item + order grain", source_path="doc_b: fields.y"),
    )
    aggregate = GuardrailError.from_collected(parts)
    assert isinstance(aggregate, GuardrailError)
    assert aggregate.collected == parts
    assert "2 error(s)" in str(aggregate)
    assert "doc_a: fields.x" in str(aggregate)
    assert "doc_b: fields.y" in str(aggregate)
    assert "currency + count" in str(aggregate)


def test_from_collected_without_source_paths() -> None:
    aggregate = SpecParseError.from_collected((SpecParseError("no path here"),))
    assert "no path here" in str(aggregate)
    assert aggregate.source_path is None


def test_one_except_catches_everything() -> None:
    for cls in ALL_ERROR_CLASSES:
        with pytest.raises(BloomeryError):
            raise cls("boom")
