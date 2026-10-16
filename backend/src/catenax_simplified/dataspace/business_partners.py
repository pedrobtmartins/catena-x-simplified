"""Partners' legal names from the BPDM Pool (the dataspace's golden record)."""

from __future__ import annotations

from typing import Any, Protocol

import requests

from .ports import DataspaceError


class BusinessPartnerDirectory(Protocol):
    def legal_name(self, bpnl: str) -> str | None:
        """The legal entity's name; ``None`` if the BPNL is unknown."""
        ...


class BpdmPool:
    def __init__(self, base_url: str, oauth: Any, timeout: float = 15):
        """``base_url`` ends before the version segment; ``oauth``: the central IdP's client
        (``add_auth_header``)."""
        self._base_url = base_url.rstrip("/")
        self._oauth = oauth
        self._timeout = timeout

    def legal_name(self, bpnl: str) -> str | None:
        url = f"{self._base_url}/v7/legal-entities/{bpnl}"
        try:
            headers = self._oauth.add_auth_header({"Accept": "application/json"})
            response = requests.get(url, headers=headers, timeout=self._timeout)
        except Exception as exc:
            raise DataspaceError(f"BPDM lookup of {bpnl} failed: {exc}") from exc
        if response.status_code == 404:
            return None
        if not response.ok:
            raise DataspaceError(f"BPDM lookup of {bpnl} failed: HTTP {response.status_code}")
        try:
            return response.json().get("legalName") or None
        except ValueError as exc:
            raise DataspaceError(f"BPDM lookup of {bpnl} returned no JSON") from exc
