# RFC 0049 — Redshift dialect port

- **Status:** 📝 Draft — proposed, not scheduled. Validation method is
  [RFC 0046](0046-validating-a-dialect-port.md). The port whose local story is the most
  **misleading** rather than the weakest: every local option is PostgreSQL underneath, and
  bloomery already ships a PostgreSQL port.
- **Scope:** A `redshift` `DialectPort`, and specifically the discipline that keeps it from
  becoming the PostgreSQL port with a different name.
- **Related:** [`src/bloomery/dialects/postgres.py`](../src/bloomery/dialects/postgres.py)
  — the scaffold this must not silently inherit;
  [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py);
  RFC 0029 (transform types, retired) for the PostgreSQL-specific rewrites at stake.

---

## 1. Summary

Redshift is close enough to PostgreSQL to reuse ideas and fixtures, and different enough
that inheriting PostgreSQL behaviour without verification is dangerous.

**The existing PostgreSQL port is a scaffold, not a correctness proof.** So is every local
Redshift environment: they are PostgreSQL containers wearing a Redshift-shaped control
plane, and a query passing one of them proves only that PostgreSQL accepted it.

That double inheritance — a port derived from PostgreSQL, validated against PostgreSQL — is
this document's whole subject.

## 2. The rewrite surface

Every PostgreSQL-specific rewrite is audited before reuse. The ones bloomery actually has,
and what is at stake:

- **`JSONB` lowering and `_variant_is_jsonb`** — Redshift has `SUPER` and PartiQL path
  semantics, not `JSONB`.
- **`pg_input_is_valid`** — the PostgreSQL-specific safe-cast emulation behind
  `_guarded_try_cast`. Redshift's `TRY_CAST` is a different construct with different
  coverage.
- **`regexp_substr`'s sixth argument** — the capture-group spelling `capture_group` exists
  for. Redshift's regexp functions and argument order differ.
- **The `bytea` SHA spelling**, against Redshift's own SHA input and output types.
- **The reserved-word list** used for identifier quoting.
- **`_zoneless_parse` and the timezone implementation**, against RFC 0028's invariant.
- Plus: decimal limits and arithmetic; array and collection capability for
  `DialectFeature.ARRAY`; Unicode normalization support; functions present in PostgreSQL
  and absent in Redshift, and the reverse.

Fixtures are split into two explicitly named classes, because the local lane can only
speak to one of them:

```text
postgres-compatible
redshift-native
```

## 3. Local execution, and what it cannot say

**Floci** provides a Redshift-shaped control plane and a PostgreSQL wire-protocol data
endpoint, managing a real PostgreSQL container per emulated cluster. Genuinely useful for
provisioning and connection flows, endpoint discovery, wire-protocol integration,
dbt/SQLMesh plumbing, basic DDL/DML, and the PostgreSQL-compatible subset.

It must not be the oracle for `SUPER`, PartiQL, Redshift-only functions, Redshift type
rules, planner behaviour, or any construct where the two have diverged.

**LocalStack Redshift** emulates the AWS control plane and Data API — useful for SDK
integration and infrastructure plumbing, and optional while bloomery stays a pure compiler.

Both are rung 4 and both are marked so:

```python
@pytest.mark.surrogate("redshift_postgres")
```

## 4. Authoritative layers

```sql
EXPLAIN <query>;
EXPLAIN VERBOSE <query>;
```

against a real cluster or Serverless workgroup, building a plan without running it. It
catches syntax Redshift rejects, unavailable functions, incompatible argument types,
relation and column resolution failures, and many PostgreSQL-versus-Redshift divergences.
`EXPLAIN` covers query and DML statements but not arbitrary DDL, so DDL acceptance needs
its own small check.

The targeted execution corpus then covers `SUPER`/PartiQL extraction, timestamp conversion,
`TRY_CAST`, decimals, regexp, SHA behaviour, null semantics, and quarantine results.

## 5. Tests

```text
tests/unit/test_dialects/test_redshift.py
tests/golden/…/redshift/…
tests/support/redshift.py
tests/engines/test_redshift_surrogate.py
tests/engines/test_redshift_live.py
```

## 6. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **`RedshiftDialect` does not subclass `PostgresDialect`. It may share helper functions; it may not inherit rewrites.** Subclassing makes every PostgreSQL rewrite silently legal here — `pg_input_is_valid`, the `JSONB` lowering, `regexp_substr`'s argument order, the reserved-word list — and each one is a plausible-looking spelling that Redshift either rejects or reads differently. Locked because inheritance is the specific mechanism by which this port becomes wrong while looking finished, and because unpicking it after artifacts ship is a breaking change. |
| 2 | `LOCKED` | **A green Floci or LocalStack run proves PostgreSQL accepted the query, and the test name says so.** RFC 0046 D1 and D2, and this is the port they were written for: here the surrogate is not merely a different implementation, it is *the engine bloomery already ships a port for*, so a passing `engine("redshift")` test could be passing entirely on the scaffold. |
| 3 | `LOCKED` | **Fixtures are split into `postgres-compatible` and `redshift-native`, and the native class never runs on the surrogate.** Without the split, the surrogate lane's coverage number silently includes cases it cannot speak to — which is how a partial lane comes to be read as a full one. |
| 4 | `ASSUMED` | **`SUPER`/PartiQL replaces the `JSONB` lowering rather than being layered over it.** They are different data models, not different spellings, and a translation layer that mostly works is worse than a port that refuses `variant` until it is built. Departing means measuring that a subset genuinely maps, and saying which subset. |
| 5 | `ASSUMED` | **LocalStack is optional while bloomery remains a pure compiler.** It emulates control-plane and Data API surfaces bloomery does not touch. It becomes relevant only if a target e2e test needs AWS-facing behaviour. |
| 6 | `OPEN` | **Whether the port declares `DialectFeature.ARRAY`.** `_quality_flags` lowers to a delimited string without it (RFC 0016 D23) — a supported path, but one that changes emitted artifacts and the reject table's shape. Establish Redshift's actual collection capability on the live lane and decide from that, not from the PostgreSQL port's answer. |
| 7 | `OPEN` | **Which helpers are genuinely shared with the PostgreSQL port.** D1 forbids inheritance and permits sharing, and the boundary between them is exactly where this port will be tempted back. Enumerate the shared helpers explicitly when the port is written, so a later reader can tell a shared abstraction from a leaked assumption. |

## 7. Phasing

Rungs 1–3 with the fixture split from the start — the split is cheap before there are
fixtures and expensive afterwards. Then the surrogate lane for the `postgres-compatible`
class only. Then `EXPLAIN` against a real workgroup, which is the first rung that says
anything about the `redshift-native` class at all. Then the targeted execution corpus.
