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

from bloomery.errors import TransformRegistrationError
from bloomery.typing import ArgKind, LogicalType

if TYPE_CHECKING:
    from sqlglot import exp

__all__ = [
    "Builder",
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
type Builder = Callable[..., "exp.Expression"]

#: The read surface every consumer sees: an immutable name → spec mapping.
type Registry = Mapping[str, TransformSpec]


@dataclass(frozen=True, slots=True)
class TransformSpec:
    """One whitelisted transform (RFC 0004 §5.2).

    ``arity`` counts spec-level args (not the column). A ``variadic``
    transform accepts any positive multiple of ``arg_kinds`` (``enum_map``
    takes from/to pairs); ``arity`` is then the length of one repetition.
    """

    name: str
    arity: int
    arg_kinds: tuple[ArgKind, ...]
    input_domain: tuple[type[LogicalType], ...]
    output_type: OutputType
    builder: Builder
    variadic: bool = False


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
) -> Callable[[Builder], TransformSpec]:
    """Declare a starter transform: wrap a builder into a :class:`TransformSpec`
    and add it to the default registry at import time (RFC 0004 §5.2).

    ``output`` is either a fixed :data:`LogicalType` or a function of
    ``(input type, args)``; a fixed value is wrapped into a constant function.
    """

    def decorate(builder: Builder) -> TransformSpec:
        output_type: OutputType
        if callable(output):
            output_type = output
        else:
            fixed = output

            def output_type(_t: LogicalType, _args: tuple[str | int, ...]) -> LogicalType:
                return fixed

        spec = TransformSpec(
            name=name,
            arity=arity,
            arg_kinds=arg_kinds,
            input_domain=input,
            output_type=output_type,
            builder=builder,
            variadic=variadic,
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
