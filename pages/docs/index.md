# Bloomery

**Entity-first spec compiler: declarative entity/mapping/metric specs, compiled
deterministically into SQLMesh, dbt, and Cube artifacts.**

bloomery is a pure function library: sources, entities, mappings, and metrics go in;
stable-sorted, byte-reproducible models, audits, and semantic-layer definitions come out.
Fail-closed guardrails turn grain fan-out, additivity violations, and contract breaks into
compile errors instead of silently wrong numbers.

The project is pre-0.1 and spec-driven — the design lives as RFCs in the repository's
`rfcs/` directory, and documentation pages land here with each implementation milestone.
Start with [Introduction](get-started/introduction.md).
