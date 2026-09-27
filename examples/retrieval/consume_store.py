"""A second runtime consuming the manifest — a vector store, not a warehouse.

`consume.py` reads the manifest as SQL over the relation the manifest names:
the vectors stay where the platform's step wrote them, and a query is a
`SELECT … ORDER BY distance LIMIT k`. This reads the same manifest as an
*external vector store* would — a Qdrant-shaped service with collections, a
per-point payload, declared payload indexes and server-side fusion. The
relation is not the index here; it is the source of an ingest into one.

Two unrelated readings of one document is the only way to find out whether the
semantics are vendor-neutral or whether they were quietly shaped by the first
consumer. **What this script prints at the end is the finding**: the register of
things the two consumers had to decide differently, and the manifest keys each
one reads. `pages/docs/concepts/retrieval.md` carries the same register as prose.

No dependency and no network: the payloads are the store's documented request
shapes, built as plain data and printed. Nothing is indexed, nothing is
searched, and no embedding is computed or read — there is no corpus here and no
query vector.

**This is a demonstration, not a claim bloomery makes.** Where the vectors live,
which index to build and what k is are the runtime's, and the manifest is
deliberately silent about all of it.

Run from the repository root, after `run.py`:

    uv run python examples/retrieval/consume_store.py
"""

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
MANIFEST = HERE / "out" / "retrieval_manifest.json"

#: The store's spelling of the distances a space may declare. Same shape as
#: `consume.py`'s table and the same reason it lives here: mapping a logical
#: metric onto an engine's name is the runtime's job, not bloomery's.
STORE_DISTANCE = {"cosine": "Cosine", "l2": "Euclid", "dot": "Dot"}

#: The store's storage datatypes. `float64` has none — a `float64` space is
#: stored at `float32` and the contract is honoured approximately, where the SQL
#: consumer has a `DOUBLE` and honours it exactly. One of the disagreements.
STORE_DATATYPE = {"float16": "float16", "float32": "float32", "float64": "float32"}

#: The manifest keys `consume.py` reads, from reading it. Anything this consumer
#: needs that is not in here is a key that is load-bearing for one runtime and
#: inert for the other, which is what the register below is made of.
READ_BY_THE_SQL_CONSUMER = {
    "filterable",
    "relation",
    "return",
    "vector.field",
    "vector.space.dimensions",
    "vector.space.distance",
    "vector.space.scalar",
}


def collection(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    """The collection this profile describes, as a create-collection request.

    One collection per profile rather than per space: the two profiles here share
    `chunk_text` but not their relation, their filters or their projection, and a
    store indexes a corpus rather than a space.

    A sparse vector is configured for the lexical side, because a store has no
    full-text index to fall back on — which is where the manifest runs out: it
    names the *fields* the lexical side reads and no tokeniser, analyser or
    sparse model identity, while the dense side carries two encoder identities
    precisely so that a mismatch is refusable.
    """
    space = profile["vector"]["space"]
    config: dict[str, Any] = {
        "collection_name": name,
        "vectors": {
            space["name"]: {
                "size": space["dimensions"],
                "distance": STORE_DISTANCE[space["distance"]],
                "datatype": STORE_DATATYPE[space["scalar"]],
            }
        },
    }
    if "lexical" in profile:
        # ponytail: the sparse side is named and unparameterised, because the
        # manifest says nothing to parameterise it with.
        config["sparse_vectors"] = {"lexical": {}}
    return config


def payload_indexes(profile: dict[str, Any]) -> list[dict[str, str]]:
    """One payload index per filterable column.

    `filterable` is the key the two consumers disagree about most cheaply: in SQL
    every column is filterable for free and `consume.py` prints the list as a
    comment, while a store filters only on a field it has indexed — and it needs
    the field's *type* to build the index, which the manifest does not carry. The
    types are in the entity and mart specs, which this consumer cannot see.
    """
    return [
        {"field_name": column, "field_schema": "keyword"}  # guessed, not declared
        for column in profile["filterable"]
    ]


def ingest(name: str, profile: dict[str, Any]) -> dict[str, Any]:
    """The ingest this consumer needs and the SQL consumer does not have.

    The vectors are in the relation the manifest names; the store searches its own
    copy. So the relation is a *source* here, the grain is the point id — the
    manifest's `grain` is unread by `consume.py` and required here — and the
    payload is everything a query may filter on or return, because a payload not
    written at ingest cannot be returned later.
    """
    relation, vector = profile["relation"], profile["vector"]
    return {
        "collection_name": name,
        "from": f"{relation['namespace']}.{relation['table']}",
        "id": profile["grain"],
        "vector": {profile["vector"]["space"]["name"]: vector["field"]},
        "payload": sorted({*profile["return"], *profile["filterable"]}),
    }


def search(name: str, profile: dict[str, Any], *, limit: int = 10) -> dict[str, Any]:
    """The query request, dense or fused.

    The dense request is the whole of a dense-only profile. A hybrid profile
    becomes two prefetches and a fusion the server performs — which is where the
    manifest is thinnest: `rrf` names the method and neither the rank constant nor
    the depth of either candidate list, and both change the order of the results.
    The values here are this runtime's defaults, not the manifest's.
    """
    space = profile["vector"]["space"]
    dense = {
        "using": space["name"],
        "query": f"<{space['dimensions']} floats from {space['query_encoder']['model']}>",
    }
    request: dict[str, Any] = {
        "collection_name": name,
        "limit": limit,
        "with_payload": profile["return"],
        "filter": "<the runtime's, over " + ", ".join(profile["filterable"]) + ">",
    }

    if "fusion" not in profile:
        return {**request, **dense}

    return {
        **request,
        "prefetch": [
            {**dense, "limit": limit * 4},
            {"using": "lexical", "query": "<sparse vector, model undeclared>", "limit": limit * 4},
        ],
        # k=60 is this implementation's constant. The manifest declares the
        # method and no constant, so a second store fusing `rrf` with k=10 obeys
        # the same manifest and returns a different order.
        "query": {"fusion": profile["fusion"]["method"]},  # Qdrant spells it lowercase
    }


def keys_read(profile: dict[str, Any]) -> set[str]:
    """The manifest keys this consumer reads, as dotted paths.

    Computed from the profile rather than listed, so that a key added to the
    grammar shows up as unread by both consumers instead of being silently
    dropped by both.
    """
    read = {
        "relation",
        "grain",
        "return",
        "filterable",
        "vector.field",
        "vector.space.name",
        "vector.space.dimensions",
        "vector.space.distance",
        "vector.space.scalar",
        "vector.space.query_encoder",
    }
    if "lexical" in profile:
        read |= {"lexical", "fusion"}
    return {key for key in read if key.split(".")[0] in profile}


def unread(profile: dict[str, Any], read: set[str], prefix: str = "") -> set[str]:
    """The paths in a profile no consumer reads, pruned at the first one that is.

    A key read whole — `relation`, `fusion` — takes its children with it; what is
    left is a part of the document neither reading touches, and that is worth
    knowing before the grammar is called stable.
    """
    found = set()
    for key, value in sorted(profile.items()):
        path = f"{prefix}{key}"
        if path in read:
            continue
        if isinstance(value, dict) and any(other.startswith(f"{path}.") for other in read):
            found |= unread(value, read, f"{path}.")
        else:
            found.add(path)
    return found


def register(manifest: dict[str, Any]) -> list[str]:
    """What the two consumers disagreed about. The point of the second consumer.

    The first four lines are computed from the manifest; the rest are the
    judgements, and each names a key rather than a vibe.
    """
    profiles = manifest["profiles"]
    mine = set().union(*(keys_read(p) for p in profiles.values()))
    both = mine | READ_BY_THE_SQL_CONSUMER
    neither = set().union(*(unread(p, both) for p in profiles.values()))

    return [
        (
            "load-bearing here, inert in consume.py: "
            f"{', '.join(sorted(mine - READ_BY_THE_SQL_CONSUMER))}"
        ),
        (
            "load-bearing in consume.py, inert here: "
            f"{', '.join(sorted(READ_BY_THE_SQL_CONSUMER - mine)) or 'none'}"
        ),
        (
            f"read by neither consumer: {', '.join(sorted(neither))} — the two"
            " document-side identities exist to be compared at compile time, and no"
            " query path needs them; the query encoder is the one a runtime calls"
        ),
        (
            "the relation: consume.py queries it in place, this ingests from it — the"
            " manifest names a relation and no index, so the two readings disagree"
            " about whether it is the corpus or the source of a copy of the corpus"
        ),
        (
            "the collection name: derived from the profile name here, because nothing"
            " in the manifest identifies an index; two stores would disagree"
        ),
        (
            "`grain`: unread by consume.py, the point id here — and a composite grain"
            " has to become one id by a rule the manifest does not give"
        ),
        (
            "`return`: a query-time projection for consume.py, an ingest-time decision"
            " here — adding a column to `return` is a reindex, not a new query"
        ),
        (
            "`filterable`: free in SQL, a declared index here — and the field's type is"
            " needed to declare it and is not in the manifest, so it is guessed"
        ),
        (
            "`fusion: rrf`: names the method and not the rank constant or the candidate"
            " depth per side, so two consumers honouring it return different orders —"
            " the weakest point of the vendor-neutral claim"
        ),
        (
            "the lexical side: `fields` and no tokeniser, analyser or sparse model"
            " identity, while the dense side carries two encoder identities so a"
            " mismatch is refusable — the same class of bug, undefended on one side"
        ),
        (
            "`scalar`: honoured exactly by a SQL DOUBLE, approximately by a store with"
            f" no float64 storage type (stored {STORE_DATATYPE['float64']})"
        ),
    ]


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("run examples/retrieval/run.py first — no manifest to consume")

    manifest = json.loads(MANIFEST.read_text())
    print(f"manifest version {manifest['retrieval_manifest_version']}")

    for name, profile in sorted(manifest["profiles"].items()):
        print(f"\n-- {name} --")
        for request in (
            collection(name, profile),
            {"payload_indexes": payload_indexes(profile)},
            {"ingest": ingest(name, profile)},
            {"search": search(name, profile)},
        ):
            print(json.dumps(request, indent=2, sort_keys=True))

    print("\n-- what the two consumers disagreed about --")
    for line in register(manifest):
        print(f"* {line}")


if __name__ == "__main__":
    main()
