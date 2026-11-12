"""Aspect model adapters: published versions (v3, v4, industry_core v4) → internal model."""

from .adapters import AspectPayloadError
from .identifiers import instance_id
from .model import Classification, Part, PartKind, Relation, Relations, RelationSource
from .registry import (
    PART_TYPES,
    AspectType,
    contradiction,
    is_supported,
    lookup,
    parse,
    part_preference,
    part_types,
)

__all__ = [
    "PART_TYPES",
    "AspectPayloadError",
    "AspectType",
    "Classification",
    "Part",
    "PartKind",
    "Relation",
    "RelationSource",
    "Relations",
    "contradiction",
    "instance_id",
    "is_supported",
    "lookup",
    "parse",
    "part_preference",
    "part_types",
]
