"""Version-independent internal model.

Everything outside the ``aspects`` package works with these types only; the adapters translate
the different published aspect model versions into them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PartKind(StrEnum):
    SERIAL = "serial"
    BATCH = "batch"


class RelationSource(StrEnum):
    """Which aspect declared a relation."""

    BOM = "bom"  # SingleLevelBomAsBuilt of the parent
    USAGE = "usage"  # SingleLevelUsageAsBuilt of the child


@dataclass(frozen=True)
class Classification:
    standard: str
    id: str
    description: str | None = None


@dataclass(frozen=True)
class Part:
    """A serialized part or a batch (Industry Core "PartInstance" twin)."""

    global_asset_id: str
    kind: PartKind
    semantic_id: str
    manufacturer_part_id: str | None = None
    customer_part_id: str | None = None
    name_at_manufacturer: str | None = None
    name_at_customer: str | None = None
    local_identifiers: dict[str, str] = field(default_factory=dict)
    production_date: str | None = None
    country: str | None = None
    site_ids: tuple[str, ...] = ()
    classifications: tuple[Classification, ...] = ()


@dataclass(frozen=True)
class Relation:
    """An as-built parent/child relation (one level)."""

    parent_id: str
    child_id: str
    source: RelationSource
    business_partner: str | None = None
    quantity: float | None = None
    unit: str | None = None
    is_only_potential_parent: bool = False


@dataclass(frozen=True)
class Relations:
    """Relations declared by one submodel of one twin."""

    declared_by: str
    source: RelationSource
    items: tuple[Relation, ...]
    customers: tuple[str, ...] = ()
