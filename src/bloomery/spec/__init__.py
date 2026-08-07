"""The spec layer (RFC 0002): strict frozen Pydantic models for the five spec
kinds plus the ``Project`` container and the pure loaders.

Parse validates *shape and grammar* only — reference existence is resolution's
job (RFC 0002 D4). Only :mod:`bloomery.errors` is imported from below.
"""

from bloomery.spec.catalog import (
    CanonicalField,
    CanonicalRelationship,
    Catalog,
    DateDimension,
    MetricTemplate,
    Recipe,
)
from bloomery.spec.common import RatioSpec, SemiAdditivePolicy, SpecModel
from bloomery.spec.entity import AssertClause, Entity, EntityModel, Field, Relationship
from bloomery.spec.mapping import (
    FieldMapping,
    KeyField,
    Mapping,
    RecipeFieldMapping,
    SimpleFieldMapping,
    TransformStep,
)
from bloomery.spec.marts import DateRoleStep, FlattenStep, Mart, MartSet, ViaStep
from bloomery.spec.metrics import CumulativeSpec, Metric, MetricSet
from bloomery.spec.project import Project, load_catalog, load_project

__all__ = [
    # catalog
    "Catalog",
    "CanonicalField",
    "CanonicalRelationship",
    "DateDimension",
    "MetricTemplate",
    "Recipe",
    # common
    "RatioSpec",
    "SemiAdditivePolicy",
    "SpecModel",
    # entity model
    "AssertClause",
    "Entity",
    "EntityModel",
    "Field",
    "Relationship",
    # mapping
    "FieldMapping",
    "KeyField",
    "Mapping",
    "RecipeFieldMapping",
    "SimpleFieldMapping",
    "TransformStep",
    # marts
    "DateRoleStep",
    "FlattenStep",
    "Mart",
    "MartSet",
    "ViaStep",
    # metrics
    "CumulativeSpec",
    "Metric",
    "MetricSet",
    # project + loaders
    "Project",
    "load_catalog",
    "load_project",
]
