<!-- torve:managed examples/lakehouse — rendered from the corpus; do not edit by hand -->

## Decisions governing `examples/lakehouse/`

### S-0044/D-1 — `LOCKED` (ISO 8601 timestamps across dialects)

`{parse_ts: ISO8601}` must accept the `T` separator on every shipping dialect. The argument names a standard; a whitelisted transform that implements it on two ports of three is a defect in the transform, not a caveat for the docs.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-2 — `LOCKED` (ISO 8601 timestamps across dialects)

The fix may **not** be a blanket render-time rewrite of `CAST(… AS TIMESTAMP)` on Trino. Emitted artifacts already cast operands that are timestamps and NULLs, and `REPLACE` over either is a type error, not a no-op (§2).

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-3 — `LOCKED` (ISO 8601 timestamps across dialects)

The fix lives in the **neutral spelling**, not at the port, because provenance does not survive the canonical-text round-trip (§3). Any option that needs the dialect to know a cast came from `parse_ts` is out.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0044/D-7 — `LOCKED` (ISO 8601 timestamps across dialects)

Until this lands, the divergence is **documented, not refused**. (d) is the S-0025/D-3-pure answer and it breaks working projects to punish a bug they already routed around; the projects that hit it hit it loudly, through the `coercible` rule, not silently.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/postgres.py` `src/bloomery/dialects/trino.py` `src/bloomery/ir/nodes.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-1 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

`to_utc` produces a **zoneless UTC** value. The type is already documented as always-UTC and the map already declares `TIMESTAMP`; producing a zone-aware value contradicts both.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-2 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

The normalization lives in the **ports**, not in the transform builder. The three spellings are one meaning, and a builder produces dialect-neutral AST (S-0021/D-7). The neutral tree keeps carrying `AtTimeZone`; each port renders the whole interpretation.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-3 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

This is a **restating** change: artifacts change, spec meaning does not, and stored values move. A project that built tables before this has data whose derived dates were wrong; a restatement is the migration.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0045/D-4 — `LOCKED` (`timestamp` is zoneless UTC, on every port)

No new spec surface. A per-column "keep the zone" escape hatch would reintroduce the ambiguity this removes, and nothing has asked for one.

- Paths: `examples/lakehouse/**` `src/bloomery/dialects/base.py` `src/bloomery/transforms/_builtins.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
