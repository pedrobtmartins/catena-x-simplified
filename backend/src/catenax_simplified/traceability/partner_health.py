"""Connectivity checks of direct partners, recorded per run.

Which notification assets a partner must offer follows from its roles in the own BoM/usage
data (see ``dataspace.health.NOTIFICATION_TYPES``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from ..dataspace.edc import Partner
from ..dataspace.health import LEVELS, CheckStep, PartnerHealthChecker, notification_types
from ..storage import PartnerCheckRepository, PartnerCheckRow, PartnerRepository, PartRepository

log = logging.getLogger(__name__)


def overall_status(steps: list[CheckStep]) -> str:
    if any(step.status == "failed" for step in steps):
        return "failed"
    if any(step.status == "warn" for step in steps):
        return "degraded"
    return "healthy"


class PartnerHealth:
    def __init__(
        self,
        checker: PartnerHealthChecker,
        session_factory: sessionmaker[Session],
        own_bpnl: str,
        configured_connectors: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        """``configured_connectors``: BPNL → DSP address from the settings; an address stored
        for the partner (set through the API) takes precedence."""
        self._checker = checker
        self._session_factory = session_factory
        self._own_bpnl = own_bpnl
        self._configured = dict(configured_connectors or {})
        self._clock = clock

    def _partners(self) -> dict[str, tuple[list[str], str | None]]:
        """BPNL → (roles, connector address) of every known direct partner."""
        with self._session_factory() as session:
            counterparts = PartRepository(session).partner_counterparts()
            stored = {row.bpnl: row.connector_address for row in PartnerRepository(session).all()}
        partners = {}
        for bpnl in sorted((set(counterparts) | set(stored)) - {self._own_bpnl}):
            roles = counterparts.get(bpnl, {})
            partners[bpnl] = (
                [r for r in ("supplier", "customer") if roles.get(r)],
                stored.get(bpnl) or self._configured.get(bpnl),
            )
        return partners

    def known(self, bpnl: str) -> bool:
        return bpnl in self._partners()

    def run(
        self, level: str, bpnl: str | None = None, only_unhealthy: bool = False
    ) -> list[PartnerCheckRow]:
        """Check one partner (``bpnl``) or all; ``only_unhealthy`` skips partners whose last
        check was healthy. Partners are checked one after the other."""
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        partners = self._partners()
        if bpnl is not None:
            partners = {bpnl: partners[bpnl]} if bpnl in partners else {}
        if only_unhealthy:
            with self._session_factory() as session:
                latest = PartnerCheckRepository(session).latest_by_partner()
            partners = {
                b: p
                for b, p in partners.items()
                if b not in latest or latest[b].status != "healthy"
            }
        return [self._check(b, roles, address, level) for b, (roles, address) in partners.items()]

    def _check(
        self, bpnl: str, roles: list[str], address: str | None, level: str
    ) -> PartnerCheckRow:
        started_at = self._clock()
        if address:
            steps = self._checker.check(Partner(bpnl, address), level, notification_types(roles))
        else:
            steps = [
                CheckStep(
                    "discovery",
                    "Connector discovery",
                    "failed",
                    "no connector address known for this partner",
                )
            ]
        row = PartnerCheckRow(
            bpnl=bpnl,
            level=level,
            status=overall_status(steps),
            connector_address=address,
            started_at=started_at,
            finished_at=self._clock(),
            steps=[step.__dict__.copy() for step in steps],
        )
        with self._session_factory.begin() as session:
            PartnerCheckRepository(session).add(row)
        log.info("partner %s: %s check %s", bpnl, level, row.status)
        return row
