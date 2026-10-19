"""The FastAPI application: the REST API for the web UI and the runtime that holds the adapters.

``create_app`` builds the app from the settings. ``Runtime`` owns everything built from the
effective settings (the deployment's, completed by what an admin entered on the Setup page) and
rebuilds it in place when they change. The long-running jobs (own sync, partner sync, partner
checks) run one at a time each through an ``ExclusiveRunner``. The Notification API endpoints that
partners call live in ``api/notifications.py``, the admin login and the settings editor in
``api/admin.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path as FsPath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from ..admin import ConfigStore, SecretBox, effective_settings
from ..aspects.registry import SUPPORTED
from ..config import Settings
from ..dataspace import DataspaceError, SubmodelReader, TwinRegistry
from ..dataspace.business_partners import BusinessPartnerDirectory
from ..dataspace.connections import ConnectionTester
from ..dataspace.discovery import ConnectorDiscovery
from ..dataspace.health import PartnerHealthChecker
from ..dataspace.notification_assets import NotificationAssetPublisher
from ..dataspace.notifications import NotificationSender
from ..dataspace.partners import PartnerDataClient
from ..notifications import NotificationService
from ..storage import (
    PartnerCheckRepository,
    PartnerRepository,
    PartRepository,
    SyncRunRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from ..traceability import (
    OwnTwinSync,
    PartnerHealth,
    PartnerSync,
    bom_findings,
    parse_twin_ids,
    part_structure,
    part_tree,
    where_used,
)
from ..wiring import (
    build_admin_auth,
    build_asset_publisher,
    build_connection_tester,
    build_connector_discovery,
    build_edc_consumer,
    build_health_checker,
    build_notification_sender,
    build_partner_client,
    build_partner_directory,
    build_submodel_reader,
    build_twin_registry,
    central_auth,
    dtr_auth,
)
from . import admin, notifications, policies
from .schemas import (
    ConnectionCheckOut,
    ConnectorDiscoveryOut,
    DataChecksOut,
    DataFindingOut,
    HealthOut,
    LegalEntityOut,
    NotificationAssetsOut,
    PartListItem,
    PartnerBatchCheckRequest,
    PartnerCheckOut,
    PartnerCheckPage,
    PartnerCheckRequest,
    PartnerNameOut,
    PartnerOut,
    PartnerSyncReportOut,
    PartnerSyncRequest,
    PartnerUpdate,
    PartOut,
    PartPage,
    PartRefOut,
    PartStructureOut,
    PartTreeOut,
    StatsOut,
    StructureLinkOut,
    StructurePartOut,
    SyncReportOut,
    SyncRunPage,
    WhereUsedOut,
)

log = logging.getLogger(__name__)


class ExclusiveRunner:
    """Runs a job at most once at a time; ``job`` is ``None`` when it is not configured."""

    def __init__(self, job: Callable[..., Any] | None):
        self.job = job
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        """Whether there is a job to run (its adapters are configured)."""
        return self.job is not None

    def run(self, *args: Any, **kwargs: Any) -> Any | None:
        """Run the job; returns ``None`` if it is already running."""
        if self.job is None:
            raise RuntimeError("not configured")
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self.job(*args, **kwargs)
        finally:
            self._lock.release()


def _session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(_session)]
Bpnl = Annotated[str, Path(pattern=r"^BPNL[0-9A-Za-z]{12}$")]
# Changing partners needs an admin session once the admin login is set up.
AdminIfEnabled = Annotated[str | None, Depends(admin.admin_if_enabled)]

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    """What the app is connected to and can do: the own BPNL, which adapters are configured (DTR,
    EDC, discovery, names), how they authenticate, the state of the notification assets and the
    supported aspect models. The UI reads it on every page to show or hide actions.
    """
    settings: Settings = request.app.state.settings
    return HealthOut(
        status="ok",
        own_bpnl=settings.own_bpnl,
        dtr_configured=request.app.state.sync_runner.configured,
        edc_configured=request.app.state.partner_runner.configured,
        can_send_notifications=request.app.state.notifications.can_send,
        dev_direct=settings.dev_direct,
        can_check_partners=request.app.state.health_runner.configured,
        can_discover_connectors=request.app.state.discovery is not None,
        can_look_up_names=request.app.state.directory is not None,
        names_source=getattr(request.app.state.directory, "source", None),
        dtr_auth="oauth" if dtr_auth(settings) else "none",
        edc_auth=[
            name
            for name, used in (
                ("oauth", settings.edc_oauth_token_url),
                ("api_key", settings.edc_api_key),
            )
            if used
        ],
        central_idp_url=settings.central_idp_url,
        notification_assets=request.app.state.asset_publishing.status,
        dtr_url=settings.dtr_base_url,
        sync_interval_seconds=settings.sync_interval_seconds,
        sync_subset=len(parse_twin_ids(settings.sync_twin_ids)),
        supported_aspects=sorted(SUPPORTED),
    )


@router.post("/setup/connection-tests", response_model=list[ConnectionCheckOut])
async def test_connections(request: Request) -> list[ConnectionCheckOut]:
    """Read-only calls to the own DTR and EDC and to the core services, with the configured
    credentials."""
    tester: ConnectionTester = request.app.state.connection_tester
    checks = await run_in_threadpool(tester.run)
    return [ConnectionCheckOut.model_validate(c) for c in checks]


@router.get("/stats", response_model=StatsOut)
def stats(session: SessionDep, request: Request) -> StatsOut:
    """Counts for the Parts page: own parts by kind and aspect model, and the links to suppliers
    and customers. Links between two own parts are internal and count for neither.
    """
    return StatsOut(**PartRepository(session).stats(request.app.state.settings.own_bpnl))


# The identifier that names one unit or lot; manufacturerId only says who made it.
INSTANCE_KEYS = ("partInstanceId", "van", "batchId")


def instance_id(local_identifiers: dict[str, str]) -> str | None:
    """The identifier that names one unit or lot in a part's local identifiers (``partInstanceId``,
    ``van``, ``batchId``), else any other than ``manufacturerId``.
    """
    for key in INSTANCE_KEYS:
        if local_identifiers.get(key):
            return local_identifiers[key]
    return next((v for k, v in local_identifiers.items() if k != "manufacturerId"), None)


@router.get("/data-checks", response_model=DataChecksOut)
def data_checks(
    session: SessionDep,
    part: Annotated[str | None, Query(description="Only findings about this part")] = None,
) -> DataChecksOut:
    """Contradictions in the own bills of material, found in the local cache: a part declared
    in an assembly and again in one of its sub-assemblies, or in two unrelated own parts."""
    repository = PartRepository(session)
    findings = bom_findings(repository)
    if part:
        findings = [f for f in findings if part == f.global_asset_id or part in f.parents]
    ids = {gid for f in findings for gid in (f.global_asset_id, *f.parents)}
    parts = repository.get_parts(ids)
    names = {p.bpnl: p.name for p in PartnerRepository(session).all()}

    def ref(gid: str) -> PartRefOut:
        row = parts.get(gid)
        serial = instance_id(row.local_identifiers) if row else None
        return PartRefOut(
            global_asset_id=gid, name=row.name_at_manufacturer if row else None, serial=serial
        )

    return DataChecksOut(
        total=len(findings),
        findings=[
            DataFindingOut(
                kind=f.kind,
                part=ref(f.global_asset_id),
                business_partner=f.business_partner,
                partner_name=names.get(f.business_partner) if f.business_partner else None,
                parents=[ref(p) for p in f.parents],
            )
            for f in findings
        ],
    )


@router.get("/parts", response_model=PartPage)
def list_parts(
    session: SessionDep,
    search: str | None = None,
    kind: Annotated[str | None, Query(pattern="^(serial|batch)$")] = None,
    aspect_major: Annotated[int | None, Query(ge=1, le=99)] = None,
    own_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PartPage:
    """Cached parts, own and partner (or own only), by name, with how many parents and children
    each has. ``search`` matches the Catena-X ID, part numbers and names; ``kind`` filters
    serialized parts or batches, ``aspect_major`` the aspect model's major version (3 or 4)."""
    repository = PartRepository(session)
    rows, total = repository.list_parts(
        search=search,
        kind=kind,
        aspect_major=aspect_major,
        own_only=own_only,
        limit=limit,
        offset=offset,
    )
    counts = repository.relation_counts([r.global_asset_id for r in rows])
    items = [
        PartListItem(
            **PartOut.model_validate(r).model_dump(),
            parents_count=counts[r.global_asset_id][0],
            children_count=counts[r.global_asset_id][1],
        )
        for r in rows
    ]
    return PartPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/parts/{global_asset_id}", response_model=PartOut)
def get_part(global_asset_id: str, session: SessionDep) -> PartOut:
    """One cached part by its Catena-X ID."""
    row = PartRepository(session).get_part(global_asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="part not found")
    return PartOut.model_validate(row)


@router.get("/parts/{global_asset_id}/tree", response_model=PartTreeOut)
def get_part_tree(global_asset_id: str, session: SessionDep) -> PartTreeOut:
    """A part with its direct parents (where it is used, from usage aspects) and children (what it
    is built from, from BoM aspects), one level each way. Partner twins not cached yet appear
    without their part data.
    """
    tree = part_tree(PartRepository(session), global_asset_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="part not found")
    return PartTreeOut.model_validate(tree)


def _structure_parts(
    session: Session, rows: dict, partners: dict[str, str | None], own_bpnl: str
) -> list[StructurePartOut]:
    names = {p.bpnl: p.name for p in PartnerRepository(session).all()}
    out = []
    for gid, row in rows.items():
        maker = (row.manufacturer_id if row else None) or partners.get(gid)
        out.append(
            StructurePartOut(
                global_asset_id=gid,
                cached=row is not None,
                own=(row.is_own if row else False) or maker == own_bpnl,
                kind=row.kind if row else None,
                name=row.name_at_manufacturer if row else None,
                serial=instance_id(row.local_identifiers) if row else None,
                part_number=row.manufacturer_part_id if row else None,
                manufacturer_id=maker,
                manufacturer_name=names.get(maker) if maker else None,
                customer_part_number=row.customer_part_id if row else None,
                production_date=row.production_date if row else None,
                country=row.country if row else None,
                synced_at=row.synced_at if row else None,
            )
        )
    return out


@router.get("/parts/{global_asset_id}/structure", response_model=PartStructureOut)
def get_part_structure(
    global_asset_id: str, session: SessionDep, request: Request
) -> PartStructureOut:
    """Everything under a part: own parts at every level (all known locally), other companies'
    parts as leaves, with quantities. A part declared in two places is linked twice."""
    own_bpnl = request.app.state.settings.own_bpnl
    structure = part_structure(PartRepository(session), global_asset_id, own_bpnl)
    if structure is None:
        raise HTTPException(status_code=404, detail="part not found")
    makers = {link.child: link.business_partner for link in structure.links}
    return PartStructureOut(
        root=structure.root,
        parts=_structure_parts(session, structure.parts, makers, own_bpnl),
        links=[
            StructureLinkOut.model_validate(link, from_attributes=True) for link in structure.links
        ],
        truncated=structure.truncated,
    )


@router.get("/parts/{global_asset_id}/where-used", response_model=WhereUsedOut)
def get_where_used(global_asset_id: str, session: SessionDep, request: Request) -> WhereUsedOut:
    """Every path from a part up to the products that contain it, through own BoMs (and a
    customer's part where the usage names one): the parts a quality alert concerns."""
    used = where_used(PartRepository(session), global_asset_id)
    return WhereUsedOut(
        part=used.part,
        parts=_structure_parts(session, used.parts, {}, request.app.state.settings.own_bpnl),
        paths=used.paths,
        truncated=used.truncated,
    )


@router.post("/sync", response_model=SyncReportOut)
async def trigger_sync(request: Request) -> SyncReportOut:
    """Reads the own twins from the DTR into the cache now, and waits for the result. 409 while
    another sync runs; 503 without a DTR.
    """
    runner: ExclusiveRunner = request.app.state.sync_runner
    if not runner.configured:
        raise HTTPException(status_code=503, detail="no Digital Twin Registry configured")
    report = await run_in_threadpool(runner.run)
    if report is None:
        raise HTTPException(status_code=409, detail="a sync is already running")
    return SyncReportOut.model_validate(report)


@router.get("/sync/last", response_model=SyncReportOut)
def last_sync(session: SessionDep) -> SyncReportOut:
    """The most recent own-twin sync run."""
    runs = SyncRunRepository(session).recent(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="no sync has run yet")
    return SyncReportOut.model_validate(runs[0])


@router.get("/sync/runs", response_model=SyncRunPage)
def sync_runs(session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 20) -> SyncRunPage:
    """Recent own-twin sync runs, newest first, with their issues."""
    runs = SyncRunRepository(session).recent(limit=limit)
    return SyncRunPage(items=[SyncReportOut.model_validate(r) for r in runs])


@router.get("/partners", response_model=list[PartnerOut])
def list_partners(session: SessionDep, request: Request) -> list[PartnerOut]:
    """Direct partners: every BPNL named in the own parts' BoM (suppliers) or usage (customers),
    plus partners set by hand, never the own BPNL. Each with its roles, linked twins, cached
    parts, connector address and where it comes from, last partner sync and last connector
    check.
    """
    settings: Settings = request.app.state.settings
    counterparts = PartRepository(session).partner_counterparts()
    rows = {row.bpnl: row for row in PartnerRepository(session).all()}
    cached = PartRepository(session).partner_part_counts()
    checks = PartnerCheckRepository(session).latest_by_partner()
    partners = []
    for bpnl in sorted((set(counterparts) | set(rows)) - {settings.own_bpnl}):
        roles = counterparts.get(bpnl, {"supplier": set(), "customer": set()})
        row = rows.get(bpnl)
        stored = row.connector_address if row else None
        configured = settings.partner_connectors.get(bpnl)
        partners.append(
            PartnerOut(
                bpnl=bpnl,
                name=row.name if row else None,
                roles=[r for r in ("supplier", "customer") if roles[r]],
                linked_twins=len(roles["supplier"] | roles["customer"]),
                cached_parts=cached.get(bpnl, 0),
                connector_address=stored or configured,
                connector_source="api" if stored else ("settings" if configured else None),
                last_sync_at=row.last_sync_at if row else None,
                last_status=row.last_status if row else None,
                last_message=row.last_message if row else None,
                twins_found=row.twins_found if row else 0,
                twins_missing=row.twins_missing if row else 0,
                last_check=PartnerCheckOut.model_validate(checks[bpnl]) if bpnl in checks else None,
            )
        )
    return partners


@router.put("/partners/{bpnl}", response_model=PartnerOut)
def update_partner(
    bpnl: Bpnl, update: PartnerUpdate, session: SessionDep, request: Request, _: AdminIfEnabled
) -> PartnerOut:
    """Sets a partner's name or DSP connector address (fields left out stay as they are). Needs an
    admin session once the admin login is set up.
    """
    if bpnl == request.app.state.settings.own_bpnl:
        raise HTTPException(status_code=422, detail="that is your own BPNL")
    row = PartnerRepository(session).get_or_create(bpnl)
    fields = update.model_dump(exclude_unset=True)
    if "name" in fields:
        row.name = fields["name"]
    if "connector_address" in fields:
        row.connector_address = fields["connector_address"]
    session.commit()
    return next(p for p in list_partners(session, request) if p.bpnl == bpnl)


@router.delete("/partners/{bpnl}", status_code=204)
def remove_partner(bpnl: Bpnl, session: SessionDep, _: AdminIfEnabled) -> Response:
    """Forget what was set for a partner (name, address, last sync). A partner found in your
    own twins stays listed; one added by hand disappears. Its check history is kept."""
    repository = PartnerRepository(session)
    row = repository.get(bpnl)
    if row is None:
        raise HTTPException(status_code=404, detail="partner not found")
    repository.delete(row)
    session.commit()
    return Response(status_code=204)


def _directory(request: Request) -> BusinessPartnerDirectory:
    directory: BusinessPartnerDirectory | None = request.app.state.directory
    if directory is None:
        raise HTTPException(
            status_code=503,
            detail="no source of partner names configured "
            "(CXS_BPDM_POOL_URL, or CXS_BP_EXPLORER_ADDRESS with an EDC)",
        )
    return directory


@router.get("/partners/{bpnl}/legal-entity", response_model=LegalEntityOut)
async def legal_entity(bpnl: Bpnl, request: Request) -> LegalEntityOut:
    """A BPNL's legal name from the BPDM Pool or the Business Partner Explorer. Nothing is
    stored."""
    directory = _directory(request)
    try:
        name = await run_in_threadpool(directory.legal_name, bpnl)
    except DataspaceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return LegalEntityOut(bpnl=bpnl, legal_name=name)


@router.post("/partners/names", response_model=list[PartnerNameOut])
async def fill_partner_names(request: Request, _: AdminIfEnabled) -> list[PartnerNameOut]:
    """Name every partner without a name after its legal name in the BPDM Pool or the Business
    Partner Explorer. Names set by hand are kept."""
    directory = _directory(request)
    with request.app.state.session_factory() as session:
        unnamed = [p.bpnl for p in list_partners(session, request) if not p.name]
    results = []
    for bpnl in unnamed:
        try:
            name = await run_in_threadpool(directory.legal_name, bpnl)
        except DataspaceError as exc:
            results.append(PartnerNameOut(bpnl=bpnl, status="failed", message=str(exc)))
            continue
        if name is None:
            results.append(PartnerNameOut(bpnl=bpnl, status="not_found"))
            continue
        with request.app.state.session_factory() as session:
            row = PartnerRepository(session).get_or_create(bpnl)
            row.name = name[:255]
            session.commit()
        results.append(PartnerNameOut(bpnl=bpnl, status="named", name=name))
    return results


@router.get("/partners/{bpnl}/discovery", response_model=ConnectorDiscoveryOut)
async def discover_connectors(bpnl: Bpnl, request: Request) -> ConnectorDiscoveryOut:
    """Ask the dataspace's discovery services for the DSP endpoints registered for a BPNL. Nothing
    is stored: pick one and set it with PUT /api/partners/{bpnl}."""
    discovery: ConnectorDiscovery | None = request.app.state.discovery
    if discovery is None:
        raise HTTPException(
            status_code=503,
            detail="no discovery configured (CXS_EDC_DISCOVERY_URL or CXS_DISCOVERY_FINDER_URL)",
        )
    try:
        endpoints = await run_in_threadpool(discovery.find, bpnl)
    except DataspaceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ConnectorDiscoveryOut(bpnl=bpnl, endpoints=endpoints)


@router.post("/partners/sync", response_model=PartnerSyncReportOut)
async def sync_partners(
    request: Request, bpnl: str | None = None, body: PartnerSyncRequest | None = None
) -> PartnerSyncReportOut:
    """Reads the direct partners' counterpart twins through the EDC into the cache (all partners,
    or only ``bpnl``). With a body, reads only the ``twins`` listed, leaving the rest of the
    cache and the partners' last-sync summary as they are; IDs no own part is linked to come back
    in ``not_linked``. Negotiates with the partners' connectors. 409 while another partner sync
    runs; 503 without an EDC.
    """
    runner: ExclusiveRunner = request.app.state.partner_runner
    if not runner.configured:
        raise HTTPException(status_code=503, detail="no EDC configured")
    twins = body.twins if body else None
    report = await run_in_threadpool(runner.run, bpnl, twins)
    if report is None:
        raise HTTPException(status_code=409, detail="a partner sync is already running")
    return PartnerSyncReportOut.model_validate(report)


def _health_runner(request: Request, body: PartnerCheckRequest) -> ExclusiveRunner:
    runner: ExclusiveRunner = request.app.state.health_runner
    if not runner.configured:
        raise HTTPException(status_code=503, detail="no EDC configured")
    if body.level == "full" and not body.confirm_state_change:
        raise HTTPException(
            status_code=409,
            detail="a full check negotiates a contract and opens a transfer in both connectors: "
            "set confirm_state_change",
        )
    return runner


@router.get("/partners/checks", response_model=PartnerCheckPage)
def partner_checks(
    session: SessionDep,
    bpnl: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PartnerCheckPage:
    """Recent connector checks, newest first, optionally of one partner."""
    rows = PartnerCheckRepository(session).recent(bpnl=bpnl, limit=limit)
    return PartnerCheckPage(items=[PartnerCheckOut.model_validate(r) for r in rows])


@router.post("/partners/checks", response_model=PartnerCheckPage)
async def check_partners(request: Request, body: PartnerBatchCheckRequest) -> PartnerCheckPage:
    """Checks every partner's connector at the requested level (or only those not healthy). A
    ``full`` check negotiates a contract and opens a transfer in both connectors, so it needs
    ``confirm_state_change``.
    """
    runner = _health_runner(request, body)
    rows = await run_in_threadpool(runner.run, body.level, only_unhealthy=body.only_unhealthy)
    if rows is None:
        raise HTTPException(status_code=409, detail="a partner check is already running")
    return PartnerCheckPage(items=[PartnerCheckOut.model_validate(r) for r in rows])


@router.post("/partners/{bpnl}/checks", response_model=PartnerCheckOut)
async def check_partner(bpnl: str, request: Request, body: PartnerCheckRequest) -> PartnerCheckOut:
    """Checks one partner's connector at the requested level: ``discovery``, ``catalog`` or
    ``full`` (see ``check_partners``)."""
    runner = _health_runner(request, body)
    rows = await run_in_threadpool(runner.run, body.level, bpnl)
    if rows is None:
        raise HTTPException(status_code=409, detail="a partner check is already running")
    if not rows:
        raise HTTPException(status_code=404, detail="partner not found")
    return PartnerCheckOut.model_validate(rows[0])


class AssetPublishing:
    """Publishes the notification assets in our EDC and remembers how it went."""

    def __init__(self, publisher: NotificationAssetPublisher | None):
        self.publisher = publisher
        self.status = NotificationAssetsOut(
            state="not_configured" if publisher is None else "publishing"
        )
        self._lock = threading.Lock()

    def run(self) -> NotificationAssetsOut:
        """Publishes the notification assets now and records the outcome; never raises."""
        if self.publisher is None:
            return self.status
        with self._lock:
            self.status = NotificationAssetsOut(state="publishing")
            try:
                ids = self.publisher.publish()
                self.status = NotificationAssetsOut(
                    state="published", at=datetime.now(UTC), asset_ids=ids
                )
            except Exception as exc:
                log.exception("publishing the notification assets failed")
                self.status = NotificationAssetsOut(
                    state="failed", message=str(exc)[:500], at=datetime.now(UTC)
                )
        return self.status


@router.post("/notifications/assets", response_model=NotificationAssetsOut)
async def publish_assets(request: Request) -> NotificationAssetsOut:
    """Publishes, again, the eight notification assets (receive and update, alert and
    investigation, Notification API 1.2.1 and 2.0.0) in the own EDC. They are also published at
    startup; this retries after a failure or a change.
    """
    publishing: AssetPublishing = request.app.state.asset_publishing
    if publishing.publisher is None:
        raise HTTPException(
            status_code=503,
            detail="needs an EDC and CXS_NOTIFICATION_BASE_URL",
        )
    return await run_in_threadpool(publishing.run)


async def _periodic_sync(runners: list[ExclusiveRunner], interval: int) -> None:
    while True:
        for runner in runners:
            try:
                await run_in_threadpool(runner.run)
            except Exception:  # keep the loop alive; the next run may succeed
                log.exception("periodic sync failed")
        await asyncio.sleep(interval)


class Runtime:
    """Everything built from the effective settings (the deployment's, completed by what an admin
    entered in the UI). An admin's change rebuilds it in place: the runners keep their locks, so
    a sync that is running finishes and the next one uses the new adapters."""

    def __init__(
        self,
        app: FastAPI,
        base: Settings,
        session_factory: sessionmaker[Session],
        store: ConfigStore,
        overrides: dict[str, Any],
    ):
        self.app = app
        self.base = base
        self.session_factory = session_factory
        self.store = store
        self.overrides = overrides
        self.sync_runner = ExclusiveRunner(None)
        self.partner_runner = ExclusiveRunner(None)
        # One check at a time, so a batch does not flood our own connector.
        self.health_runner = ExclusiveRunner(None)
        self._tasks: list[asyncio.Task] = []
        # Two admins saving at once must not leave the first rebuild's background tasks running.
        self._reload_lock = asyncio.Lock()

    def settings(self) -> Settings:
        """The effective settings: the deployment's, completed by those stored from the Setup
        page.
        """
        values, unreadable = self.store.values()
        if unreadable:
            log.warning(
                "stored secrets %s cannot be decrypted with the current CXS_SECRET_KEY",
                ", ".join(sorted(unreadable)),
            )
        return effective_settings(self.base, values)

    def build(self) -> None:
        """Builds every adapter and job from the effective settings and puts them on
        ``app.state``. Adapters given as ``overrides`` (tests, demos) are used as they are.
        """
        settings = self.settings()
        o = self.overrides
        session_factory = self.session_factory
        registry = o.get("registry") or build_twin_registry(settings)
        injected = ("partner_client", "notification_sender", "health_checker")
        needs_consumer = not all(o.get(k) for k in injected) or (
            settings.bp_explorer_address and not o.get("directory")
        )
        consumer = build_edc_consumer(settings) if needs_consumer else None
        partner_client = o.get("partner_client") or build_partner_client(settings, consumer)
        # Own submodels behind a data plane that wants an EDR are read through the own EDC.
        reader = o.get("reader") or build_submodel_reader(settings, partner_client)
        sync = (
            OwnTwinSync(
                registry,
                reader,
                session_factory,
                settings.own_bpnl,
                twin_ids=parse_twin_ids(settings.sync_twin_ids),
            )
            if registry is not None
            else None
        )
        sender = o.get("notification_sender") or build_notification_sender(settings, consumer)
        partner_sync = (
            PartnerSync(
                partner_client,
                session_factory,
                settings.own_bpnl,
                configured_connectors=settings.partner_connectors,
            )
            if partner_client is not None
            else None
        )
        health_checker = o.get("health_checker") or build_health_checker(settings, consumer)
        partner_health = (
            PartnerHealth(
                health_checker,
                session_factory,
                settings.own_bpnl,
                configured_connectors=settings.partner_connectors,
            )
            if health_checker is not None
            else None
        )
        central = central_auth(settings)

        state = self.app.state
        state.settings = settings
        # The own EDC's consumer side, for one-off catalog reads (api/policies.py); None without.
        state.consumer = consumer if consumer is not None else build_edc_consumer(settings)
        self.sync_runner.job = sync.run if sync is not None else None
        self.partner_runner.job = partner_sync.run if partner_sync is not None else None
        self.health_runner.job = partner_health.run if partner_health is not None else None
        state.notifications = NotificationService(
            session_factory,
            settings.own_bpnl,
            sender,
            configured_connectors=settings.partner_connectors,
        )
        state.asset_publishing = AssetPublishing(
            o.get("asset_publisher") or build_asset_publisher(settings)
        )
        state.discovery = o.get("discovery") or build_connector_discovery(settings, central)
        state.directory = o.get("directory") or build_partner_directory(settings, central, consumer)
        state.connection_tester = o.get("connection_tester") or build_connection_tester(
            settings, consumer
        )

    def start(self) -> None:
        """Background work for the current settings; call from the event loop."""
        settings: Settings = self.app.state.settings
        publishing: AssetPublishing = self.app.state.asset_publishing
        if publishing.publisher is not None:
            # In the background: the app serves while the EDC is still unreachable.
            self._tasks.append(asyncio.create_task(run_in_threadpool(publishing.run)))
        periodic = [r for r in (self.sync_runner, self.partner_runner) if r.configured]
        if periodic and settings.sync_interval_seconds > 0:
            self._tasks.append(
                asyncio.create_task(_periodic_sync(periodic, settings.sync_interval_seconds))
            )

    async def stop(self) -> None:
        """Cancels the background tasks (periodic sync, asset publishing)."""
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def reload(self) -> None:
        """Rebuilds after a settings change, one change at a time; running jobs finish with
        the old adapters.
        """
        async with self._reload_lock:
            await self.stop()
            await run_in_threadpool(self.build)
            self.start()


def create_app(
    settings: Settings,
    *,
    registry: TwinRegistry | None = None,
    reader: SubmodelReader | None = None,
    partner_client: PartnerDataClient | None = None,
    notification_sender: NotificationSender | None = None,
    asset_publisher: NotificationAssetPublisher | None = None,
    health_checker: PartnerHealthChecker | None = None,
    discovery: ConnectorDiscovery | None = None,
    directory: BusinessPartnerDirectory | None = None,
    connection_tester: ConnectionTester | None = None,
) -> FastAPI:
    """Create the application. The keyword arguments override the configured adapters (tests)."""
    engine = make_engine(settings.database_url)
    init_schema(engine)
    session_factory = make_session_factory(engine)
    if settings.dev_direct:
        log.warning("CXS_DEV_DIRECT is on: partners are reached without EDCs (development only)")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime.start()
        yield
        await runtime.stop()
        engine.dispose()

    app = FastAPI(title="catena-x-simplified", version="0.1.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.admin = build_admin_auth(settings)
    store = ConfigStore(
        session_factory, SecretBox(settings.secret_key) if settings.secret_key else None
    )
    overrides = {
        "registry": registry,
        "reader": reader,
        "partner_client": partner_client,
        "notification_sender": notification_sender,
        "asset_publisher": asset_publisher,
        "health_checker": health_checker,
        "discovery": discovery,
        "directory": directory,
        "connection_tester": connection_tester,
    }
    runtime = Runtime(app, settings, session_factory, store, overrides)
    runtime.build()
    app.state.runtime = runtime
    app.state.sync_runner = runtime.sync_runner
    app.state.partner_runner = runtime.partner_runner
    app.state.health_runner = runtime.health_runner
    app.include_router(router)
    app.include_router(admin.router)
    app.include_router(policies.router)
    app.include_router(notifications.router)
    app.include_router(notifications.kit_router)

    if settings.web_dist_dir:
        app.mount("/", WebFiles(directory=FsPath(settings.web_dist_dir), html=True), name="web")
    return app


class WebFiles(StaticFiles):
    """The built UI. Vite names the files in assets/ by content hash, so they can be cached for
    good; everything else (index.html) is revalidated, so an upgrade shows the new UI at once."""

    def file_response(self, full_path, stat_result, scope, status_code=200) -> Response:
        """Built assets have content hashes in their names and are cached for a year;
        ``index.html`` is revalidated, so an upgrade shows at once.
        """
        response = super().file_response(full_path, stat_result, scope, status_code)
        if FsPath(full_path).parent.name == "assets":
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response
