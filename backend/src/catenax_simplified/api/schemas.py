from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _as_utc(value: datetime | None) -> datetime | None:
    # Timestamps are stored in UTC; SQLite returns them without a timezone.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


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
    synced_at: UtcDatetime


class PartListItem(PartOut):
    parents_count: int
    children_count: int


class PartPage(BaseModel):
    items: list[PartListItem]
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

    id: int | None
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    twins: int
    parts: int
    relation_sets: int
    unsupported_submodels: int
    removed_parts: int
    complete: bool
    issues: list[SyncIssueOut]


class SyncRunPage(BaseModel):
    items: list[SyncReportOut]


class StatsOut(BaseModel):
    own_parts: int
    own_parts_by_kind: dict[str, int]
    own_parts_by_semantic_id: dict[str, int]
    supplier_links: int
    suppliers: int
    customer_links: int
    customers: int


class HealthOut(BaseModel):
    status: str
    own_bpnl: str
    dtr_configured: bool
    edc_configured: bool
    dtr_url: str | None
    sync_interval_seconds: int
    supported_aspects: list[str]


class PartnerOut(BaseModel):
    bpnl: str
    name: str | None
    roles: list[str]  # supplier and/or customer
    linked_twins: int
    cached_parts: int
    connector_address: str | None
    connector_source: str | None  # "api" (set here) or "settings"
    last_sync_at: UtcDatetime | None
    last_status: str | None  # ok | partial | failed | no_connector
    last_message: str | None
    twins_found: int
    twins_missing: int


class PartnerUpdate(BaseModel):
    name: str | None = None
    connector_address: str | None = Field(default=None, max_length=512)


class PartnerSyncResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bpnl: str
    roles: list[str]
    linked_twins: int
    twins_found: int
    twins_missing: int
    removed_parts: int
    status: str
    issues: list[str]


class PartnerSyncReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    partners: list[PartnerSyncResultOut]
