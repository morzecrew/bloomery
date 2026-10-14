"""One reading of a scope glob (S-0105/D-1).

The scope gate reads a glob the way gitignore does, through pathspec. This
module holds that reading in the standard library alone, so the engine and the
pre-write hook share one function: `matches` asks whether a path falls under
any of a set of globs, and `overlap` asks whether two sets of globs can both
match one path. Both are decided by `_meet`, a segment-wise meet of two
normalised patterns.

Normalisation follows gitignore: a pattern with no inner `/` matches at any
depth, a leading `/` anchors it to the root, a trailing `/` names a directory
(what is under it matches), `**` as a whole segment spans segments while `*`
and `?` stay within one, and a bracket class reads as any one character —
which can only make `overlap` report an overlap that is not there.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable

__all__ = ["matches", "overlap"]

# The two patterns that normalise to a language of their own: every path
# (`**`, `*` and `/**`) and every path with a slash (`**/` and `*/`).
_ALL = ("all",)
_SLASHED = ("slashed",)

# A normalised pattern is one of those sentinels or a tuple of segments; `**`
# is only ever a whole segment.
_Pattern = tuple[str, ...]

_STAR = "*"
_ANY = "?"


def _normalise(glob: str) -> _Pattern | None:
    """A glob as gitignore reads it: the segments, with an unanchored
    single-segment pattern given a leading `**`, a trailing `/` turned into a
    trailing `**`, duplicate `**` collapsed, and the pure-wildcard spellings
    reduced to the two languages above. The empty pattern, `/` alone and a
    comment match nothing."""

    pattern = glob.rstrip()

    if not pattern or pattern == "/" or pattern.startswith("#"):
        return None

    segments = pattern.split("/")
    is_dir = not segments[-1]

    if segments[0] == "":
        # A leading slash anchors the pattern to the root; drop the empty part.
        del segments[0]
    elif (len(segments) == 1 or (len(segments) == 2 and not segments[1])) and segments[0] != "**":
        # No slash before the last segment: match at any depth.
        segments.insert(0, "**")

    if not segments:
        return None

    if not segments[-1]:
        # A trailing slash names a directory: everything under it matches.
        segments[-1] = "**"

    for index in range(len(segments) - 1, 0, -1):
        if segments[index - 1] == "**" and segments[index] == "**":
            del segments[index]

    if len(segments) == 1 and segments[0] == "**":
        return _SLASHED if is_dir else _ALL

    if len(segments) == 2 and segments[0] == "**" and segments[1] == "*":
        return _ALL

    if len(segments) == 3 and segments[:2] == ["**", "*"] and segments[2] == "**":
        return _SLASHED

    return tuple(segments)


def _epsilon(pattern: _Pattern, states: set[int]) -> set[int]:
    """Close *states* over the zero-segment transitions: a `**` that is not
    the last segment may consume nothing and move on."""

    out = set(states)

    for state in list(out):
        while 0 <= state < len(pattern) - 1 and pattern[state] == "**":
            state += 1
            out.add(state)

    return out


def _consume(pattern: _Pattern, state: int, segment: str) -> set[int]:
    """Where one path segment lands from *state*: a plain segment matches it,
    a non-final `**` keeps the state (it consumes any segment), a final `**`
    consumes it and ends, and the accept state loops on any segment."""

    if state == len(pattern):
        return {state}

    piece = pattern[state]

    if piece == "**":
        return {len(pattern)} if state == len(pattern) - 1 else {state}

    return {state + 1} if fnmatch.fnmatchcase(segment, piece) else set()


def _accepts(pattern: _Pattern, path: tuple[str, ...]) -> bool:
    """Whether a normalised pattern matches a path's segments."""

    if pattern is _ALL:
        return bool(path)

    if pattern is _SLASHED:
        return len(path) >= 2

    states = _epsilon(pattern, {0})

    for segment in path:
        reached: set[int] = set()

        for state in states:
            reached |= _epsilon(pattern, _consume(pattern, state, segment))

        if not reached:
            return False

        states = reached

    return len(pattern) in states


def matches(path: str, globs: Iterable[str]) -> bool:
    """Whether *path* falls under any of *globs*, in the gitignore reading the
    scope gate uses: the same glob answers the same set of paths everywhere the
    engine reads it."""

    segments = tuple(part for part in path.split("/") if part)

    if not segments:
        return False

    for glob in globs:
        pattern = _normalise(glob)

        if pattern is not None and _accepts(pattern, segments):
            return True

    return False


# ----------------------- #


def _atoms(segment: str) -> list[tuple[str, ...]]:
    """One segment's glob atomised: `*`, `?`, a bracket class read as any one
    character, or a literal character."""

    atoms: list[tuple[str, ...]] = []
    index = 0

    while index < len(segment):
        character = segment[index]

        if character == "*":
            atoms.append(("star",))
        elif character == "?":
            atoms.append(("any",))
        elif character == "[":
            end = segment.find("]", index + 1)

            if end == -1:
                atoms.append(("char", "["))
            else:
                atoms.append(("any",))
                index = end
        else:
            atoms.append(("char", character))

        index += 1

    return atoms


def _atom_consume(atoms: list[tuple[str, ...]], index: int) -> list[tuple[int, str, str]]:
    """One atom's consuming transitions, as `(next, kind, character)`: a `*`
    loops, `?` and a class consume any one character, a literal consumes
    itself."""

    if index >= len(atoms):
        return []

    atom = atoms[index]

    if atom[0] == "star":
        return [(index, "any", "")]

    if atom[0] == "any":
        return [(index + 1, "any", "")]

    return [(index + 1, "char", atom[1])]


def _atom_epsilon(atoms: list[tuple[str, ...]], index: int) -> int | None:
    """The zero-character move a `*` may take, or `None`."""

    if index < len(atoms) and atoms[index][0] == "star":
        return index + 1

    return None


def _segment_closure(
    left: list[tuple[str, ...]],
    right: list[tuple[str, ...]],
    state: tuple[int, int],
) -> set[tuple[int, int]]:
    """Close a pair of atom positions over the zero-character `*` moves."""

    out = {state}
    stack = [state]

    while stack:
        index, other = stack.pop()

        for atoms, position in ((left, index), (right, other)):
            nxt = _atom_epsilon(atoms, position)

            if nxt is None:
                continue

            moved = (nxt, other) if atoms is left else (index, nxt)

            if moved not in out:
                out.add(moved)
                stack.append(moved)

    return out


def _segment_meet(left: str, right: str) -> bool:
    """Whether two segment globs share one nonempty string. A bracket class
    reads as any one character, so a class can only over-report."""

    left_atoms = _atoms(left)
    right_atoms = _atoms(right)
    end = (len(left_atoms), len(right_atoms))
    seen = {
        (index, other, False) for index, other in _segment_closure(left_atoms, right_atoms, (0, 0))
    }
    stack = list(seen)

    while stack:
        index, other, used = stack.pop()

        if used and (index, other) == end:
            return True

        for first, kind, character in _atom_consume(left_atoms, index):
            for second, other_kind, other_character in _atom_consume(right_atoms, other):
                if kind != "any" and other_kind != "any" and character != other_character:
                    continue

                for moved in _segment_closure(left_atoms, right_atoms, (first, second)):
                    state = (moved[0], moved[1], True)

                    if state not in seen:
                        seen.add(state)
                        stack.append(state)

    return False


# ----------------------- #


def _consuming(pattern: _Pattern, state: int) -> list[tuple[int, str, str]]:
    """One state's consuming transitions, as `(next, kind, glob)`: `any`
    consumes any segment, `seg` consumes one matching the glob."""

    if state == len(pattern):
        return [(state, "any", "")]

    piece = pattern[state]

    if piece == "**":
        return [(len(pattern), "any", "")] if state == len(pattern) - 1 else [(state, "any", "")]

    return [(state + 1, "seg", piece)]


def _meet(left: _Pattern, right: _Pattern) -> bool:
    """Whether two normalised patterns match one common path. A pure-wildcard
    pattern matches every path, or every path with a slash, and every other
    pattern matches such a path; both general, the product of their segment
    automata is searched for a common accepting run."""

    if left is _ALL or left is _SLASHED or right is _ALL or right is _SLASHED:
        return True

    seen = _pattern_closure(left, right, (0, 0))
    stack = list(seen)
    end = (len(left), len(right))

    while stack:
        state = stack.pop()

        if state == end:
            return True

        for first, kind, glob in _consuming(left, state[0]):
            for second, other_kind, other_glob in _consuming(right, state[1]):
                if kind == "seg" and other_kind == "seg" and not _segment_meet(glob, other_glob):
                    continue

                for moved in _pattern_closure(left, right, (first, second)):
                    if moved not in seen:
                        seen.add(moved)
                        stack.append(moved)

    return False


def _pattern_closure(
    left: _Pattern, right: _Pattern, state: tuple[int, int]
) -> set[tuple[int, int]]:
    """Close a pair of pattern positions over the zero-segment `**` moves."""

    out = {state}
    stack = [state]

    while stack:
        index, other = stack.pop()

        for pattern, position in ((left, index), (right, other)):
            if position < len(pattern) - 1 and pattern[position] == "**":
                moved = (position + 1, other) if pattern is left else (index, position + 1)

                if moved not in out:
                    out.add(moved)
                    stack.append(moved)

    return out


def overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    """Whether two sets of globs can both match one path: exact on the gitignore
    grammar, so the fence never runs two tasks that can write one file."""

    patterns = [_normalise(glob) for glob in right]

    for glob in left:
        one = _normalise(glob)

        if one is None:
            continue

        for other in patterns:
            if other is not None and _meet(one, other):
                return True

    return False
