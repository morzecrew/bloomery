<!-- torve:managed examples/targets — rendered from the corpus; do not edit by hand -->

## Decisions governing `examples/targets/`

### S-0061/D-1 — `LOCKED` (The SQLMesh project file)

bloomery emits `config.yaml` with `model_defaults` and **never** a `gateways:` block. The dbt precedent is not an analogy but the same rule: `dbt_project.yml` is emitted, `profiles.yml` is not, because a connection carries hosts and credentials and the compiler reads no environment. M2 measures that SQLMesh accepts the split.

- Paths: `examples/targets/run.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

### S-0061/D-3 — `LOCKED` (The SQLMesh project file)

`start` is **derived**, never a new spec key. The catalog's date dimension already states the project's temporal extent; a second declaration of one fact is two declarations that will disagree.

- Paths: `examples/targets/run.py` `src/bloomery/emit/dbt/__init__.py` `src/bloomery/emit/sqlmesh/__init__.py` `src/bloomery/ir/nodes.py`
- Touching these paths owes a divergence entry: `torve log owed <task> --touched <files>` before you finish

<!-- /torve:managed -->
