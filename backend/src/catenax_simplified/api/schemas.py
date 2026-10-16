from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from ..notifications import NotificationType, Severity, Status


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


class NotificationAssetsOut(BaseModel):
    # not_configured | publishing | published | failed
    state: str
    message: str | None = None
    at: UtcDatetime | None = None
    asset_ids: list[str] = []


class HealthOut(BaseModel):
    status: str
    own_bpnl: str
    dtr_configured: bool
    edc_configured: bool
    can_send_notifications: bool
    dev_direct: bool  # development mode: partners reached without EDCs
    can_check_partners: bool
    can_discover_connectors: bool  # a Discovery Finder is configured
    can_look_up_names: bool  # a BPDM Pool or a Business Partner Explorer is configured
    names_source: str | None  # where the names come from, e.g. "BPDM Pool"
    dtr_auth: str  # oauth | none
    edc_auth: list[str]  # oauth and/or api_key; empty: no credentials
    central_idp_url: str | None
    notification_assets: NotificationAssetsOut
    dtr_url: str | None
    sync_interval_seconds: int
    supported_aspects: list[str]


class PartnerCheckStepOut(BaseModel):
    key: str
    name: str
    status: str  # ok | warn | failed | skipped
    detail: str


class PartnerCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bpnl: str
    level: str  # discovery | catalog | full
    status: str  # healthy | degraded | skipped (development mode) | failed
    connector_address: str | None
    started_at: UtcDatetime
    finished_at: UtcDatetime
    steps: list[PartnerCheckStepOut]


class PartnerCheckPage(BaseModel):
    items: list[PartnerCheckOut]


class PartnerCheckRequest(BaseModel):
    level: str = Field(pattern="^(discovery|catalog|full)$")
    # A full check negotiates a contract and opens a transfer in both connectors.
    confirm_state_change: bool = False


class PartnerBatchCheckRequest(PartnerCheckRequest):
    # Only partners that were never checked or whose last check was not healthy.
    only_unhealthy: bool = True


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
    last_check: PartnerCheckOut | None = None


class PartnerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    connector_address: str | None = Field(default=None, max_length=512, pattern=r"^https?://\S+$")


class ConnectionCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str  # dtr | edc | central_idp | discovery | bpdm | bp_explorer
    name: str
    status: str  # ok | failed | skipped | not_configured
    detail: str


class LegalEntityOut(BaseModel):
    bpnl: str
    legal_name: str | None  # None: the BPNL is not in the golden record


class PartnerNameOut(BaseModel):
    bpnl: str
    status: str  # named | not_found | failed
    name: str | None = None
    message: str | None = None


class ConnectorDiscoveryOut(BaseModel):
    bpnl: str
    endpoints: list[str]  # DSP endpoints registered for the BPNL, in the service's order


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


# -- notifications -----------------------------------------------------------------------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_id: str
    type: NotificationType
    direction: str  # outbound | inbound
    partner_bpnl: str
    status: Status
    severity: Severity
    description: str | None
    affected_items: list[str]
    expected_response_by: str | None
    related_message_id: str | None
    forwarded_from_id: int | None
    api_version: str | None
    last_error: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    limit: int
    offset: int


class NotificationSummaryOut(BaseModel):
    inbound_open: int
    inbound_new: int  # received, not yet acknowledged
    outbound_open: int


class NotificationMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    direction: str
    operation: str  # receive | update
    message_id: str
    status: str | None
    information: str | None
    at: UtcDatetime


class AffectedItemOut(BaseModel):
    global_asset_id: str
    part: PartOut | None  # None if the part is not in the local cache


class NotificationDetailOut(NotificationOut):
    items: list[AffectedItemOut]
    messages: list[NotificationMessageOut]
    forwarded_from: NotificationOut | None
    forwarded_to: list[NotificationOut]
    # What this side can do next: "send" for drafts, else target statuses.
    actions: list[str]


class PlanRequest(BaseModel):
    type: NotificationType
    affected_items: list[str] = Field(min_length=1, max_length=1000)


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: NotificationType
    recipients: dict[str, list[str]]
    unmatched: list[str]


class ForwardPlanOut(PlanOut):
    source_id: int
    own_parts: list[str]


class NotificationCreate(BaseModel):
    type: NotificationType
    affected_items: list[str] = Field(min_length=1, max_length=1000)
    severity: Severity
    description: str = Field(min_length=1, max_length=1000)
    expected_response_by: datetime | None = None
    forwarded_from: int | None = None
    send: bool = False  # send the drafts right away


class StatusChange(BaseModel):
    status: Status
    information: str | None = Field(default=None, max_length=1000)
