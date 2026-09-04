# RFC 0050 — Databricks SQL dialect port

- **Status:** 📝 Draft — proposed, not scheduled. Validation method is
  [RFC 0046](0046-validating-a-dialect-port.md). The only one of the four with **no local
  replacement that may be treated as authoritative** — which is a constraint on the test
  strategy, not a blocker on the port.
- **Scope:** A `databricks` `DialectPort`, a clearly labelled local Spark surrogate, and a
  small live Databricks SQL lane. Also settles what does **not** happen: bloomery does not
  gain Spark.
- **Related:** [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py);
  [`pyproject.toml`](../pyproject.toml) — the dependency groups a test-only driver would
  join; RFC 0003 (determinism and no-I/O contract, retired), RFC 0028 (zoneless UTC,
  retired).

---

## 1. Summary

There is no "Databricks SQL Warehouse in Docker". Local Spark is a *surrogate*: it shares
much of the language and is a different product. The response is a multi-fidelity strategy
with the surrogate labelled as one, plus a small live lane — and Databricks Free Edition is
enough to bootstrap that lane.

## 2. The rewrite surface

- **`TIMESTAMP` versus `TIMESTAMP_NTZ`**, against RFC 0028's UTC-zoneless invariant — the
  same shape as 0047 D1 and 0048 D1, and the same risk.
- **ISO-8601 parsing** and RFC 0036's offset guard.
- **`try_cast`**, against RFC 0016 D3's NULL-on-failure contract.
- **`VARIANT` and semi-structured behaviour**, and the JSON functions beside it.
- **Regexp functions and capture indexes**; **arrays** for `DialectFeature.ARRAY`;
  **timezone functions**; **SHA functions and binary-to-hex**; **decimal precision and
  division**.
- **ANSI mode**, which changes cast and arithmetic behaviour and must be pinned in any
  surrogate session.
- **Functions in Databricks SQL but not generic Spark, and the reverse** — the divergence
  list the surrogate cannot see.

## 3. bloomery does not gain Spark

PySpark is a **test-only optional dependency**, never a bloomery dependency, and core
bloomery never executes Spark jobs. The package is `specs → IR → artifacts`, a pure
function with no I/O (RFC 0003). Adding Spark execution would make installation much
heavier, put JVM and runtime concerns into a pure compiler library, blur compilation and
execution, constrain supported Python and JDK combinations, raise CI cost for users who
never target Databricks, and — the one that matters most — create the impression that Spark
is the Databricks engine.

```toml
[dependency-groups]
databricks-test = ["pyspark>=4,<5"]
```

Pinned reproducibly in the lockfile, never installed for `uv add bloomery`. The harness
lives in `tests/support/spark.py` and owns the `SparkSession` lifecycle, deterministic
session settings, timezone, ANSI mode, fixture registration, and result canonicalization.

## 4. The surrogate lane, and its boundary

```python
@pytest.mark.surrogate("databricks_spark")
def test_timestamp_semantics(...): ...
```

Good surrogate candidates: joins, filters, `CASE`, aggregates, windows, common casts,
regexp, arrays, basic date and timestamp expressions, null propagation, arithmetic.

Excluded or separately marked: Databricks `VARIANT`, Unity Catalog semantics, Databricks
SQL-only functions, serverless-specific behaviour, optimizer behaviour, and any expression
known to diverge from upstream Spark.

## 5. Authoritative layers

Two commands, and the second is unusually valuable here:

```sql
EXPLAIN EXTENDED <query>;   -- parsing, analysis, planning
DESCRIBE QUERY <query>;     -- output column names and types
```

`DESCRIBE QUERY` returns the result schema, which matters for bloomery because type
conformance is asserted alongside syntax — it is the closest thing any of the four ports
has to a declared-versus-produced check without executing.

Then a small runtime corpus: timezone normalization, timestamp parsing, decimals, regexp
capture, `try_cast`, JSON/`VARIANT`, arrays, SHA-to-hex, null behaviour, quarantine rows.

### Environment contract

```text
DATABRICKS_HOST   DATABRICKS_TOKEN   DATABRICKS_SQL_WAREHOUSE_ID
DATABRICKS_CATALOG   DATABRICKS_SCHEMA
```

The first two are Databricks' own unified-auth names; the third is required by the
Statement Execution API request and is also the harness's. `.env` is already gitignored
(`.gitignore:151`); an `.env.example` carries the names with empty values. A smoke test
that proves host, auth, warehouse ID and API reachability — and nothing about the dialect:

```bash
curl --fail-with-body -X POST "${DATABRICKS_HOST}/api/2.0/sql/statements" \
  -H "Authorization: Bearer ${DATABRICKS_TOKEN}" -H "Content-Type: application/json" \
  -d "{\"warehouse_id\":\"${DATABRICKS_SQL_WAREHOUSE_ID}\",
       \"statement\":\"SELECT 1\",\"wait_timeout\":\"30s\"}"
```

The harness lives at `tests/support/databricks.py`: read environment, submit to
`/api/2.0/sql/statements`, poll, normalize rows, surface Databricks errors, enforce a
timeout, and optionally run `EXPLAIN EXTENDED` and `DESCRIBE QUERY`.

### Free Edition, and its authentication caveat

Free Edition gives serverless-only compute, one SQL warehouse capped at `2X-Small`,
fair-use quotas, no SLA, and administrative limitations. That is enough for a small
conformance suite and **not** enough to run the generated or property corpus continuously.

Databricks recommends OAuth for automation, and Free Edition lacks account-level
administration — so a service-principal OAuth M2M flow must not be documented as guaranteed
to work there. Priority: OAuth M2M on a normal workspace; OAuth U2M (`databricks auth
login`) for local interactive use; a workspace PAT for Free Edition CI **only if that
workspace exposes PAT creation**. If it does not, Free Edition tests stay local and manual
and unattended CI uses a normal workspace.

A PAT gets the shortest practical lifetime, is scoped to the test workspace, rotates when
maintainers change, is revoked immediately if exposed, and never appears in `.env.example`,
workflow YAML, issue text or a snapshot.

### CI lane

`workflow_dispatch`, `push` to `main` under `src/bloomery/dialects/**`, and a schedule —
behind a GitHub Environment (`databricks-free`) rather than raw repository secrets, per
RFC 0046 D5. A dedicated catalog or schema (`workspace.bloomery_conformance`) so tests
never touch notebook or demo tables.

## 6. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **PySpark is a test-only optional dependency; bloomery never executes Spark and no Spark code enters `src/bloomery`.** RFC 0046 D4 applied, and the stakes are highest here because Spark is the one surrogate that could plausibly be mistaken for the product. A JVM in the install path of a pure compiler is also a dependency nobody removes later. |
| 2 | `LOCKED` | **The Spark lane is named `surrogate`, never `engine("databricks")`.** Local Spark checks shared Spark semantics; only live Databricks SQL checks the Databricks dialect. The distinction has to survive being read in a CI log by someone who was not here, which is what the name — not the docstring — decides. |
| 3 | `LOCKED` | **`DESCRIBE QUERY` is part of the authoritative lane, not an optional extra.** It returns the result schema, so it checks bloomery's declared-versus-produced type contract against the real analyzer without executing anything. No other cloud port in this sequence has an equivalent, and skipping it would leave type conformance resting on the surrogate — which is precisely where Spark and Databricks SQL are documented to differ. |
| 4 | `LOCKED` | **No service-principal OAuth flow is documented as working on Free Edition.** It lacks account-level administration, and a setup guide that confidently describes an unavailable flow costs a reader more than no guide. The fallback is stated instead: PAT if the workspace offers it, otherwise local and manual, with unattended CI on a normal workspace. |
| 5 | `ASSUMED` | **Free Edition is sufficient to bootstrap the live lane, provided it stays small.** Serverless-only, one `2X-Small` warehouse, fair-use quotas. Departing means the conformance suite outgrowing it, which is a signal to shrink the suite before a signal to buy a workspace — an authoritative lane large enough to need paid compute has stopped being the small lane RFC 0046 §3 describes. |
| 6 | `ASSUMED` | **The surrogate lane is added only if it catches defects rungs 1–3 miss.** A Spark session is a heavy fixture with its own JDK matrix, and the excluded list in §4 is long enough that its coverage may not repay the maintenance. Measure over one port's work; keep it or drop it on that evidence. |
| 7 | `OPEN` | **Which timestamp type each bloomery type maps to, given `TIMESTAMP` and `TIMESTAMP_NTZ`.** Constrained by RFC 0028's invariant exactly as in 0047 D1 and 0048 D1, and this document does not guess the table. Establish it on the live lane, and pin ANSI mode in the surrogate to the setting that matches whatever is chosen. |
| 8 | `OPEN` | **Whether the port targets Databricks SQL only, or claims generic Spark SQL too.** They are documented as differing in both directions, and one port cannot honestly be both without a capability split. Decide before the first golden, since the answer names the dialect and the artifacts carry the name. |

## 7. Phasing

Rungs 1–3 first, since they need nothing. Then the live compile lane — `EXPLAIN EXTENDED`
plus `DESCRIBE QUERY` — which is the first rung that says anything about Databricks
specifically, and is reachable on Free Edition. The Spark surrogate comes last and is
justified by what it catches, per D6: it is the only rung in this sequence whose existence
is conditional on measurement rather than on need.
