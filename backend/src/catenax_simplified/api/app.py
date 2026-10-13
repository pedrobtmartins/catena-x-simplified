from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from ..aspects.registry import SUPPORTED
from ..config import Settings
from ..dataspace import SubmodelReader, TwinRegistry
from ..storage import (
    PartRepository,
    SyncRunRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from ..traceability import OwnTwinSync, SyncReport, part_tree
from ..wiring import build_submodel_reader, build_twin_registry
from .schemas import (
    HealthOut,
    PartListItem,
    PartOut,
    PartPage,
    PartTreeOut,
    StatsOut,
    SyncReportOut,
    SyncRunPage,
)

log = logging.getLogger(__name__)


class SyncRunner:
    """Runs at most one own-twin sync at a time (each run records itself)."""

    def __init__(self, sync: OwnTwinSync | None):
        self.sync = sync
        self._lock = threading.Lock()

    def run(self) -> SyncReport | None:
        """Run a sync; returns ``None`` if one is already running."""
        if self.sync is None:
            raise RuntimeError("no Digital Twin Registry configured")
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self.sync.run()
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
        dtr_configured=request.app.state.sync_runner.sync is not None,
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
    runner: SyncRunner = request.app.state.sync_runner
    if runner.sync is None:
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


async def _periodic_sync(runner: SyncRunner, interval: int) -> None:
    while True:
        try:
            await run_in_threadpool(runner.run)
        except Exception:  # keep the loop alive; the next run may succeed
            log.exception("periodic own twin sync failed")
        await asyncio.sleep(interval)


def create_app(
    settings: Settings,
    *,
    registry: TwinRegistry | None = None,
    reader: SubmodelReader | None = None,
) -> FastAPI:
    """Create the application. ``registry``/``reader`` override the configured adapters (tests)."""
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
    runner = SyncRunner(sync)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = None
        if sync is not None and settings.sync_interval_seconds > 0:
            task = asyncio.create_task(_periodic_sync(runner, settings.sync_interval_seconds))
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        engine.dispose()

    app = FastAPI(title="catena-x-simplified", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.sync_runner = runner
    app.include_router(router)

    if settings.web_dist_dir:
        app.mount("/", StaticFiles(directory=Path(settings.web_dist_dir), html=True), name="web")
    return app
