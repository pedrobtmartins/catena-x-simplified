"""Partners' legal names from the golden record of the dataspace.

Two sources, one per dataspace setup:

- ``BpdmPool``: a BPDM Pool reached directly with a central IdP token (``/v7/legal-entities``);
- ``BpExplorer``: a BPDM Pool offered as an asset in the operator's EDC, such as the Cofinity-X
  Business Partner Explorer. Our EDC negotiates for the asset; the EDR's data plane then serves
  the Pool's ``/v6/members`` API (``POST /legal-entities/search`` with ``bpnLs``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import requests

from .edc import ASSET_ID_KEY, ConnectorConsumer, EdcNegotiator, equals
from .health import dataset_ids
from .ports import DataspaceError

# The Cofinity-X Business Partner Explorer (both environments use this BPN).
COFINITY_X_BP_EXPLORER_BPNL = "BPNLCOFINITYEZFA"


class BusinessPartnerDirectory(Protocol):
    """Where partner names come from: the BPDM Pool directly, or through an EDC (the Business
    Partner Explorer).
    """

    source: str  # shown to users, e.g. "BPDM Pool"

    def legal_name(self, bpnl: str) -> str | None:
        """The legal entity's name; ``None`` if the BPNL is unknown."""
        ...


class BpdmPool:
    """The BPDM Pool's golden record, reached directly with a technical user of the central
    IdP.
    """

    source = "BPDM Pool"

    def __init__(self, base_url: str, oauth: Any, timeout: float = 15):
        """``base_url`` ends before the version segment; ``oauth``: the central IdP's client
        (``add_auth_header``)."""
        self._base_url = base_url.rstrip("/")
        self._oauth = oauth
        self._timeout = timeout

    def legal_name(self, bpnl: str) -> str | None:
        """The legal name of the BPNL's legal entity (``GET /v7/legal-entities/{bpnl}``)."""
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


class BpExplorer:
    """A BPDM Pool offered through a connector (the Cofinity-X Business Partner Explorer): our
    EDC negotiates for its asset, like for a partner's registry, and reuses the token for a
    minute.
    """

    source = "Business Partner Explorer"

    def __init__(
        self,
        consumer: ConnectorConsumer,
        accepted_policies: list[dict] | None,
        address: str,
        bpnl: str = COFINITY_X_BP_EXPLORER_BPNL,
        asset_id: str | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        token_ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        """``address``: the explorer's DSP endpoint; ``bpnl``: the BPN of its connector;
        ``asset_id``: the asset to negotiate for, found in the catalog when it offers exactly one.
        ``accepted_policies``: see ``EdcNegotiator``."""
        self._edc = EdcNegotiator(consumer, accepted_policies)
        self.address = address
        self.bpnl = bpnl
        self._asset_id = asset_id
        self._session = session or requests.Session()
        self._timeout = timeout
        self._token_ttl = token_ttl_seconds
        self._clock = clock
        self._access: tuple[float, str, str] | None = None

    def find_offer(self) -> str:
        """The asset the explorer's catalog offers us (read-only: no negotiation)."""
        wanted = self._asset_id
        filters = [equals(ASSET_ID_KEY, wanted)] if wanted else []
        ids = dataset_ids(self._edc.catalog(self.bpnl, self.address, filters))
        if not ids:
            if wanted:
                raise DataspaceError(f"the catalog of {self.bpnl} does not offer us {wanted}")
            raise DataspaceError(
                f"the catalog of {self.bpnl} offers us no asset: is the subscription active?"
            )
        if len(ids) > 1 and not wanted:
            raise DataspaceError(
                f"the catalog of {self.bpnl} offers several assets ({', '.join(ids[:5])}); "
                "set the asset ID (CXS_BP_EXPLORER_ASSET_ID)"
            )
        return wanted or ids[0]

    def _asset(self) -> str:
        if not self._asset_id:
            self._asset_id = self.find_offer()
        return self._asset_id

    def _endpoint(self) -> tuple[str, str]:
        if self._access and self._clock() - self._access[0] < self._token_ttl:
            return self._access[1], self._access[2]
        asset_id = self._asset()
        endpoint, token = self._edc.negotiate(
            self.bpnl, self.address, [equals(ASSET_ID_KEY, asset_id)]
        )
        self._access = (self._clock(), endpoint, token)
        return endpoint, token

    def legal_name(self, bpnl: str) -> str | None:
        """The legal name of the BPNL, through the explorer's data plane (Pool ``/v6/members``
        search).
        """
        endpoint, token = self._endpoint()
        url = f"{endpoint.rstrip('/')}/legal-entities/search"
        try:
            response = self._session.post(
                url,
                params={"page": 0, "size": 10},
                json={"bpnLs": [bpnl]},
                headers={"Authorization": token, "Accept": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise DataspaceError(f"{self.source} lookup of {bpnl} failed: {exc}") from exc
        if response.status_code in (401, 403):
            self._access = None  # the next lookup negotiates again
        if not response.ok:
            raise DataspaceError(
                f"{self.source} lookup of {bpnl} failed: HTTP {response.status_code}"
            )
        try:
            content = (response.json() or {}).get("content") or []
        except (ValueError, AttributeError) as exc:
            raise DataspaceError(f"{self.source} lookup of {bpnl} returned no page") from exc
        for entity in content:
            if isinstance(entity, dict) and entity.get("bpnl") == bpnl:
                return entity.get("legalName") or None
        return None
