"""Entity-first spec compiler: declarative entity/mapping/metric specs compiled
deterministically into SQLMesh, dbt, and Cube artifacts.

Public API so far (M1): the pure loaders (``load_catalog``, ``load_project``),
the IR content hash (``project_fingerprint``), and the total error hierarchy
rooted at ``BloomeryError`` (import leaves from :mod:`bloomery.errors`).
"""

from bloomery.errors import BloomeryError
from bloomery.ir import project_fingerprint
from bloomery.spec import load_catalog, load_project

__all__ = [
    "BloomeryError",
    "load_catalog",
    "load_project",
    "project_fingerprint",
]
