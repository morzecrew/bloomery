# RFC 0015 — Query vocabulary: filters, sort, pagination

- **Status:** 📝 Draft — design locked; implementation is the next planner wave (post-M11). The
  source doc's "no milestone movement" predates M7 shipping: this is now a migration of shipped
  pre-0.1 surface, acceptable without a deprecation cycle because the API is not yet stable.
- **Scope:** The filter/sort/pagination DSL of the planner contract: `planner/request.py`
  (`FilterExpr` → `Predicate`/`AnyOf`/`Clause`, operator set, `Scalar`, `OrderSpec`), a **new
  public module** `planner/parse.py` (Mongo-flavoured JSON grammar → typed clauses, with
  normalization), the `UnsupportedFilter` taxonomy in `errors.py` with the exported
  `KNOWN_UNSUPPORTED` closed list, one `Feature` addition, and rendering amendments to
  `planner/filters.py` (per-clause `where_constraints`, parenthesized disjunction). Amends
  RFC 0003 D5 (the float-ban boundary interpretation, §5.1), RFC 0011 D2 (request/filter
  types), and RFC 0013 §5.6/R6 (rendering); the rest of the RFC 0011 contract (`QueryPlan`,
  refusal policy, `Explanation` shape) is untouched. `RowPolicy`'s *semantics* — always
  first, in every scan — are untouched, but its surface migrates with the vocabulary:
  `as_filter()` renames to `as_clause()`, and its operator space narrows with `Op`, so a
  policy declared with `between`/`contains` is invalid after the migration (pre-0.1, no
  deprecation cycle; §5.4). Does **not** cover the Forze app adapter (§8).
- **Related:** [`_bloomery-query-vocabulary.md`](_bloomery-query-vocabulary.md) (source,
  D-Q1–D-Q7 — where this RFC diverges, this RFC wins); the shipped surfaces
  [`planner/request.py`](../src/bloomery/planner/request.py),
  [`planner/filters.py`](../src/bloomery/planner/filters.py),
  [`planner/result.py`](../src/bloomery/planner/result.py),
  [`errors.py`](../src/bloomery/errors.py), [`emit/base.py`](../src/bloomery/emit/base.py);
  RFC 0002 (errors), RFC 0003 D5 (float ban), RFC 0009 (test tiers), RFC 0011 (contract),
  RFC 0013 (R6 filter safety).

---

## 1. Summary

`MetricRequest.filters` becomes CNF — `Clause = Predicate | AnyOf`, implicit AND across clauses,
exactly one level of disjunction. `between` and `contains` are removed; `like`/`ilike` added;
scalars gain a string carrier with a non-finite guard. A new public `planner/parse.py` accepts
the Mongo-flavoured JSON grammar directly, normalizing (De Morgan → complement inversion → CNF)
before refusing, and refusing only from a closed, drift-guarded list exported as
`bloomery.planner.KNOWN_UNSUPPORTED`. Sort stays direction-only; pagination stays limit-only.
Rendering emits one `where_constraints` entry per clause, `AnyOf` always parenthesized, policy
first.

## 2. Motivation

Bloomery sits between two vocabularies it does not own: an HTTP boundary speaking recursive
`$and`/`$or`/`$not` filter documents (Forze's grammar — itself the de-facto Mongo-ish
convention) and MetricFlow's `where_constraints` (RFC 0013 §5.6). Shipped `FilterExpr` is a flat
tuple with implicit AND, so *any* disjunction — "region = EU OR region = UK", a filter every BI
UI builds — is untranslatable today. What overlaps between the layers is eleven operator names
and their semantics — a table, not an engine; with a shared operator table and a drift-guarded
closed refusal list, a change on one side cannot force an unnoticed change on the other.
`MetricRequest` is the stable public contract — changing it after clients bind is expensive;
changing it now, pre-0.1, is a rename.

## 3. Current state

Verified against the shipped code (M7):

- [`planner/request.py`](../src/bloomery/planner/request.py): `FilterExpr(dimension, op, values)`
  with `FilterOp` a `Literal` of eleven strings including **`between`** (arity exactly 2),
  **`contains`** (arity 1), and **`is_null`** (arity **0** — no operand). `JsonScalar = str |
  int | bool | Decimal`; `_check_scalar` **refuses floats outright** (RFC 0003 D5 message).
  `OrderSpec(field, direction)` has no nulls control; `MetricRequest` has `limit` only — no
  offset field exists.
- [`planner/filters.py`](../src/bloomery/planner/filters.py): one constraint per `FilterExpr`;
  `contains` → `LIKE` with `%`/`_`/`\` escaped, `%…%`-wrapped, `ESCAPE '\'`; `between` →
  `BETWEEN`; `is_null` → `IS NULL` (no `IS NOT NULL` path). Policy prepended via
  `RowPolicy.as_filter()`. RFC 0013 §5.6 safety rules enforced and fuzz-tested.
- [`planner/result.py`](../src/bloomery/planner/result.py): `Explanation.filters:
  tuple[str, ...]` — human-readable strings.
- [`errors.py`](../src/bloomery/errors.py): `PlannerError` leaves are `UnknownMember`,
  `UnreachableAtGrain`, `AmbiguousDimension`, `InvalidRequest`, `FilterTypeMismatch` — no
  `UnsupportedFilter` hierarchy, no stable reason codes.
- [`emit/base.py`](../src/bloomery/emit/base.py): `Feature` has twelve members; no sort-nulls
  capability. No `planner/parse.py` exists; no disjunction of any kind.

## 4. Goals / Non-goals

**Goals**

- One vocabulary decision, made once — every gap a *reviewed refusal* carrying a typed
  `UnsupportedFilter` with a stable `.reason` from a closed, drift-guarded list.
- A public, pure, dependency-free JSON filter parser that normalizes before refusing.
- Shipped rendering safety (RFC 0013 §5.6) preserved verbatim under the new types.

**Non-goals**

- The Forze adapter (`$values` unwrapping, `$fields`/quantifier refusal) — application code,
  ~30 lines, depends on both packages, depended on by neither (§8).
- `regex`, set relations, hierarchy operators, offset/cursor pagination, sort-nulls placement —
  deliberate refusals with named errors (§5.3), not deferred features.
- A second representation: `parse.py` is a front door over the same typed constructors, which
  remain the primary path.

## 5. Design

### 5.1 Types (replaces RFC 0011 D2's `FilterExpr`/`OrderSpec`)

```python
# bloomery/planner/request.py
type Scalar = int | float | Decimal | bool | str | date | datetime | UUID

class Op(StrEnum):
    EQ = "eq"; NE = "ne"; GT = "gt"; GTE = "gte"; LT = "lt"; LTE = "lte"   # ← $eq $neq $gt …
    IN = "in"; NOT_IN = "not_in"; IS_NULL = "is_null"                      # ← $in $nin $null
    LIKE = "like"; ILIKE = "ilike"                                         # ← $like $ilike

@dataclass(frozen=True)
class Predicate:
    dimension: str                       # role-qualified ("shipped_date"); never field-to-field
    op: Op
    values: tuple[Scalar, ...] = ()      # arity checked per operator

@dataclass(frozen=True)
class AnyOf:
    predicates: tuple[Predicate, ...]    # disjunction — one level only (D-Q3)

type Clause = Predicate | AnyOf

@dataclass(frozen=True)
class OrderSpec:
    field: str                           # a requested metric or dimension
    direction: Literal["asc", "desc"] = "asc"    # no `nulls` — D-Q6

@dataclass(frozen=True)
class MetricRequest:
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: tuple[Clause, ...] = ()     # implicit AND across clauses
    time_grain: TimeGrain | None = None
    order_by: tuple[OrderSpec, ...] = ()
    limit: int | None = None
```

| Operator | `values` (validated at construction) |
|---|---|
| `eq` `ne` `gt` `gte` `lt` `lte` | exactly 1 |
| `in` `not_in` | 1 or more |
| `is_null` | exactly 1, a `bool` (`False` renders `IS NOT NULL`) |
| `like` `ilike` | 1 or more patterns, OR semantics (matching upstream) |

Migration from the shipped shape (pre-0.1, no deprecation cycle): `FilterExpr` renames to
`Predicate`; **`between` removed** (compose `gte`+`lte`; a dialect-preferred `BETWEEN` is a
rendering detail, not a DSL concept — D-Q1); **`contains` splits into `like`/`ilike`** (a single
`contains` forces a case-sensitivity guess whose wrong answer is a silently wrong number —
D-Q2); **`is_null` changes arity 0 → exactly one bool**, giving `$not $null` a complement.
Naming stays plain `eq`, not `$eq` — the *semantics* must match upstream, not the spelling.

`Scalar` (D-Q5): a `str` operand for an ordering operator is cast per the dimension's declared
type at render time — the carrier for values JSON numbers cannot express exactly (a `Decimal`
money bound, an ISO datetime). **`NaN`/`Infinity`/`-Infinity` are refused on ordering
operators** even though they parse as `Decimal`: Postgres sorts `'NaN'::numeric` above every
number, so `lt "NaN"` fails *open* and matches every row — exactly the bug class this project
exists to prevent. `UUID` renders as a string literal against string-typed dimensions — no UUID
`LogicalType` exists and none is added.

**Amendment note — `float` in `Scalar` (a real conflict, resolved).** The source doc's `Scalar`
includes `float`; shipped `_check_scalar` refuses floats per RFC 0003 D5. Decision: floats
**are** accepted at the request boundary — JSON's number type parses to float, and refusing it
would cripple `parse_filter_json` — and are normalized to `Decimal` via `Decimal(str(value))` at
validation time, so no float ever reaches literal rendering, the IR, or any emission path — the
determinism ban's actual target. Non-finite floats and their string forms are `InvalidLiteral`.
RFC 0003 D5 is amended in spirit, not letter: "no float reaches output" holds; the boundary
widens.

### 5.2 Normalize before refusing — `planner/parse.py` (new, public)

A public feature of the package, not scaffolding for one application. Pure: no I/O, no tenant
awareness, deterministic, total errors. No new dependencies.

```python
def parse_filter_json(payload: JsonDict) -> tuple[Clause, ...]:
    """Parse a Mongo-flavoured filter document into clauses.

    Grammar: {"$and": [...]}, {"$or": [...]}, {"$not": {...}}, and a field map
    {field: scalar | {op: value}} using the operators in `Op`. Scalars are the $eq
    shortcut; arrays are the $in shortcut; null is is_null: true. Raises
    UnsupportedFilter with a stable `.reason` — see KNOWN_UNSUPPORTED.
    """

KNOWN_UNSUPPORTED: Final[frozenset[str]] = frozenset({...})
```

Normalization (D-Q4) runs **before** any refusal — a large share of expressions that *look*
unsupported are supported after it:

1. Push negations to leaves via De Morgan (`$not{$and:[a,b]}` → `$or[$not a, $not b]`).
2. Invert negated leaves through the complement table: `$not $eq → ne`, `$not $in → not_in`,
   `$not $gt → lte`, `$not $null:true → is_null false`, … A leaf with no complement
   (`like`/`ilike`) stays negated → `UnsupportedNegation`.
3. Distribute to CNF.
4. Cap the blow-up: CNF is worst-case exponential — refuse with `FilterTooComplex` above a
   configurable clause count (default **64**) rather than hanging.
5. Validate each clause against the operator set and the single-field rule.

`parse_sort_json` and `parse_page_json` ship alongside for symmetry — each a dozen lines,
carrying the D-Q6/D-Q7 refusals. Typed constructors remain the primary path.

### 5.3 The closed list — what cannot cross

The deliverable of this RFC: every entry is a deliberate, reviewed refusal with a specific error
type; anything not on this list must translate. **Owned by bloomery** — raised by
`planner/parse.py`, reason codes exported as `bloomery.planner.KNOWN_UNSUPPORTED`, testable with
no Forze present:

| Construct | Refusal | Why |
|---|---|---|
| `$superset` `$subset` `$disjoint` `$overlaps` | `UnsupportedSetRelation` | Marts are flattened and scalar by construction; no array columns exist to relate. |
| `$descendant_of` `$ancestor_of` | `UnsupportedHierarchy` | Backend-specific (`ltree`), capability-gated even upstream. Model hierarchy as flattened level columns on the mart. |
| `$regex` | `UnsupportedTextOperator` | Dialect-divergent syntax, unbounded cost. `like`/`ilike` cover the BI cases; revisit only with demonstrated need. |
| `$empty` | `UnsupportedTextOperator` | Ambiguous across types. Express as `eq ""` or `is_null true` explicitly. |
| Nesting deeper than AND-of-`AnyOf` | `UnsupportedNesting` | D-Q3. Message includes the normalization result so the caller sees the shape it reached. |
| CNF expansion above the clause cap | `FilterTooComplex` | §5.2 step 4. |
| Negated leaf with no complement | `UnsupportedNegation` | e.g. `$not $like`. Add `not_like` only if real usage demands it. |
| Non-finite numeric operand | `InvalidLiteral` | D-Q5 — fails open if permitted. |
| `nulls` placement other than the canonical default | `UnsupportedSortNulls` | D-Q6 below. |
| `offset` ≠ 0, or cursor pagination | `UnsupportedPagination` | D-Q7 below. |

**Migration note (`InvalidLiteral`):** shipped `filters.py` already refuses non-finite
values — as `FilterTypeMismatch`. This RFC re-homes that refusal to `InvalidLiteral`, a
vocabulary-level concern checked at request validation, before rendering;
`FilterTypeMismatch` remains the type-vs-dimension mismatch error.

**Owned by the app adapter** — Forze-specific constructs bloomery's parser never sees, declared
alongside so the conformance test checks one union:

| Construct | Refusal | Why |
|---|---|---|
| `$fields` (field-to-field compare) | `UnsupportedFieldCompare` | A dimension-to-dimension comparison in a metric query is almost always a modelling error — add a derived boolean dimension to the spec instead. |
| `$any` / `$all` / `$none` quantifiers | `UnsupportedQuantifier` | Marts are flattened and scalar; an array column on a mart means the flattening was incomplete. |

All subclass a new `UnsupportedFilter(PlannerError)` (declared in `errors.py` per RFC 0002 D3;
planner errors unbatched per RFC 0011 D9), carrying `.reason` (stable string code),
`.source_path`, and where relevant `.normalized` — actionable, not merely correct. **Flagged
divergence:** the source doc declares `UnsupportedFilter(BloomeryError)`; this RFC chooses
`UnsupportedFilter(PlannerError)` to match `errors.py`'s stage grouping — still a
`BloomeryError` transitively. `KNOWN_UNSUPPORTED` is the union of reason codes raisable by
all **three** parse functions — `parse_filter_json`, `parse_sort_json`, `parse_page_json` —
which is why `UnsupportedSortNulls` and `UnsupportedPagination` legitimately sit in the
export even though the filter parser never raises them. The drift-guard test asserts exact
equality against that union, introspected across all three functions. (The source doc's §5
scopes the list to the filter parser while its §7.1 lists the sort/pagination codes — a
tension resolved here as the three-function union.)

**Sort (D-Q6):** MetricFlow's `order_by_names` is direction-only. `OrderSpec` carries **no**
`nulls` field — accepting a parameter that is silently dropped is worse than refusing it.
`parse_sort_json` maps the spec form `{"dir": …, "nulls": …}` against the canonical default
(`first` for `asc`, `last` for `desc`): redundant → dropped, else → `UnsupportedSortNulls`.
`Feature.SORT_NULLS_PLACEMENT` is added to the `Feature` enum (RFC 0008 vocabulary) and declared
**unsupported** by `MetricFlowPlanner`.

**Pagination (D-Q7):** limit-only. MetricFlow has no offset, and offset paging over an aggregate
is semantically shaky — underlying rows change between pages. Non-zero `offset` and cursors →
`UnsupportedPagination`. Paging large metric results belongs to the serving layer (materialize,
page the materialization), never `MetricRequest`.

### 5.4 Rendering (amends RFC 0013 §5.6 / R6)

`planner/filters.py` renders **one `where_constraints` entry per `Clause`**, policy clause first
via `RowPolicy.as_clause()` (renaming `as_filter()`):

```
Predicate → {{ Dimension('order_item__carrier') }} = 'DHL'
AnyOf     → ({{ Dimension('order__region') }} = 'EU' OR {{ Dimension('order__region') }} = 'UK')
```

Every `AnyOf` is parenthesized, always: `policy AND a OR b` leaks every row matching `b` — a
correctness bug, not a style choice, and both forms parse fine. All shipped R6 safety rules are
unchanged and remain merge-blocking: dimension names only from validated resolutions via
`names.py`; literals only through the typed dialect-aware renderer, never `f"'{value}'"`;
`like`/`ilike` escape `%`/`_`/`\` with an `ESCAPE` clause; type mismatches are
`FilterTypeMismatch`, never a cast. `Explanation.filters` is built from the `Clause` objects —
never by parsing rendered SQL. `RowPolicy` itself stays single-predicate and gains nothing
from this migration: a policy is one object, so a `between`-shaped policy has no
post-migration form as two policy clauses — callers with range policies compose the range
into the request filters instead, or declare a gte-only/lte-only policy.

## 6. Tests

Per RFC 0009 tiers; every row runs inside bloomery with no Forze and no infrastructure — the
practical payoff of owning the parser.

| Tier | Test |
|---|---|
| Unit | Operator arity for every `Op` member |
| Unit | Negation-complement table (`not eq → ne`, `not gt → lte`, `not is_null:true → is_null:false`, …) |
| Unit | Every bloomery-owned §5.3 refusal: right type, message contains the normalized form |
| Unit | Drift guard: `KNOWN_UNSUPPORTED` == the union of codes the three parse functions (`parse_filter_json`/`parse_sort_json`/`parse_page_json`) actually raise, introspected across all three |
| Property | Non-finite literals (`NaN`/`Infinity`/`-Infinity` and string forms) refused on all six ordering operators |
| Property | CNF normalization terminates and respects the clause cap on adversarial nesting |
| Property | Parse totality: any generated document parses or raises a `KNOWN_UNSUPPORTED` reason; parsed output checked by `semantically_equivalent` — **evaluated against generated rows**, never structural comparison (structural comparison after normalization is circular) |
| Property (R6) | Shipped filter fuzz extended to `like`/`ilike` wildcards: adversarial values render to SQL with unchanged predicate structure and exactly the expected scanned mart |
| Execution | An `AnyOf` clause returns the same rows as two separate queries UNIONed |
| Execution | Policy + `AnyOf`: policy predicate in every scan, `AnyOf` parenthesized — asserted on the parsed AST |

App-side tests (adapter totality over `KNOWN_UNSUPPORTED | APP_UNSUPPORTED`,
`strip_values_wrapper` refusals) are the adapter's obligation, out of scope here.

## 7. Docs

`parse.py` is documented in the README as a **feature** — a filter front door anyone building on
bloomery wants — not internal plumbing. The refusal explanation page gains the closed-list
framing (a reviewed gap, not drift); D-Q6/D-Q7 wording says "refused", never "unsupported for now".

## 8. Out of scope

- **The app adapter** (`to_bloomery`: Forze `$values` unwrapping, `$fields`/quantifier refusal,
  `.reason` → HTTP problem responses) — application code, ~30 lines, delegating everything else
  to `parse_filter_json`. Becomes a `bloomery-forze` bridge only if a second product needs it.
- **`not_like` / `regex` / offset paging** — named escape hatches, built only on demonstrated
  need; each currently a §5.3 refusal.
- **A query optimizer** — folding `gte`+`lte` into `BETWEEN` is a rendering detail the emitter
  may adopt; the DSL never grows the concept back.

## 9. Risks

- *CNF blow-up on adversarial input* — bounded by the clause cap, property-tested.
- *The float amendment read as weakening RFC 0003 D5* — mitigated by restating the invariant at
  its actual target (no float reaches rendering or emission) and unit-testing the boundary
  normalization (`Decimal(str(f))`, non-finite refused).
- *`like`/`ilike` silently changing shipped `contains` semantics* (substring-wrap vs raw
  pattern) — flagged in §10; the fuzz corpus is extended, not merely renamed.
- *Refusal-list ossification* — the drift guard makes additions deliberate, which is the point;
  the cost is a PR per new operator, accepted.

## 10. Unresolved questions

- `like`/`ilike` pattern semantics at the boundary: shipped `contains` escapes wildcards and
  wraps `%…%` (substring); upstream `$like` passes patterns. Whether caller wildcards pass
  through (escaping only the escape char) or stay literal substrings is implementation-settled
  against upstream semantics — §5.4's escaping rules bind either way.
- Exact `JsonDict` alias and clause-cap plumbing (constructor arg vs module constant) —
  implementation-settled.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | **D-Q1:** `between` removed — callers compose `gte`+`lte`; `BETWEEN` is a rendering detail a dialect may re-derive, never a DSL concept. Shipped `FilterExpr.between` (arity 2) is deleted in the migration. |
| 2 | **D-Q2:** `contains` splits into `like`/`ilike` (1+ patterns, OR semantics, matching upstream) — a single `contains` forces a case-sensitivity guess whose wrong answer is a silently wrong number. `regex` is not adopted (`UnsupportedTextOperator`). |
| 3 | **D-Q3:** filters are CNF — `Clause = Predicate \| AnyOf`, `MetricRequest.filters: tuple[Clause, ...]` implicit AND, exactly one level of disjunction. Covers every filter a BI UI builds; each clause is one `where_constraints` entry, independently renderable and explainable. Deeper nesting → `UnsupportedNesting` with the normalization result in the message. |
| 4 | **D-Q4:** normalize before refusing, in new public `planner/parse.py`: De Morgan → complement inversion table → CNF distribution → clause cap (default 64, `FilterTooComplex`) → per-clause validation. Pure, deterministic, zero new dependencies. |
| 5 | **D-Q5:** string-carrier scalars — `str` operands on ordering operators cast per the dimension's declared type at render time; `NaN`/`Infinity`/`-Infinity` refused (`InvalidLiteral`) even though they parse as `Decimal` — `lt "NaN"` fails open on Postgres and matches every row. `UUID` renders as a string literal against string-typed dimensions; no UUID `LogicalType` is added. |
| 6 | **Float amendment (RFC 0003 D5):** floats accepted at the request boundary (JSON numbers parse to float; refusing cripples `parse_filter_json`), normalized to `Decimal` via `str(float)` at validation — no float ever reaches literal rendering or emission, the ban's actual target. Reverses shipped `_check_scalar`'s outright refusal. |
| 7 | **D-Q6:** `OrderSpec` carries no `nulls` field — accepting-and-dropping is worse than refusing. Placements equal to the canonical default (`first`/asc, `last`/desc) translate and drop; anything else → `UnsupportedSortNulls`. `Feature.SORT_NULLS_PLACEMENT` added (RFC 0008 vocabulary) and declared unsupported by `MetricFlowPlanner`. |
| 8 | **D-Q7:** pagination is limit-only. Non-zero `offset` and cursor pagination → `UnsupportedPagination`; paging aggregates belongs to the serving layer (materialize, then page). |
| 9 | The §5.3 closed list is the deliverable: nine bloomery-owned refusal types + two app-adapter codes (`UnsupportedFieldCompare`, `UnsupportedQuantifier`) declared alongside, all subclassing new `UnsupportedFilter(PlannerError)` with `.reason` (stable code), `.source_path`, optional `.normalized`. `KNOWN_UNSUPPORTED: frozenset[str]` exported from `bloomery.planner` as the union of codes raisable by all three parse functions (`parse_filter_json`/`parse_sort_json`/`parse_page_json`); drift-guard test: export == that union, introspected across all three. Anything not on the list must translate. |
| 10 | `parse.py` is a public feature (Mongo-flavoured grammar front door: `$and`/`$or`/`$not` + field maps, scalar = `$eq` shortcut, array = `$in` shortcut, null = `is_null true`), with `parse_sort_json`/`parse_page_json` for symmetry. Typed constructors remain the primary path. The Forze adapter (~30 lines) lives in the application — out of bloomery scope. |
| 11 | Rendering: one `where_constraints` entry per `Clause`; `AnyOf` **always** parenthesized (`policy AND a OR b` leaks every row matching `b`); policy first via `RowPolicy.as_clause()` (renaming `as_filter()`; `RowPolicy` stays single-predicate, its op space narrowing with `Op` — `between`/`contains` policies are invalid post-migration, and range policies move into the request filters or become gte-only/lte-only policies); all shipped RFC 0013 §5.6 safety rules unchanged and merge-blocking; `Explanation.filters` built from `Clause` objects, never from parsing SQL. |
| 12 | Migration is pre-0.1, no deprecation cycle: `FilterExpr` → `Predicate`; `between`/`contains` removed; `is_null` arity 0 → exactly one bool (gaining `IS NOT NULL`). Affected shipped tests (fuzz corpus, request validation, execution filters) renamed/extended in the implementing wave. |

## 12. Phasing

Design locked by this RFC; implementation lands as wave **M14** (post-M11; the number
continues the corpus sequence after RFC 0016's M12 and RFC 0017's M13, but this wave is
independent of both and may execute first — it touches only the planner surface). Affected
in that wave: `request.py` (types), `filters.py` (per-clause rendering), `explain` /
`Explanation.filters` provenance, the R6 fuzz corpus, and `golden_requests` when the
equivalence tier (RFC 0009, M11) lands. When the wave ships, dated amendment rows are
appended to RFC 0003, RFC 0011, and RFC 0013 — the practice RFC 0016/0017 follow for
their amended RFCs. App-adapter work is unscheduled here — it tracks the application's
own milestones.
