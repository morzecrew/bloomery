<!-- torve:managed tests/fixtures/currency_convert_refusal — rendered from the corpus; do not edit by hand -->

## Decisions governing `tests/fixtures/currency_convert_refusal/`

### S-0040/D-4 — `LOCKED` (Temporal joins: SCD2 flattening and currency conversion)

`convert` raises `UnsupportedByTarget` at **emit**, on all three dialects. It stays a registered transform with an unchanged typecheck, so the spec surface does not move and a future dialect clears the refusal by declaring a `Feature` — the mechanism S-0025 already provides.

- Paths: `src/bloomery/emit/lower/silver.py` `src/bloomery/evidence.py` `src/bloomery/resolve/build.py` `src/bloomery/transforms/_builtins.py` `tests/fixtures/currency_convert_refusal/entity_model.yaml` `tests/support/type_conformance.py` `tests/unit/test_emit/test_currency_convert.py` `tests/unit/test_evidence.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
