"""Notification endpoints: the KIT's Notification API (called by partners through our EDC) and
the app's own API for the inbox/outbox."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..notifications import (
    Direction,
    NotificationError,
    NotificationService,
    NotificationType,
    Status,
    local_targets,
)
from ..storage import NotificationRepository, NotificationRow, PartRepository
from .schemas import (
    AffectedItemOut,
    ForwardPlanOut,
    NotificationCreate,
    NotificationDetailOut,
    NotificationMessageOut,
    NotificationOut,
    NotificationPage,
    NotificationSummaryOut,
    PartOut,
    PlanOut,
    PlanRequest,
    StatusChange,
)


def _service(request: Request) -> NotificationService:
    return request.app.state.notifications


def _session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


ServiceDep = Annotated[NotificationService, Depends(_service)]
SessionDep = Annotated[Session, Depends(_session)]


def _raise(exc: NotificationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# -- Notification API (Traceability KIT 1.2.1 / 2.0.0) ---------------------------------------


def _check_api_key(request: Request, x_api_key: str | None) -> None:
    expected = request.app.state.settings.notification_api_key
    if expected and not hmac.compare_digest((x_api_key or "").encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="missing or wrong X-Api-Key")


async def _kit_call(request: Request, x_api_key: str | None, handler) -> None:
    _check_api_key(request, x_api_key)
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="the body is not valid JSON") from exc
    try:
        await run_in_threadpool(handler, body)
    except NotificationError as exc:
        _raise(exc)


kit_router = APIRouter(prefix="/api/qualitynotifications", tags=["Notification API"])


@kit_router.post("/receive", status_code=201, response_class=Response)
async def receive(
    request: Request, service: ServiceDep, x_api_key: Annotated[str | None, Header()] = None
) -> Response:
    """A partner sends a new quality alert or investigation (Notification API 1.2.1/2.0.0)."""
    await _kit_call(request, x_api_key, service.receive)
    return Response(status_code=201)


@kit_router.post("/update", status_code=200, response_class=Response)
async def update(
    request: Request, service: ServiceDep, x_api_key: Annotated[str | None, Header()] = None
) -> Response:
    """A partner changes the status of a quality alert or investigation."""
    await _kit_call(request, x_api_key, service.update)
    return Response(status_code=200)


# -- inbox / outbox ----------------------------------------------------------------------


router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _actions(row: NotificationRow) -> list[str]:
    actions = []
    if row.direction == Direction.OUTBOUND and row.status == Status.CREATED:
        actions.append("send")
    order = list(Status)
    targets = local_targets(Direction(row.direction), Status(row.status))
    return actions + [s.value for s in sorted(targets, key=order.index)]


def _detail(session: Session, row: NotificationRow) -> NotificationDetailOut:
    repository = NotificationRepository(session)
    parts = PartRepository(session).get_parts(row.affected_items)
    source = repository.get(row.forwarded_from_id) if row.forwarded_from_id else None
    return NotificationDetailOut(
        **NotificationOut.model_validate(row).model_dump(),
        items=[
            AffectedItemOut(
                global_asset_id=gid,
                part=PartOut.model_validate(parts[gid]) if gid in parts else None,
            )
            for gid in row.affected_items
        ],
        messages=[NotificationMessageOut.model_validate(m) for m in repository.messages(row.id)],
        forwarded_from=NotificationOut.model_validate(source) if source else None,
        forwarded_to=[NotificationOut.model_validate(r) for r in repository.forwarded_to(row.id)],
        actions=_actions(row),
    )


@router.get("", response_model=NotificationPage)
def list_notifications(
    session: SessionDep,
    direction: Annotated[str | None, Query(pattern="^(inbound|outbound)$")] = None,
    type: NotificationType | None = None,
    status: Status | None = None,
    partner: str | None = None,
    open_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationPage:
    """The inbox (``direction=inbound``) or outbox (``outbound``), most recently updated first,
    filtered by type, status, partner BPNL or, with ``open_only``, by those not closed."""
    rows, total = NotificationRepository(session).list(
        direction=direction,
        type=type.value if type else None,
        status=status.value if status else None,
        partner_bpnl=partner,
        open_only=open_only,
        limit=limit,
        offset=offset,
    )
    items = [NotificationOut.model_validate(r) for r in rows]
    return NotificationPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=NotificationSummaryOut)
def summary(session: SessionDep) -> NotificationSummaryOut:
    """Counts for the Notifications page: new and open received notifications, open sent ones."""
    return NotificationSummaryOut(**NotificationRepository(session).counts())


@router.post("/plan", response_model=PlanOut)
def plan(request: PlanRequest, service: ServiceDep) -> PlanOut:
    """Who would receive a notification about these parts, before creating it: an alert goes to the
    direct customers of own parts (usage), an investigation to the direct suppliers of the parts
    (BoM). Parts with no known partner are listed as unmatched.
    """
    return PlanOut.model_validate(service.plan(request.type, request.affected_items))


@router.post("", response_model=list[NotificationOut], status_code=201)
async def create(request: NotificationCreate, service: ServiceDep) -> list[NotificationOut]:
    """Creates one notification per recipient from the plan, each with only the parts that concern
    that partner, and sends them when ``send`` is set. A notification whose delivery fails stays
    a draft with the error; ``forwarded_from`` links a next hop to the received notification it
    came from.
    """
    if request.send and not service.can_send:
        raise HTTPException(status_code=503, detail="no EDC configured")
    try:
        rows = service.create(
            request.type,
            request.affected_items,
            request.severity,
            request.description,
            expected_response_by=request.expected_response_by,
            forwarded_from=request.forwarded_from,
        )
    except NotificationError as exc:
        _raise(exc)
    if request.send:
        sent = []
        for row in rows:
            try:
                row = await run_in_threadpool(service.send, row.id)
            except NotificationError:
                row = service.get(row.id)  # stays a draft, with the delivery error
            sent.append(row)
        rows = sent
    return [NotificationOut.model_validate(r) for r in rows]


@router.get("/{pk}", response_model=NotificationDetailOut)
def get_notification(pk: int, session: SessionDep) -> NotificationDetailOut:
    """One notification with its affected parts (as known locally), message log, the hop it was
    forwarded from or to, and the status changes allowed next.
    """
    row = NotificationRepository(session).get(pk)
    if row is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return _detail(session, row)


@router.get("/{pk}/forward-plan", response_model=ForwardPlanOut)
def forward_plan(pk: int, service: ServiceDep) -> ForwardPlanOut:
    """The next hop for a received notification: for an alert, the own parts that contain the
    affected parts and their customers; for an investigation, the components of the affected own
    parts and their suppliers.
    """
    try:
        return ForwardPlanOut.model_validate(service.forward_plan(pk))
    except NotificationError as exc:
        _raise(exc)


@router.post("/{pk}/send", response_model=NotificationOut)
async def send(pk: int, service: ServiceDep) -> NotificationOut:
    """Sends a draft through the EDC, in the highest Notification API version the partner offers.
    On failure it stays a draft with the error.
    """
    try:
        return NotificationOut.model_validate(await run_in_threadpool(service.send, pk))
    except NotificationError as exc:
        _raise(exc)


@router.post("/{pk}/status", response_model=NotificationOut)
async def change_status(pk: int, change: StatusChange, service: ServiceDep) -> NotificationOut:
    """Acknowledges, accepts, declines or closes a notification, following the KIT state model. The
    partner is told first; the status changes locally only once the partner accepted the update.
    """
    try:
        row = await run_in_threadpool(service.change_status, pk, change.status, change.information)
    except NotificationError as exc:
        _raise(exc)
    return NotificationOut.model_validate(row)
