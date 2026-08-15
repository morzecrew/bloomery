"""The docs floor: what the reference *claims* must still be true (RFC 0025 §5.1).

A link checker would have passed the defect this exists for. Every link on
`concepts/data-quality.md` resolved while its warning block said Postgres
"cannot host a quality-carrying entity" — a statement that had been true and
stopped being true when RFC 0016 D84 gave `TRY_CAST` a Postgres spelling. An
external reviewer read it and concluded Postgres was "closer to a demo dialect
than a peer". A stale refusal cost a supported dialect its standing, and
nothing in any gate could have caught it (D2).

So the floor checks claims. Four of them, in increasing strength:

1. **The documented class set is the exported class set** — both directions.
   A renamed or deleted refusal fails, and so does one added to
   `bloomery.errors` and never written down. Static, total, runs anywhere.
2. **Every documented class is constructed during the suite** — the refusal
   census, in `tests/conftest.py`. Session-scoped, so it lives there rather
   than here; this module owns the list it is checked against.
3. **Every claim block's claim holds** — the table below. This is the only
   check pitched finely enough to have caught the Postgres warning, because
   that claim was never "`UnsupportedByTarget` no longer exists" (it does, dbt
   raises it) but "*this input* refuses", which stopped being true while the
   class stayed. Claims therefore assert an *outcome for an input*, and an
   outcome may be "does not refuse" — the reframed Postgres sentence is now
   itself pinned that way.
4. **Every repo-relative path cited in prose resolves.** Page links are
   Zensical's job and `just build-docs --strict` now fails on them; nothing
   was watching the `src/...` paths in backticks.

**What this does not catch, deliberately.** A stale claim in ordinary prose.
189 paragraphs in `pages/docs/` contain a refusal verb and 132 of them name no
error class, so a rule over prose is either 132 edits or an allowlist that
defeats itself — which is the "prose cannot be parsed for claims in general"
§5.1 anticipated. The trigger is admonition blocks (D11): the deliberate form
for "this will refuse you", the form the Postgres claim used, and the form a
reader treats as binding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from bloomery import Target, compile_project
from bloomery.errors import BloomeryError, GuardrailError, UnsupportedByTarget
from conftest import census_is_enforceable
from support.compiling import load_fixture
from support.docs_claims import (
    TAXONOMY_SMOKE_MODULE,
    census_exempt_classes,
    documented_error_classes,
    exported_error_classes,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "pages" / "docs"

#: An admonition that asserts something — the D11 trigger. `note`/`info` are
#: excluded: they carry context, not contracts.
_ADMONITION = re.compile(r'^!!! (?:warning|danger) "(?P<title>[^"]*)"\n(?P<body>(?:^ +.*\n|^\n)*)', re.M)

#: A backticked repo-relative path in prose. Anchored on the top-level
#: directories that exist, so ordinary code spans are not mistaken for paths.
_REPO_PATH = re.compile(r"`((?:src|tests|pages|rfcs|tools|\.github)/[A-Za-z0-9_./-]+)`")


# ....................... #
# 1. The documented set is the exported set


def test_every_documented_error_class_is_exported() -> None:
    """A renamed or deleted refusal leaves the reference describing nothing."""
    undefined = sorted(documented_error_classes() - exported_error_classes())
    assert undefined == [], (
        f"errors.md documents {undefined}, which bloomery.errors does not export"
    )


def test_every_exported_error_class_is_documented() -> None:
    """The reference opens with "the total `BloomeryError` hierarchy", and a
    class a caller can catch but cannot look up makes that sentence false.

    This direction is the one that was failing: `StepError`,
    `StepContractViolation` and `StepDeterminismError` are raised by code
    bloomery *generates into the consumer's warehouse*, so they are the
    refusals a user is most likely to meet and was least able to look up.
    """
    undocumented = sorted(exported_error_classes() - documented_error_classes())
    assert undocumented == [], (
        f"bloomery.errors exports {undocumented}, which errors.md does not document"
    )


# ....................... #
# 3. Documented claims still hold


@dataclass(frozen=True)
class Claim:
    """One assertion a docs block makes, and what checks it.

    ``expect`` is the error class the claim says is raised, or ``None`` for a
    claim that something is **accepted**. The negative form is not symmetry for
    its own sake: the Postgres defect was a positive claim that had quietly
    become false, and the sentence replacing it ("none of the three can fire on
    a shipped dialect") is exactly the kind that decays the same way.
    """

    page: str
    names: str
    expect: type[BloomeryError] | None
    provoke: Callable[[], object]


def _guardrail_aggregate() -> object:
    """`fanout_trap` — the corpus's batched-refusal case."""
    project, catalog = load_fixture("fanout_trap")
    from bloomery import build_project_ir  # noqa: PLC0415 — kept beside its one use

    return build_project_ir(project, catalog)


def _quality_corpus_on_every_dialect() -> object:
    """The quality corpus compiled for all three shipped dialects.

    The claim under test is that none of the three NULL-on-failure/normalize
    refusals can fire on a dialect that ships — so this must *return*, and the
    day a dialect loses the capability it stops returning.
    """
    project, catalog = load_fixture("dirty_corpus")
    return [
        compile_project(project, target=Target.SQLMESH, dialect=dialect, catalog=catalog)
        for dialect in ("duckdb", "postgres", "trino")
    ]


#: Every claim block in the docs, and what makes its claim checkable.
#: Completeness is enforced by
#: :func:`test_every_claim_block_is_represented_in_the_table` — a row nobody
#: added is the failure a curated table exists to prevent, so the table is
#: curated *with omissions visible* rather than trusted.
CLAIMS: tuple[Claim, ...] = (
    Claim(
        page="concepts/guardrails.md",
        names="GuardrailError",
        expect=GuardrailError,
        provoke=_guardrail_aggregate,
    ),
    Claim(
        page="concepts/data-quality.md",
        names="UnsupportedByTarget",
        expect=None,  # "No shipped dialect is in that position"
        provoke=_quality_corpus_on_every_dialect,
    ),
)


@pytest.mark.parametrize("claim", CLAIMS, ids=lambda c: f"{c.page}:{c.names}")
def test_each_documented_claim_still_holds(claim: Claim) -> None:
    if claim.expect is None:
        claim.provoke()  # must not raise
        return
    with pytest.raises(claim.expect):
        claim.provoke()


def test_the_guardrail_aggregate_really_batches() -> None:
    """The `!!! danger` block claims *one* aggregate carrying every violation,
    not the first one — the part of the claim a `pytest.raises` alone would
    not check."""
    with pytest.raises(GuardrailError) as excinfo:
        _guardrail_aggregate()
    assert len(excinfo.value.collected) > 1
    assert all(leaf.source_path for leaf in excinfo.value.collected)


def test_the_dialect_refusal_still_exists_for_a_dialect_without_the_capability() -> None:
    """The other half of the reframed Postgres sentence.

    "They are what a fourth dialect would meet if it arrived without the
    capability" is a claim about code that no shipped configuration reaches, so
    deleting the guard would leave every other check green. A dialect declaring
    no features is what provokes it.
    """
    from bloomery.dialects import get_dialect  # noqa: PLC0415 — one use, kept adjacent
    from bloomery.emit import EmitContext  # noqa: PLC0415
    from bloomery.emit.lower import entity_select  # noqa: PLC0415
    from bloomery.naming import DefaultNaming  # noqa: PLC0415

    class _Incapable(type(get_dialect("duckdb"))):  # type: ignore[misc]
        name = "incapable"
        features = frozenset()

    project, catalog = load_fixture("dirty_corpus")
    from bloomery import build_project_ir  # noqa: PLC0415

    ir = build_project_ir(project, catalog)
    entity = next(e for e in ir.entities if any(r.kind == "coercible" for r in e.quality))
    ctx = EmitContext(
        fingerprint="blm1:test", naming=DefaultNaming(), dialect=_Incapable()
    )
    with pytest.raises(UnsupportedByTarget) as excinfo:
        entity_select(entity, ctx)
    assert "NULL-on-failure cast" in str(excinfo.value)


def test_every_claim_block_is_represented_in_the_table() -> None:
    """D11's completeness trigger: an admonition asserting a refusal must name
    an error class, and that (page, class) pair must be in :data:`CLAIMS`.

    A curated table only checks the rows someone added, which is the failure it
    exists to catch. This is the tractable half — it makes an omission visible
    at the one place the docs make a claim deliberately.
    """
    covered = {(claim.page, claim.names) for claim in CLAIMS}
    missing: list[str] = []
    for page in sorted(DOCS.rglob("*.md")):
        rel = page.relative_to(DOCS).as_posix()
        for block in _ADMONITION.finditer(page.read_text()):
            named = set(re.findall(r"`([A-Z][A-Za-z]+)`", block["body"])) & exported_error_classes()
            if not named:
                missing.append(f"{rel}: !!! block {block['title']!r} names no error class")
                continue
            missing += [
                f"{rel}: !!! block {block['title']!r} claims {name} with no row in CLAIMS"
                for name in sorted(named)
                if (rel, name) not in covered
            ]
    assert missing == [], "\n".join(missing)


# ....................... #
# 2. The census's own precondition
#
# The census decides for itself when not to run, and a gate that does that
# needs its decision tested: the RFC-corpus check spent a release skipping its
# SHA half in CI because a shallow checkout was silently the normal path, and
# this one skipped *every* run until the detection below was pinned — pytest
# fills `args` from the `testpaths` ini, so a full run arrives as `['tests']`
# and comparing against the rootdir called it narrowed.


@dataclass(frozen=True)
class _FakeConfig:
    args: list[str]
    rootpath: Path
    option: object

    def getini(self, name: str) -> list[str]:
        assert name == "testpaths"
        return ["tests"]


def _config(args: list[str], keyword: str = "") -> _FakeConfig:
    return _FakeConfig(
        args=args, rootpath=ROOT, option=SimpleNamespace(keyword=keyword)
    )


@pytest.mark.parametrize(
    ("args", "keyword"),
    [
        (["tests"], ""),  # what `just test` and CI actually pass
        ([str(ROOT)], ""),
        ([], ""),
    ],
)
def test_the_census_enforces_on_a_whole_suite_run(args: list[str], keyword: str) -> None:
    assert census_is_enforceable(cast("pytest.Config", _config(args, keyword))) is None


@pytest.mark.parametrize(
    ("args", "keyword", "why"),
    [
        (["tests/unit/test_docs_floor.py"], "", "narrowed to"),
        (["tests/unit"], "", "narrowed to"),
        (["tests"], "docs", "narrowed by -k"),
    ],
)
def test_the_census_stands_down_on_a_narrowed_run(
    args: list[str], keyword: str, why: str
) -> None:
    """And says which — a silent skip is the failure mode being avoided."""
    reason = census_is_enforceable(cast("pytest.Config", _config(args, keyword)))
    assert reason is not None
    assert why in reason


def test_the_taxonomy_smoke_module_it_discounts_still_exists() -> None:
    """The census discounts one module by path. If that module is renamed, the
    discount silently stops applying and the census starts passing for the
    wrong reason — every class is 'produced' again."""
    assert (ROOT / TAXONOMY_SMOKE_MODULE).is_file()


def test_every_census_exemption_is_declared_in_the_reference() -> None:
    """An exemption is an edit to the public page, not a list beside the gate.
    `BloomeryError` is the one structural exemption — it is the base every
    other row is a kind of."""
    page = (DOCS / "reference" / "errors.md").read_text()
    for name in sorted(census_exempt_classes() - {"BloomeryError"}):
        row = next(line for line in page.splitlines() if line.startswith(f"| `{name}` |"))
        assert "never raised by bloomery" in row


# ....................... #
# 4. Cited repo paths resolve


def test_every_repo_relative_path_cited_in_docs_resolves() -> None:
    """The check that decays fastest without a gate, and the half Zensical
    cannot see: it resolves page links (and `--strict` now fails the build on a
    broken one), but a backticked `src/...` path is prose to it."""
    broken = sorted(
        f"{page.relative_to(DOCS).as_posix()}: {cited}"
        for page in DOCS.rglob("*.md")
        for cited in _REPO_PATH.findall(page.read_text())
        if not (ROOT / cited.split("#")[0]).exists()
    )
    assert broken == []
