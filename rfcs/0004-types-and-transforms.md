# RFC 0004 — Logical types and the transform registry

- **Status:** ✅ Complete — shipped 2026-08-07 (M2): closed `LogicalType` set, the
  versioned transform whitelist built as SQLGlot ASTs, and chain typechecking with
  tracked decimal precision landed as designed (`bloomery/typing/`,
  `bloomery/transforms/`).
- **Scope:** The type layer of the compiler: the closed `LogicalType` set and the typecheck
  stage (`bloomery/typing/`, spec §5.3), and the closed, versioned transform whitelist
  (`bloomery/transforms/`, spec §3.5) — the security and reviewability boundary that bounds
  what any proposal can possibly say. Covers type parsing from spec-layer strings, transform
  declaration and registration, chain typechecking, and the `register_transform` extension
  point. Does not cover unit/tax-basis/grain semantics (guardrails, RFC 0006), dialect
  rendering of transform ASTs (RFC 0008), or how chains reach the typechecker (resolution,
  RFC 0005). New modules: `bloomery/typing/`, `bloomery/transforms/`.
- **Related:** [`rfcs/_original-smelter-spec.md`](_original-smelter-spec.md) §3.5, §5.3, §8;
  RFC 0002 (type-string grammar validated at parse; error hierarchy §5.4), RFC 0003
  (`LogicalType` appears in `ColumnIR`; determinism rules), RFC 0005 (feeds resolved chains
  here), RFC 0006 (`convert` marker consumed by the currency guardrail), RFC 0008
  (emit-time dialect feature checks).
- **Origin:** Original `smelter` spec v0.1, renamed `bloomery`.

---

## 1. Summary

A closed set of seven logical types as frozen dataclasses, parsed from the spec layer's
grammar-validated type strings. A closed transform whitelist where each transform declares
its name, arity, argument kinds, input type domain, output type function, and a builder
producing a dialect-neutral SQLGlot AST — registered via a `@transform(...)` decorator into
a module-level immutable registry, extensible through `register_transform`. The typecheck
stage walks every transform chain and verifies the terminal type is assignable to the
declared field type, tracking decimal precision/scale through arithmetic.

## 2. Motivation

Two failure classes meet here. First, silent type coercion: a string column multiplied by a
quantity "works" on most engines and produces garbage on some — the chain
`str → parse_ts → timestamp → to_utc → timestamp` must be provable before any SQL exists.
Second, unbounded expressiveness: specs arrive from humans and upstream LLM-assisted
proposal systems (spec §1.3); if a mapping could name arbitrary SQL, reviewing a proposal
would mean reviewing SQL. A closed whitelist makes the reviewable surface the registry, not
the specs — a proposal can only compose vetted transforms, and an unknown name fails at
compile with the closest match named.

## 3. Current state

Greenfield. RFC 0002 pins the input side: type strings are grammar-validated at parse
(regex), `TransformStep(name, args)` is normalized at parse, and registry existence checks
are explicitly deferred to this layer (RFC 0002 D4). `UnknownTransformError` and
`TypeCheckError` are already declared in `bloomery/errors.py` (RFC 0002 §5.4).

## 4. Goals / Non-goals

**Goals**

- `LogicalType` union: `string`, `int`, `decimal(p, s)`, `bool`, `date`, `timestamp`
  (always UTC-normalized), `variant` — frozen dataclasses, parsed from spec type strings.
- `TransformSpec` + `@transform(...)` decorator + default registry with the starter set.
- `typecheck` stage: pure function over resolved chains, raising `TypeCheckError` /
  `UnknownTransformError` with source paths.
- `register_transform(spec)` as the public extension point (spec §8).

**Non-goals**

- Unit, tax-basis, currency, grain, additivity checks — semantics on top of types; that is
  the guardrail stage (RFC 0006). This layer answers "is this SQL well-typed", not "is this
  arithmetic meaningful".
- Dialect-specific rendering or capability checks — a transform whose AST cannot render on
  some dialect is caught at emit via `DialectPort` feature queries (RFC 0008), not here.
  The type layer is dialect-blind by construction.
- Physical/engine type mapping (`decimal(12,4)` → `DECIMAL(12,4)` vs `NUMERIC`) — that is
  `DialectPort.physical_type` (RFC 0008).

## 5. Design

### 5.1 Logical types (`bloomery/typing/types.py`)

```python
@dataclass(frozen=True, slots=True)
class StringType: ...
@dataclass(frozen=True, slots=True)
class IntType: ...
@dataclass(frozen=True, slots=True)
class DecimalType:
    precision: int
    scale: int
@dataclass(frozen=True, slots=True)
class BoolType: ...
@dataclass(frozen=True, slots=True)
class DateType: ...
@dataclass(frozen=True, slots=True)
class TimestampType: ...   # semantically always UTC; to_utc is how you get here from local
@dataclass(frozen=True, slots=True)
class VariantType: ...

LogicalType = StringType | IntType | DecimalType | BoolType | DateType | TimestampType | VariantType

def parse_type(text: str, *, source_path: str) -> LogicalType: ...
```

The set is closed for v0.1 — no `float` (banned package-wide, RFC 0003 D5), no `time`, no
arrays/structs (`variant` is the escape hatch for the unmapped tail). `parse_type` consumes
the grammar the spec layer already validated (RFC 0002 §5.5), so it can only fail on
grammar the regex admits but the type set rejects; it still raises `TypeCheckError` with
the field's source path rather than asserting. `TimestampType` carries no zone parameter:
a timestamp in bloomery *is* UTC, and `to_utc(tz)` is the only door in — this keeps the
type set closed while making mixed-zone arithmetic unrepresentable rather than checked.

**Assignability** (`assignable(actual, declared) -> bool`): identity for all scalar types;
anything is assignable to `variant`; `DecimalType` is assignable to a wider or equal
declared decimal (both `p - s` and `s` non-decreasing). Narrowing is never implicit — see
§5.4.

### 5.2 Transform declaration (`bloomery/transforms/registry.py`)

```python
@dataclass(frozen=True, slots=True)
class TransformSpec:
    name: str
    arity: int                                   # number of spec-level args (not the column)
    arg_kinds: tuple[ArgKind, ...]               # STR | INT | ENUM_MAP — parse-level shape
    input_domain: tuple[type[LogicalType], ...]  # accepted input types (classes)
    output_type: Callable[[LogicalType, tuple], LogicalType]   # may depend on args
    builder: Callable[..., exp.Expression]       # (col_ast, *args) -> dialect-neutral AST

def transform(name: str, *, arity: int, ...) -> Callable[..., TransformSpec]: ...
```

The `@transform(...)` decorator wraps a builder function into a `TransformSpec` and
registers it in the default registry at import:

```python
@transform("to_decimal", arity=2, input=(StringType, IntType, DecimalType),
           output=lambda t, args: DecimalType(args[0], args[1]))
def to_decimal(col: exp.Expression, p: int, s: int) -> exp.Expression:
    return exp.cast(col, exp.DataType.build(f"DECIMAL({p},{s})"))
```

`output_type` is a function, not a value, because output can depend on args
(`to_decimal(12,4)` → `decimal(12,4)`) or on the input type (`coalesce` preserves it).
Builders return SQLGlot AST **only** — string formatting inside a builder is a review-time
ban, and the property tests (§6) enforce that every builder output round-trips through
`sqlglot.parse_one`. Dialect-neutral means the AST uses generic SQLGlot nodes; the IR
stores it as canonical text per RFC 0003 §5.2.

### 5.3 The registry: closed default, sorted iteration, overlay extension

The default registry is a module-level immutable `Mapping[str, TransformSpec]` built at
import time from the decorated starter set. `register_transform(spec)` — public API per
spec §8 — adds to a process-global overlay consulted after the default map. A registration
whose name collides with any existing name (default or overlay) raises
`TransformRegistrationError` (a `BloomeryError`); shadowing a vetted transform silently
would defeat the whitelist's audit value. All registry iteration is sorted by name — the
registry is one of the few module-global structures in the package and must not leak
insertion order into output (RFC 0003 §5.5).

The overlay is deliberately process-global mutation — a tension with purity, accepted
because extension is a deployment-time act (an adapter package registering at import), not
a per-compile one. Alternative considered: threading a registry parameter through
`compile_project`. Rejected for v0.1: it complicates every stage signature for an
extension point with no second user yet; named as the escape hatch if per-compile
registries become real.

**Starter set (exact, v0.1):** `trim upper lower to_string to_int to_decimal to_bool
parse_ts parse_date to_utc enum_map coalesce nullif split_part regex_extract strip_prefix
strip_suffix multiply divide round abs concat json_path`, plus **`convert`** — the
explicit currency-conversion marker the currency guardrail requires for mixed-currency
arithmetic (RFC 0006). `convert` type-checks as `decimal → decimal` here; its *semantic*
obligations (rate source, target currency) are guardrail/emit concerns.

### 5.4 Typecheck stage (`bloomery/typing/check.py`)

```python
def typecheck_chain(input_type: LogicalType, steps: tuple[TransformStep, ...],
                    declared: LogicalType, *, registry: Registry,
                    source_path: str) -> LogicalType: ...
```

Pure function; runs after resolution (RFC 0005) has bound every chain to a source column
and an input type (source columns from JSONPath extraction start as `string` or `variant`).
Per step:

1. Look up the name. Unknown → `UnknownTransformError` naming the closest match via
   `difflib.get_close_matches(name, sorted(registry), n=1)` — deterministic, stdlib, and
   the sorted candidate list pins tie-breaks.
2. Check arity and arg kinds against `arg_kinds` → `TypeCheckError` on mismatch, path
   suffixed `transform[i]`.
3. Check the current type is in `input_domain` → `TypeCheckError` naming the actual type,
   the transform, and its accepted domain.
4. Current type ← `output_type(current, args)`.

The terminal type must be `assignable` to the declared field type, else `TypeCheckError`
showing both types and, when the failure is a decimal narrowing, the exact fix: *decimal
widening is implicit; narrowing requires an explicit `to_decimal(p, s)` step*. Precision
and scale are tracked through arithmetic transforms with the usual SQL rules
(`multiply`: `p1+p2`, `s1+s2`, capped at 38 with `TypeCheckError` on overflow rather than
silent truncation; `divide` follows the same capped-widening scheme). Failures are batched
per stage (all chains checked, one combined `TypeCheckError` listing every path) —
consistent with the parse layer's one-round-trip principle (RFC 0002 D6).

## 6. Tests

- Unit: `parse_type` for every type and every malformed-but-grammar-passing string; one
  test per starter transform asserting input domain, output type (including arg-dependent
  cases), and builder AST shape; unknown-name suggestions ("pars_ts" → `parse_ts`);
  collision on re-registration; decimal widening/narrowing/overflow branches.
- Property (Hypothesis): every builder output parses under `sqlglot.parse_one`; random
  valid chains typecheck to the type the composed `output_type`s predict; registry
  iteration order is invariant under registration order of overlay entries.
- The `messy_types` fixture (RFC 0009) exercises string-numerics, mixed date formats, and
  dirty enums end-to-end through chains.

## 7. Docs

`pages/reference/transforms.md` — one entry per starter transform: signature, input
domain, output type, one YAML example. Generated-adjacent: hand-written but asserted
against the registry in a doc test so it cannot drift. Explanation page on the whitelist
as a security boundary — worded carefully: it bounds *expressiveness*, it does not
sandbox builder code (a registered extension transform is trusted code).

## 8. Out of scope

- **User-defined transforms in YAML** — expressions in specs would dissolve the whitelist;
  extension is Python-only via `register_transform`, so every new transform is code review,
  not config review. This is the point, not a limitation.
- **Registry versioning surface** — the registry is "versioned" by the package version and
  the docs page; a machine-readable registry manifest is deferred until a consumer exists.
- **Timezone-aware timestamp type** — `timestamp` is UTC by fiat; local-time semantics live
  entirely inside `parse_ts`/`to_utc` arguments.

## 9. Risks

- *Decimal arithmetic rules diverge across engines* (cap-at-38 vs engine-specific caps).
  Mitigation: bloomery's rules are the strictest common denominator; the dialect matrix
  execution tests (spec §7.5) assert numeric agreement, and a dialect that cannot honor a
  checked type fails at emit via `physical_type`, not silently.
- *The overlay makes compile output depend on import side effects* — two processes with
  different adapter packages loaded compile differently. Accepted and documented: the
  fingerprint (RFC 0003) covers IR content, and identical inputs still yield identical
  outputs *given the same registry*; the determinism contract is scoped to a fixed
  installed set.
- *Closest-match suggestions read as fuzzy behavior* — mitigated by pinning
  `difflib.get_close_matches` over a sorted candidate list and snapshot-testing the
  suggestions.

## 10. Unresolved questions

- None blocking. Implementation is free to settle `ArgKind` granularity and whether
  `enum_map`'s mapping arg is modeled as a kind or a dedicated spec field, as long as parse
  (RFC 0002) and this layer agree on the normalized `TransformStep` shape.

## 11. Decisions

| # | Decision |
| --- | --- |
| 1 | Closed `LogicalType` set for v0.1: `string`, `int`, `decimal(p,s)`, `bool`, `date`, `timestamp` (always UTC-normalized), `variant` — frozen dataclasses parsed from the spec layer's grammar-validated type strings. Adding a type is a spec-grammar + typing + dialect change, deliberately expensive. |
| 2 | The transform registry is a closed, versioned whitelist and is the security/reviewability boundary. Each transform declares name, arity/arg kinds, input type domain, output type *function* (may depend on args), and a builder producing a dialect-neutral SQLGlot expression; declared via `@transform(...)` building a `TransformSpec`. |
| 3 | Starter set is exactly: `trim upper lower to_string to_int to_decimal to_bool parse_ts parse_date to_utc enum_map coalesce nullif split_part regex_extract strip_prefix strip_suffix multiply divide round abs concat json_path`, plus `convert` as the explicit currency-conversion marker required by the currency guardrail (RFC 0006). |
| 4 | Unknown transform name → `UnknownTransformError` naming the closest match, computed with `difflib.get_close_matches` over the sorted registry — deterministic suggestions, no external fuzzy dependency. |
| 5 | Typecheck walks each chain and requires the terminal type assignable to the declared field type. Decimal precision/scale tracked through arithmetic; widening is implicit, narrowing requires an explicit `to_decimal(p,s)` step, else `TypeCheckError`. |
| 6 | `register_transform(spec)` is public API; the default registry is a module-level immutable mapping built at import, extensions live in a process-global overlay, name collisions are errors, and all registry iteration is sorted by name. Consequence: determinism is scoped to a fixed installed extension set. |
| 7 | Transform builders produce SQLGlot AST only — never string formatting. Dialect rendering happens at emit (RFC 0008); dialect incapability is an emit-time `DialectPort` feature failure, never a typing concern. |

## 12. Phasing

Ships in M2 (types + typecheck + the subset of transforms `minimal` needs) and completes
the starter set by M3, when catalog recipes (RFC 0005) start exercising arithmetic
transforms and decimal tracking. `convert` lands with the currency guardrail in M4
(RFC 0006) but is registered from day one so the whitelist is complete.
