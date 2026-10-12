"""Aspect model adapters: published versions (v3, v4, industry_core v4) → internal model."""

from .adapters import AspectPayloadError
from .model import Classification, Part, PartKind, Relation, Relations, RelationSource
from .registry import AspectType, is_supported, lookup, parse

__all__ = [
    "AspectPayloadError",
    "AspectType",
    "Classification",
    "Part",
    "PartKind",
    "Relation",
    "RelationSource",
    "Relations",
    "is_supported",
    "lookup",
    "parse",
]
