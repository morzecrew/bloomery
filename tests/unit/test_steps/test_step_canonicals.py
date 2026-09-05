"""Canonical links on step outputs (RFC 0017 D41/D49).

D36 claimed §5.8's "downstream mappings, marts, and metrics reference them
like any silver entity" and only two thirds of it was true: marts worked,
metrics did not. The reason was precise rather than deep — a metric is
reachable iff every leaf of its ``requires`` closure is *available*, and a
canonical field is available iff something links to it with ``canonical:``.
Only mapped entity fields could draw that link, so a step's columns were
never available and any metric over one was unreachable.

What was missing was a *surface*, not a mechanism: somewhere for an authored
spec to say which canonical field a step output column is. It lives on the
wiring rather than in the manifest, because canonical names are the authored
spec's vocabulary — a manifest naming them could not be reused by a second
project with different ones, which is the fork §5.7 exists to refuse.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import SpecParseError
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  customer_raw:
    grain: one row per source row
    key: [source_system, source_id]
    fields:
      source_system: {type: string, required: true}
      source_id: {type: string, required: true}
"""

CATALOG = """
catalog_version: 1
vertical: ecom_retail
canonical_fields:
  match_confidence:
    entity: customer
    type: decimal(4,3)
"""

METRICS = """
metrics_version: 1
metrics:
  peak_confidence:
    requires: [match_confidence]
    grain: customer
    # `max` rather than `avg`: this fixture is about a metric reaching a step
    # output column, and an average declared additive is refused on its own
    # account since RFC 0038 D2 — which would make every assertion below fail
    # for a reason that has nothing to do with what they test.
    additivity: additive
    agg: max
    expr: "match_confidence"
"""

MANIFEST = StepManifest.model_validate(
    {
        "ref": "resolve_customers",
        "version": 3,
        "kind": "python_model",
        "entrypoint": "platform_steps.resolve_customers:resolve",
        "determinism": "pure",
        "runtime_lock": "sha256:a91f",
        "outputs": {
            "customer": {
                "grain": "customer",
                "key": ["canonical_id"],
                "produces": {
                    "canonical_id": {"type": "string", "required": True},
                    "confidence": {"type": "decimal(4,3)"},
                },
            },
            "customer_xref": {
                "grain": "xref",
                "key": ["source_system", "source_id"],
                "produces": {
                    "source_system": {"type": "string", "required": True},
                    "source_id": {"type": "string", "required": True},
                },
            },
        },
    }
)

REGISTRY = StepRegistry({("resolve_customers", 3): MANIFEST})

MAPPING = """
mapping_version: 1
target: customer_raw
source: bronze.crm__customers
key:
  source_system: {from: "$.source_system"}
  source_id: {from: "$.source_id"}
fields: {}
"""


def steps_doc(canonical: str = "    canonical: {customer: {confidence: match_confidence}}\n") -> str:
    return (
        "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
        "    outputs: {customer: silver.customer, customer_xref: silver.customer_xref}\n"
        + canonical
    )


def build(canonical: str | None = None, *, metrics: bool = True):  # noqa: ANN201 — ProjectIR
    sources = {"entity_model": ENTITY_MODEL, "steps": steps_doc()
               if canonical is None else steps_doc(canonical)}
    if metrics:
        sources["metrics"] = METRICS
    project = load_project(sources)
    return build_project_ir(project, catalog=load_catalog(CATALOG), steps=REGISTRY)


def test_a_metric_over_a_step_output_column_is_reachable() -> None:
    """The whole point of D41. Without the link this was
    ``unreachable metric … no mapped derivation path``."""
    ir = build()
    assert [metric.name for metric in ir.metrics] == ["peak_confidence"]
    assert ir.unreachable == ()


def test_without_the_link_the_metric_stays_unreachable() -> None:
    """The control: reachability must come from the declared link, not from a
    step output being present at all. Auto-linking by column name would be the
    guessing RFC 0006 exists to refuse — `confidence` and `match_confidence`
    are deliberately spelled differently here for exactly that reason."""
    ir = build(canonical="")
    assert [u.name for u in ir.unreachable] == ["peak_confidence"]
    assert ir.unreachable[0].missing == ("match_confidence",)


def test_the_column_carries_its_canonical_link_into_the_ir() -> None:
    ir = build()
    (entity,) = [e for e in ir.entities if e.name == "customer"]
    links = {column.name: column.canonical for column in entity.columns}
    assert links == {"canonical_id": None, "confidence": "match_confidence"}


# ....................... #
# Shape refusals (RFC 0002: the spec layer checks shape, resolve checks refs)


def test_linking_an_output_the_wiring_does_not_bind_is_refused() -> None:
    with pytest.raises(SpecParseError, match="does not bind"):
        load_project(
            {
                "entity_model": ENTITY_MODEL,
                "steps": steps_doc("    canonical: {nope: {confidence: match_confidence}}\n"),
            }
        )


def test_linking_a_column_the_output_does_not_produce_is_refused() -> None:
    """A resolution question, not a shape one: the manifest is what says which
    columns exist, and the spec layer has never seen it."""
    from bloomery.errors import StepError

    with pytest.raises(StepError, match="does not produce"):
        build("    canonical: {customer: {ghost: match_confidence}}\n")


def test_linking_to_a_canonical_field_the_catalog_lacks_is_refused() -> None:
    from bloomery.errors import BloomeryError

    with pytest.raises(BloomeryError, match="match_confidence|unknown canonical"):
        build("    canonical: {customer: {confidence: not_in_catalog}}\n")


# ....................... #
# reconcile over a step output (the other half of D41)


RECONCILE_MODEL = ENTITY_MODEL + """
reconcile:
  - name: customers_agree
    left: "count(customer_xref.source_id) by source_system"
    right: "count(customer_raw.source_id) by source_system"
    tolerance: "0"
    on_fail: fail
"""


def test_a_reconcile_side_may_name_a_step_output() -> None:
    """`reconcile` resolved sides against *declared, mapped* entities. A step
    output is neither — it is synthesized during lowering and no mapping
    targets it — so a check naming one was refused as "declared but no mapping
    targets", which is true and useless: the step writes the relation."""
    project = load_project(
        {
            "entity_model": RECONCILE_MODEL,
            "steps": steps_doc(),
            "mapping": MAPPING,
        }
    )
    ir = build_project_ir(project, catalog=load_catalog(CATALOG), steps=REGISTRY)
    assert [check.name for check in ir.reconcile] == ["customers_agree"]


def test_a_reconcile_side_naming_a_column_a_step_does_not_produce_is_refused() -> None:
    """The step output earns no exemption from the column check: its manifest
    is what says which columns exist."""
    from bloomery.errors import GuardrailError

    bad = RECONCILE_MODEL.replace(
        "count(customer_xref.source_id) by source_system",
        "sum(customer_xref.ghost) by source_system",
    )
    project = load_project(
        {"entity_model": bad, "steps": steps_doc(), "mapping": MAPPING}
    )
    with pytest.raises(GuardrailError, match="no such field"):
        build_project_ir(project, catalog=load_catalog(CATALOG), steps=REGISTRY)
