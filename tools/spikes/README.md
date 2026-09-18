# Spikes

Throwaway-by-intent programs that were run **once**, to answer a question a design document
could not answer from the code. They are here because the answer is cited in a task log, and
a measurement nobody can re-run is a claim rather than evidence (`flag-dont-flip`).

They are not tests. No marker, no CI, no fixture contract: they build a project in a
temporary directory, run a real framework against DuckDB, print a transcript and exit. A
spike that stops working is a fact about the tree having moved on, not a failure — re-read
the log entry it supports before repairing it, because the question may no longer be live.

| Spike | Question | Answer |
|---|---|---|
| `rfc0060_dbt.py`, `rfc0060_sqlmesh.py` | does a row admitted into a framework-maintained `scd: type2` relation, by any route, become visible to an as-of join? (S-0003 (§6)) | yes, by two of the three routes and on both targets — see `logs/T-0057.md` |

```bash
PYTHONPATH=tests uv run python tools/spikes/rfc0060_dbt.py
PYTHONPATH=tests uv run python tools/spikes/rfc0060_sqlmesh.py
```
