"""The closed transform whitelist (RFC 0004): the security and reviewability
boundary that bounds what any proposal can possibly say.

Importing this package builds the default registry from the starter set
(:mod:`bloomery.transforms._builtins`); :data:`DEFAULT_REGISTRY` is that
immutable snapshot, :func:`registry` the merged (default + overlay) view,
and :func:`register_transform` the public extension point (spec §8).
"""

from bloomery.transforms import _builtins as _builtins
from bloomery.transforms._builtins import CONVERT_MARKER, DIVIDE_MARKER, ISO_TEXT_MARKER
from bloomery.transforms.registry import (
    Builder,
    OutputType,
    Registry,
    TransformSpec,
    neutral_type,
    register_transform,
    registry,
    transform,
)

# ----------------------- #

__all__ = [
    "CONVERT_MARKER",
    "DIVIDE_MARKER",
    "ISO_TEXT_MARKER",
    "DEFAULT_REGISTRY",
    "Builder",
    "OutputType",
    "Registry",
    "TransformSpec",
    "neutral_type",
    "register_transform",
    "registry",
    "transform",
]

#: The starter set, frozen at import — a module-level immutable mapping
#: sorted by name (RFC 0004 D6). Extensions live in the overlay and are
#: visible through :func:`registry`, never here.
DEFAULT_REGISTRY: Registry = registry()
