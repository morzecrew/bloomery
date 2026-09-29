<!-- torve:managed tests/golden/path_conflict/sqlmesh/duckdb/audits — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/golden/path_conflict/sqlmesh/duckdb/audits/`

### S-0023/D-12 — `ASSUMED` (Guardrails: refusing plausible-but-wrong arithmetic)

Guardrails read the parsed expression with sqlglot's `find_all` over the node types they judge — `arithmetic.py` visits `exp.Add`, `exp.Sub`, `exp.Mul` and `exp.Div` and branches with `isinstance` — rather than a visitor class or a `match` statement. The `RECONCILE` audit selects rows where `<column> IS DISTINCT FROM <column>__direct`

- Paths: `src/bloomery/guardrails/arithmetic.py` `src/bloomery/emit/lower/predicates.py` `tests/golden/path_conflict/sqlmesh/duckdb/audits/item_net_price_reconcile.sql` `tests/unit/test_guardrails/test_conflict.py`
- Consequence: A row where exactly one of the two paths is NULL counts as a disagreement, and changing the reconcile predicate moves the checked-in `path_conflict` audit goldens

<!-- /torve:managed -->
