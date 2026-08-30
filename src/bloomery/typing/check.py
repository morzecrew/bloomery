"""The typecheck stage (RFC 0004 §5.4): walk every transform chain and prove
the terminal type assignable to the declared field type.

Pure functions; run after resolution (RFC 0005) has bound every chain to a
source column and an input type. Unknown names raise
:class:`~bloomery.errors.UnknownTransformError` naming the closest match via
``difflib.get_close_matches`` over the *sorted* registry — deterministic
suggestions, no external fuzzy dependency (RFC 0004 D4). Failures are batched
per stage by :func:`typecheck_chains`: all chains checked, one combined
:class:`~bloomery.errors.TypeCheckError` listing every path (the
one-round-trip principle, RFC 0002 D6).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, TypeCheckError, UnknownTransformError
from bloomery.typing.types import ArgKind, DecimalType, LogicalType, assignable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery.spec.mapping import TransformStep
    from bloomery.transforms.registry import Registry, TransformSpec

# ----------------------- #

__all__ = [
    "ChainCheck",
    "typecheck_chain",
    "typecheck_chains",
]


def _describe(t: LogicalType) -> str:
    """A type as the spec layer spells it (``decimal(12, 4)``, ``string``)."""

    if isinstance(t, DecimalType):
        return f"decimal({t.precision}, {t.scale})"

    return type(t).__name__.removesuffix("Type").lower()


# ....................... #


def _is_number(value: str | int) -> bool:
    if isinstance(value, bool):
        return False

    if isinstance(value, int):
        return True

    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


# ....................... #


def _arg_matches(kind: ArgKind, value: str | int) -> bool:
    if kind is ArgKind.STR:
        return isinstance(value, str)

    if kind is ArgKind.INT:
        return isinstance(value, int) and not isinstance(value, bool)

    if kind is ArgKind.NUMBER:
        return _is_number(value)

    # ArgKind.LITERAL — a str or an int, mirrored into SQL as-is (a non-str
    # value is an int by the parameter type; only bool must be excluded).
    return isinstance(value, str) or not isinstance(value, bool)


# ....................... #


def _check_args(spec: TransformSpec, args: tuple[str | int, ...], *, source_path: str) -> None:
    if spec.variadic:
        if not args or len(args) % spec.arity != 0:
            msg = (
                f"{spec.name!r} takes a positive multiple of {spec.arity} argument(s), "
                f"got {len(args)}"
            )
            raise TypeCheckError(msg, source_path=source_path)
    elif len(args) != spec.arity:
        msg = f"{spec.name!r} takes {spec.arity} argument(s), got {len(args)}"
        raise TypeCheckError(msg, source_path=source_path)

    for position, value in enumerate(args):
        kind = spec.arg_kinds[position % len(spec.arg_kinds)]
        if not _arg_matches(kind, value):
            msg = (
                f"{spec.name!r} argument {position} must be {kind.value}, "
                f"got {value!r} ({type(value).__name__})"
            )
            raise TypeCheckError(msg, source_path=source_path)


# ....................... #


def _lookup(name: str, registry: Registry, *, source_path: str) -> TransformSpec:
    spec = registry.get(name)

    if spec is not None:
        return spec

    matches = difflib.get_close_matches(name, sorted(registry), n=1)
    hint = f"; closest match: {matches[0]!r}" if matches else ""
    msg = f"unknown transform {name!r}{hint}"
    raise UnknownTransformError(msg, source_path=source_path)


# ....................... #


def typecheck_chain(
    input_type: LogicalType,
    steps: tuple[TransformStep, ...],
    declared: LogicalType,
    *,
    registry: Registry,
    source_path: str,
) -> LogicalType:
    """Typecheck one transform chain (RFC 0004 §5.4).

    Per step: look up the name (unknown → :class:`UnknownTransformError` with
    the closest match), check arity and arg kinds, check the current type
    against the transform's input domain, then propagate through its output
    type function. The terminal type must be assignable to ``declared``.
    Step failures carry ``source_path`` suffixed ``.transform[i]``.
    """
    current = input_type

    for index, step in enumerate(steps):
        step_path = f"{source_path}.transform[{index}]"
        spec = _lookup(step.name, registry, source_path=step_path)
        _check_args(spec, step.args, source_path=step_path)
        if not isinstance(current, spec.input_domain):
            accepted = ", ".join(
                sorted(cls.__name__.removesuffix("Type").lower() for cls in spec.input_domain)
            )
            msg = (
                f"{spec.name!r} does not accept {_describe(current)}: "
                f"accepted input types are {accepted}"
            )
            raise TypeCheckError(msg, source_path=step_path)
        try:
            current = spec.output_type(current, step.args)
        except TypeCheckError as exc:
            raise TypeCheckError(str(exc), source_path=step_path) from None

    if not assignable(current, declared):
        msg = (
            f"chain produces {_describe(current)}, which is not assignable to "
            f"the declared {_describe(declared)}"
        )
        if isinstance(current, DecimalType) and isinstance(declared, DecimalType):
            msg += (
                " — decimal widening is implicit; narrowing requires an "
                "explicit to_decimal(p, s) step"
            )
        raise TypeCheckError(msg, source_path=source_path)

    return current


# ....................... #


@dataclass(frozen=True, slots=True)
class ChainCheck:
    """One chain queued for the batched check: input type, authored steps,
    declared terminal type, and the chain's source path."""

    input_type: LogicalType
    steps: tuple[TransformStep, ...]
    declared: LogicalType
    source_path: str


# ....................... #


def typecheck_chains(
    checks: Sequence[ChainCheck], *, registry: Registry
) -> tuple[LogicalType, ...]:
    """Typecheck every chain, batched (RFC 0004 §5.4): all chains are checked,
    and all failures are raised as one combined :class:`TypeCheckError`
    listing every path (a single failure is raised as itself)."""
    results: list[LogicalType] = []
    errors: list[BloomeryError] = []

    for check in checks:
        try:
            results.append(
                typecheck_chain(
                    check.input_type,
                    check.steps,
                    check.declared,
                    registry=registry,
                    source_path=check.source_path,
                )
            )
        except (TypeCheckError, UnknownTransformError) as exc:
            errors.append(exc)

    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise TypeCheckError.from_collected(tuple(errors))

    return tuple(results)
