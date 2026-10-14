from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from ..aspects.registry import SUPPORTED
from ..config import Settings
from ..dataspace import SubmodelReader, TwinRegistry
from ..dataspace.notification_assets import NotificationAssetPublisher
from ..dataspace.notifications import NotificationSender
from ..dataspace.partners import PartnerDataClient
from ..notifications import NotificationService
from ..storage import (
    PartnerRepository,
    PartRepository,
    SyncRunRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from ..traceability import OwnTwinSync, PartnerSync, part_tree
from ..wiring import (
    build_asset_publisher,
    build_edc_consumer,
    build_notification_sender,
    build_partner_client,
    build_submodel_reader,
    build_twin_registry,
)
from . import notifications
from .schemas import (
    HealthOut,
    NotificationAssetsOut,
    PartListItem,
    PartnerOut,
    PartnerSyncReportOut,
    PartnerUpdate,
    PartOut,
    PartPage,
    PartTreeOut,
    StatsOut,
    SyncReportOut,
    SyncRunPage,
)

log = logging.getLogger(__name__)


class ExclusiveRunner:
    """Runs a job at most once at a time; ``job`` is ``None`` when it is not configured."""

    def __init__(self, job: Callable[..., Any] | None):
        self.job = job
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
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

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthOut)
def health(request: Request) -> HealthOut:
    settings: Settings = request.app.state.settings
    return HealthOut(
        status="ok",
        own_bpnl=settings.own_bpnl,
        dtr_configured=request.app.state.sync_runner.configured,
        edc_configured=request.app.state.partner_runner.configured,
        can_send_notifications=request.app.state.notifications.can_send,
        notification_assets=request.app.state.asset_publishing.status,
        dtr_url=settings.dtr_base_url,
        sync_interval_seconds=settings.sync_interval_seconds,
        supported_aspects=sorted(SUPPORTED),
    )


@router.get("/stats", response_model=StatsOut)
def stats(session: SessionDep) -> StatsOut:
    return StatsOut(**PartRepository(session).stats())


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
    row = PartRepository(session).get_part(global_asset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="part not found")
    return PartOut.model_validate(row)


@router.get("/parts/{global_asset_id}/tree", response_model=PartTreeOut)
def get_part_tree(global_asset_id: str, session: SessionDep) -> PartTreeOut:
    tree = part_tree(PartRepository(session), global_asset_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="part not found")
    return PartTreeOut.model_validate(tree)


@router.post("/sync", response_model=SyncReportOut)
async def trigger_sync(request: Request) -> SyncReportOut:
    runner: ExclusiveRunner = request.app.state.sync_runner
    if not runner.configured:
        raise HTTPException(status_code=503, detail="no Digital Twin Registry configured")
    report = await run_in_threadpool(runner.run)
    if report is None:
        raise HTTPException(status_code=409, detail="a sync is already running")
    return SyncReportOut.model_validate(report)


@router.get("/sync/last", response_model=SyncReportOut)
def last_sync(session: SessionDep) -> SyncReportOut:
    runs = SyncRunRepository(session).recent(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="no sync has run yet")
    return SyncReportOut.model_validate(runs[0])


@router.get("/sync/runs", response_model=SyncRunPage)
def sync_runs(session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 20) -> SyncRunPage:
    runs = SyncRunRepository(session).recent(limit=limit)
    return SyncRunPage(items=[SyncReportOut.model_validate(r) for r in runs])


@router.get("/partners", response_model=list[PartnerOut])
def list_partners(session: SessionDep, request: Request) -> list[PartnerOut]:
    settings: Settings = request.app.state.settings
    counterparts = PartRepository(session).partner_counterparts()
    rows = {row.bpnl: row for row in PartnerRepository(session).all()}
    cached = PartRepository(session).partner_part_counts()
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
            )
        )
    return partners


@router.put("/partners/{bpnl}", response_model=PartnerOut)
def update_partner(
    bpnl: str, update: PartnerUpdate, session: SessionDep, request: Request
) -> PartnerOut:
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


@router.post("/partners/sync", response_model=PartnerSyncReportOut)
async def sync_partners(request: Request, bpnl: str | None = None) -> PartnerSyncReportOut:
    runner: ExclusiveRunner = request.app.state.partner_runner
    if not runner.configured:
        raise HTTPException(status_code=503, detail="no EDC configured")
    report = await run_in_threadpool(runner.run, bpnl)
    if report is None:
        raise HTTPException(status_code=409, detail="a partner sync is already running")
    return PartnerSyncReportOut.model_validate(report)


class AssetPublishing:
    """Publishes the notification assets in our EDC and remembers how it went."""

    def __init__(self, publisher: NotificationAssetPublisher | None):
        self.publisher = publisher
        self.status = NotificationAssetsOut(
            state="not_configured" if publisher is None else "publishing"
        )
        self._lock = threading.Lock()

    def run(self) -> NotificationAssetsOut:
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


def create_app(
    settings: Settings,
    *,
    registry: TwinRegistry | None = None,
    reader: SubmodelReader | None = None,
    partner_client: PartnerDataClient | None = None,
    notification_sender: NotificationSender | None = None,
    asset_publisher: NotificationAssetPublisher | None = None,
) -> FastAPI:
    """Create the application. The keyword arguments override the configured adapters (tests)."""
    engine = make_engine(settings.database_url)
    init_schema(engine)
    session_factory = make_session_factory(engine)

    registry = registry or build_twin_registry(settings)
    reader = reader or build_submodel_reader(settings)
    sync = (
        OwnTwinSync(registry, reader, session_factory, settings.own_bpnl)
        if registry is not None
        else None
    )
    runner = ExclusiveRunner(sync.run if sync is not None else None)
    consumer = (
        build_edc_consumer(settings)
        if partner_client is None or notification_sender is None
        else None
    )
    partner_client = partner_client or build_partner_client(settings, consumer)
    notification_sender = notification_sender or build_notification_sender(settings, consumer)
    notification_service = NotificationService(
        session_factory,
        settings.own_bpnl,
        notification_sender,
        configured_connectors=settings.partner_connectors,
    )
    asset_publishing = AssetPublishing(asset_publisher or build_asset_publisher(settings))
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
    partner_runner = ExclusiveRunner(partner_sync.run if partner_sync is not None else None)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = None
        publish = None
        if asset_publishing.publisher is not None:
            # In the background: the app serves while the EDC is still unreachable.
            publish = asyncio.create_task(run_in_threadpool(asset_publishing.run))
        periodic = [r for r in (runner, partner_runner) if r.configured]
        if periodic and settings.sync_interval_seconds > 0:
            task = asyncio.create_task(_periodic_sync(periodic, settings.sync_interval_seconds))
        yield
        for background in (task, publish):
            if background is not None:
                background.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await background
        engine.dispose()

    app = FastAPI(title="catena-x-simplified", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.sync_runner = runner
    app.state.partner_runner = partner_runner
    app.state.notifications = notification_service
    app.state.asset_publishing = asset_publishing
    app.include_router(router)
    app.include_router(notifications.router)
    app.include_router(notifications.kit_router)

    if settings.web_dist_dir:
        app.mount("/", StaticFiles(directory=Path(settings.web_dist_dir), html=True), name="web")
    return app
