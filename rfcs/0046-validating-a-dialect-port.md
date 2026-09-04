# RFC 0046 — Validating a dialect port against an engine we cannot run

- **Status:** 📝 Draft — proposed. **Root of the cloud-dialect sequence:** the shared
  validation method for [0047](0047-snowflake-dialect.md) (Snowflake),
  [0048](0048-bigquery-dialect.md) (BigQuery), [0049](0049-redshift-dialect.md) (Redshift)
  and [0050](0050-databricks-dialect.md) (Databricks). Those four documents carry each
  engine's own risks and decisions; this one carries what they share, so the shared half
  cannot drift into four differing accounts.
- **Scope:** How a dialect port earns confidence when the engine is a hosted service rather
  than a container. The tier ladder, what each rung proves and does not, the naming and
  credential discipline that keeps the distinction visible, and where a live harness may
  live. No new dialect ships here.
- **Related:** [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py) —
  `DialectPort`, `DialectFeature`, `SQLGlotDialect`;
  [`src/bloomery/dialects/__init__.py`](../src/bloomery/dialects/__init__.py) —
  `register_dialect`; [`pyproject.toml`](../pyproject.toml) — the six-tier marker table;
  [`tests/engines/`](../tests/engines/) — the existing Postgres and Trino tier;
  RFC 0008 (ports and emitters, retired), RFC 0009 (testing strategy, retired),
  RFC 0028 (zoneless UTC, retired), RFC 0029 (transform types, retired).

---

## 1. Summary

bloomery ships three dialects — DuckDB, PostgreSQL, Trino — and every one of them runs in a
container. The tier ladder was built on that: Tier 5 is `@pytest.mark.engine(name)` over
testcontainers, and it is the layer that has caught the port defects the other tiers could
not see.

Snowflake, BigQuery, Redshift and Databricks break the assumption. Each has *something*
local — an emulator, a surrogate engine, a Postgres-backed shim — and **none of those
things is the engine.** A port validated against them alone would be validated against a
different implementation of a similar language, and the failures that hurt in this codebase
have always been the ones where a spelling was accepted by one engine and meant something
else on another.

This RFC defines the ladder that replaces the missing container, and the rule that keeps
each rung honest about what it proves.

## 2. Current state

Verified at `6d9361f`:

- **The port surface is five methods** — `render`, `physical_type`, `supports`,
  `text_sha256`, `json_object` (`dialects/base.py:351-359`). Port complexity is not in the
  interface, it is in the rewrites each `render` applies.
- **`DialectFeature` is five capabilities** — `JSON_EXTRACT`, `TIMEZONE_CONVERT`,
  `REGEXP_EXTRACT`, `VARIANT_TYPE`, `ARRAY` — and a dialect lacking `ARRAY` lowers
  `_quality_flags` to a delimited string instead.
- **The shared rewrite points already exist and are the real port surface:**
  `strip_iso_text` and `space_separated` (the ISO separator and offset guard),
  `utc_from_zone` (RFC 0028's zoneless-UTC invariant), `capture_group`, `text_sha256`,
  `json_object`, and the NFC-normalize transform. A new port's risk list is largely "what
  does this engine do at each of those six points".
- **Extension dialects are already supported.** `register_dialect` (RFC 0008 D8) takes a
  `DialectPort` from outside the package, and the `pattern` quality rule is already checked
  against registered extension dialects. A cloud port does not have to be in-tree to exist.
- **The marker table has no surrogate rung.** `engine(name)` is Tier 5 and means Docker
  plus the real engine. Nothing today distinguishes "ran against the engine" from "ran
  against something engine-shaped".
- **`.env` is already gitignored** (`.gitignore:151`), so the per-engine credential
  instructions in 0047–0050 need add nothing there.

## 3. The ladder

Each rung, and the honest statement of what a green rung proves:

| # | Rung | Backend | On PR? | Proves |
|---|---|---|---|---|
| 1 | Unit | none | yes | the port's rewrites and declared capabilities |
| 2 | Golden | none | yes | byte-stable artifacts for (fixture × target × dialect) |
| 3 | Syntax sanity | SQLGlot | yes | the generated SQL re-parses under that dialect |
| 4 | Surrogate execution | emulator / Spark / Postgres shim | per port | *something* executes it and returns rows |
| 5 | Authoritative compile | the real engine, no execution | no | the engine's own parser, binder and type checker accept it |
| 6 | Authoritative execution | the real engine | no | selected runtime semantics |

Rung 3 is cheap and belongs on every PR:

```python
sql = SomeDialect().render(node)
assert sqlglot.parse_one(sql, read="<dialect>") is not None
```

It catches malformed output and generator regressions, and it proves nothing about the
engine — SQLGlot is deliberately broader and more permissive than any live warehouse.

**Rung 5 is the one that changes the economics.** Every one of the four engines can
validate a statement without running it — Snowflake's `EXPLAIN USING JSON`, BigQuery's dry
run, Redshift's `EXPLAIN`, Databricks' `EXPLAIN EXTENDED` and `DESCRIBE QUERY`. That is the
engine's own compiler answering, at negligible cost and with no data scanned. It is a
better acceptance oracle than any emulator, and it is why none of these ports is blocked on
the absence of a container.

Rung 6 exists because rung 5 cannot settle *values*: a timestamp's instant, a decimal's
scale, a regexp capture, a SHA's hex casing, whether a quarantined row was quarantined.
Keep it deliberately small and its tables tiny.

## 4. Naming, so a green tier cannot overstate itself

A surrogate is not the engine, and the place that claim gets made is a test name. A
Postgres-backed Redshift shim marked `engine("redshift")` reads, in a CI log and in a
report six months later, as "Redshift passed".

Rung 4 therefore gets its own marker, distinct from `engine`:

```python
@pytest.mark.surrogate("redshift_postgres")
def test_postgres_compatible_subset(...): ...
```

The same discipline applies to prose: a document may say *"local Spark checks shared Spark
semantics; only live Databricks SQL checks the Databricks dialect."* It may not say the
Databricks dialect is tested locally.

## 5. Credentials and CI

- **`just test` never requires a cloud credential.** The default tiers stay offline, as
  they are today.
- **A live lane never runs on an untrusted pull request.** GitHub does not expose secrets
  to fork PR workflows, and a public PR must not be able to run arbitrary SQL under a
  maintainer's cloud identity. `pull_request_target` executing contributor code is not an
  acceptable workaround.
- **Live lanes run on `main`, on release changes, on a schedule, and on manual dispatch**,
  behind a GitHub Environment rather than raw repository secrets, so protection rules apply
  and the credential is isolated from unrelated jobs.
- **Compile-only and execution lanes are separate jobs**, so the default cloud lane cannot
  accidentally scan or bill.
- **Federated identity over long-lived keys** where the provider supports it — Workload
  Identity Federation with GitHub OIDC for BigQuery, OAuth M2M for Databricks — and a
  scoped token only where it does not.
- Tests **skip with a stated reason** when the variables are absent, never fail:

```python
if not all(os.getenv(name) for name in required):
    pytest.skip("live <engine> credentials are not configured")
```

## 6. Where the harness lives

No engine driver, no Spark session and no cloud SDK enters `src/bloomery`. bloomery is
`specs → IR → artifacts`, a pure function with no I/O (RFC 0003), and a live harness is
test apparatus:

```text
tests/support/<engine>.py      # connection, submission, polling, row canonicalization
tests/engines/test_<engine>_*.py
```

Drivers are test-only optional dependency groups, never installed for
`uv add bloomery`.

## 7. Tests

The per-engine documents own their fixtures. What this document requires of all four: the
existing shared fixture corpus is what rungs 1–6 run, not a per-engine corpus, so that a
divergence shows up as one fixture behaving differently rather than as two suites that
cannot be compared.

## 8. Unresolved questions

- **Whether a cloud port ships in-tree or as an extension package.** `register_dialect`
  makes both possible and they have different release, dependency and support stories.
- **How many of the four are actually wanted.** This sequence describes how to validate a
  port; it does not argue that all four should exist.

## 9. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **An emulator, a surrogate engine or a compatible-wire shim is *evidence*, never the oracle. The real engine's own compiler is the dialect oracle.** Every one of the four has something local that runs SQL, and every one of them is an independent implementation of a similar language. Locked because the failure is not a wrong test result — it is a *green* one, quoted later as engine conformance, and no amount of care at the call site survives a name that already claimed too much. |
| 2 | `LOCKED` | **Rung 4 carries a `surrogate` marker, distinct from `engine`.** The claim a test makes is its name, in a CI log and in a report nobody re-reads the body of. `engine("redshift")` over a Postgres container is D1 violated in the one place it is invisible. |
| 3 | `LOCKED` | **The authoritative compile rung exists for every cloud port, because every one of the four engines has one.** `EXPLAIN`, dry run, `EXPLAIN EXTENDED`, `DESCRIBE QUERY` — the engine's own parser, binder and type resolution, without executing and without scanning. It is what makes "no local container" a non-blocker, and a port that skips it has no authoritative layer at all. |
| 4 | `LOCKED` | **No engine driver, SDK or Spark session enters `src/bloomery`; live harnesses live in `tests/support/`.** The package is a pure compiler under RFC 0003 and installing it must not pull a JVM or a cloud SDK. This is also the boundary that stops "bloomery targets Databricks" turning into "bloomery executes Spark". |
| 5 | `LOCKED` | **No cloud credential is reachable from an untrusted pull request, and `just test` never requires one.** Live lanes run on `main`, releases, schedules and manual dispatch, behind a GitHub Environment. `pull_request_target` executing contributor code is named here so it is not proposed later as a convenience. |
| 6 | `ASSUMED` | **All six rungs run the *shared* fixture corpus, not a per-engine one.** A divergence then presents as one fixture behaving differently across ports, which is comparable; two corpora produce two suites nobody can diff. Departing means an engine whose surface genuinely has no shared analogue — `VARIANT`, `SUPER` — where a port-native fixture is added alongside rather than instead. |
| 7 | `ASSUMED` | **Rungs 1–3 are required on every PR; rung 4 is per port; rungs 5–6 never are.** The split follows cost and trust rather than value. Not `LOCKED` because an engine whose surrogate is both cheap and faithful may earn a PR slot, and 0047's OSS emulator is the likely first case. |
| 8 | `OPEN` | **Whether a cloud port ships in-tree or as an extension package.** `register_dialect` (RFC 0008 D8) already accepts a `DialectPort` from outside, and the two paths differ in dependency weight, release cadence and who is on the hook when a hosted engine changes under a shipped port. Decide it before the first cloud port lands, since moving a shipped dialect between the two is a breaking change either way. |
| 9 | `OPEN` | **Whether `surrogate` is a new pytest marker or a parameter on `engine`.** D2 fixes the requirement, not the spelling; `@pytest.mark.engine("redshift", surrogate=True)` satisfies it as well as a separate marker and keeps one selector. Whoever adds the first surrogate lane decides, and updates the marker table in `pyproject.toml` with the reason. |

## 10. Phasing

This document lands alone — it is method, and it constrains four documents that are not
scheduled. Any one of 0047–0050 may then proceed independently; none of them depends on
another. The order they are written in reflects how much a local rung 4 can carry, which is
the main thing that varies between them.
