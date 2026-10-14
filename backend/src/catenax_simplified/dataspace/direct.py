"""Development only: reach partners without EDCs (``CXS_DEV_DIRECT``).

For local demos of several participants on one machine. Nothing here negotiates a contract or
checks a usage policy, so it must never be used in a dataspace:

- ``DirectPartnerClient`` reads a partner's DTR and submodels straight from their URLs;
- ``DirectNotificationSender`` POSTs to the partner app's Notification API, the partner's
  "connector address" being that app's base URL.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import requests
from tractusx_sdk.dataspace.tools.encoding_tools import encode_as_base64_url_safe

from .dtr import twin_from_descriptor
from .edc import Partner
from .notifications import NotificationRejected
from .ports import DataspaceError, SubmodelRef, TwinRef
from .submodels import value_url

API_VERSION = "2.0.0"


class _Http:
    def __init__(self, session: requests.Session | None, timeout: float):
        self._session = session or requests.Session()
        self._timeout = timeout

    def get_json(self, url: str, params: Any = None) -> Any:
        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise DataspaceError(f"GET {url} failed: {exc}") from exc
        if response.status_code == 404:
            return None
        if not response.ok:
            raise DataspaceError(f"GET {url} returned HTTP {response.status_code}")
        return response.json()


class DirectPartnerClient(_Http):
    def __init__(
        self,
        registries: Mapping[str, str],
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        """``registries``: partner BPNL → DTR URL including the API path (``…/api/v3``)."""
        super().__init__(session, timeout)
        self._registries = dict(registries)

    def find_twin(self, partner: Partner, global_asset_id: str) -> TwinRef | None:
        base = self._registries.get(partner.bpnl)
        if not base:
            raise DataspaceError(f"no registry URL for {partner.bpnl} (CXS_DEV_PARTNER_DTRS)")
        base = base.rstrip("/")
        asset_id = json.dumps({"name": "globalAssetId", "value": global_asset_id})
        lookup = self.get_json(
            f"{base}/lookup/shells", params={"assetIds": encode_as_base64_url_safe(asset_id)}
        )
        ids = (lookup or {}).get("result") or []
        if not ids:
            return None
        descriptor = self.get_json(f"{base}/shell-descriptors/{encode_as_base64_url_safe(ids[0])}")
        return twin_from_descriptor(descriptor) if descriptor else None

    def read_submodel(self, partner: Partner, ref: SubmodelRef) -> dict[str, Any]:
        payload = self.get_json(value_url(ref))
        if not isinstance(payload, dict):
            raise DataspaceError(f"submodel at {ref.href} is missing or not a JSON object")
        return payload


class DirectNotificationSender(_Http):
    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(session, timeout)
        self._headers = {"X-Api-Key": api_key} if api_key else {}

    def send(
        self, partner: Partner, asset_type: str, build: Callable[[str], dict[str, Any]]
    ) -> str:
        operation = "receive" if "#Receive" in asset_type else "update"
        url = f"{partner.connector_address.rstrip('/')}/api/qualitynotifications/{operation}"
        try:
            response = self._session.post(
                url, json=build(API_VERSION), headers=self._headers, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise DataspaceError(f"POST {url} failed: {exc}") from exc
        if not response.ok:
            raise NotificationRejected(partner.bpnl, response.status_code, response.text[:500])
        return API_VERSION
