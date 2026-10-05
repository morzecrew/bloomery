# bloomery skills

One agent skill, `bloomery-skills`, for people and agents writing a bloomery
project: specs, compiling, planning a change, quality rules, targets and the
Python API.

## Install

```console
npx skills add morzecrew/bloomery
```

This copies `skills/bloomery-skills/` into the project's agent skills directory
(for Claude Code, `.claude/skills/bloomery-skills/`). Only that directory ships:
this README, `AUTHORING.md` and the census beside them are for maintainers.

## How it is read

`SKILL.md` is an index. It states the mental model, then a routing table keyed
by task: each row names the three to five references that task needs, in the
order to read them. An agent reads the whole row, not the first reference, and
uses the index for anything the row left out. The routing table in
[`bloomery-skills/SKILL.md`](bloomery-skills/SKILL.md#routing) is the one copy;
it gains its rows as the references land.

Changing bloomery itself is not covered here: that guidance lives in the
repository's `AGENTS.md` files and `.agents/skills/`.
