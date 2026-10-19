"""Caches the twins of direct partners that own parts are linked to (one level only).

For every partner named in the own parts' BoM (suppliers) and usage (customers) relations, the
counterpart twins are looked up in the partner's registry and their SerialPart/Batch submodel is
read. Partners' own BoM or usage is never read: deeper levels travel through notifications.

A sync can also be limited to a selection of those twins (the supplier parts under one assembly,
picked in the UI): it then reads only them, and leaves the rest of the cache and the partners'
last-sync summary as they are.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from .. import aspects
from ..aspects.ids import normalize_global_asset_id
from ..dataspace import DataspaceError
from ..dataspace.partners import Partner, PartnerDataClient
from ..storage import PartnerRepository, PartRepository

log = logging.getLogger(__name__)

PART_ASPECTS = {aspects.AspectType.SERIAL_PART, aspects.AspectType.BATCH}


@dataclass
class PartnerSyncResult:
    """What a partner sync read for one partner."""

    bpnl: str
    roles: list[str]
    linked_twins: int
    twins_found: int = 0
    twins_missing: int = 0
    removed_parts: int = 0
    status: str = "ok"  # ok | partial | failed | no_connector
    issues: list[str] = field(default_factory=list)


@dataclass
class PartnerSyncReport:
    """One partner sync run, per partner."""

    started_at: datetime
    finished_at: datetime | None = None
    partners: list[PartnerSyncResult] = field(default_factory=list)
    # The twins asked for that no own part is linked to (a selection only).
    not_linked: list[str] = field(default_factory=list)


class PartnerSync:
    """Caches the direct partners' counterpart twins (one level, through
    ``PartnerDataClient``) and records per partner how it went. Partner parts no longer
    linked to an own part are removed.
    """

    def __init__(
        self,
        client: PartnerDataClient,
        session_factory: sessionmaker[Session],
        own_bpnl: str,
        configured_connectors: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        """``configured_connectors``: BPNL → DSP address from the settings; an address stored
        for the partner (set through the API) takes precedence."""
        self._client = client
        self._session_factory = session_factory
        self._own_bpnl = own_bpnl
        self._configured = dict(configured_connectors or {})
        self._clock = clock

    def run(
        self, only_bpnl: str | None = None, only_twins: Collection[str] | None = None
    ) -> PartnerSyncReport:
        """Syncs every direct partner, or only ``only_bpnl``; the own BPNL is never a partner.
        With ``only_twins``, reads only those counterpart twins, from the partners that own
        them."""
        report = PartnerSyncReport(started_at=self._clock())
        with self._session_factory() as session:
            counterparts = PartRepository(session).partner_counterparts()
            stored = {row.bpnl: row.connector_address for row in PartnerRepository(session).all()}
        selection = set(only_twins) if only_twins is not None else None
        if selection is not None:
            linked = {
                gid
                for bpnl, roles in counterparts.items()
                if bpnl != self._own_bpnl
                for gid in roles["supplier"] | roles["customer"]
            }
            report.not_linked = sorted(selection - linked)
            counterparts = {
                bpnl: {role: ids & selection for role, ids in roles.items()}
                for bpnl, roles in counterparts.items()
            }
        for bpnl in sorted(counterparts):
            if bpnl == self._own_bpnl or (only_bpnl and bpnl != only_bpnl):
                continue
            roles = counterparts[bpnl]
            if selection is not None and not (roles["supplier"] or roles["customer"]):
                continue
            address = stored.get(bpnl) or self._configured.get(bpnl)
            report.partners.append(
                self._sync_partner(bpnl, roles, address, whole=selection is None)
            )
        report.finished_at = self._clock()
        return report

    def _sync_partner(
        self, bpnl: str, roles: Mapping[str, set[str]], address: str | None, whole: bool = True
    ) -> PartnerSyncResult:
        """``whole``: every counterpart of the partner, so parts no longer linked are removed
        and the partner's last-sync summary is updated; a selection does neither."""
        twin_ids = sorted(roles["supplier"] | roles["customer"])
        result = PartnerSyncResult(
            bpnl=bpnl,
            roles=[role for role in ("supplier", "customer") if roles[role]],
            linked_twins=len(twin_ids),
        )
        if not address:
            result.status = "no_connector"
            result.issues.append("no connector address known for this partner")
            if whole:
                self._record(result)
            return result

        partner = Partner(bpnl=bpnl, connector_address=address)
        parts: list[aspects.Part] = []
        for gid in twin_ids:
            try:
                twin = self._client.find_twin(partner, gid)
            except DataspaceError as exc:
                # The registry itself is unreachable: no point trying the remaining twins.
                result.status = "failed"
                result.issues.append(str(exc))
                break
            if twin is None:
                result.twins_missing += 1
                continue
            result.twins_found += 1
            part = self._read_part(partner, twin, gid, result)
            if part is not None:
                parts.append(part)

        synced_at = self._clock()
        with self._session_factory.begin() as session:
            repository = PartRepository(session)
            for part in parts:
                repository.upsert_part(
                    part, manufacturer_id=bpnl, is_own=False, synced_at=synced_at
                )
            if whole and result.status != "failed":
                result.removed_parts = repository.delete_partner_parts_except(bpnl, set(twin_ids))
        if result.status == "ok" and (result.issues or result.twins_missing):
            result.status = "partial"
        if whole:
            self._record(result)
        return result

    def _read_part(self, partner: Partner, twin, gid: str, result: PartnerSyncResult):
        refs = [
            ref
            for ref in twin.submodels
            if (supported := aspects.lookup(ref.semantic_id)) and supported.type in PART_ASPECTS
        ]
        if not refs:
            result.issues.append(f"{gid}: no supported SerialPart or Batch submodel")
            return None
        for ref in refs:
            try:
                part = aspects.parse(ref.semantic_id, self._client.read_submodel(partner, ref))
            except (DataspaceError, aspects.AspectPayloadError) as exc:
                result.issues.append(f"{gid}: {exc}")
                continue
            if part.global_asset_id != normalize_global_asset_id(gid):
                result.issues.append(f"{gid}: submodel describes {part.global_asset_id}")
                continue
            return part
        return None

    def _record(self, result: PartnerSyncResult) -> None:
        with self._session_factory.begin() as session:
            row = PartnerRepository(session).get_or_create(result.bpnl)
            row.last_sync_at = self._clock()
            row.last_status = result.status
            row.last_message = "; ".join(result.issues)[:2000] or None
            row.twins_found = result.twins_found
            row.twins_missing = result.twins_missing
        log.info(
            "partner %s: %s (%d found, %d missing)",
            result.bpnl,
            result.status,
            result.twins_found,
            result.twins_missing,
        )
