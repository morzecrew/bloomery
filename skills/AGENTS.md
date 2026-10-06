<!-- torve:managed skills — rendered from the corpus; do not edit by hand -->

## Decisions governing `skills/`

### S-0089/D-1 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

bloomery publishes one agent skill, `skills/bloomery-skills/` with frontmatter `name: bloomery-skills`, installed by `npx skills add morzecrew/bloomery`. It holds `SKILL.md` and `references/*.md` only. The maintainer rules, install instructions and census table sit at `skills/`, outside what ships

- Paths: `skills/README.md` `skills/AUTHORING.md` `tests/unit/test_skills.py`
- Consequence: a consumer installs one name, and nothing for maintainers reaches their `.claude/skills/`

### S-0089/D-2 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

The skill is for people and agents writing a bloomery project: specs, compiling, planning, quality, targets and the Python API. Changing bloomery itself is not taught there

- Paths: `skills/AUTHORING.md`
- Consequence: contributor guidance stays in `AGENTS.md` and `.agents/skills/`, and the skill never tells a reader to read `src/`

### S-0089/D-3 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

`SKILL.md` is a routing index: the mental model, the rule that a task needs its whole row, a routing table keyed by task naming every reference the task needs, and an index of every reference

- Paths: `skills/AUTHORING.md` `tests/unit/test_skills.py`
- Consequence: an agent reads three to five references for a task, not one and not twenty-five

### S-0089/D-4 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

A reference covers one job, never splits a procedure, stands alone, and runs 60 to 250 lines; a shorter one records its reason in `AUTHORING.md`

- Paths: `skills/AUTHORING.md` `tests/unit/test_skills.py`
- Consequence: a reference answers its task without a second file for context, and no reference is a narrative chapter

### S-0089/D-5 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

The reference map in this document's design is the file set; adding or removing a reference amends this document in the same change that creates or deletes the file

- Paths: `skills/AUTHORING.md` `tests/unit/test_skills.py`
- Consequence: a reference cannot appear or vanish without a reviewed amendment, and the parity check makes that enforceable

### S-0089/D-6 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

A reference links between references with relative links that never leave the skill directory. It links the published documentation as `https://morzecrew.github.io/bloomery/latest/<page>/`

- Paths: `skills/AUTHORING.md` `tests/unit/test_skills.py`
- Consequence: every link works in a consumer's checkout, and none hits the 404 the docs give a URL with no version segment

### S-0089/D-8 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

`skills/coverage.toml` gives every spec kind, emit target, CLI command and quality-rule kind either a reference that shows it in a checked example or out of scope with a reason. The test reads the units from bloomery and fails on a missing entry or a covered unit with no example

- Paths: `skills/coverage.toml` `tests/unit/test_skills.py`
- Consequence: a new kind, target or command cannot land without a decision about what the skill says about it

### S-0089/D-9 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

When the skill lands, every routing-table row is verified once by behaviour: a cold agent given only `SKILL.md` and a task from that row opens every reference the row names. The opened files are observed, and the cases and results are recorded in `skills/AUTHORING.md`

- Paths: `skills/AUTHORING.md`
- Consequence: the routing table is known to work, not assumed to, and a later row adds a case

### S-0089/D-10 — `ASSUMED` (One agent skill teaches a bloomery project) — implementation: none

Retrieval (`RetrievalSpec`, vectors and encoder identities) gets no reference yet: the census records it out of scope, with the trigger that a project outside bloomery's own examples declares a `RetrievalSpec`, and that trigger adds the reference by amendment

- Paths: `skills/coverage.toml`
- Consequence: the first skill covers what adopters write today, and retrieval cannot be forgotten, because the census names it and the condition that brings it in

<!-- /torve:managed -->
