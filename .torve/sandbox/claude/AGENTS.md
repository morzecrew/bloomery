<!-- torve:managed sandboxes/claude — rendered from the corpus; do not edit by hand -->

## Decisions governing `sandboxes/claude/`

### The image knows how to equip itself (torve, document 63, decision 18, locked)

The seats this repository dispatches to authenticate by variable name and mount no credential — the claude image takes `CLAUDE_CODE_OAUTH_TOKEN`, dsh takes `DEEPSEEK_API_KEY`. The auth-volume route stays for a harness that has no env form, and where one is used it is mounted read-write: a harness that cannot persist a refreshed token does not fail, it hangs.

- Paths: `sandboxes/claude/**` `.torve/harnesses/**`
- Consequence: an attempt holds one token for its own lifetime instead of reading a refresh token out of a volume that outlives every sandbox that ever mounted it
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
