"""Transform declaration and registration (RFC 0004 §5.2–§5.3).

A transform is a :class:`TransformSpec`: name, arity and per-argument kinds,
input type domain, output type *function* (output may depend on args), and a
builder producing a dialect-neutral SQLGlot AST — never string SQL (RFC 0004
D7). The ``@transform(...)`` decorator wraps a builder into a spec and adds it
to the default registry at import; :func:`register_transform` is the public
extension point, adding to a process-global overlay. Name collisions raise
:class:`~bloomery.errors.TransformRegistrationError` — shadowing a vetted
transform silently would defeat the whitelist's audit value (RFC 0004 D6).

All registry iteration is sorted by name: the registry is one of the few
module-global structures in the package and must not leak insertion order
into output (RFC 0003 §5.5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import TransformRegistrationError
from bloomery.typing import (
    ArgKind,
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)

if TYPE_CHECKING:
    from sqlglot.expressions.core import Expression

__all__ = [
    "Builder",
    "neutral_type",
    "OutputType",
    "Registry",
    "TransformSpec",
    "register_transform",
    "registry",
    "transform",
]

#: Output type as a function of (input type, spec-level args) — a function,
#: not a value, because output can depend on args (``to_decimal(12, 4)``) or
#: on the input type (``coalesce`` preserves it).
type OutputType = Callable[[LogicalType, tuple[str | int, ...]], LogicalType]

#: ``(column AST, *spec-level args) -> dialect-neutral SQLGlot AST``.
#:
#: A spec declaring ``types=True`` is additionally passed ``input_type=`` — the
#: logical type entering the step. The signature is deliberately *not* changed
#: to take it positionally: this alias is exported from ``bloomery.__all__`` and
#: named in the API reference as an extension point, and moving it would break
#: every registered third-party builder to serve the handful of built-ins that
#: need the type (RFC 0029 D1, logs/T-0002.md D-001).
type Builder = Callable[..., "Expression"]

#: The read surface every consumer sees: an immutable name → spec mapping.
type Registry = Mapping[str, TransformSpec]


@dataclass(frozen=True, slots=True)
class TransformSpec:
    """One whitelisted transform (RFC 0004 §5.2).

    ``arity`` counts spec-level args (not the column). A ``variadic``
    transform accepts any positive multiple of ``arg_kinds`` (``enum_map``
    takes from/to pairs); ``arity`` is then the length of one repetition.

    ``nullifies`` declares that the transform can return NULL from a non-NULL
    input **on purpose**. It exists because RFC 0016's ``coercible`` rule
    infers a cause from an effect: its marker is "the output vanished while
    the source was there", which is a failed cast only if nothing in the chain
    nulls a value deliberately. A transform that does is not a coercion
    failure and must not be quarantined as one, so the flag is declared here —
    on the transform that knows — rather than kept as a name list inside the
    quality lowering, where the next transform added would reintroduce the
    false positive silently (RFC 0016 §5.2).

    ``types`` declares that the builder must be told the logical type entering
    the step, and is passed it as ``input_type=``. A builder that constructs a
    cast, a coercion or a narrowing cannot be correct without it — the
    *declaration* of what a transform produces is a function of the input type
    and the construction was not, so the two could disagree and did
    (RFC 0029 D1). It is declared rather than inferred from the signature so
    that a builder which forgets to accept the argument fails loudly at its
    first call rather than silently receiving nothing.
    """

    name: str
    arity: int
    arg_kinds: tuple[ArgKind, ...]
    input_domain: tuple[type[LogicalType], ...]
    output_type: OutputType
    builder: Builder
    variadic: bool = False
    nullifies: bool = False
    types: bool = False


_NEUTRAL_TYPES: dict[type[LogicalType], str] = {
    StringType: "TEXT",
    IntType: "BIGINT",
    BoolType: "BOOLEAN",
    DateType: "DATE",
    TimestampType: "TIMESTAMP",
    VariantType: "JSON",
}


def neutral_type(t: LogicalType) -> exp.DataType:
    """The dialect-neutral SQLGlot type for a logical type.

    Physical DDL types are the dialect port's job (RFC 0008); this is the type
    a *neutral* cast names, rendered per dialect at emit.

    It lives in this layer rather than in ``ir`` because a builder that
    declares ``types`` needs it — to cast a literal argument to the column's
    type, say — and ``transforms`` sits below ``ir``. Kept as one definition
    with :func:`bloomery.ir.generic_type` delegating here, because two maps of
    seven rows are two maps that can disagree about one.
    """
    if isinstance(t, DecimalType):
        return exp.DataType.build(f"DECIMAL({t.precision}, {t.scale})")
    return exp.DataType.build(_NEUTRAL_TYPES[type(t)])


_default: dict[str, TransformSpec] = {}
_overlay: dict[str, TransformSpec] = {}


def _validate(spec: TransformSpec) -> None:
    if spec.arity < 0:
        msg = f"transform {spec.name!r}: arity must be >= 0, got {spec.arity}"
        raise TransformRegistrationError(msg)
    if spec.arity != len(spec.arg_kinds):
        msg = (
            f"transform {spec.name!r}: arity ({spec.arity}) must match the "
            f"number of declared arg kinds ({len(spec.arg_kinds)})"
        )
        raise TransformRegistrationError(msg)
    if spec.variadic and spec.arity == 0:
        msg = f"transform {spec.name!r}: a variadic transform needs at least one arg kind"
        raise TransformRegistrationError(msg)
    if not spec.input_domain:
        msg = f"transform {spec.name!r}: input domain must not be empty"
        raise TransformRegistrationError(msg)


def _check_collision(name: str) -> None:
    if name in _default or name in _overlay:
        msg = f"transform {name!r} is already registered; shadowing is not allowed"
        raise TransformRegistrationError(msg)


def transform(
    name: str,
    *,
    arity: int,
    arg_kinds: tuple[ArgKind, ...] = (),
    input: tuple[type[LogicalType], ...],
    output: LogicalType | OutputType,
    variadic: bool = False,
    nullifies: bool = False,
    types: bool = False,
) -> Callable[[Builder], TransformSpec]:
    """Declare a starter transform: wrap a builder into a :class:`TransformSpec`
    and add it to the default registry at import time (RFC 0004 §5.2).

    ``output`` is either a fixed :data:`LogicalType` or a function of
    ``(input type, args)``; a fixed value is wrapped into a constant function.
    ``nullifies`` marks a transform that deliberately produces NULL from a
    non-NULL input, and ``types`` that its builder is passed ``input_type=`` —
    both see :class:`TransformSpec`.
    """

    def decorate(builder: Builder) -> TransformSpec:
        output_type: OutputType
        if callable(output):
            output_type = output
        else:
            fixed = output

            def constant_output(_t: LogicalType, _args: tuple[str | int, ...]) -> LogicalType:
                return fixed

            output_type = constant_output

        spec = TransformSpec(
            name=name,
            arity=arity,
            arg_kinds=arg_kinds,
            input_domain=input,
            output_type=output_type,
            builder=builder,
            variadic=variadic,
            nullifies=nullifies,
            types=types,
        )
        _validate(spec)
        _check_collision(name)
        _default[name] = spec
        return spec

    return decorate


def register_transform(spec: TransformSpec) -> None:
    """Register an extension transform (public API, spec §8).

    Adds to the process-global overlay consulted after the default map.
    Extension is a deployment-time act (an adapter package registering at
    import), not a per-compile one (RFC 0004 §5.3); determinism is scoped to
    a fixed installed extension set (RFC 0004 D6).

    Raises :class:`TransformRegistrationError` on an invalid spec or a name
    collision with any existing transform, default or overlay.
    """
    _validate(spec)
    _check_collision(spec.name)
    _overlay[spec.name] = spec


def registry() -> Registry:
    """The merged registry (default + overlay), sorted by name, immutable."""
    merged = _default | _overlay
    return MappingProxyType({name: merged[name] for name in sorted(merged)})
