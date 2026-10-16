"""Finding partners' connectors through the central discovery services.

The Discovery Finder names the EDC Discovery service (type ``bpn``), which answers with the DSP
endpoints registered for a BPNL. Both calls go through the Tractus-X SDK with a token of the
central IdP.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from tractusx_sdk.dataspace.services.discovery import (
    ConnectorDiscoveryService,
    DiscoveryFinderService,
)

from .ports import DataspaceError


class ConnectorDiscovery(Protocol):
    def find(self, bpnl: str) -> list[str]:
        """The DSP endpoints registered for a BPNL; empty if it has none."""
        ...


class SdkConnectorDiscovery:
    def __init__(self, finder_url: str, oauth: Any):
        """``oauth``: the central IdP's client (``add_auth_header``), asked for a token per call."""
        self._finder_url = finder_url
        self._oauth = oauth
        self._service: ConnectorDiscoveryService | None = None
        self._lock = threading.Lock()

    def _connect(self) -> ConnectorDiscoveryService:
        with self._lock:
            if self._service is None:
                finder = DiscoveryFinderService(url=self._finder_url, oauth=self._oauth)
                self._service = ConnectorDiscoveryService(
                    oauth=self._oauth, discovery_finder_service=finder
                )
            return self._service

    def find(self, bpnl: str) -> list[str]:
        try:
            endpoints = self._connect().find_connector_by_bpn(bpnl)
        except Exception as exc:
            raise DataspaceError(f"connector discovery for {bpnl} failed: {exc}") from exc
        # Keep the service's order; some registrations list an endpoint twice.
        return list(dict.fromkeys(endpoints or []))
