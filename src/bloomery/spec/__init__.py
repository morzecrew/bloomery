"""The spec layer (S-0019): strict frozen Pydantic models for the five spec
kinds plus the ``Project`` container and the pure loaders.

Parse validates *shape and grammar* only — reference existence is resolution's
job (S-0019/D-4). Only :mod:`bloomery.errors` is imported from below.
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
from bloomery.spec.exports import Exports, ExportSet
from bloomery.spec.exposures import Exposure, ExposureDependsOn, ExposureSet
from bloomery.spec.imports import Imports, ImportSet, UpstreamAlias
from bloomery.spec.mapping import (
    FieldMapping,
    Freshness,
    KeyField,
    Mapping,
    RecipeFieldMapping,
    SimpleFieldMapping,
    TransformStep,
)
from bloomery.spec.marts import DateRoleStep, FlattenStep, Mart, MartSet, ViaStep
from bloomery.spec.metrics import CumulativeSpec, Metric, MetricSet
from bloomery.spec.project import Project, load_catalog, load_project
from bloomery.spec.quality import (
    CoercibleRule,
    Dedupe,
    EntityQualityRule,
    ExpressionRule,
    FieldQualityRule,
    InEnumRule,
    InSetRule,
    LengthRule,
    NotNullRule,
    PatternRule,
    Quarantine,
    RangeRule,
    Reconcile,
    ReferentialRule,
    UniqueRule,
)
from bloomery.spec.steps import StepSet, StepUse, StepWiring

# ----------------------- #

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
    "Freshness",
    "KeyField",
    "Mapping",
    "RecipeFieldMapping",
    "SimpleFieldMapping",
    "TransformStep",
    # steps (S-0034)
    "StepSet",
    "StepUse",
    "StepWiring",
    # exports (S-0002)
    "ExportSet",
    "Exports",
    # imports (S-0002)
    "ImportSet",
    "Imports",
    "UpstreamAlias",
    # exposures (S-0063)
    "Exposure",
    "ExposureDependsOn",
    "ExposureSet",
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
    # quality (S-0033)
    "CoercibleRule",
    "Dedupe",
    "EntityQualityRule",
    "ExpressionRule",
    "FieldQualityRule",
    "InEnumRule",
    "InSetRule",
    "LengthRule",
    "NotNullRule",
    "PatternRule",
    "Quarantine",
    "RangeRule",
    "Reconcile",
    "ReferentialRule",
    "UniqueRule",
    # project + loaders
    "Project",
    "load_catalog",
    "load_project",
]
