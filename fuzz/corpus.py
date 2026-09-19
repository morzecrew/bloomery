"""What the batch job reads out of the working tree (S-0009/D-3).

Two things the job cannot state for itself:

*The entry count*, printed before the fuzz run and again after it. The corpus
lives in `actions/cache` rather than a storage repository, and the cost of that
is that eviction — or a key that quietly stopped matching — resets weeks of
exploration with nothing to see. A restore that brought back nothing prints
``0 entries`` before the run instead of passing for green.

*The crash verdict.* libFuzzer exits non-zero on the crash it finds itself, but
a run under ``-max_total_time`` also ends green with artifacts already on disk
from an earlier entry in the same batch. This reads the artifact directory, so
a crash file is a red job whatever the engine's exit code was.

    python fuzz/corpus.py count fuzz/corpus/cli --label before
    python fuzz/corpus.py crashes fuzz/crashes --target cli
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def count(directory: Path) -> int:
    """Corpus entries under `directory`. A missing directory is zero, not an
    error: the first run of a target has no cache to restore."""
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.rglob("*") if path.is_file())


def crashes(directory: Path, target: str) -> list[Path]:
    """The artifacts `just fuzz` writes for `target` — `-artifact_prefix` puts
    them at `<dir>/<target>-*`."""
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob(f"{target}-*") if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report on the fuzz corpus.")
    sub = parser.add_subparsers(dest="command", required=True)

    counting = sub.add_parser("count", help="print the entry count")
    counting.add_argument("directory", type=Path)
    counting.add_argument("--label", default="corpus", help="what the count is of")

    crashing = sub.add_parser("crashes", help="fail when an artifact is present")
    crashing.add_argument("directory", type=Path)
    crashing.add_argument("--target", required=True)

    args = parser.parse_args(argv)

    if args.command == "count":
        print(f"{args.label}: {count(args.directory)} entries in {args.directory}")
        return 0

    found = crashes(args.directory, args.target)
    for path in found:
        print(f"crash artifact: {path}", file=sys.stderr)
    if found:
        print(f"{args.target}: {len(found)} crash artifacts", file=sys.stderr)
        return 1

    print(f"{args.target}: no crash artifacts")
    return 0


if __name__ == "__main__":  # pragma: no cover - the lane's entry point
    raise SystemExit(main())
