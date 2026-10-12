from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClassificationOut(BaseModel):
    standard: str
    id: str
    description: str | None = None


class PartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    global_asset_id: str
    kind: str
    semantic_id: str
    manufacturer_id: str | None
    is_own: bool
    manufacturer_part_id: str | None
    customer_part_id: str | None
    name_at_manufacturer: str | None
    name_at_customer: str | None
    local_identifiers: dict[str, str]
    production_date: str | None
    country: str | None
    site_ids: list[str]
    classifications: list[ClassificationOut]
    synced_at: datetime


class PartPage(BaseModel):
    items: list[PartOut]
    total: int
    limit: int
    offset: int


class TreeNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    global_asset_id: str
    part: PartOut | None
    business_partner: str | None
    quantity: float | None
    unit: str | None
    is_only_potential_parent: bool
    declared_in: list[str]


class PartTreeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    part: PartOut
    parents: list[TreeNodeOut]
    children: list[TreeNodeOut]


class SyncIssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    global_asset_id: str
    semantic_id: str | None
    message: str


class SyncReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    started_at: datetime
    finished_at: datetime | None
    twins: int
    parts: int
    relation_sets: int
    unsupported_submodels: int
    removed_parts: int
    complete: bool
    issues: list[SyncIssueOut]


class HealthOut(BaseModel):
    status: str
    own_bpnl: str
    dtr_configured: bool
