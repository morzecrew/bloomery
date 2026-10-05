# Authoring bloomery-skills

The maintainer rules for `skills/bloomery-skills/`. The design is S-0089;
`tests/unit/test_skills.py` enforces everything below that a test can see.

## Audience

The skill is for people and agents **writing a bloomery project**: specs,
compiling, planning a change, quality rules, targets and the Python API. It
never teaches changing bloomery, and never tells a reader to read `src/`.
Contributor guidance stays in `AGENTS.md` and `.agents/skills/`.

## What ships

`skills/bloomery-skills/` holds `SKILL.md` and `references/*.md`, and nothing
else: the installer copies the directory whole into a consumer's skills
directory. Anything for maintainers (this file, `README.md`, the census) sits
in `skills/`, one level up. A stray file in the skill directory, such as an
`AGENTS.md` written by a projection, fails the test.

## The index

`SKILL.md` is a routing index, not a chapter. It holds:

- the frontmatter (`name: bloomery-skills` and a description);
- the mental model, in four sentences;
- the rule that a task needs its whole row;
- the routing table under `## Routing`: one row per task, naming every
  reference that task needs as backticked names, in reading order;
- the index under `## Index`: every reference, linked as
  `[name](references/name.md)`, grouped by area.

The index and `references/` agree in both directions, and every name in the
routing table is indexed.

## Splitting

A reference covers one job, never splits a procedure across files, and stands
alone: it answers its task without a second file for context. It runs 60 to
250 lines. A shorter one is listed under [Short references](#short-references)
with its reason; nothing may run longer.

The reference map in S-0089's design is the file set. Adding or removing a
reference amends that document in the same change that creates or deletes the
file.

## Links

- Between references: relative links that resolve and never leave
  `skills/bloomery-skills/`. Links into `skills/` or the repository break in a
  consumer's checkout.
- To the published documentation:
  `https://morzecrew.github.io/bloomery/latest/<page>/`, with `latest` and the
  trailing slash. A URL without a version segment is a 404.

## Examples

Every example is checked against the bloomery it ships with.

- A `yaml` block declares itself on its fence. ```` ```yaml spec=<kind> ````
  validates against the JSON Schema `bloomery schema --kind <kind>` exports, so
  it must be a whole document with its version key. ```` ```yaml fragment ````
  must parse and must *not* validate as a complete spec of any kind. A bare
  ```` ```yaml ```` fails.
- A `python` block parses, and imports only names in `bloomery.__all__`, from
  `bloomery` itself. Its calls are not executed; review catches a renamed
  method.
- A `bloomery …` line in a `console`, `shell`, `bash` or `sh` block names a
  command and flags the CLI accepts.

## Short references

References under 60 lines, one per line as `` - `name` — reason ``.
