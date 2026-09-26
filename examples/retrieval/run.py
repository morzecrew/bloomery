"""Retrieval: compile a document-chunk corpus to its retrieval manifest.

The specs in this directory declare documents, a step that chunks and embeds
them, a mart at chunk grain, and two retrieval profiles over the result. This
compiles them to `retrieval_manifest.json` and writes it to ./out.

Every profile carries its semantic space inlined, so a runtime with no access to
this spec tree knows the dimensions, the scalar, the distance, the encoder
identities, the physical relation, the filterable columns and the projection. It
holds no embedding and no float.

Only the retrieval target is compiled here, and that is the boundary rather than
an omission: ask a SQL dialect for this corpus and it refuses, because a declared
vector is not a column a warehouse port emits DDL for ("dialect 'duckdb' has no
physical type for vector(float32, 1536)"). The relation holding the vectors is
written by the platform's step; what bloomery contributes is the contract for
querying it.

Run from the repository root:

    uv run python examples/retrieval/run.py
"""

import json
from pathlib import Path

import yaml

from bloomery import Target, compile_project, load_project
from bloomery.steps import StepManifest, StepRegistry

HERE = Path(__file__).parent
OUT = HERE / "out"


def registry() -> StepRegistry:
    """The step registry, assembled from the manifests in `step_manifests/`.

    The registry is a compile *input*: bloomery never reads a step manifest off
    disk, because a compiler that scanned the filesystem for contracts would stop
    being a pure function of its specs. Reading these files is this script's job,
    exactly as reading the YAML specs is.
    """
    manifests = {}
    for path in sorted((HERE / "step_manifests").glob("*.yaml")):
        manifest = StepManifest.model_validate(yaml.safe_load(path.read_text()))
        manifests[manifest.ref, manifest.version] = manifest
    return StepRegistry(manifests)


def main() -> None:
    project = load_project(
        {path.name: path.read_text() for path in sorted(HERE.glob("*.yaml"))}
    )
    steps = registry()

    for artifact in compile_project(
        project, target=Target.RETRIEVAL, dialect="duckdb", steps=steps
    ):
        destination = OUT / artifact.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(artifact.content)
        print(f"wrote {destination.relative_to(HERE)}")

    # What a runtime reads. Printed rather than only written, because the shape
    # is the example: profile -> relation, space, lexical side, fusion method,
    # filterable columns, projection.
    manifest = json.loads((OUT / "retrieval_manifest.json").read_text())
    print("\n-- retrieval_manifest.json --")
    for name, profile in sorted(manifest["profiles"].items()):
        relation = profile["relation"]
        space = profile["vector"]["space"]
        fusion = profile.get("fusion", {}).get("method", "none (dense only)")
        print(f"\n{name}:")
        print(f"  corpus     {relation['namespace']}.{relation['table']} ({relation['kind']})")
        print(f"  vector     {profile['vector']['field']} in {space['name']}: "
              f"{space['dimensions']}x{space['scalar']}, {space['distance']}")
        print(f"  encoders   documents {space['document_encoder']['model']}, "
              f"queries {space['query_encoder']['model']}")
        print(f"  fusion     {fusion}")
        print(f"  filterable {', '.join(profile['filterable'])}")
        print(f"  return     {', '.join(profile['return'])}")

    print(
        "\nNo embedding was computed, read or validated here, and nothing named a "
        "vector database: the manifest is a declaration a runtime executes."
    )


if __name__ == "__main__":
    main()
