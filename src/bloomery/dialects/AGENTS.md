<!-- torve:managed src/bloomery/dialects — rendered from the corpus; do not edit by hand -->

## Decisions governing `src/bloomery/dialects/`

### S-0012/D-8 — `OPEN` (Validating a dialect port against an engine we cannot run)

Whether a cloud port ships in-tree or as an extension package registered through `register_dialect`; decide it before the first cloud port lands

- Paths: `src/bloomery/dialects/**`
- Consequence: Moving a shipped dialect between the two is a breaking change either way, so the choice is cheap now and expensive later

<!-- /torve:managed -->
