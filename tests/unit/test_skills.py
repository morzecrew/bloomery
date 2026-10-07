"""The published agent skill stays true to the bloomery it ships with (S-0089).

`skills/bloomery-skills/` is what `npx skills add morzecrew/bloomery` copies
into a consumer's repository. Four families of check keep it honest:

* **Structure** — the frontmatter, `SKILL.md` and `references/` only, the index
  and the files agreeing both ways, the routing table naming indexed
  references, and the line bounds (S-0089/D-1, S-0089/D-3–S-0089/D-5).
* **Links** — relative links resolve inside the skill directory; published
  documentation links carry `latest/` (S-0089/D-6).
* **Examples** — every `yaml` block declares itself and validates as it says,
  Python imports only `bloomery.__all__`, and `bloomery` shell lines name a
  command and flags the CLI accepts (S-0089/D-7).
* **Census** — every spec kind, emit target, CLI command and quality-rule kind,
  read from bloomery, has an entry in `skills/coverage.toml`: a reference that
  shows it in a checked example, or out of scope with a reason (S-0089/D-8).

Each check is a function returning its problems, run once over the real skill
and once over a fixture built to break it: a check never observed to fail is
indistinguishable from one that never fires.
"""

from __future__ import annotations

import argparse
import ast
import re
import shlex
import tomllib
import typing
from functools import cache
from pathlib import Path
from textwrap import indent

import pytest
import yaml
from jsonschema import Draft202012Validator

import bloomery
from bloomery import SpecKind, Target, spec_json_schema
from bloomery.cli import build_parser
from bloomery.spec.quality import EntityQualityRule, FieldQualityRule

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
SKILL = SKILLS / "bloomery-skills"
AUTHORING = SKILLS / "AUTHORING.md"
CENSUS = SKILLS / "coverage.toml"

NAME = "bloomery-skills"
MIN_LINES, MAX_LINES = 60, 250
DOCS = "https://morzecrew.github.io/bloomery/"
LATEST = DOCS + "latest/"
SHELLS = {"console", "shell", "bash", "sh"}

_FENCE = re.compile(r"^(?P<indent> *)(?P<fence>`{3,})(?P<lang>[\w-]*)(?P<info>[^`]*)$")
_LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)")
_INDEXED = re.compile(r"\]\(references/(?P<name>[\w-]+)\.md\)")
_ROUTED = re.compile(r"`(?P<name>[\w-]+)`")
_SHORT = re.compile(r"^- `(?P<name>[\w-]+)` — \S")


# ....................... #
# Reading the markdown


def _markdown(skill: Path) -> list[Path]:
    return sorted(skill.rglob("*.md"))


#: The engine's spec projection governs ``references/`` too, and writes a managed
#: ``AGENTS.md`` there (it is rendered from the corpus, not hand-authored). It
#: carries no Index entry, no routing row and no line budget, so the structure
#: checks read past it — the stray-file guard still fires on a root ``AGENTS.md``.
_MANAGED = "AGENTS.md"


def _references(skill: Path) -> list[Path]:
    """The hand-authored references in ``references/``, the managed file aside."""
    return sorted(path for path in (skill / "references").glob("*.md") if path.name != _MANAGED)


def _section(text: str, heading: str) -> str:
    """The body under ``## heading``, up to the next level-two heading."""
    match = re.search(rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", text, re.M | re.S)
    return match["body"] if match else ""


def _blocks(text: str) -> list[tuple[int, str, list[str], str]]:
    """Every fenced block as ``(line, language, info words, body)``.

    A fence may be indented (inside a list item) or longer than three backticks;
    it closes on a fence at least as long, and its body loses the opener's indent.
    """
    blocks = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        opened = _FENCE.match(lines[index])
        if opened is None:
            index += 1
            continue
        start = index
        index += 1
        closer = re.compile(rf" *`{{{len(opened['fence'])},}} *")
        body = []
        while index < len(lines) and not closer.fullmatch(lines[index]):
            line = lines[index]
            body.append(line[min(len(opened["indent"]), len(line) - len(line.lstrip(" "))) :])
            index += 1
        blocks.append((start + 1, opened["lang"], opened["info"].split(), "\n".join(body)))
        index += 1
    return blocks


def _without_code(text: str) -> str:
    """The text with fenced blocks removed: a link inside an example is the example's."""
    return re.sub(r"^ *(`{3,}).*?^ *\1`* *$", "", text, flags=re.M | re.S)


# ....................... #
# Structure (S-0089/D-1, S-0089/D-3, S-0089/D-4, S-0089/D-5)


def structure_problems(skill: Path, authoring: Path) -> list[str]:
    problems = []
    skill_md = skill / "SKILL.md"
    if not skill_md.is_file():
        return ["SKILL.md is missing"]

    for path in sorted(p for p in skill.rglob("*") if p.is_file()):
        relative = path.relative_to(skill)
        if relative.parts != ("SKILL.md",) and not (
            len(relative.parts) == 2 and relative.parts[0] == "references" and path.suffix == ".md"
        ):
            problems.append(f"{relative}: only SKILL.md and references/*.md ship")

    text = skill_md.read_text(encoding="utf-8")
    front = re.match(r"---\n(?P<yaml>.*?)\n---\n", text, re.S)
    meta = yaml.safe_load(front["yaml"]) if front else None
    if not isinstance(meta, dict):
        problems.append("SKILL.md: no frontmatter")
    else:
        if meta.get("name") != NAME:
            problems.append(f"SKILL.md: frontmatter name must be {NAME!r}")
        if not isinstance(meta.get("description"), str) or not meta["description"].strip():
            problems.append("SKILL.md: frontmatter needs a description")

    for heading in ("Mental model", "Read the whole row", "Routing", "Index"):
        if f"\n## {heading}\n" not in text:
            problems.append(f"SKILL.md: no '## {heading}' section")

    indexed = set(_INDEXED.findall(_section(text, "Index")))
    files = {path.stem for path in _references(skill)}
    problems += [f"index names {name}, which has no file" for name in sorted(indexed - files)]
    problems += [f"references/{name}.md is not in the index" for name in sorted(files - indexed)]

    table = [line for line in _section(text, "Routing").splitlines() if line.startswith("|")]
    for row in table[2:]:
        cells = row.strip("|").split("|")
        routed = _ROUTED.findall(cells[1]) if len(cells) > 1 else []
        if not routed:
            problems.append(f"routing row names no reference: {row}")
        problems += [f"routing row names unindexed {name}: {row}" for name in routed if name not in indexed]

    short = {
        match["name"]
        for line in _section(authoring.read_text(encoding="utf-8"), "Short references").splitlines()
        if (match := _SHORT.match(line))
    }
    for path in _references(skill):
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count > MAX_LINES:
            problems.append(f"references/{path.name}: {count} lines, over {MAX_LINES}")
        elif count < MIN_LINES and path.stem not in short:
            problems.append(f"references/{path.name}: {count} lines, under {MIN_LINES} with no reason recorded")
    return problems


# ....................... #
# Links (S-0089/D-6)


def link_problems(skill: Path) -> list[str]:
    problems = []
    root = skill.resolve()
    for path in _markdown(skill):
        name = path.relative_to(skill)
        for target in _LINK.findall(_without_code(path.read_text(encoding="utf-8"))):
            if target.startswith(DOCS):
                page = target.split("#")[0]
                if not page.startswith(LATEST) or not page.endswith("/"):
                    problems.append(f"{name}: {target} must be {LATEST}<page>/")
            elif re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            else:
                resolved = (path.parent / target.split("#")[0]).resolve()
                if not resolved.is_relative_to(root):
                    problems.append(f"{name}: {target} leaves the skill directory")
                elif not resolved.exists():
                    problems.append(f"{name}: {target} does not resolve")
    return problems


# ....................... #
# Examples (S-0089/D-7)


@cache
def _validator(kind: SpecKind) -> Draft202012Validator:
    return Draft202012Validator(spec_json_schema(kind))


@cache
def _commands() -> dict[str, frozenset[str]]:
    parser = build_parser()
    (commands,) = (a for a in parser._actions if isinstance(a, argparse._SubParsersAction))  # noqa: SLF001
    return {name: frozenset(sub._option_string_actions) for name, sub in commands.choices.items()}  # noqa: SLF001


def _yaml_problems(where: str, info: list[str], body: str) -> list[str]:
    kinds = [word.removeprefix("spec=") for word in info if word.startswith("spec=")]
    if "fragment" not in info and not kinds:
        return [f"{where}: a yaml block declares `spec=<kind>` or `fragment` on its fence"]
    try:
        document = yaml.safe_load(body)
    except yaml.YAMLError as error:
        return [f"{where}: does not parse: {error}"]
    if "fragment" in info:
        whole = [kind.value for kind in SpecKind if _validator(kind).is_valid(document)]
        return [f"{where}: a fragment that validates as a whole {kind} spec" for kind in whole]
    (kind,) = kinds
    if kind not in SpecKind.__members__.values():
        return [f"{where}: {kind!r} is not a spec kind"]
    return [f"{where}: {error.message}" for error in _validator(SpecKind(kind)).iter_errors(document)]


def _python_problems(where: str, body: str) -> list[str]:
    try:
        tree = ast.parse(body)
    except SyntaxError as error:
        return [f"{where}: does not parse: {error.msg}"]
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            problems += [
                f"{where}: imports {alias.name}; only bloomery's public surface"
                for alias in node.names
                if alias.name.startswith("bloomery.")
            ]
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "bloomery":
            if node.module != "bloomery":
                problems.append(f"{where}: imports from {node.module}; import from bloomery")
                continue
            problems += [
                f"{where}: {alias.name} is not in bloomery.__all__"
                for alias in node.names
                if alias.name not in bloomery.__all__
            ]
    return problems


def _shell_problems(where: str, body: str) -> list[str]:
    problems = []
    for line in body.replace("\\\n", " ").splitlines():
        words = shlex.split(line.strip().removeprefix("$ "), comments=True)
        if not words or words[0] != "bloomery":
            continue
        words = words[1 : next((i for i, w in enumerate(words) if w in {"|", "&&", "||", ";", ">"}), len(words))]
        command = next((word for word in words if not word.startswith("-")), None)
        if command is None:
            if not set(words) <= {"--version", "--help", "-h"}:
                problems.append(f"{where}: `{line.strip()}` names no command")
            continue
        if command not in _commands():
            problems.append(f"{where}: `bloomery {command}` is not a command")
            continue
        problems += [
            f"{where}: `bloomery {command}` has no flag {word.split('=')[0]}"
            for word in words
            if word.startswith("-") and word.split("=")[0] not in _commands()[command]
        ]
    return problems


def example_problems(skill: Path) -> list[str]:
    problems = []
    for path in _markdown(skill):
        for line, lang, info, body in _blocks(path.read_text(encoding="utf-8")):
            where = f"{path.relative_to(skill)}:{line}"
            if lang in {"yaml", "yml"}:
                problems += _yaml_problems(where, info, body)
            elif lang in {"python", "py"}:
                problems += _python_problems(where, body)
            elif lang in SHELLS:
                problems += _shell_problems(where, body)
    return problems


# ....................... #
# Census (S-0089/D-8)


def census_units() -> dict[str, frozenset[str]]:
    """The units bloomery names, read from bloomery itself rather than the census."""
    rules = (
        member.model_fields["rule"].annotation
        for union in (FieldQualityRule, EntityQualityRule)
        for member in typing.get_args(typing.get_args(union)[0])
    )
    return {
        "spec_kind": frozenset(kind.value for kind in SpecKind),
        "target": frozenset(target.value for target in Target),
        "command": frozenset(_commands()),
        "rule_kind": frozenset(kind for literal in rules for kind in typing.get_args(literal)),
    }


def _shows(table: str, unit: str, lang: str, info: list[str], body: str) -> bool:
    """Whether one checked block shows ``unit``; what counts is stated atop the census."""
    if table == "spec_kind":
        return lang in {"yaml", "yml"} and f"spec={unit}" in info
    if table == "rule_kind":
        return lang in {"yaml", "yml"} and re.search(rf"\brule:\s*{unit}\b", body) is not None
    if lang not in SHELLS:
        return table == "target" and lang in {"python", "py"} and f"Target.{Target(unit).name}" in body
    lines = [line for line in body.replace("\\\n", " ").splitlines() if re.match(r"(\$ )?bloomery\b", line.strip())]
    if table == "command":
        return any(re.match(rf"(\$ )?bloomery(\s+-\S+)*\s+{unit}\b", line.strip()) for line in lines)
    return any(re.search(rf"--target[ =]{unit}\b", line) for line in lines)


def census_problems(skill: Path, census: Path, units: dict[str, frozenset[str]]) -> list[str]:
    problems = []
    entries = tomllib.loads(census.read_text(encoding="utf-8"))
    problems += [f"census table [{table}] is no unit kind" for table in sorted(entries.keys() - units.keys())]
    for table, names in sorted(units.items()):
        recorded = entries.get(table, {})
        problems += [f"{table} {name}: no census entry" for name in sorted(names - recorded.keys())]
        problems += [f"{table} {name}: bloomery has no such unit" for name in sorted(recorded.keys() - names)]
        for name in sorted(names & recorded.keys()):
            entry = recorded[name]
            reference, reason = entry.get("reference"), entry.get("out_of_scope")
            if (reference is None) == (reason is None) or set(entry) - {"reference", "out_of_scope"}:
                problems.append(f"{table} {name}: give exactly one of reference or out_of_scope")
            elif reason is not None:
                if not isinstance(reason, str) or not reason.strip():
                    problems.append(f"{table} {name}: out_of_scope needs a reason")
            elif not (path := skill / "references" / f"{reference}.md").is_file():
                problems.append(f"{table} {name}: references/{reference}.md does not exist")
            elif not any(
                _shows(table, name, lang, info, body) for _, lang, info, body in _blocks(path.read_text(encoding="utf-8"))
            ):
                problems.append(f"{table} {name}: references/{reference}.md shows it in no checked example")
    return problems


# ....................... #
# The real skill


def test_the_skill_is_well_formed() -> None:
    assert structure_problems(SKILL, AUTHORING) == []


def test_the_skills_links_stay_inside_and_on_latest() -> None:
    assert link_problems(SKILL) == []


def test_every_example_in_the_skill_checks() -> None:
    assert example_problems(SKILL) == []


def test_every_census_unit_has_an_entry() -> None:
    assert census_problems(SKILL, CENSUS, census_units()) == []


# ....................... #
# Fixtures: a clean twin that passes, and one break per check that fails

_CLEAN_SKILL = """\
---
name: bloomery-skills
description: A fixture.
---

## Mental model

Specs compile.

## Read the whole row

Read it.

## Routing

| I want to… | Read, in order |
|---|---|
| Start | `alpha` → `beta` |

## Index

- [alpha](references/alpha.md)
- [beta](references/beta.md)
"""

_CLEAN_SPEC = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
"""


def _reference(*body: str, lines: int = MIN_LINES) -> str:
    text = "\n".join(body)
    return text + "\n" * (lines - len(text.splitlines()) + 1)


@pytest.fixture
def fixture_skill(tmp_path: Path) -> tuple[Path, Path]:
    skill = tmp_path / NAME
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(_CLEAN_SKILL, encoding="utf-8")
    (skill / "references" / "alpha.md").write_text(
        _reference(
            "# alpha",
            "See [beta](beta.md) and [the docs](https://morzecrew.github.io/bloomery/latest/how-to/emit-dbt/#run).",
            "```yaml spec=mapping",
            _CLEAN_SPEC.rstrip(),
            "```",
            "```yaml fragment",
            "fields: {kind: {from: $.kind}}",
            "```",
            "```python",
            "from bloomery import compile_project, load_project",
            "import bloomery",
            "```",
            "```console",
            "$ bloomery compile specs --target dbt --dialect=duckdb | head",
            "bloomery schema \\",
            "  --kind mapping",
            "bloomery --version",
            "```",
        ),
        encoding="utf-8",
    )
    (skill / "references" / "beta.md").write_text(_reference("# beta"), encoding="utf-8")
    authoring = tmp_path / "AUTHORING.md"
    authoring.write_text("# Authoring\n\n## Short references\n\n", encoding="utf-8")
    return skill, authoring


def _all_problems(skill: Path, authoring: Path) -> list[str]:
    return structure_problems(skill, authoring) + link_problems(skill) + example_problems(skill)


def test_the_clean_fixture_passes_every_check(fixture_skill: tuple[Path, Path]) -> None:
    """The twin: a check that cannot pass is as broken as one that cannot fail."""
    assert _all_problems(*fixture_skill) == []


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def _skill_md(skill: Path) -> Path:
    return skill / "SKILL.md"


def _alpha(skill: Path) -> Path:
    return skill / "references" / "alpha.md"


def _example(skill: Path, block: str) -> None:
    _replace(_alpha(skill), "# alpha\n", f"# alpha\n{block}\n")


BREAKS = {
    # Structure
    "no frontmatter": lambda s: _replace(
        _skill_md(s), "---\nname: bloomery-skills\ndescription: A fixture.\n---\n", ""
    ),
    "wrong frontmatter name": lambda s: _replace(_skill_md(s), "name: bloomery-skills", "name: other"),
    "a stray file ships": lambda s: (s / "AGENTS.md").write_text("# managed\n", encoding="utf-8"),
    "a nested directory ships": lambda s: (s / "references" / "deep").mkdir()
    or (s / "references" / "deep" / "x.md").write_text("x\n", encoding="utf-8"),
    "a reference file removed": lambda s: (s / "references" / "beta.md").unlink(),
    "an unindexed reference": lambda s: (s / "references" / "gamma.md").write_text(
        _reference("# gamma"), encoding="utf-8"
    ),
    "a routing row naming an unindexed reference": lambda s: _replace(_skill_md(s), "`beta` |", "`beta` → `gamma` |"),
    "a routing row naming nothing": lambda s: _replace(_skill_md(s), "| Start |", "| Start | |\n| Finish |"),
    "a reference too short": lambda s: (s / "references" / "beta.md").write_text("# beta\n", encoding="utf-8"),
    "a reference too long": lambda s: (s / "references" / "beta.md").write_text(
        _reference("# beta", lines=MAX_LINES + 1), encoding="utf-8"
    ),
    "a missing section": lambda s: _replace(_skill_md(s), "## Read the whole row", "## Read whatever"),
    # Links
    "a link out of the skill": lambda s: _example(s, "[authoring](../../AUTHORING.md)"),
    "a link that does not resolve": lambda s: _example(s, "[gone](gone.md)"),
    "a published link without latest": lambda s: _example(
        s, "[docs](https://morzecrew.github.io/bloomery/how-to/emit-dbt/)"
    ),
    "a published link without its trailing slash": lambda s: _example(
        s, "[docs](https://morzecrew.github.io/bloomery/latest/how-to/emit-dbt)"
    ),
    # Examples
    "an undeclared yaml block": lambda s: _example(s, f"```yaml\n{_CLEAN_SPEC}```"),
    "an undeclared indented yaml block": lambda s: _example(s, "- item\n\n  ```yaml\n  colour: red\n  ```"),
    "an undeclared four-backtick yaml block": lambda s: _example(s, f"````yaml\n{_CLEAN_SPEC}````"),
    "an invalid indented spec": lambda s: _example(
        s, "- item\n\n" + indent(f"```yaml spec=mapping\n{_CLEAN_SPEC}colour: red\n```", "  ")
    ),
    "a spec with a field its kind lacks": lambda s: _example(s, f"```yaml spec=mapping\n{_CLEAN_SPEC}colour: red\n```"),
    "a spec missing its version key": lambda s: _example(
        s, "```yaml spec=mapping\n" + _CLEAN_SPEC.replace("mapping_version: 1\n", "") + "```"
    ),
    "a spec of an unknown kind": lambda s: _example(s, f"```yaml spec=widget\n{_CLEAN_SPEC}```"),
    "a fragment that is a whole spec": lambda s: _example(s, f"```yaml fragment\n{_CLEAN_SPEC}```"),
    "a fragment that does not parse": lambda s: _example(s, "```yaml fragment\nkey: [unclosed\n```"),
    "a python import outside __all__": lambda s: _example(s, "```python\nfrom bloomery import NoSuchThing\n```"),
    "a python import from a submodule": lambda s: _example(s, "```python\nfrom bloomery.cli import io\n```"),
    "python that does not parse": lambda s: _example(s, "```python\ndef broken(:\n```"),
    "a cli command that does not exist": lambda s: _example(s, "```console\n$ bloomery deploy specs\n```"),
    "a cli flag that does not exist": lambda s: _example(s, "```bash\nbloomery compile specs --turbo\n```"),
    "a cli flag on the wrong command": lambda s: _example(s, "```sh\nbloomery schema --target dbt\n```"),
}


@pytest.mark.parametrize("name", BREAKS)
def test_each_check_fails_on_its_break(name: str, fixture_skill: tuple[Path, Path]) -> None:
    skill, authoring = fixture_skill
    assert _all_problems(skill, authoring) == []
    BREAKS[name](skill)
    assert _all_problems(skill, authoring) != []


def test_a_short_reference_with_a_recorded_reason_passes(fixture_skill: tuple[Path, Path]) -> None:
    skill, authoring = fixture_skill
    (skill / "references" / "beta.md").write_text("# beta\n", encoding="utf-8")
    _append(authoring, "- `beta` — one table, nothing more to say\n")
    assert structure_problems(skill, authoring) == []


# ....................... #
# The census: a clean twin, and one break per way an entry goes wrong

_UNITS = {
    "spec_kind": frozenset({"mapping"}),
    "target": frozenset({"dbt", "retrieval"}),
    "command": frozenset({"compile", "schema"}),
    "rule_kind": frozenset({"unique"}),
}

_CLEAN_CENSUS = """\
[spec_kind]
mapping = { reference = "alpha" }

[target]
dbt = { reference = "alpha" }
retrieval = { out_of_scope = "no adopter declares it yet" }

[command]
compile = { reference = "alpha" }
schema = { reference = "alpha" }

[rule_kind]
unique = { out_of_scope = "prose only" }
"""


@pytest.fixture
def fixture_census(fixture_skill: tuple[Path, Path]) -> tuple[Path, Path]:
    skill, authoring = fixture_skill
    census = authoring.parent / "coverage.toml"
    census.write_text(_CLEAN_CENSUS, encoding="utf-8")
    return skill, census


def test_the_units_are_read_from_bloomery() -> None:
    units = census_units()
    assert "mapping" in units["spec_kind"]
    assert "retrieval" in units["target"]
    assert "compile" in units["command"]
    assert {"not_null", "referential"} <= units["rule_kind"]


def test_the_clean_census_passes(fixture_census: tuple[Path, Path]) -> None:
    assert census_problems(*fixture_census, _UNITS) == []


CENSUS_BREAKS = {
    "a spec kind added with no entry": lambda units, census: {**units, "spec_kind": units["spec_kind"] | {"widget"}},
    "a cli command added with no entry": lambda units, census: {**units, "command": units["command"] | {"deploy"}},
    "an entry for a unit bloomery lacks": lambda units, census: _append(census, '\n[command.deploy]\nreference = "alpha"\n'),
    "an unknown table": lambda units, census: _append(census, '\n[widget]\nx = { reference = "alpha" }\n'),
    "out of scope with no reason": lambda units, census: _replace(census, '"prose only"', '" "'),
    "both reference and out of scope": lambda units, census: _replace(
        census, '{ out_of_scope = "prose only" }', '{ reference = "alpha", out_of_scope = "prose only" }'
    ),
    "a reference that does not exist": lambda units, census: _replace(
        census, 'compile = { reference = "alpha" }', 'compile = { reference = "gone" }'
    ),
    "a covered spec kind with no example": lambda units, census: _replace(
        census, 'mapping = { reference = "alpha" }', 'mapping = { reference = "beta" }'
    ),
    "a covered target with no example": lambda units, census: _replace(
        census, 'dbt = { reference = "alpha" }', 'dbt = { reference = "beta" }'
    ),
    "a covered target shown in no example": lambda units, census: _replace(
        census, '{ out_of_scope = "no adopter declares it yet" }', '{ reference = "alpha" }'
    ),
    "a covered rule kind in prose only": lambda units, census: _replace(
        census, '{ out_of_scope = "prose only" }', '{ reference = "alpha" }'
    ),
}


@pytest.mark.parametrize("name", CENSUS_BREAKS)
def test_each_census_check_fails_on_its_break(name: str, fixture_census: tuple[Path, Path]) -> None:
    skill, census = fixture_census
    assert census_problems(skill, census, _UNITS) == []
    units = CENSUS_BREAKS[name](_UNITS, census) or _UNITS
    assert census_problems(skill, census, units) != []
