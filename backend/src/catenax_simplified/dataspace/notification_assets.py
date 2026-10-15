"""Publishing our notification endpoints as assets in our own EDC (Traceability KIT).

One asset per ``dct:type`` and Notification API version we accept (4 types x 1.2.1/2.0.0), all
pointing to the same two endpoints: the parser reads both versions. Each asset gets a contract
definition with the configured access and usage policies. Publishing is idempotent: existing
entries are updated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from tractusx_sdk.dataspace.models.connector.model_factory import ModelFactory

from ..notifications.messages import API_VERSIONS, NotificationType
from .edc import ASSET_ID_KEY
from .ports import DataspaceError

log = logging.getLogger(__name__)

ASSET_CONTEXT = {
    "edc": "https://w3id.org/edc/v0.0.1/ns/",
    "cx-common": "https://w3id.org/catenax/ontology/common#",
    "cx-taxo": "https://w3id.org/catenax/taxonomy#",
    "dct": "http://purl.org/dc/terms/",
}

# CX-0152 (Saturn) policies, Catena-X ODRL profile 2025-9.
DEFAULT_ACCESS_PERMISSIONS: list[dict[str, Any]] = [
    {
        "action": "access",
        "constraint": {
            "and": [{"leftOperand": "Membership", "operator": "eq", "rightOperand": "active"}]
        },
    }
]
DEFAULT_USAGE_PERMISSIONS: list[dict[str, Any]] = [
    {
        "action": "use",
        "constraint": {
            "and": [
                {
                    "leftOperand": "FrameworkAgreement",
                    "operator": "eq",
                    "rightOperand": "DataExchangeGovernance:1.0",
                },
                {
                    "leftOperand": "UsagePurpose",
                    "operator": "isAnyOf",
                    "rightOperand": ["cx.core.qualityNotifications:1"],
                },
            ]
        },
    }
]


class ConnectorProvider(Protocol):
    """The subset of the Tractus-X SDK's Saturn ``ConnectorProviderService`` used here."""

    assets: Any
    policies: Any
    contract_definitions: Any


@dataclass(frozen=True)
class NotificationAsset:
    asset_id: str
    dct_type: str
    version: str
    url: str


def notification_assets(base_url: str, prefix: str) -> list[NotificationAsset]:
    """``base_url``: where our EDC's data plane reaches this app, e.g. ``http://app:8000``."""
    base = base_url.rstrip("/")
    assets = []
    for operation in ("receive", "update"):
        for type_ in NotificationType:
            for version in API_VERSIONS:
                assets.append(
                    NotificationAsset(
                        asset_id=f"{prefix}-{operation}-{type_.value}-{version}",
                        dct_type=type_.asset_type(operation),
                        version=version,
                        url=f"{base}/api/qualitynotifications/{operation}",
                    )
                )
    return assets


class NotificationAssetPublisher:
    def __init__(
        self,
        provider: ConnectorProvider,
        base_url: str,
        *,
        prefix: str = "cxs-qualitynotification",
        headers: dict[str, str] | None = None,
        access_permissions: list[dict] | None = None,
        usage_permissions: list[dict] | None = None,
    ):
        self._provider = provider
        self._base_url = base_url
        self._prefix = prefix
        self._headers = headers or {}
        self._access = access_permissions or DEFAULT_ACCESS_PERMISSIONS
        self._usage = usage_permissions or DEFAULT_USAGE_PERMISSIONS

    def _upsert(self, controller: Any, model: Any, what: str, *, by_id: str | None = None) -> None:
        response = controller.create(obj=model)
        if response.status_code == 409:
            if by_id:
                # The EDC updates policy definitions only at their ID (PUT on the collection is
                # 405), while the SDK's update() always uses the collection.
                response = controller.adapter.put(
                    url=f"{controller.endpoint_url}/{by_id}", data=model.to_data()
                )
            else:
                response = controller.update(obj=model)
        if response.status_code not in (200, 204):
            raise DataspaceError(
                f"could not publish {what}: HTTP {response.status_code} {response.text[:300]}"
            )

    def publish(self) -> list[str]:
        """Create or update the policies, assets and contract definitions; returns asset IDs."""
        access_id, usage_id = f"{self._prefix}-access", f"{self._prefix}-usage"
        for oid, permissions in ((access_id, self._access), (usage_id, self._usage)):
            policy = ModelFactory.get_policy_model(
                dataspace_version="saturn", oid=oid, permissions=permissions
            )
            self._upsert(self._provider.policies, policy, f"policy {oid}", by_id=oid)

        published = []
        for asset in notification_assets(self._base_url, self._prefix):
            data_address = {
                "@type": "DataAddress",
                "type": "HttpData",
                "baseUrl": asset.url,
                "proxyMethod": "true",
                "proxyBody": "true",
                "proxyPath": "false",
                "proxyQueryParams": "false",
                "method": "POST",
                "contentType": "application/json",
            }
            for key, value in self._headers.items():
                data_address[f"header:{key}"] = value
            model = ModelFactory.get_asset_model(
                dataspace_version="saturn",
                oid=asset.asset_id,
                context=ASSET_CONTEXT,
                data_address=data_address,
                properties={
                    "dct:type": {"@id": asset.dct_type},
                    "cx-common:version": asset.version,
                },
            )
            self._upsert(self._provider.assets, model, f"asset {asset.asset_id}")
            contract = ModelFactory.get_contract_definition_model(
                dataspace_version="saturn",
                oid=f"{asset.asset_id}-contract",
                access_policy_id=access_id,
                contract_policy_id=usage_id,
                context={"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
                assets_selector=[
                    {"operandLeft": ASSET_ID_KEY, "operator": "=", "operandRight": asset.asset_id}
                ],
            )
            self._upsert(
                self._provider.contract_definitions, contract, f"contract for {asset.asset_id}"
            )
            published.append(asset.asset_id)
        log.info("published %d notification assets", len(published))
        return published
