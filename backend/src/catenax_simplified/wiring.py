"""Builds the infrastructure adapters from the settings."""

from __future__ import annotations

from tractusx_sdk.dataspace.managers import OAuth2Manager
from tractusx_sdk.dataspace.managers.connection.memory.memory_connection_manager import (
    MemoryConnectionManager,
)
from tractusx_sdk.dataspace.services.connector.service_factory import ServiceFactory
from tractusx_sdk.industry.services import AasService

from .config import Settings
from .dataspace.direct import DirectNotificationSender, DirectPartnerClient
from .dataspace.dtr import SdkTwinRegistry
from .dataspace.health import DirectHealthChecker, EdcHealthChecker
from .dataspace.notification_assets import NotificationAssetPublisher
from .dataspace.notifications import EdcNotificationSender
from .dataspace.partners import EdcPartnerClient
from .dataspace.submodels import HttpSubmodelReader


def build_twin_registry(settings: Settings) -> SdkTwinRegistry | None:
    if not settings.dtr_base_url:
        return None
    auth = None
    if settings.oauth_url:
        auth = OAuth2Manager(
            auth_url=settings.oauth_url,
            realm=settings.oauth_realm,
            clientid=settings.oauth_client_id,
            clientsecret=settings.oauth_client_secret,
        )
    service = AasService(
        base_url=settings.dtr_base_url,
        base_lookup_url=settings.dtr_lookup_url or settings.dtr_base_url,
        api_path=settings.dtr_api_path,
        auth_service=auth,
    )
    # Sent as Edc-Bpn: the DTR shows a shell's globalAssetId and specific asset IDs to its owner
    # and to the BPNs they are shared with; an anonymous call sees no shells at all.
    return SdkTwinRegistry(service, page_size=settings.dtr_page_size, bpn=settings.own_bpnl)


def build_submodel_reader(settings: Settings) -> HttpSubmodelReader:
    return HttpSubmodelReader(
        rewrites=settings.submodel_href_rewrites, headers=settings.submodel_headers
    )


def _edc_headers(settings: Settings) -> dict[str, str] | None:
    return {"X-Api-Key": settings.edc_api_key} if settings.edc_api_key else None


def _accepted_policies(settings: Settings) -> list[dict] | None:
    return None if settings.accept_any_policy else settings.accepted_policies


def build_edc_consumer(settings: Settings):
    """The Saturn consumer service of our EDC; ``None`` if no EDC is configured. One instance
    is shared by partner reads and notification sending."""
    if not settings.edc_management_url or settings.dev_direct:
        return None
    return ServiceFactory.get_connector_consumer_service(
        dataspace_version="saturn",
        base_url=settings.edc_management_url,
        dma_path=settings.edc_management_path,
        headers=_edc_headers(settings),
        # Negotiated contracts and EDRs are reused for the lifetime of the process.
        connection_manager=MemoryConnectionManager(),
        verbose=False,
    )


def build_partner_client(settings: Settings, consumer=None):
    if settings.dev_direct:
        return DirectPartnerClient(settings.dev_partner_dtrs) if settings.dev_partner_dtrs else None
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return EdcPartnerClient(consumer, accepted_policies=_accepted_policies(settings))


def build_notification_sender(settings: Settings, consumer=None):
    if settings.dev_direct:
        return DirectNotificationSender(settings.notification_api_key)
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return EdcNotificationSender(consumer, accepted_policies=_accepted_policies(settings))


def build_health_checker(settings: Settings, consumer=None):
    if settings.dev_direct:
        return DirectHealthChecker(settings.dev_partner_dtrs)
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return EdcHealthChecker(consumer, accepted_policies=_accepted_policies(settings))


def build_asset_publisher(settings: Settings) -> NotificationAssetPublisher | None:
    if settings.dev_direct or not (settings.edc_management_url and settings.notification_base_url):
        return None
    provider = ServiceFactory.get_connector_provider_service(
        dataspace_version="saturn",
        base_url=settings.edc_management_url,
        dma_path=settings.edc_management_path,
        headers=_edc_headers(settings),
        verbose=False,
    )
    return NotificationAssetPublisher(
        provider,
        settings.notification_base_url,
        prefix=settings.notification_asset_prefix,
        headers={"X-Api-Key": settings.notification_api_key}
        if settings.notification_api_key
        else None,
        access_permissions=settings.notification_access_policy or None,
        usage_permissions=settings.notification_usage_policy or None,
    )
