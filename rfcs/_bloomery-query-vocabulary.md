# `bloomery` — Query Vocabulary Alignment

**Document 4.** Apply after documents 1–3. Scope: the filter/sort/pagination DSL inside
`planner/request.py`, a new `planner/parse.py` that owns filter normalization, and the refusal
taxonomy both share.

**Amends:** `MetricRequest`, `FilterExpr`, `OrderSpec` from `bloomery-changes.md` D1, and
`planner/filters.py` from `bloomery-metricflow-pivot.md` R6.

**Adds one module** (`planner/parse.py`) and no dependencies. No milestone movement. This is a
schema decision made early because `MetricRequest` is the stable public contract — changing it
after clients bind to it is expensive; changing it now is a rename.

> **Note (RFC corpus):** Preserved verbatim as source material alongside the three earlier
> input documents. Lands in the corpus as RFC 0015 (query vocabulary). Where RFCs diverge
> from this document, the RFCs win.

---

## 1. The problem, stated precisely

Bloomery sits between two vocabularies it does not own:

```
HTTP / app boundary          bloomery                 planner backend
─────────────────────        ────────────────         ───────────────────
Forze QueryFilterExpression  →  FilterExpr  →  MetricFlow where_constraints
recursive $and/$or/$not         ???             Jinja-templated SQL strings
```

If `FilterExpr` is designed in isolation, **both** translations end up lossy in ways nobody
notices until a filter silently disappears or a query is refused for no articulable reason.

Bloomery must not depend on Forze, and Forze must not depend on bloomery. That constraint is
correct and stays.

### 1.1 This is not two DSL engines

Worth counting what actually overlaps before accepting duplication, because the instinct that
"we now maintain two query languages" overstates it considerably.

| Forze `querying` owns | bloomery `planner` owns |
|---|---|
| JSON grammar parsing | CNF normalization |
| Capability gating per backend | Dimension resolution against the IR |
| Field policy / authorization checks | Type checking against declared dimension types |
| Type coercion per adapter | Literal escaping per dialect |
| Rendering to Mongo / Postgres / Meilisearch | Rendering to MetricFlow Jinja |

Almost nothing overlaps. What overlaps is **eleven operator names and their semantics** — a
table, not an engine, and a table whose semantics are near-universal because the `$eq` / `$and`
/ `$or` grammar is a de facto convention rather than anyone's invention.

Every layered system repeats predicate names across its layers; Forze already does it internally,
re-rendering the same query types in every backend adapter. The test for whether repetition is a
problem is not "is anything repeated" but **"does a change on one side force an unnoticed change
on the other?"** With a shared operator table, a parser that owns normalization, and a closed
refusal list guarded by a test, the answer is no: adding an operator upstream breaks nothing,
and bloomery refuses it until someone deliberately adds it. A reviewed gap, not drift.

### 1.2 The consequence: bloomery parses the JSON grammar itself

Because that grammar is a convention and not a Forze artifact, **bloomery accepts it natively**
as a documented input format, depending on nothing.

That puts the interesting logic — normalization, the closed list, the refusal taxonomy — inside
bloomery, where it is unit-testable with no Forze, no database, and no infrastructure in sight.
It is also a genuine feature of a standalone package: anyone building on bloomery wants a filter
parser.

The app-side adapter then collapses to unwrapping Forze's two structural additions (`$values` /
`$fields`, and element quantifiers) and handing the rest straight through — roughly thirty lines
instead of three hundred.

This document specifies the operator subset, the normalization rules, and — critically — the
**closed list of things that cannot cross**, so the gap is reviewed rather than discovered.

---

## 2. The upstream vocabulary (reference)

Recorded here so the implementer doesn't need to read Forze's source.

**Operators** (`QueryValueOpConjunction`):

```
$eq $neq                       scalar equality
$gt $gte $lt $lte              ordering, operand type Numeric
$in $nin                       membership, operand Array
$null $empty                   unary, operand bool
$like $ilike $regex            text patterns, operand str | Sequence[str] (OR at parse time)
$superset $subset $disjoint $overlaps      set relations on arrays
$descendant_of $ancestor_of                materialized-path hierarchy
```

**Combinators** — recursive:

```python
QueryConjunction = {"$and": Sequence[QueryFilterExpression]}
QueryDisjunction = {"$or":  Sequence[QueryFilterExpression]}
QueryNegation    = {"$not": QueryFilterExpression}
QueryConstraintPredicate = {"$values": QueryValueMap, "$fields": QueryFieldsMap}
```

`$values` is field-to-literal; `$fields` is **field-to-field compare** (`$eq $neq $gt $gte $lt
$lte`, right-hand side is another field path). Both present means implicit AND.

Also present: element quantifiers `$any` / `$all` / `$none` over array fields.

**Sort** — `QuerySortExpression = Mapping[str, "asc" | "desc" | {"dir": …, "nulls": "first" | "last"}]`.
Canonical default when `nulls` is omitted: `first` for `asc`, `last` for `desc` (a null sorts as
the smallest value).

**Pagination** — `PaginationExpression = {"limit": int | None, "offset": int | None}`;
`CursorPaginationExpression` adds opaque `after` / `before` tokens.

**One design detail worth copying verbatim.** Forze's `Numeric` alias admits `str`:

> `str` is the JSON carrier for values JSON numbers cannot express exactly — an exact `Decimal`
> range bound on a money column, an ISO datetime — validated per field at render time, which
> refuses a string the field's type cannot parse **and any non-finite numeric** (`"NaN"` /
> `"Infinity"` parse as `Decimal` but are not range bounds: Postgres sorts `'NaN'::numeric`
> above every number, so a `$lt "NaN"` filter would fail open and match every row).

That last clause is a real bug bloomery would otherwise ship. See D-Q5.

---

## 3. Decisions

### D-Q1 — Drop `between`

Forze has no `$between`; it composes `$gte` + `$lte` in one operator map. Keeping `between` in
bloomery creates a special case in one direction and an ambiguity in the other (is
`$gte`+`$lte` on one field a `between`, or two independent filters?).

**Remove `between` from the operator set.** Callers pass `gte` and `lte`. The compiler may
optimise the pair into a `BETWEEN` in generated SQL if a dialect prefers it — that's a rendering
detail, not a DSL concept.

### D-Q2 — Split `contains` into `like` / `ilike`

A single `contains` forces the translator to guess case sensitivity, and a wrong guess in a
filter produces a silently wrong number rather than an error.

**Adopt `like` and `ilike` as distinct operators**, matching Forze. Both take one pattern or a
sequence of patterns with OR semantics, as upstream does. Wildcard escaping is bloomery's
responsibility (see §6).

`regex` is deliberately **not** adopted — see the closed list in §5.

### D-Q3 — One level of disjunction, in conjunctive normal form ⚠️

The structural decision, and the one to get right.

Forze filters are arbitrary boolean trees. Bloomery's draft was a flat tuple with implicit AND,
which makes any disjunction untranslatable.

Note that MetricFlow is **not** the constraint here: `where_constraints` is a sequence of
Jinja-templated SQL boolean expressions, ANDed together, and each string can itself contain
`OR`. So disjunction is renderable downstream. The question is purely what `MetricRequest`
should accept.

**Decision: accept CNF — a top-level AND over clauses, where a clause is either a single
predicate or an `any_of` group of single-field predicates. No deeper nesting.**

```
filters = AND( clause, clause, … )
clause  = Predicate | AnyOf(Predicate, Predicate, …)
```

Rationale: this covers every filter a BI UI actually builds ("carrier in [DHL, UPS] **and**
(region = EU **or** region = UK)"), keeps every clause independently renderable and independently
explainable, and — because each clause is a separate `where_constraints` entry — keeps the
generated SQL readable and each predicate individually attributable in the `Explanation`.

Arbitrary nesting is refused, explicitly, with the normalization result in the error message.

### D-Q4 — Normalize before refusing

A large share of incoming expressions that *look* unsupported are supported after normalization.
`planner/parse.py` (§7) must attempt this before giving up:

1. **Push negations to leaves** via De Morgan: `$not{$and:[a,b]}` → `$or[$not a, $not b]`, etc.
2. **Invert negated leaves** into their complement operator:
   `$not $eq → ne`, `$not $in → not_in`, `$not $null:true → null:false`, `$not $gt → lte`, …
   A leaf whose operator has no complement (`like`, set relations) stays negated and is refused.
3. **Distribute to CNF.**
4. **Cap the blow-up.** CNF conversion is exponential in the worst case — refuse with
   `FilterTooComplex` above a configurable clause count (default 64) rather than hanging.
5. **Check each clause** against the supported operator set and the single-field rule.

Step 2 is worth the effort: it turns a common shape (`$not` over an equality) from a refusal into
a clean translation.

### D-Q5 — Adopt the string-carrier numeric, including the non-finite guard

```python
Scalar = int | float | Decimal | bool | str | date | datetime | UUID
```

with the rule that a `str` operand for an ordering operator is cast per the dimension's declared
type at render time, and **`NaN` / `Infinity` / `-Infinity` are refused** even though they parse
as `Decimal`. A `lt "NaN"` predicate that fails open and matches every row is exactly the class
of bug this project exists to prevent.

Add to §8's test list: a property test asserting every non-finite literal is refused on every
ordering operator.

### D-Q6 — `OrderSpec` carries no nulls control

MetricFlow's `order_by_names` is `metric` / `-metric` — direction only, no `NULLS FIRST/LAST`.

**Do not put a `nulls` field on `OrderSpec`.** Accepting a parameter that is silently dropped is
worse than refusing it. The translator maps Forze's `{"dir": …, "nulls": …}` spec form by
checking whether the requested placement equals the canonical default for that direction
(`first` for `asc`, `last` for `desc`); if it does, translate and drop the redundant field, if it
doesn't, refuse with `UnsupportedSortNulls`.

Also declare it in `TargetCapabilities`:

```python
class Feature(StrEnum):
    ...
    SORT_NULLS_PLACEMENT = "sort_nulls_placement"   # MetricFlowPlanner: not supported
```

### D-Q7 — Pagination is limit-only

`MetricRequest` has `limit`. Forze's `PaginationExpression` also carries `offset`, and
`CursorPaginationExpression` carries opaque cursors.

MetricFlow's request has `limit` and no offset. Offset paging over an aggregate is also
semantically shaky — the underlying rows can change between pages.

**Keep `limit` only.** The translator refuses a non-zero `offset` with `UnsupportedPagination`,
and cursor pagination outright. If paging over large metric results becomes a requirement, it
belongs at the serving layer (materialise the result, page the materialisation), not in
`MetricRequest`.

---

## 4. Revised types

Replaces the `FilterExpr` / `OrderSpec` definitions in D1 §"Types".

```python
# bloomery/planner/request.py

type Scalar = int | float | Decimal | bool | str | date | datetime | UUID

class Op(StrEnum):
    EQ      = "eq"        # ← $eq
    NE      = "ne"        # ← $neq
    GT      = "gt"        # ← $gt
    GTE     = "gte"       # ← $gte
    LT      = "lt"        # ← $lt
    LTE     = "lte"       # ← $lte
    IN      = "in"        # ← $in
    NOT_IN  = "not_in"    # ← $nin
    IS_NULL = "is_null"   # ← $null   (operand: bool)
    LIKE    = "like"      # ← $like
    ILIKE   = "ilike"     # ← $ilike


@dataclass(frozen=True)
class Predicate:
    """One single-field constraint. Never field-to-field — see §5."""
    dimension: str                       # role-qualified, e.g. "shipped_date"
    op: Op
    values: tuple[Scalar, ...] = ()      # arity checked per operator


@dataclass(frozen=True)
class AnyOf:
    """Disjunction of predicates — one level only (D-Q3)."""
    predicates: tuple[Predicate, ...]


type Clause = Predicate | AnyOf


@dataclass(frozen=True)
class OrderSpec:
    field: str                           # a requested metric or dimension; never an expression
    direction: Literal["asc", "desc"] = "asc"
    # no `nulls` — see D-Q6


@dataclass(frozen=True)
class MetricRequest:
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: tuple[Clause, ...] = ()     # implicit AND across clauses
    time_grain: TimeGrain | None = None
    order_by: tuple[OrderSpec, ...] = ()
    limit: int | None = None
```

Operator arity, validated at construction:

| Operator | `values` |
|---|---|
| `eq` `ne` `gt` `gte` `lt` `lte` | exactly 1 |
| `in` `not_in` | 1 or more |
| `is_null` | exactly 1, a `bool` |
| `like` `ilike` | 1 or more patterns (OR semantics, matching upstream) |

Naming: plain `eq`, not `$eq`. Bloomery is a standalone package with its own public API and
shouldn't inherit a JSON-transport convention. The **semantics** are what must match; the map is
one-to-one either way.

---

## 5. The closed list — what cannot cross

This is the deliverable of the whole document. Every entry is a deliberate, reviewed refusal
with a specific error type. Anything not on this list must translate.

**Owned by bloomery** — raised by `planner/parse.py`, exported as
`bloomery.planner.KNOWN_UNSUPPORTED`, and testable with no Forze present:

| Construct | Refusal | Why |
|---|---|---|
| `$superset` `$subset` `$disjoint` `$overlaps` | `UnsupportedSetRelation` | Marts are flattened and scalar by construction; no array columns exist to relate. |
| `$descendant_of` `$ancestor_of` | `UnsupportedHierarchy` | Backend-specific (`ltree`) and capability-gated even upstream. Model hierarchy as flattened level columns on the mart instead. |
| `$regex` | `UnsupportedTextOperator` | Dialect-divergent syntax and unbounded cost. `like` / `ilike` cover the BI cases. Revisit only with a demonstrated need. |
| `$empty` | `UnsupportedTextOperator` | Ambiguous across types (empty string vs empty array vs null). Express as `eq ""` or `is_null true` explicitly. |
| Nesting deeper than AND-of-`AnyOf` | `UnsupportedNesting` | D-Q3. Error message includes the normalization result so the caller can see the shape it reached. |
| CNF expansion above the clause cap | `FilterTooComplex` | D-Q4 step 4. |
| Negated leaf with no complement operator | `UnsupportedNegation` | e.g. `$not $like`. Add `not_like` only if it turns up in real usage. |
| Non-finite numeric operand | `InvalidLiteral` | D-Q5. Fails open if permitted. |
| `nulls` placement other than the canonical default | `UnsupportedSortNulls` | D-Q6. |
| `offset` ≠ 0, or cursor pagination | `UnsupportedPagination` | D-Q7. |

**Owned by the app adapter** — the two constructs specific to Forze's grammar, which bloomery's
parser never sees because the adapter strips or refuses them first:

| Construct | Refusal | Why |
|---|---|---|
| `$fields` (field-to-field compare) | `UnsupportedFieldCompare` | A dimension-to-dimension comparison in a metric query is almost always a modelling error — it belongs in the mart definition, not in a filter. If genuinely needed, add a derived boolean dimension to the spec. |
| `$any` / `$all` / `$none` element quantifiers | `UnsupportedQuantifier` | Marts are flattened and scalar; an array column on a mart means the flattening was incomplete. |

All of these subclass `UnsupportedFilter(BloomeryError)`, carrying `.reason` (a stable string
code), `.source_path`, and where relevant `.normalized` (the post-normalization form) so the
error is actionable rather than merely correct. The app adapter's two reason codes are declared
alongside bloomery's, so the conformance test in §7 checks one union.

---

## 6. Rendering to MetricFlow (amends R6)

`planner/filters.py` renders each `Clause` to one `where_constraints` entry.

```python
def to_where(filters: tuple[Clause, ...], policy: RowPolicy | None) -> tuple[str, ...]:
    out: list[str] = []
    if policy is not None:
        out.append(render_clause(policy.as_clause()))     # always first
    out.extend(render_clause(c) for c in filters)
    return tuple(out)
```

`render_clause` emits, per D-Q3, one string per clause:

```
Predicate  →  {{ Dimension('order_item__carrier') }} = 'DHL'
AnyOf      →  ({{ Dimension('order__region') }} = 'EU' OR {{ Dimension('order__region') }} = 'UK')
```

The safety rules from R6 are unchanged and remain merge-blocking:

- The dimension name inside `{{ Dimension(...) }}` comes from `names.py` from a validated
  `DimensionRef` — never from caller input.
- Literals go through a typed, dialect-aware renderer. Never `f"'{value}'"`.
- `like` / `ilike` patterns escape `%`, `_`, and the escape character itself.
- Values are type-checked against the dimension's declared type before rendering;
  a mismatch is `FilterTypeMismatch`, not a cast.
- Parenthesise every `AnyOf` group. An unparenthesised `OR` inside an ANDed constraint list is a
  correctness bug, not a style one.

One addition: `render_clause` must be **injective enough to round-trip for the explanation** —
`Explanation.filters` is built from the `Clause` objects, not by parsing the rendered strings.

---

## 7. Where parsing lives

Two pieces, and the split is the substance of §1.2.

### 7.1 `bloomery/planner/parse.py` — the parser (new module)

A public feature of the package, not scaffolding for one application. Pure: no I/O, no tenant
awareness, deterministic, total errors — the same five invariants as everything else in bloomery.

```python
def parse_filter_json(payload: JsonDict) -> tuple[Clause, ...]:
    """Parse a Mongo-flavoured filter document into clauses.

    Grammar: {"$and": [...]}, {"$or": [...]}, {"$not": {...}}, and a field map
    {field: scalar | {op: value}} using the operators in `Op`. Scalars are the
    `$eq` shortcut; arrays are the `$in` shortcut; null is `is_null: true`.

    Normalizes per D-Q4 (De Morgan → complement inversion → CNF → clause cap),
    then validates each clause against the single-field rule.

    Raises UnsupportedFilter with a stable `.reason` for anything outside the
    supported subset. See KNOWN_UNSUPPORTED.
    """

KNOWN_UNSUPPORTED: Final[frozenset[str]] = frozenset({...})
"""Every reason code parse_filter_json can raise. Exported so downstream
adapters can assert their own refusal set is a superset of this one."""
```

Also export `parse_sort_json` and `parse_page_json` for symmetry — both are a dozen lines and
both carry the D-Q6 / D-Q7 refusals.

`planner/request.py` keeps the typed constructors; `parse.py` is the JSON front door. Callers
that build `Clause` objects directly never touch the parser, and that path stays the primary
one — the parser is a convenience over the same types, not a second representation.

### 7.2 The app adapter — thin

Lives in the application, depends on both packages, is depended on by neither.

```
platform_core/translate/
  filters.py      QueryFilterExpression  →  tuple[Clause, ...]
  sort.py         QuerySortExpression    →  tuple[OrderSpec, ...]
  page.py         PaginationExpression   →  limit
  errors.py       UnsupportedFilter      →  the HTTP problem response
```

`filters.py` is roughly thirty lines. Forze's grammar is the same Mongo-flavoured base plus two
structural additions, so the adapter handles exactly those and delegates the rest:

```python
def to_bloomery(expr: QueryFilterExpression) -> tuple[Clause, ...]:
    """Unwrap Forze's $values/$fields split, refuse its two extensions, delegate."""
    return parse_filter_json(strip_values_wrapper(expr))
```

`strip_values_wrapper` walks the tree, unwraps `$values` maps into plain field maps, and raises
`UnsupportedFieldCompare` / `UnsupportedQuantifier` on `$fields` and the element quantifiers.
Everything else — normalization, operator validation, the clause cap — happens inside bloomery.

If a second product ever needs this adapter it becomes a small `bloomery-forze` bridge package,
but not before. Same two-implementations rule that governs everything else here.

### 7.3 Conformance tests — two, at different levels

**In bloomery's own suite**, over the JSON grammar, with no Forze anywhere:

```python
@given(filter_documents())                  # hypothesis strategy over the Mongo-ish grammar
def test_parse_is_total_or_explicitly_refuses(doc):
    try:
        clauses = parse_filter_json(doc)
    except UnsupportedFilter as e:
        assert e.reason in KNOWN_UNSUPPORTED
        return
    assert semantically_equivalent(doc, clauses)    # evaluate both against generated rows
```

**In the app's suite**, much thinner — only the two Forze-specific shapes:

```python
@given(forze_filter_expressions())
def test_adapter_is_total_or_explicitly_refuses(expr):
    try:
        to_bloomery(expr)
    except UnsupportedFilter as e:
        assert e.reason in KNOWN_UNSUPPORTED | APP_UNSUPPORTED   # union from §5
```

`KNOWN_UNSUPPORTED` is bloomery's export; `APP_UNSUPPORTED` is the app's two codes. A new refusal
reason in either that isn't in the union fails the test — which is what keeps the closed list
closed and forces a reviewed decision every time something new can't cross.

`semantically_equivalent` must evaluate both forms against a generated row set rather than
compare structures; structural comparison after normalization is circular.

---

## 8. Tests to add

All but the last two run **inside bloomery**, with no Forze and no infrastructure — which is the
practical payoff of §1.2.

| Repo | Layer | Test |
|---|---|---|
| bloomery | Unit | Operator arity validation for every `Op` member |
| bloomery | Unit | Negation-complement table: `not eq → ne`, `not in → not_in`, `not gt → lte`, `not is_null:true → is_null:false` |
| bloomery | Unit | Every bloomery-owned §5 refusal fires with the right error type and a message containing the normalized form |
| bloomery | Unit | `KNOWN_UNSUPPORTED` equals the set of reason codes `parse_filter_json` can actually raise — a drift guard on the export itself |
| bloomery | Property | Non-finite literals (`NaN`, `Infinity`, `-Infinity`, and their string forms) refused on all six ordering operators |
| bloomery | Property | CNF normalization terminates and respects the clause cap on adversarial nesting |
| bloomery | Property | §7.3's `parse_filter_json` totality test |
| bloomery | Property (R6) | Filter fuzzing — adversarial values (`' OR 1=1 --`, `{{ Dimension('x') }}`, unicode quote variants, embedded newlines, `%`/`_` in `like`) render to SQL whose parsed predicate structure is unchanged and whose scanned relations are exactly the expected mart |
| bloomery | Execution | An `AnyOf` clause produces the same rows as two separate queries UNIONed |
| bloomery | Execution | Row policy plus an `AnyOf` clause: the policy predicate is present in every scan, and the `AnyOf` is parenthesised (assert on the parsed AST) |
| app | Unit | `strip_values_wrapper` refuses `$fields` and each element quantifier |
| app | Property | §7.3's adapter totality test over the union refusal set |

The parenthesisation test deserves emphasis: `policy AND (a OR b)` versus `policy AND a OR b`
differ, the second leaks every row matching `b`, and both parse fine.

---

## 9. Checklist

**In bloomery:**

- [ ] `between` removed from `Op`; callers use `gte` + `lte`
- [ ] `contains` split into `like` / `ilike`
- [ ] `Clause = Predicate | AnyOf` introduced; `MetricRequest.filters` retyped
- [ ] `Scalar` widened to the string-carrier form, with the non-finite guard
- [ ] `OrderSpec.nulls` absent; `Feature.SORT_NULLS_PLACEMENT` added and declared unsupported
- [ ] `limit` only; no offset, no cursors
- [ ] `UnsupportedFilter` hierarchy with the §5 reason codes as stable strings
- [ ] **`planner/parse.py` added** — `parse_filter_json`, `parse_sort_json`, `parse_page_json`
- [ ] **`KNOWN_UNSUPPORTED` exported** from `bloomery.planner`, with the drift-guard test
- [ ] D-Q4 normalization lives in the parser, not in any caller
- [ ] `render_clause` parenthesises `AnyOf`; policy clause rendered first
- [ ] `Explanation.filters` built from `Clause` objects, not by parsing SQL
- [ ] `parse.py` documented in the README — it's a feature, not internal plumbing

**In the application:**

- [ ] `strip_values_wrapper` + `to_bloomery`, ~30 lines, delegating to `parse_filter_json`
- [ ] `APP_UNSUPPORTED` frozenset with exactly two codes
- [ ] Adapter totality test over `KNOWN_UNSUPPORTED | APP_UNSUPPORTED`
- [ ] `errors.py` maps `UnsupportedFilter.reason` to HTTP problem responses
