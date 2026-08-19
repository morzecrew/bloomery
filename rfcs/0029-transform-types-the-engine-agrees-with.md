# RFC 0029 — Transform types the engine agrees with

- **Status:** 📝 Draft — the defects are measured on all three engines and
  registered as executable rows; none of the repairs is designed yet.
- **Scope:** The 29 divergences RFC 0028 D5's battery registered on its first
  run: places where a transform's declared output type is not what the engine
  produces, or where a whitelisted transform does not run at all on a shipped
  dialect. Touches `transforms/registry.py` (the builder protocol), all three
  ports' `render`, and every golden holding decimal arithmetic. Adds no spec
  surface.
- **Related:**
  [`tests/support/type_conformance.py`](../tests/support/type_conformance.py)
  (the register — each row is one item of this document's work),
  [`src/bloomery/transforms/registry.py`](../src/bloomery/transforms/registry.py)
  (`Builder`, `OutputType`), RFC 0003 D5 (no floats in an emission path),
  RFC 0004 §5.4 (decimal precision tracking), RFC 0008 D3 (fail loud, never
  approximate), RFC 0027 D4 (the neutral-text marker pattern).
- **Origin:** RFC 0028 D5 asked whether a declared-vs-produced type check
  should exist. It does now, at the engine tiers. This is what it found.

---

## 1. Summary

Every transform declares an output logical type and separately constructs the
AST that computes it. The two were never compared. Comparing them against real
DuckDB, PostgreSQL and Trino turns up four distinct problems and one root cause.

The root cause is small and structural: **a builder is never told its input
type.** `Builder` is `(column AST, *spec args) -> AST`, while `OutputType` is
`(input type, args) -> LogicalType`. So the function that *declares*
`decimal(13, 4)` knows the input type and the function that *builds* the
expression does not — which is why no builder can narrow a result back to what
it promised.

## 2. What was measured

Full rows in the register; grouped here by what has to change.

### 2.1 Decimal arithmetic widens past the tracked (p, s)

| Case | Declared | DuckDB | PostgreSQL | Trino |
| --- | --- | --- | --- | --- |
| `coalesce` over `decimal(12,4)` | `decimal(12,4)` | `decimal(14,4)` | `numeric` | `decimal(14,4)` |
| `multiply` by 2 | `decimal(13,4)` | `decimal(18,4)` | `numeric` | `decimal(22,4)` |
| `round(…, 2)` | `decimal(10,2)` | `decimal(12,2)` | `numeric` | `decimal(13,4)` |
| `abs` | `decimal(12,4)` | `decimal(12,4)` | `numeric` | `decimal(12,4)` |
| `round(…, 0)` over `int` | `bigint` | `bigint` | `numeric` | `bigint` |

No value is lost — every one of these is a widening. What is lost is the
meaning of the declaration, and with it the **38-digit precision cap**: RFC 0004
§5.4 computes the cap over the numbers it tracks, and the engine is computing
over different ones. A chain the typechecker approves can exceed an engine's own
limit, and a mart column's declared type can be a number no engine holds.

PostgreSQL is the sharper case: it drops the typmod through any expression, so
the result is *unconstrained* `numeric` rather than a wider one.

### 2.2 `divide` yields a binary float, on every port

| Port | Emitted | Produced |
| --- | --- | --- |
| DuckDB | `x / 2` | `DOUBLE` |
| PostgreSQL | `CAST(x AS DOUBLE PRECISION) / 2` | `double precision` |
| Trino | `CAST(x AS DOUBLE) / 2` | `DOUBLE` |

RFC 0003 D5 forbids a float anywhere on an emission path, and this is the
transform whose output is most often money. It is shipping: three goldens
compute `unit_price` as `CAST(CAST(total AS DOUBLE PRECISION) / qty AS
DECIMAL(12, 4))` — the outer cast is bloomery's own declared-type cast, so the
column's *type* is right and its value has been through a float.

SQLGlot's `Div(typed=True)` fixes the PostgreSQL and Trino spelling, and
**does not survive the canonical text round trip** (RFC 0003 D2): `x / 2` carries
no flag. DuckDB has no exact decimal division at all — `/` is float division and
`//` is integer division — so on that port the repair cannot be an expression at
all.

### 2.3 PostgreSQL cannot run four transforms

| Case | Result |
| --- | --- |
| `regex_extract` | `REGEXP_EXTRACT` is not defined on PostgreSQL 16 (`42883`) |
| `strip_suffix` | `ENDS_WITH` is not defined on PostgreSQL at all (`42883`) — `STARTS_WITH` is, which is why `strip_prefix` runs |
| `to_int` over `bool` | PostgreSQL refuses `boolean` → `bigint` (`42846`); only `int4` converts |
| `to_bool` over `int` | the same refusal in reverse |

Each is loud at plan time, which is the acceptable failure mode — but a shipped
dialect refusing a whitelisted transform belongs behind a capability flag and an
emit-time refusal naming the transform (RFC 0008 D3), not behind the engine's
own message on first run. `DialectFeature.REGEXP_EXTRACT` already exists and is
consulted only by the `pattern` quality rule; the `regex_extract` transform
never asks.

### 2.4 Two more, one per port

- **PostgreSQL, `parse_ts` with an explicit format** produces `timestamptz`:
  `to_timestamp(text, text)` returns a zone-aware value. This is the RFC 0028
  defect exactly, surviving in the branch no fixture uses — every fixture writes
  `{parse_ts: ISO8601}`.
- **PostgreSQL, `json_path` deeper than one key** produces `json` where
  `variant` is declared `JSONB`: the port lowers a multi-segment path through
  `CAST(x AS JSON)` and `json_extract_path`.
- **Trino, `coalesce` and `nullif` over non-string columns** do not plan
  (`TYPE_MISMATCH`): Trino does not coerce a varchar literal to the column's
  type, so a fallback or sentinel that runs on DuckDB and PostgreSQL fails
  here. Eight rows — every non-string input type, both transforms.

## 3. Decisions

| # | Decision | Grade |
| --- | --- | --- |
| **D1** | A builder is told its **input logical type**. `Builder` becomes `(input type, column AST, *args) -> AST` or gains it by keyword; the declaration and the construction then read the same fact. This is the enabling change for §2.1 and §2.2. | `ASSUMED` |
| **D2** | Arithmetic transforms **narrow their own result** to the type they declare, rather than leaving it to `build.py`'s terminal cast — which only fires when the chain's terminal type differs from the field's, and so never fires for a chain ending in `multiply`. | `ASSUMED` |
| **D3** | `divide` carries a **neutral-text marker**, the pattern RFC 0027 D4 established for `parse_ts`, because a flag on the node does not survive the round trip and re-reading every `Div` at render would change integer division in metric expressions. | `ASSUMED` |
| **D4** | Where an engine cannot express a transform, the port **declares the capability absent** and emit refuses by name, rather than the engine failing on first run. | `ASSUMED` |
| **D5** | Whether `to_bool`/`to_int` across the boolean boundary get a PostgreSQL spelling (`x::int::boolean`) or a refusal. A spelling is cheap; a refusal is honest about `to_bool` over an arbitrary integer having no agreed meaning. | `OPEN` |
| **D6** | Whether Trino's `coalesce`/`nullif` literals are cast to the column type at build (needing D1) or the spec surface narrows to reject a literal whose type cannot match. | `OPEN` |

## 4. What "fixed" looks like

Deleting rows from the register. It asserts set equality per port, so a repair
that lands without removing its row fails just as loudly as a regression that
adds one — the document is finished when `KNOWN` is empty on all three ports.

Two rows will not be deleted by any repair to bloomery and need a different
disposition: DuckDB's `DOUBLE` for `divide` (the engine has no exact decimal
division) and PostgreSQL's unconstrained `numeric` (the engine drops the typmod
through every expression). Both are engine properties, and the honest form for
them is a documented port note plus a narrowing cast, not a row that never goes
away.

## 5. Not in scope

**Widening the cap or changing the precision algebra.** RFC 0004 §5.4's rules
are not in question here; what is in question is whether the emitted SQL obeys
them.

**A float type.** There is none and this document does not propose one — §2.2 is
about removing a float that arrived without anyone choosing it.
