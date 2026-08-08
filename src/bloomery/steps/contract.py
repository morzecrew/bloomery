"""The run-time step contract (RFC 0017 §5.4, D4) — the only bloomery module
meant to be imported *outside* compilation.

Compile time trusts a manifest's ``produces``; this is what makes that trust
survive contact with reality. The generated wrapper calls
:func:`assert_step_contract` on every run, and the call is **non-optional and
non-configurable** by construction — there is no flag, no environment
variable, and no "warn" mode. That is the point rather than an oversight: a
claim that is checked is a commitment, a claim that is not is a comment, and
``produces`` left unchecked decays into stale documentation within a quarter.

**Dependency discipline** (D12, strengthened). The RFC budgets for pandas
imported *lazily* here; in fact this module does not import it at all. Every
check is expressed against the dataframe protocol the step already returned —
``.columns``, ``.dtype``, ``.isna()``, ``.duplicated()`` — so the checker
works on whatever frame the step produced and never needs to name the library
that made it. The ``bloomery[steps]`` extra therefore exists for the *step
body's* sake, not the contract's, and compile-time use of the registry needs
no pandas either.

The only import here is :mod:`bloomery.errors`. That is what makes the module
importable in a step runtime without dragging the compile pipeline behind it
— see the lazy package ``__getattr__`` that keeps ``import
bloomery.steps.contract`` from executing the whole surface.

The manifest reaches this function as **plain data**, not as a
:class:`~bloomery.steps.manifest.StepManifest`. The generated wrapper embeds a
literal dict, so verifying a contract costs no pydantic import and the step
runtime does not need bloomery's spec layer to exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bloomery.errors import StepContractViolation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "assert_step_contract",
]

#: The logical types a step may produce, mapped to the pandas dtype *kinds*
#: that satisfy them. Deliberately permissive about width (``int32`` satisfies
#: ``int``) and strict about family: the check exists to catch a step
#: returning text where a number was promised, not to police storage size.
#:
#: ``object`` satisfies everything because pandas uses it for strings, for
#: ``Decimal``, and for any column holding nulls beside another type — an
#: assertion that rejected it would fire on correct steps constantly, which is
#: the fastest way to have a mandatory check disabled.
_KIND_BY_TYPE: dict[str, frozenset[str]] = {
    "string": frozenset({"O", "U", "S"}),
    "int": frozenset({"i", "u", "O"}),
    "bool": frozenset({"b", "O"}),
    "date": frozenset({"M", "O"}),
    "timestamp": frozenset({"M", "O"}),
    "variant": frozenset({"O"}),
    #: ``decimal`` was missing here, and its absence did not fail — it fell
    #: through ``.get()`` and skipped the check entirely, so the RFC's own
    #: flagship column (``confidence: decimal(4,3)``) accepted a
    #: ``datetime64`` without complaint. Exactly the failure D21 records, one
    #: type short of it. An unknown base type is now a violation rather than a
    #: skip (see :func:`_check_columns`), so the next gap fails loudly.
    "decimal": frozenset({"O", "f", "i", "u"}),
}


def _base_type(declared: str) -> str:
    """``decimal(12,4)`` → ``decimal``; every other type is its own base."""
    return declared.split("(", 1)[0].strip()


def _violation(step: str, output: str, detail: str) -> StepContractViolation:
    return StepContractViolation(
        f"step {step!r} output {output!r}: {detail} (RFC 0017 §5.4)",
        source_path=f"step: {step}.{output}",
    )


def _check_columns(step: str, name: str, frame: Any, produces: Mapping[str, Any]) -> None:
    """Exact column set, then assignable types, then required-null checks.

    In that order on purpose: a wrong column set makes every downstream
    complaint noise, so it is reported alone and first.
    """
    actual = list(frame.columns)
    declared = set(produces)
    missing = sorted(declared - set(actual))
    undeclared = sorted(set(actual) - declared)
    if missing or undeclared:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if undeclared:
            parts.append(f"undeclared {', '.join(undeclared)}")
        raise _violation(
            step,
            name,
            f"column set does not match the manifest — {'; '.join(parts)}; "
            f"declared: {', '.join(sorted(declared))}",
        )

    for column in sorted(declared):
        spec = produces[column]
        base = _base_type(str(spec["type"]))
        kinds = _KIND_BY_TYPE.get(base)
        series = frame[column]
        if kinds is None:
            raise _violation(
                step,
                name,
                f"column {column!r} declares type {spec['type']!r}, which this checker "
                "does not know how to verify — refusing rather than passing it silently",
            )
        if series.dtype.kind not in kinds:
            raise _violation(
                step,
                name,
                f"column {column!r} is declared {spec['type']} but holds dtype "
                f"{series.dtype} — the declaration is what downstream models were "
                "typechecked against",
            )
        if spec.get("required") and bool(series.isna().any()):
            count = int(series.isna().sum())
            raise _violation(
                step,
                name,
                f"column {column!r} is declared required but holds {count} null(s)",
            )


def _check_key(step: str, name: str, frame: Any, key: Sequence[str]) -> None:
    """The declared grain is unique over its declared key columns (§5.2).

    This is the check that makes ``grain`` mean something. A grain sentence is
    prose nobody can verify; a key is columns, and duplicated keys are a
    fan-out waiting to multiply every number computed downstream.
    """
    columns = list(key)
    duplicated = int(frame.duplicated(subset=columns).sum())
    if duplicated:
        raise _violation(
            step,
            name,
            f"declared grain is not unique: {duplicated} duplicate row(s) over "
            f"key ({', '.join(columns)})",
        )


def assert_step_contract(outputs: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    """Verify a step's actual outputs against its manifest, or raise.

    Checked in the order §5.4 states: every declared output present, no
    undeclared outputs, exact column set, assignable types, ``required``
    columns null-free, declared grain unique over its key.

    ``outputs`` maps an output name to its dataframe; ``manifest`` is the
    plain-data manifest the generated wrapper embeds.

    Every wrapper checks **all** declared outputs, not merely the one it
    returns (D16). That is deliberate and cheap: with each output emitted as
    its own model, a step that lies about one of them should be caught
    wherever the run happens to start, not only in the model that returns the
    output it lied about.
    """
    step = str(manifest.get("ref", "?"))
    declared_outputs: Mapping[str, Any] = manifest.get("outputs", {})

    missing = sorted(set(declared_outputs) - set(outputs))
    if missing:
        raise _violation(step, ", ".join(missing), "declared output(s) not returned by the step")
    undeclared = sorted(set(outputs) - set(declared_outputs))
    if undeclared:
        raise _violation(
            step,
            ", ".join(undeclared),
            "step returned output(s) the manifest does not declare — an undeclared "
            "output is a relation nothing was typechecked against",
        )

    for name in sorted(declared_outputs):
        declared = declared_outputs[name]
        frame = outputs[name]
        if not hasattr(frame, "columns"):
            raise _violation(step, name, f"expected a dataframe, got {type(frame).__name__}")
        _check_columns(step, name, frame, declared["produces"])
        _check_key(step, name, frame, declared["key"])
