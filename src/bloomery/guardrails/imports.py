"""The import guards (S-0002 (§5.4), S-0002/D-1, S-0002/D-8): the three ways a declared
dependency can fail to be one.

An imports document is entirely references, like the export list it mirrors —
an alias and three lists of names — so what can go wrong with it is what can
go wrong with a name. Three things can, and each has a different repair:

* **the upstream was never supplied.** How the upstream artifact reaches the
  compile is the caller's (D8), so a declared alias with no IR behind it is a
  spec and a caller disagreeing about what this compile is. The refusal names
  what *was* supplied, because an empty set is a different repair from a
  misspelled alias — :class:`~bloomery.errors.UnknownStep`'s reasoning, one
  input over.
* **the upstream does not export it.** The refusal that makes an export list
  mean something. Without it "exported" would be a label with no consequence,
  and D1's explicit boundary would be explicit about nothing.
* **a name is claimed twice.** Two things of one kind answering to one name
  (§5.4), which §2 names as composition's payoff and which is invisible until
  a boundary exists to make the two meet. Twice over: a *local* name against
  an imported one, and two *upstreams* against each other — §5.4 names only
  the first, and the second is the same ambiguity with neither claimant
  local, so neither author can see it from their own file.

**Which side each local kind is read from is not uniform, and the split is the
one the tree already makes.** Marts and metrics come from the authored
documents, because a mart that failed to flatten is absent from the draft
while very much declared — :func:`~bloomery.guardrails.exports.check_export_targets`'s
argument, unchanged. **Entities come from the draft**, because a step output is
an entity too, named after the last segment of the relation its wiring binds
(S-0034/emission-and-the-dag), and a project whose step produces `customer` declares nothing
of that name in its entity model. That is
:func:`~bloomery.guardrails.lineage.check_lineage_names`'s argument, and taking
the authored model here would make the collision guard blind to exactly the
entities the spec layer never sees.

The upstream side is always its IR, because under D2 that is what crosses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import ImportCollision, UnexportedImport, UnknownUpstream

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from bloomery.errors import GuardrailError
    from bloomery.ir.nodes import ProjectIR
    from bloomery.spec.imports import Imports
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_imports",
    "declared_locally",
]

#: Import kind → the singular a refusal names one by. Written out rather than
#: sliced off the plural, which spells "entities" as "entitie" — and one table
#: is also what stops a kind being added to one side of the boundary and
#: silently unchecked on the other, since the two documents mirror each other.
_KINDS = {"entities": "entity", "marts": "mart", "metrics": "metric"}


def _listed(candidates: frozenset[str]) -> str:
    """What is available, for the refusal to end on.

    The whole list rather than a nearest match, capped — the same reasoning as
    the dangling-export guard's: the mistake is a name renamed on one side of
    a boundary and not the other, and a nearest match would name one candidate
    and hide the rename.
    """

    if not candidates:
        return "(none)"

    shown = sorted(candidates)
    listed = ", ".join(repr(candidate) for candidate in shown[:8])
    suffix = f", … ({len(shown)} in total)" if len(shown) > 8 else ""
    return f"{listed}{suffix}"


# ....................... #


def declared_locally(project: Project, entities: Iterable[str]) -> dict[str, frozenset[str]]:
    """Every name this project declares, by kind — the collision side.

    Two sources on purpose; the module docstring argues which and why. The
    entity names are passed rather than read off a draft, because the other
    caller is :func:`~bloomery.resolve.build._bind_imports`, which needs them
    while the draft is still being built — and the two agreeing about what a
    local name is, is what keeps a bound import from being refused as a
    collision with itself (S-0002/D-2).
    """

    return {
        "entities": frozenset(entities),
        "marts": (
            frozenset(project.marts.marts) | frozenset(project.marts.rollups)
            if project.marts is not None
            else frozenset[str]()
        ),
        "metrics": (
            frozenset(project.metric_set.metrics)
            if project.metric_set is not None
            else frozenset[str]()
        ),
    }


# ....................... #


def _claimed_twice(declared: Mapping[str, Imports]) -> list[GuardrailError]:
    """Refuse a name two upstreams both supply (§5.4, widened).

    §5.4 names the local-against-imported collision and stops there, which
    covers the case somebody noticed. This is the same ambiguity with neither
    claimant local: two upstreams exporting `customer`, both imported, and
    every later reference to it belonging to whichever lookup runs first.
    Worse than the local case rather than lesser, because no single author can
    see it — each upstream's file is correct on its own.

    Reported per colliding *name*, naming every alias that supplies it: a
    refusal per pair would say the same thing twice for three upstreams.
    """

    errors: list[GuardrailError] = []

    for kind, singular in _KINDS.items():
        suppliers: dict[str, list[str]] = {}
        for alias, read in declared.items():
            for name in getattr(read, kind):
                suppliers.setdefault(name, []).append(alias)

        for name, aliases in sorted(suppliers.items()):
            if len(aliases) < 2:
                continue
            named = ", ".join(repr(alias) for alias in sorted(aliases))
            errors.append(
                ImportCollision(
                    f"imports {singular} {name!r} from {len(aliases)} upstreams — {named}. "
                    f"Two {kind} answering to one name make every later reference ambiguous "
                    f"(S-0002 (§5.4)), and neither upstream's author can see it: each file "
                    f"is correct on its own. Fix: import it from one of them",
                    source_path="imports: imports",
                )
            )

    return errors


# ....................... #


def check_imports(
    project: Project, draft: ProjectIR, upstream: Mapping[str, ProjectIR]
) -> list[GuardrailError]:
    """Refuse every import that names nothing it can name (D1, D8).

    Every failing name is reported rather than the first: an imports document
    is authored as a list per upstream, and a boundary is usually got wrong in
    the same way more than once — one refusal per round-trip would make an
    author fix a rename four times.

    A missing upstream **short-circuits its own alias**: with no IR there is
    no export list to compare against, so reporting every name under it as
    unexported would be three refusals for one mistake, each naming a fix that
    is not the fix.
    """

    if project.imports is None:
        return []

    errors: list[GuardrailError] = _claimed_twice(project.imports.imports)
    local = declared_locally(project, (entity.name for entity in draft.entities))

    for alias, read in sorted(project.imports.imports.items()):
        source_path = f"imports: imports.{alias}"
        source = upstream.get(alias)

        if source is None:
            errors.append(
                UnknownUpstream(
                    f"imports from {alias!r}, which this compile was not given. How an "
                    f"upstream reaches a compile is the caller's — it is passed in, not "
                    f"discovered (S-0002/D-8) — so what was passed is the whole world. "
                    f"Fix: pass it as upstream[{alias!r}], or drop the import. Supplied: "
                    f"{_listed(frozenset(upstream))}",
                    source_path=source_path,
                    supplied=tuple(sorted(upstream)),
                )
            )
            continue

        exported = {
            kind: frozenset(getattr(source.exports, kind) if source.exports else ())
            for kind in _KINDS
        }

        for kind, singular in _KINDS.items():
            for name in sorted(getattr(read, kind)):
                if name not in exported[kind]:
                    errors.append(
                        UnexportedImport(
                            f"imports {singular} {name!r} from {alias!r}, which does not "
                            f"export it. An export list is explicit so that what is not on "
                            f"it is unavailable (S-0002/D-1). Fix: correct the name, or "
                            f"export it upstream. Exported {kind}: {_listed(exported[kind])}",
                            source_path=source_path,
                        )
                    )
                elif name in local[kind]:
                    errors.append(
                        ImportCollision(
                            f"imports {singular} {name!r} from {alias!r} and declares one of "
                            f"its own by that name. Two {kind} answering to one name make "
                            f"every later reference ambiguous (S-0002 (§5.4)), and a "
                            f"precedence rule would be invisible from the other project's "
                            f"file. Fix: rename the local one, or stop importing it",
                            source_path=source_path,
                        )
                    )

    return errors
