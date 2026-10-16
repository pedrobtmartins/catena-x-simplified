"""Digital Twin Registry access through the Tractus-X SDK."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Mapping
from typing import Any

from tractusx_sdk.industry.services import AasService

from .ports import DataspaceError, SubmodelRef, TwinRef

MANUFACTURER_ID_KEY = "manufacturerId"


def _first_endpoint(descriptor: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    for endpoint in descriptor.get("endpoints") or []:
        info = endpoint.get("protocolInformation") or {}
        if info.get("href"):
            return info["href"], endpoint.get("interface"), info.get("subprotocolBody")
    return None, None, None


def _semantic_id(descriptor: Mapping[str, Any]) -> str | None:
    keys = (descriptor.get("semanticId") or {}).get("keys") or []
    return keys[0].get("value") if keys else None


def twin_from_descriptor(shell: Mapping[str, Any]) -> TwinRef | None:
    """Translate an AAS v3 shell descriptor (JSON) into a :class:`TwinRef`.

    Shells without a ``globalAssetId`` are not Catena-X part twins and are skipped.
    """
    global_asset_id = shell.get("globalAssetId")
    if not global_asset_id:
        return None
    manufacturer_id = next(
        (
            s.get("value")
            for s in shell.get("specificAssetIds") or []
            if s.get("name") == MANUFACTURER_ID_KEY
        ),
        None,
    )
    submodels = []
    for descriptor in shell.get("submodelDescriptors") or []:
        semantic_id = _semantic_id(descriptor)
        href, interface, subprotocol_body = _first_endpoint(descriptor)
        if semantic_id and href:
            submodels.append(
                SubmodelRef(
                    semantic_id=semantic_id,
                    href=href,
                    interface=interface,
                    subprotocol_body=subprotocol_body,
                )
            )
    return TwinRef(
        aas_id=shell.get("id", ""),
        global_asset_id=global_asset_id,
        manufacturer_id=manufacturer_id,
        submodels=tuple(submodels),
    )


class SdkTwinRegistry:
    """Reads the shell descriptors of a DTR: all of them (following the pagination cursor), or
    single ones by AAS ID or by ``globalAssetId``."""

    def __init__(self, service: AasService, page_size: int = 100, bpn: str | None = None):
        self._service = service
        self._page_size = page_size
        self._bpn = bpn

    def iter_twins(self) -> Iterator[TwinRef]:
        cursor: str | None = None
        while True:
            try:
                page = self._service.get_all_asset_administration_shell_descriptors(
                    limit=self._page_size, cursor=cursor, bpn=self._bpn
                )
            except Exception as exc:  # network errors, invalid JSON, validation errors
                raise DataspaceError(f"DTR request failed: {exc}") from exc
            if not hasattr(page, "result"):
                raise DataspaceError(f"DTR returned an error: {page}")
            for shell in page.result or []:
                twin = twin_from_descriptor(shell.model_dump(by_alias=True, exclude_none=True))
                if twin is not None:
                    yield twin
            metadata = page.paging_metadata
            cursor = metadata.cursor if metadata else None
            if not cursor:
                return

    def get_twin(self, aas_id: str) -> TwinRef | None:
        """The twin with this AAS ID; None if the DTR does not have (or show) it."""
        try:
            shell = self._service.get_asset_administration_shell_descriptor_by_id(
                aas_id, bpn=self._bpn
            )
        except Exception as exc:
            raise DataspaceError(f"DTR request for {aas_id} failed: {exc}") from exc
        if not hasattr(shell, "model_dump") or not hasattr(shell, "id"):
            return None  # an error result (e.g. 404)
        return twin_from_descriptor(shell.model_dump(by_alias=True, exclude_none=True))

    def find_aas_ids(self, global_asset_id: str) -> list[str]:
        """The AAS IDs of the shells for a ``globalAssetId`` (DTR lookup API)."""
        asset_id = json.dumps({"name": "globalAssetId", "value": global_asset_id})
        encoded = base64.urlsafe_b64encode(asset_id.encode()).decode().rstrip("=")
        url = f"{self._service.aas_lookup_url}/lookup/shells"
        try:
            response = self._service.session.get(
                url,
                params={"assetIds": encoded},
                headers=self._service._prepare_headers(self._bpn),
                verify=self._service.verify_ssl,
                timeout=30,
            )
        except Exception as exc:
            raise DataspaceError(f"DTR lookup of {global_asset_id} failed: {exc}") from exc
        if response.status_code == 404:
            return []
        if not response.ok:
            raise DataspaceError(
                f"DTR lookup of {global_asset_id} failed: HTTP {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise DataspaceError(f"DTR lookup of {global_asset_id} returned no JSON") from exc
        ids = body.get("result", []) if isinstance(body, dict) else body
        return [i for i in ids or [] if isinstance(i, str)]
