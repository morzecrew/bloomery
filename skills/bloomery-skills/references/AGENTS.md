<!-- torve:managed skills/bloomery-skills/references — rendered from the corpus; do not edit by hand -->

## Decisions governing `skills/bloomery-skills/references/`

### S-0091/D-4 — `ASSUMED` (A recipe's operands carry types) — implementation: none

Every catalog in the repository that computes a recipe over a non-canonical operand declares `types:`; the reference pages and the skill's catalog reference document the key, and the changelog marks the refusal as breaking with an upgrade note.

- Paths: `tests/fixtures/` `examples/` `pages/docs/reference/` `skills/bloomery-skills/references/` `CHANGELOG.md`
- Consequence: the repository's own catalogs compile under D-3, and a user upgrading reads what to add

<!-- /torve:managed -->
