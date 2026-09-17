"""Turn the equipment manifest into the session flags claude takes (S-0063/D-3).

A real file rather than a heredoc, so the thing the image ships is the thing
a test can run.

    python3 equip_flags.py <manifest.json> <args-file>
"""

import json
import os
import shlex
import shutil
import sys

# One flag per kind, for the kinds a session flag actually reaches. A kind that
# is not here is a kind this harness has no channel for, and the engine refused
# the profile that declared it before the sandbox existed (S-0063/D-4) — so an
# unknown kind here is a bug, not input.
#
# `skill` is deliberately absent. `--add-dir` adds a directory to the working
# set and does *not* load skills: measured, a session given five skills through
# it listed only claude's built-ins. Skills load from a skills root, so they are
# copied to the one the engine named.
#
# The directory a hook item carries per harness (S-0072/D-1), named after the
# harness this image is — `claude-sandbox` reads `claude/`. This script lives in
# the claude image, so it reaches for claude's and knows nothing of the others.
HARNESS_DIR = "claude"
FLAG = {
    "plugin": "--plugin-dir",
    "mcp": "--mcp-config",
    "hook": "--settings",
    "agent": "--agents",
}

manifest, args = sys.argv[1], sys.argv[2]
root = os.path.expanduser(os.environ.get("TORVE_EQUIP_ROOT", ""))

with open(manifest, encoding="utf-8") as handle:
    items = json.load(handle).get("items", [])

words = []

for item in items:
    kind, path = item["kind"], item["path"]

    if kind == "skill":
        if not root:
            raise SystemExit(
                "this harness loads skills from a skills root and the engine named no "
                "`TORVE_EQUIP_ROOT` — the manifest owes an `equip_root` (S-0063/D-19)"
            )

        os.makedirs(root, exist_ok=True)
        shutil.copytree(path, os.path.join(root, os.path.basename(path)), dirs_exist_ok=True)
        continue

    if kind == "mcp":
        # `--mcp-config` reads JSON files or strings, never a directory
        # (measured on 2.1.252), so an mcp item is a directory holding one
        # `mcp.json` beside whatever that config launches — the same shape a
        # hook item has. Handing the flag the directory is what silently
        # produced a session with `mcp_servers: []` while the plugin it was
        # meant to serve loaded fine and declared nothing.
        path = os.path.join(path, "mcp.json")

        if not os.path.isfile(path):
            raise SystemExit(
                f"mcp item has no mcp.json at {path} — an mcp item is a directory "
                "holding one `mcp.json`, because `--mcp-config` reads a file"
            )

    if kind == "hook":
        # `--settings` reads a file; every other flag here reads the directory an
        # item was fetched into. A hook item keeps its payload at the root and one
        # directory per harness beside it (S-0072/D-1), so the flag points at the
        # harness's own file, and the scripts the settings name stay reachable at
        # the item's root.
        path = os.path.join(path, HARNESS_DIR, "settings.json")

        if not os.path.isfile(path):
            raise SystemExit(
                f"hook item {item['kind']!r} has no {HARNESS_DIR} settings at {path} — a "
                "hook is a directory of scripts with one settings file per harness "
                "beside them"
            )

    words += [FLAG[kind], path]

with open(args, "w", encoding="utf-8") as handle:
    handle.write(" ".join(shlex.quote(word) for word in words))
