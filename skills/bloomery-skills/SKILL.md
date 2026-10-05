---
name: bloomery-skills
description: Write a bloomery project — spec YAML (catalog, entities, mappings, metrics, marts, steps, exposures, composition), compiling to dbt, SQLMesh, MetricFlow or Cube, planning a spec change, quality rules, and the Python API. Use when creating, editing, compiling or debugging bloomery specs, or when a bloomery compile refuses.
---

# bloomery

## Mental model

A bloomery project is a directory of YAML spec documents (mappings, entity models, metrics, marts, steps, exposures, exports and imports), each identified by its version key, read against a catalog that declares the vertical's domain graph. `bloomery compile` resolves those documents into one deterministic intermediate representation, proves what it can about it, and refuses with a located error when a guardrail fails rather than emitting something wrong. A target (dbt, SQLMesh, MetricFlow, Cube) is only a rendering of that representation, so the same specs compile to any of them byte-for-byte reproducibly. bloomery reads files and executes nothing: running the emitted project is the target's job, and planning a change compares two compiled representations.

## Read the whole row

Most tasks need three to five references; read the whole row. Find your task in the routing table below and read every reference that row names, in order, before writing a spec. One reference alone leaves out a rule another one states, and the spec it produces is confidently incomplete. If no row fits, pick the closest rows and read the union, then use the index for anything they left out.

## Routing

| I want to… | Read, in order |
|---|---|

## Index

### Foundations

### Specs

### Correctness

### Targets

### Change

### Consumption

### Running

## Documentation versions

Links to the published documentation use `https://morzecrew.github.io/bloomery/latest/<page>/`, the newest release. If the project pins an older bloomery, replace `latest` with that minor version, for example `https://morzecrew.github.io/bloomery/0.4/<page>/`, so the page matches the installed behaviour. A URL with no version segment returns 404.
