# RFC 0047 — Snowflake dialect port

- **Status:** 📝 Draft — proposed, not scheduled. Validation method is
  [RFC 0046](0046-validating-a-dialect-port.md); this document carries Snowflake's own
  risks and decisions. Of the four cloud ports it has the **strongest** story at both ends
  — two credible local emulators and a cheap authoritative compile layer.
- **Scope:** A `snowflake` `DialectPort`, its rewrite surface, and the fixtures and tiers
  that establish it. No change to the shipped three dialects.
- **Related:** [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py);
  RFC 0028 (zoneless UTC, retired), RFC 0029 (transform types, retired), RFC 0036
  (offset-bearing timestamps).

---

## 1. Summary

bloomery is a compiler, not a warehouse runtime. The Snowflake dialect is correct when
several independent layers agree: the lowering is deterministic, the emitted SQL is
syntactically plausible, representative queries execute on a Snowflake-like local engine,
and a small authoritative suite is accepted by Snowflake itself.

Snowflake has native primitives for much of what bloomery needs, so the port should not
reproduce the PostgreSQL workarounds. **The risks are semantic rather than architectural.**

## 2. The rewrite surface

Snowflake's port is measured at the same six points every port is (RFC 0046 §2), and each
one has a known Snowflake question:

- **Timestamps.** `TIMESTAMP_NTZ`, `TIMESTAMP_TZ` and `TIMESTAMP_LTZ` are three types where
  bloomery has one. RFC 0028's invariant — `timestamp` is always UTC and zoneless — has to
  be mapped deliberately, and `TIMESTAMP_LTZ`'s session dependence is exactly the
  reader-dependence that invariant exists to remove.
- **ISO parsing and the offset guard.** RFC 0036's `SUBSTRING(…, 11)` window plus two
  `LIKE`s must render and mean the same thing here, and the separator rewrite may or may
  not be needed — measure it, do not assume from Trino.
- **`TRY_CAST` and the `TRY_*` family**, which the quality system's NULL-on-failure
  lowering depends on.
- **Regexp capture-group numbering** — the divergence that already needed
  `capture_group` for PostgreSQL.
- **JSON/`VARIANT` extraction**, and specifically scalar-versus-variant result typing.
- **`text_sha256`**, whose contract is lowercase hex and which Trino already needed
  `TO_UTF8`/`TO_HEX`/`LOWER` to satisfy.
- Also: decimal precision, scale and division result types; Unicode normalization;
  reserved identifiers and quoting; null propagation; `DialectFeature.ARRAY`.

## 3. Local execution

Two credible emulators, with different trade-offs.

**`ghcr.io/sivchari/snowflake-emulator`** — OSS, no token, documented Testcontainers and
GitHub Actions usage, a health endpoint. Documented limits: no distributed execution, no
meaningful access control, no warehouse management, no guaranteed transaction isolation.

**LocalStack for Snowflake** — higher fidelity, and requires an auth token (a Developer
token locally, a CI token in CI), which must never be committed:

```yaml
services:
  snowflake:
    image: localstack/snowflake:<pinned>
    ports: ["4566:4566", "4510-4559:4510-4559", "443:443"]
    environment:
      LOCALSTACK_AUTH_TOKEN: ${LOCALSTACK_AUTH_TOKEN:?}
```

Readiness: `curl -d '{}' http://snowflake.localhost.localstack.cloud:4566/session`.
Mocked `test`/`test` credentials are accepted for emulator connections.

Both are rung 4 under RFC 0046 D1 — evidence, not the oracle — and both carry the
`surrogate` marker.

## 4. Authoritative layers

```sql
EXPLAIN USING JSON <statement>;
```

produces the logical plan without executing, exercising Snowflake's own parser, binder and
function resolution. That is the acceptance oracle.

The small execution corpus then covers what a plan cannot settle: timezone normalization,
ISO parsing, decimal division, `TRY_CAST`, regexp extraction, VARIANT extraction, Unicode
normalization, SHA-256 output, null behaviour, and quarantine row disposition. Tiny seed
tables; canonicalized rows and types compared against the shared expectations.

## 5. Tests

```text
tests/unit/test_dialects/test_snowflake.py
tests/golden/…/snowflake/…
tests/support/snowflake.py
tests/engines/test_snowflake_surrogate.py
tests/engines/test_snowflake_live.py
```

Unit and golden on every PR; the OSS emulator lane is the candidate for a PR slot under
RFC 0046 D7; the live lanes are manual, `main`, release and scheduled.

## 6. Unresolved questions

- **Which emulator is the default lane**, and whether the second earns its maintenance.
- **Which Snowflake timestamp type each bloomery type maps to**, which §7 D1 constrains but
  does not spell.

## 7. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The timestamp mapping preserves RFC 0028's invariant: a bloomery `timestamp` is UTC and zoneless, whatever Snowflake calls it.** `TIMESTAMP_LTZ` renders against the session zone, which is precisely the reader-dependence RFC 0028 removed at real cost — two mappings landing one instant on two dates. Locked because it is not this port's decision to revisit: a port that "usefully" picked `LTZ` would reintroduce a shipped defect on one engine only, where the other three ports look fine. |
| 2 | `LOCKED` | **Nothing is inherited from the PostgreSQL or Trino port without being measured on Snowflake.** Snowflake has native primitives for much of what those two needed workarounds for, and a carried-over workaround is at best dead weight and at worst a rewrite that changes meaning. Each of the six rewrite points is re-established here from evidence. |
| 3 | `ASSUMED` | **The OSS emulator is the default local lane and LocalStack is optional.** No token, no licence, documented Testcontainers usage — which is what makes it a candidate for a PR slot at all, since a lane requiring a secret cannot run on a fork PR (RFC 0046 D5). Departing means the OSS emulator's documented gaps hitting a fixture that matters, in which case LocalStack becomes the default and the token constraint follows it. |
| 4 | `ASSUMED` | **Both emulators are `surrogate`-marked and neither gates a release.** RFC 0046 D1 applied; recorded here because Snowflake is the port where the local story is good enough to tempt an exception. |
| 5 | `OPEN` | **Whether the LocalStack lane is maintained at all.** Two emulators is two maintenance surfaces, two pinned versions and two sets of gaps to know. Run both for one port's worth of work, count the defects each found that the other missed, and decide from that — not before. |
| 6 | `OPEN` | **The concrete type map: which Snowflake type each bloomery logical type lowers to**, `VARIANT` and the decimal bounds included. D1 fixes the timestamp constraint; the rest is a table this document deliberately does not guess, because `physical_type` is a one-way door once artifacts exist in the wild. |

## 8. Phasing

Rungs 1–3 with the fixture corpus; then the OSS emulator lane; then `EXPLAIN USING JSON`
against a real account; then the small execution corpus. The emulator lane is worth having
before the live one — not because it proves more, but because it is where iteration is
cheap.
