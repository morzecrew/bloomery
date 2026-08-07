"""The mart permutation harness (RFC 0010 §6, reused by RFC 0013 §6): two
independent marts over the ``role_playing_dates`` entities, reassembled with
the marts document in every permutation. Both marts list the same measure, so
the harness also exercises the emitter's owning-mart selection rule."""

from __future__ import annotations

from support.compiling import fixture_sources

MART_BLOCKS = {
    "by_ordered": """\
  by_ordered:
    grain: order
    base: order
    flatten:
      - {date: order_date, role: ordered}
    measures: [revenue]
""",
    "by_shipped": """\
  by_shipped:
    grain: order
    base: order
    flatten:
      - {date: ship_date, role: shipped}
    measures: [revenue]
""",
}


def sources_with_marts(order: list[str]) -> dict[str, str]:
    sources = fixture_sources("role_playing_dates")
    sources["marts"] = "marts_version: 1\nmarts:\n" + "".join(MART_BLOCKS[name] for name in order)
    return sources
