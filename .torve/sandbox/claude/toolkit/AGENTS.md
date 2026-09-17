<!-- torve:managed sandboxes/claude/toolkit — rendered from the corpus; do not edit by hand -->

## Decisions governing `sandboxes/claude/toolkit/`

### S-0066/D-1 — `LOCKED` (An attempt's inputs are declared, and the image says what it loaded)

A sandbox attempt's inputs are what its profile declared; the files the worktree carries for other readers — `.mcp.json`, `.claude/skills`, `.agents/skills`, `AGENTS.md` — are shut out by each image's own switch

- Paths: `sandboxes/claude/toolkit/run` `sandboxes/dsh/toolkit/run` `sandboxes/mimo/toolkit/run`
- Consequence: the regime digest means what it claims, so two attempts recorded under one digest saw one set of inputs; a session is unaffected, because it makes no such claim
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0066/D-3 — `ASSUMED` (An attempt's inputs are declared, and the image says what it loaded)

Each image emits a machine-readable trace whose last line is still the result envelope the engine parses, so the burn parser is fed without moving the seam

- Paths: `sandboxes/claude/toolkit/run` `sandboxes/dsh/toolkit/report-usage` `sandboxes/mimo/toolkit/run`
- Consequence: `parse_burn` produces its first profile in the engine's history, and the per-turn and per-tool facts every later seat comparison needs start being recorded

### S-0073/D-8 — `ASSUMED` (The working rules live once, and say what an attempt costs)

Each image reads the system text the engine staged, through its own channel — claude's `--append-system-prompt`, dsh's persona row — and a seat whose image does not read it is the engine's silence, not the model's

- Paths: `sandboxes/claude/toolkit/run` `sandboxes/dsh/toolkit/run`
- Consequence: the rules arrive before the contract rather than as a file the attempt happens to open on its third call, which is what D-2 claims matters and what D-5 cannot be judged without

<!-- /torve:managed -->
