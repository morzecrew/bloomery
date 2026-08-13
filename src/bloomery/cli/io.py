"""The only module in the package that reads or writes files (RFC 0020 D5, D12).

Everything else under ``src/bloomery/`` takes strings and returns values, and
``tools/check_purity.py`` enforces that by refusing ``os``, ``pathlib`` and
friends outright. This file is the single named exception on that allowlist,
with the reason stated there and here: a command line has to reach a disk, and
the honest place for that is one module a reader can hold in their head.

The carve-out is one **file**, not the ``bloomery/cli/`` package. A
package-wide exemption would let the argument parser or the renderer open a
file while this module's docstring still claimed one did — the guard and the
document disagreeing, which is worse than no guard.

The direction is enforced separately and mechanically: ``bloomery.cli`` is the
top layer of the import contract, so it may read the library and no library
module may read it. The two mechanisms answer different questions — who may
touch the disk, and which way imports run — and collapsing them into one
allowlist loses the first.

Everything here returns ``str``. The library never sees a path.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "CliIoError",
    "read_spec_directory",
    "read_text",
    "write_files",
]

#: The extensions a spec directory is scanned for. Both, because a project that
#: writes ``.yml`` is not writing a different language, and silently skipping
#: half a directory is the worst available outcome.
SPEC_SUFFIXES = (".yaml", ".yml")

#: The conventional catalog filename. A catalog is loaded separately from a
#: project (RFC 0002 D8), so it has to be told apart from the project documents
#: somehow; ``--catalog`` is the explicit way and this is the default one.
#: Recognized by *name*, never by peeking at the contents — the CLI adds no
#: logic of its own (D4), and ``load_project`` already refuses a catalog
#: document with a message that names the fix.
CATALOG_STEMS = ("catalog",)


class CliIoError(Exception):
    """A path the command line could not use.

    Deliberately **not** a :class:`~bloomery.errors.BloomeryError`: the library's
    hierarchy is about specs being wrong, and a missing directory is about the
    invocation being wrong. The exit codes keep the same split — a refusal is
    ``1``, a usage error is ``2`` — and collapsing the two would make a script
    unable to tell "your spec is invalid" from "you typed the path wrong".
    """


def read_text(path: str) -> str:
    """One file's text, or :class:`CliIoError` naming it."""
    target = Path(path)
    if not target.is_file():
        msg = f"{path}: not a file"
        raise CliIoError(msg)
    return target.read_text(encoding="utf-8")


def read_spec_directory(
    path: str, *, catalog: str | None = None
) -> tuple[dict[str, str], str | None]:
    """A spec directory as ``(project documents, catalog text or None)``.

    Documents are keyed by filename stem, which is what
    :func:`~bloomery.load_project` uses as the source-path prefix in every
    error message — so a refusal points at ``metrics: metrics.revenue.agg``
    and the reader knows which file that is.

    ``catalog`` names the catalog file explicitly; without it, a
    ``catalog.yaml`` sitting in the directory is used and excluded from the
    project. An explicit ``--catalog`` outside the directory is left where it
    is, so pointing several projects at one shared catalog works.
    """
    directory = Path(path)
    if not directory.is_dir():
        msg = f"{path}: not a directory"
        raise CliIoError(msg)
    files = sorted(
        entry for entry in directory.iterdir() if entry.is_file() and entry.suffix in SPEC_SUFFIXES
    )
    if not files:
        joined = "/".join(SPEC_SUFFIXES)
        msg = f"{path}: no {joined} files"
        raise CliIoError(msg)

    explicit = Path(catalog).resolve() if catalog is not None else None
    sources: dict[str, str] = {}
    conventional: Path | None = None
    for entry in files:
        if explicit is not None and entry.resolve() == explicit:
            continue
        if explicit is None and entry.stem in CATALOG_STEMS:
            conventional = entry
            continue
        sources[entry.stem] = entry.read_text(encoding="utf-8")

    if catalog is not None:
        return sources, read_text(catalog)
    if conventional is not None:
        return sources, conventional.read_text(encoding="utf-8")
    return sources, None


def write_files(directory: str, files: dict[str, str]) -> list[str]:
    """Write ``{relative path: content}`` under ``directory``; return the paths.

    Parent directories are created, because an emitted artifact's path carries
    its own layout (``models/gold/orders.sql``) and asking a caller to
    pre-create it would be asking them to reimplement the emitter's opinion.
    """
    root = Path(directory)
    written: list[str] = []
    for relative, content in sorted(files.items()):
        destination = root / relative
        if not destination.resolve().is_relative_to(root.resolve()):
            # Artifact paths come from the emitters, not from user input, so
            # this cannot fire today. It is here because "cannot fire today" is
            # the condition under which a path-traversal check gets left out.
            msg = f"{relative}: escapes the output directory"
            raise CliIoError(msg)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        written.append(str(destination))
    return written
