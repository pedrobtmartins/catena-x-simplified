"""The usage policies the company accepts, on the Setup page.

The deployment's ``CXS_ACCEPTED_POLICIES`` stay as they are (locked); an admin adds policies
here, and the app accepts both. To find the policy a connector offers, the app reads that
connector's catalog for an asset (only the catalog: nothing is negotiated) and shows each
offered policy with whether it is accepted, so it can be accepted as offered.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..admin.config_store import MAX_ADDED_POLICIES, POLICIES, parse_policies
from ..dataspace import DataspaceError
from ..dataspace.edc import ASSET_ID_KEY, DCT_TYPE_KEY, EdcNegotiator, equals
from ..dataspace.health import scrub
from ..dataspace.partners import DTR_ASSET_TYPE
from ..dataspace.policies import describe, same_policy
from ..storage import PartnerRepository
from . import admin

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup/policies", tags=["Setup"])

AdminIfEnabled = Annotated[str | None, Depends(admin.admin_if_enabled)]
# A serialized policy above this is not a usage policy someone means to accept.
MAX_POLICY_BYTES = 8_000


class PolicyOut(BaseModel):
    """An accepted usage policy: its short form and its ODRL body."""

    description: str
    policy: dict[str, Any]


class PoliciesOut(BaseModel):
    """The policies the app accepts: the deployment's (locked) and those added on Setup."""

    deployment: list[PolicyOut]
    added: list[PolicyOut]
    # An admin can add and remove policies (admin login and CXS_SECRET_KEY are set up).
    editable: bool
    # CXS_ACCEPT_ANY_POLICY: development only, every offer is accepted.
    accept_any: bool


class PoliciesUpdate(BaseModel):
    """The policies added on Setup, as a whole (the deployment's are not part of it)."""

    added: list[dict[str, Any]] = Field(max_length=MAX_ADDED_POLICIES)


class OffersRequest(BaseModel):
    """Whose catalog to read and for which asset.

    ``bpnl`` is the connector's owner (the own BPNL for the own connector). Without
    ``connector_address`` the partner's known DSP address is used. Without ``asset_id`` the
    connector's Digital Twin Registry offer is read.
    """

    bpnl: str = Field(pattern=r"^BPNL[0-9A-Za-z]{12}$")
    connector_address: str | None = Field(default=None, max_length=512, pattern=r"^https?://\S+$")
    asset_id: str | None = Field(default=None, max_length=512)


class OfferOut(BaseModel):
    """A policy the connector offers for an asset, and whether it is accepted."""

    asset_id: str
    description: str
    policy: dict[str, Any]
    accepted: bool


def _out(policy: dict[str, Any]) -> PolicyOut:
    return PolicyOut(description=describe(policy), policy=policy)


def _added(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.runtime.store
    values, _ = store.values()
    return parse_policies(values.get(POLICIES.key))


def _policies(request: Request) -> PoliciesOut:
    runtime = request.app.state.runtime
    return PoliciesOut(
        deployment=[_out(p) for p in runtime.base.accepted_policies],
        added=[_out(p) for p in _added(request)],
        editable=request.app.state.admin is not None and runtime.store.available,
        accept_any=request.app.state.settings.accept_any_policy,
    )


def _check(policy: dict[str, Any]) -> str | None:
    """Why this is not a usage policy to accept, or ``None``."""
    if len(json.dumps(policy)) > MAX_POLICY_BYTES:
        return "too large"
    if not any(k.split(":")[-1] in ("permission", "prohibition", "obligation") for k in policy):
        return "not an ODRL policy (no permission)"
    return None


@router.get("", response_model=PoliciesOut)
def get_policies(request: Request) -> PoliciesOut:
    """The usage policies the app accepts when it negotiates: the deployment's and those an admin
    added. An offer whose policy means the same as one of them is accepted."""
    return _policies(request)


@router.put("", response_model=PoliciesOut)
async def put_policies(update: PoliciesUpdate, request: Request, user: admin.Admin) -> PoliciesOut:
    """Replaces the policies added on Setup and applies them without a restart. A policy that
    means the same as one already accepted is kept once."""
    runtime = request.app.state.runtime
    if not runtime.store.available:
        raise HTTPException(status_code=503, detail="CXS_SECRET_KEY is not set")
    errors = [f"policy {i + 1}: {why}" for i, p in enumerate(update.added) if (why := _check(p))]
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    added: list[dict[str, Any]] = []
    for policy in update.added:
        known = [*runtime.base.accepted_policies, *added]
        if not any(same_policy(policy, p) for p in known):
            added.append(policy)
    value = json.dumps(added) if added else None
    await run_in_threadpool(runtime.store.save, {POLICIES.key: value}, user)
    log.info("accepted usage policies changed by %s: %d added", user, len(added))
    await runtime.reload()
    return _policies(request)


@router.post("/offers", response_model=list[OfferOut])
async def offered_policies(
    body: OffersRequest, request: Request, _: AdminIfEnabled
) -> list[OfferOut]:
    """Reads a connector's catalog through the own EDC and lists the usage policies it offers for
    the asset, each with whether it is accepted. Only the catalog is read; nothing is
    negotiated."""
    consumer = request.app.state.consumer
    if consumer is None:
        raise HTTPException(status_code=503, detail="no EDC configured")
    settings = request.app.state.settings
    address = body.connector_address
    if address is None:
        with request.app.state.session_factory() as session:
            row = PartnerRepository(session).get(body.bpnl)
        address = (row.connector_address if row else None) or settings.partner_connectors.get(
            body.bpnl
        )
    if not address:
        raise HTTPException(
            status_code=422, detail=f"no connector address known for {body.bpnl}: give one"
        )
    negotiator = EdcNegotiator(
        consumer, None if settings.accept_any_policy else settings.accepted_policies
    )
    filter_expression = [
        equals(ASSET_ID_KEY, body.asset_id)
        if body.asset_id
        else equals(DCT_TYPE_KEY, DTR_ASSET_TYPE)
    ]
    try:
        offers = await run_in_threadpool(
            negotiator.offered_policies, body.bpnl, address, filter_expression
        )
    except DataspaceError as exc:
        raise HTTPException(status_code=502, detail=scrub(str(exc))) from exc
    return [
        OfferOut(
            asset_id=o.asset_id,
            description=describe(o.policy),
            policy=o.policy,
            accepted=o.accepted,
        )
        for o in offers
    ]
