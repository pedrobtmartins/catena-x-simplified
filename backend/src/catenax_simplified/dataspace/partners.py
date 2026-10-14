"""Reading direct partners' twins through the dataspace (EDC + the partner's DTR).

Flow per the Industry Core / Digital Twin KITs:

1. negotiate for the partner's Digital Twin Registry asset (``dct:type`` DigitalTwinRegistry);
2. look the twin up by its Catena-X ID (``/lookup/shells``) and read its shell descriptor
   through the partner's data plane;
3. negotiate for the submodel's asset (``id`` in the descriptor's ``subprotocolBody``) at the
   ``dspEndpoint`` it names, and read ``{href}/$value`` with the access token.

Contract negotiations and access tokens are reused through the Tractus-X SDK's connection
manager; a negotiation happens only once per partner, asset and accepted policy set.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import requests
from tractusx_sdk.dataspace.tools.encoding_tools import encode_as_base64_url_safe

from .dtr import twin_from_descriptor
from .edc import (
    ASSET_ID_KEY,
    DCT_TYPE_KEY,
    ConnectorConsumer,
    EdcNegotiator,
    Partner,
    equals,
)
from .ports import DataspaceError, SubmodelRef, TwinRef
from .submodels import value_url

log = logging.getLogger(__name__)

DTR_ASSET_TYPE = "https://w3id.org/catenax/taxonomy#DigitalTwinRegistry"

__all__ = [
    "ASSET_ID_KEY",
    "DCT_TYPE_KEY",
    "DTR_ASSET_TYPE",
    "EdcPartnerClient",
    "Partner",
    "PartnerDataClient",
    "parse_subprotocol_body",
]


class PartnerDataClient(Protocol):
    def find_twin(self, partner: Partner, global_asset_id: str) -> TwinRef | None:
        """The partner's twin with this Catena-X ID, or ``None`` if its registry has none."""
        ...

    def read_submodel(self, partner: Partner, ref: SubmodelRef) -> dict[str, Any]:
        """A submodel of a partner twin, in value-only serialization."""
        ...


def parse_subprotocol_body(body: str | None) -> dict[str, str]:
    """``"dspEndpoint=https://…;id=a1"`` → ``{"dspEndpoint": "https://…", "id": "a1"}``."""
    result: dict[str, str] = {}
    for part in (body or "").split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            result[key.strip()] = value.strip()
    return result


class EdcPartnerClient:
    def __init__(
        self,
        consumer: ConnectorConsumer,
        accepted_policies: list[dict] | None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        token_ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        """``accepted_policies``: see ``EdcNegotiator``; ``None`` accepts any policy
        (development only)."""
        self._edc = EdcNegotiator(consumer, accepted_policies)
        self._session = session or requests.Session()
        self._timeout = timeout
        self._token_ttl = token_ttl_seconds
        self._clock = clock
        self._dtr_access: dict[str, tuple[float, str, str]] = {}

    # -- dataspace -----------------------------------------------------------------------

    def _dtr(self, partner: Partner) -> tuple[str, str]:
        cached = self._dtr_access.get(partner.bpnl)
        if cached and self._clock() - cached[0] < self._token_ttl:
            return cached[1], cached[2]
        endpoint, token = self._edc.negotiate(
            partner.bpnl, partner.connector_address, [equals(DCT_TYPE_KEY, DTR_ASSET_TYPE)]
        )
        self._dtr_access[partner.bpnl] = (self._clock(), endpoint, token)
        return endpoint, token

    def _get_json(self, url: str, token: str, params: Any = None) -> Any:
        try:
            response = self._session.get(
                url,
                params=params,
                headers={"Authorization": token, "Accept": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise DataspaceError(f"GET {url} failed: {exc}") from exc
        if response.status_code == 404:
            return None
        if not response.ok:
            raise DataspaceError(f"GET {url} returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise DataspaceError(f"GET {url} did not return JSON") from exc

    # -- PartnerDataClient ---------------------------------------------------------------

    def find_twin(self, partner: Partner, global_asset_id: str) -> TwinRef | None:
        endpoint, token = self._dtr(partner)
        base = endpoint.rstrip("/")
        asset_id = json.dumps({"name": "globalAssetId", "value": global_asset_id})
        lookup = self._get_json(
            f"{base}/lookup/shells", token, params={"assetIds": encode_as_base64_url_safe(asset_id)}
        )
        aas_ids = (lookup or {}).get("result") or []
        if not aas_ids:
            return None
        if len(aas_ids) > 1:
            log.warning(
                "%s has %d twins for %s; using the first",
                partner.bpnl,
                len(aas_ids),
                global_asset_id,
            )
        descriptor = self._get_json(
            f"{base}/shell-descriptors/{encode_as_base64_url_safe(aas_ids[0])}", token
        )
        if not descriptor:
            return None
        return twin_from_descriptor(descriptor)

    def read_submodel(self, partner: Partner, ref: SubmodelRef) -> dict[str, Any]:
        body = parse_subprotocol_body(ref.subprotocol_body)
        if "id" not in body:
            raise DataspaceError(f"submodel descriptor at {ref.href} names no asset id")
        address = body.get("dspEndpoint") or partner.connector_address
        _, token = self._edc.negotiate(partner.bpnl, address, [equals(ASSET_ID_KEY, body["id"])])
        payload = self._get_json(value_url(ref), token)
        if not isinstance(payload, dict):
            raise DataspaceError(f"submodel at {ref.href} is missing or not a JSON object")
        return payload
