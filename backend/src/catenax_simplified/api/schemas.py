"""Request and response models of the REST API (Pydantic). They are what ``/docs`` shows;
field comments say what a value means where the name alone does not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..notifications import NotificationType, Severity, Status


def _as_utc(value: datetime | None) -> datetime | None:
    # Timestamps are stored in UTC; SQLite returns them without a timezone.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class ClassificationOut(BaseModel):
    """A part classification, e.g. a customs or product code, with the standard it comes from."""

    standard: str
    id: str
    description: str | None = None


class PartOut(BaseModel):
    """A cached part (own or a partner's) as read from its SerialPart or Batch aspect, in any
    supported version. ``kind``: serial or batch; ``semantic_id``: the aspect model it was
    read from.
    """

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
    """A part in the parts list, with how many parents (where it is used) and children (what
    it contains) it has.
    """

    parents_count: int
    children_count: int


class PartPage(BaseModel):
    """One page of the parts list."""

    items: list[PartListItem]
    total: int
    limit: int
    offset: int


class TreeNodeOut(BaseModel):
    """A direct parent or child of a part. ``part`` is ``None`` for a partner twin not cached
    yet; ``declared_in`` says whether the link comes from the BoM, the usage aspect, or
    both.
    """

    model_config = ConfigDict(from_attributes=True)

    global_asset_id: str
    part: PartOut | None
    business_partner: str | None
    quantity: float | None
    unit: str | None
    is_only_potential_parent: bool
    declared_in: list[str]


class PartTreeOut(BaseModel):
    """A part with its direct parents and children: the as-built tree, one level each way."""

    model_config = ConfigDict(from_attributes=True)

    part: PartOut
    parents: list[TreeNodeOut]
    children: list[TreeNodeOut]


class StructurePartOut(BaseModel):
    """A part in a structure or a where-used path, named for a person. ``cached``: its part
    aspect is in the cache (own parts, and partner parts after a partner sync)."""

    global_asset_id: str
    cached: bool
    own: bool
    kind: str | None
    name: str | None
    serial: str | None
    part_number: str | None
    manufacturer_id: str | None
    manufacturer_name: str | None
    # The company's own number for it (customerPartId), as the maker published it.
    customer_part_number: str | None = None
    production_date: str | None = None
    country: str | None = None
    synced_at: UtcDatetime | None = None


class StructureLinkOut(BaseModel):
    """A parent contains a child; ``business_partner`` is the child's maker as the BoM says."""

    parent: str
    child: str
    business_partner: str | None
    quantity: float | None
    unit: str | None
    declared_in: list[str]


class PartStructureOut(BaseModel):
    """A part and everything under it: own parts at every level, other companies' parts as
    leaves. ``truncated``: the structure was cut at the size limit."""

    root: str
    parts: list[StructurePartOut]
    links: list[StructureLinkOut]
    truncated: bool


class WhereUsedOut(BaseModel):
    """Every path from a part up to a product nothing contains, the part first."""

    part: str
    parts: list[StructurePartOut]
    paths: list[list[str]]
    truncated: bool


class SyncIssueOut(BaseModel):
    """A problem with one twin or submodel during a sync; the sync carries on with the others."""

    model_config = ConfigDict(from_attributes=True)

    global_asset_id: str
    semantic_id: str | None
    message: str


class SyncReportOut(BaseModel):
    """One own-twin sync run. ``complete``: the listing (the whole registry, or the selected
    twins) was read without error, so own parts not in it were removed from the cache."""

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
    """Recent sync runs, newest first."""

    items: list[SyncReportOut]


class StatsOut(BaseModel):
    """Counts for the Parts page. Links between two own parts are internal and count as
    neither supplier nor customer links.
    """

    own_parts: int
    own_parts_by_kind: dict[str, int]
    own_parts_by_semantic_id: dict[str, int]
    supplier_links: int
    suppliers: int
    customer_links: int
    customers: int


class PartRefOut(BaseModel):
    """A part named for a person: Catena-X ID, name and the identifier of the unit or lot
    (``None`` when it is not cached).
    """

    global_asset_id: str
    name: str | None
    serial: str | None


class DataFindingOut(BaseModel):
    """A contradiction in the own bills of material: a part declared in two places (see
    ``traceability.data_checks``).
    """

    kind: Literal["two_levels", "two_assemblies"]
    part: PartRefOut
    business_partner: str | None
    partner_name: str | None
    # Own parts whose BoM declares the part. For "two_levels": the assembly, then its
    # sub-assembly.
    parents: list[PartRefOut]


class DataChecksOut(BaseModel):
    """All data findings in the cache (or those about one part)."""

    total: int
    findings: list[DataFindingOut]


class NotificationAssetsOut(BaseModel):
    """Whether the notification assets are published in the own EDC, and their IDs."""

    # not_configured | publishing | published | failed
    state: str
    message: str | None = None
    at: UtcDatetime | None = None
    asset_ids: list[str] = []


class HealthOut(BaseModel):
    """What the app is connected to and can do; the UI shows or hides actions from it."""

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
    sync_subset: int = 0  # own twins listed in CXS_SYNC_TWIN_IDS; 0: the whole registry
    supported_aspects: list[str]


class PartnerCheckStepOut(BaseModel):
    """One step of a connector check (discovery, catalog offers, negotiation, registry
    answer).
    """

    key: str
    name: str
    status: str  # ok | warn | failed | skipped
    detail: str


class PartnerCheckOut(BaseModel):
    """A connector check of a partner and its steps."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    bpnl: str
    level: str  # discovery | catalog | full
    # The connector: from discovery, registry offer and EDR access only.
    status: str  # healthy | degraded | skipped (development mode) | failed
    # The quality notification offers, a separate use case: ready | incomplete | unchecked.
    notifications: str = "unchecked"
    connector_address: str | None
    started_at: UtcDatetime
    finished_at: UtcDatetime
    steps: list[PartnerCheckStepOut]

    @model_validator(mode="after")
    def _judge(self) -> PartnerCheckOut:
        # Recomputed from the steps, so checks stored before the split read the same way.
        from ..traceability.partner_health import notifications_status, overall_status

        self.status = overall_status(self.steps)
        self.notifications = notifications_status(self.steps)
        return self


class PartnerCheckPage(BaseModel):
    """Recent connector checks, newest first."""

    items: list[PartnerCheckOut]


class PartnerCheckRequest(BaseModel):
    """How far to check a partner's connector: ``discovery``, ``catalog`` or ``full``."""

    level: str = Field(pattern="^(discovery|catalog|full)$")
    # A full check negotiates a contract and opens a transfer in both connectors.
    confirm_state_change: bool = False


class PartnerBatchCheckRequest(PartnerCheckRequest):
    """A connector check of every partner."""

    # Only partners that were never checked or whose last check was not healthy.
    only_unhealthy: bool = True


class PartnerOut(BaseModel):
    """A direct partner: found in the own BoM (supplier) or usage (customer) data, or set by
    hand.
    """

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
    """A partner's name or DSP address to set; fields left out stay as they are."""

    name: str | None = Field(default=None, max_length=255)
    connector_address: str | None = Field(default=None, max_length=512, pattern=r"^https?://\S+$")


class ConnectionCheckOut(BaseModel):
    """A read-only test of one configured connection (DTR, EDC, central IdP, discovery, BPDM)."""

    model_config = ConfigDict(from_attributes=True)

    key: str  # dtr | edc | central_idp | discovery | bpdm | bp_explorer
    name: str
    status: str  # ok | failed | skipped | not_configured
    detail: str


class LegalEntityOut(BaseModel):
    """A BPNL's legal name in the BPDM golden record."""

    bpnl: str
    legal_name: str | None  # None: the BPNL is not in the golden record


class PartnerNameOut(BaseModel):
    """The outcome of looking up one partner's name."""

    bpnl: str
    status: str  # named | not_found | failed
    name: str | None = None
    message: str | None = None


class ConnectorDiscoveryOut(BaseModel):
    """DSP endpoints the dataspace's discovery services know for a BPNL."""

    bpnl: str
    endpoints: list[str]  # DSP endpoints registered for the BPNL, in the service's order


class PartnerSyncResultOut(BaseModel):
    """What a partner sync read for one partner: counterpart twins found and missing, cached
    parts removed, problems.
    """

    model_config = ConfigDict(from_attributes=True)

    bpnl: str
    roles: list[str]
    linked_twins: int
    twins_found: int
    twins_missing: int
    removed_parts: int
    parts_cached: int
    duration_seconds: float
    status: str
    issues: list[str]


class PartnerSyncReportOut(BaseModel):
    """One partner sync run, per partner."""

    model_config = ConfigDict(from_attributes=True)

    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    partners: list[PartnerSyncResultOut]
    not_linked: list[str] = []


class PartnerSyncProgressPartnerOut(BaseModel):
    """One partner in a running (or the last) partner sync. ``state`` is pending, running, or
    the partner's result status once done; ``twins_failed`` counts failed lookups and twins whose
    submodel could not be read; ``current_twin``: one being read now (several are, at once);
    ``message``: the partner's first issue, once done."""

    bpnl: str
    state: str
    linked_twins: int
    twins_done: int
    twins_cached: int
    twins_missing: int
    twins_failed: int
    removed_parts: int
    current_twin: str | None
    duration_seconds: float | None
    message: str | None


class PartnerSyncProgressOut(BaseModel):
    """Where the running partner sync is, or how the last one ended (``running`` false), with
    totals over its partners. ``report``: the run's report once it is done; ``error``: why the
    run broke off, if it did."""

    run_id: int
    running: bool
    selection: bool
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    elapsed_seconds: float
    error: str | None
    partners_total: int
    partners_running: int
    partners_done: int
    linked_twins: int
    twins_done: int
    twins_cached: int
    twins_missing: int
    twins_failed: int
    removed_parts: int
    partners: list[PartnerSyncProgressPartnerOut]
    report: PartnerSyncReportOut | None


class PartnerSyncRequest(BaseModel):
    """A partner sync limited to some counterpart twins (Catena-X IDs), e.g. the supplier parts
    under one assembly."""

    twins: list[str] = Field(min_length=1, max_length=2000)


# -- notifications -----------------------------------------------------------------------------


class NotificationOut(BaseModel):
    """A quality alert or investigation, sent or received. ``notification_id`` is shared by
    both sides; ``api_version`` is the Notification API version used with the partner.
    """

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
    """One page of the inbox or outbox."""

    items: list[NotificationOut]
    total: int
    limit: int
    offset: int


class NotificationSummaryOut(BaseModel):
    """Counts for the Notifications page."""

    inbound_open: int
    inbound_new: int  # received, not yet acknowledged
    outbound_open: int


class NotificationMessageOut(BaseModel):
    """One message of a notification's log (a send or an update, either way)."""

    model_config = ConfigDict(from_attributes=True)

    direction: str
    operation: str  # receive | update
    message_id: str
    status: str | None
    information: str | None
    at: UtcDatetime


class AffectedItemOut(BaseModel):
    """An affected part of a notification, with the local part if it is cached."""

    global_asset_id: str
    part: PartOut | None  # None if the part is not in the local cache


class NotificationDetailOut(NotificationOut):
    """A notification with its parts, message log, the hops before and after it, and the
    actions allowed next.
    """

    items: list[AffectedItemOut]
    messages: list[NotificationMessageOut]
    forwarded_from: NotificationOut | None
    forwarded_to: list[NotificationOut]
    # What this side can do next: "send" for drafts, else target statuses.
    actions: list[str]


class PlanRequest(BaseModel):
    """Parts to notify about: own parts for an alert, supplier parts for an investigation."""

    type: NotificationType
    affected_items: list[str] = Field(min_length=1, max_length=1000)


class PlanOut(BaseModel):
    """Recipients of a planned notification: partner BPNL → the affected parts that concern
    it; ``unmatched``: parts with no known partner.
    """

    model_config = ConfigDict(from_attributes=True)

    type: NotificationType
    recipients: dict[str, list[str]]
    unmatched: list[str]


class ForwardPlanOut(PlanOut):
    """The next hop of a received notification: the plan, the notification it starts from and
    the own parts involved.
    """

    source_id: int
    own_parts: list[str]


class NotificationCreate(BaseModel):
    """A new alert or investigation. One notification is created per recipient of the plan."""

    type: NotificationType
    affected_items: list[str] = Field(min_length=1, max_length=1000)
    severity: Severity
    description: str = Field(min_length=1, max_length=1000)
    expected_response_by: datetime | None = None
    forwarded_from: int | None = None
    send: bool = False  # send the drafts right away


class StatusChange(BaseModel):
    """A status change with an optional message for the partner (e.g. why it is declined)."""

    status: Status
    information: str | None = Field(default=None, max_length=1000)
