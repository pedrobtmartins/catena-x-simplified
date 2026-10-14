"""Builds the infrastructure adapters from the settings."""

from __future__ import annotations

from tractusx_sdk.dataspace.managers import OAuth2Manager
from tractusx_sdk.dataspace.managers.connection.memory.memory_connection_manager import (
    MemoryConnectionManager,
)
from tractusx_sdk.dataspace.services.connector.service_factory import ServiceFactory
from tractusx_sdk.industry.services import AasService

from .config import Settings
from .dataspace.dtr import SdkTwinRegistry
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
    return SdkTwinRegistry(service, page_size=settings.dtr_page_size)


def build_submodel_reader(settings: Settings) -> HttpSubmodelReader:
    return HttpSubmodelReader(
        rewrites=settings.submodel_href_rewrites, headers=settings.submodel_headers
    )


def build_partner_client(settings: Settings) -> EdcPartnerClient | None:
    if not settings.edc_management_url:
        return None
    consumer = ServiceFactory.get_connector_consumer_service(
        dataspace_version="saturn",
        base_url=settings.edc_management_url,
        dma_path=settings.edc_management_path,
        headers={"X-Api-Key": settings.edc_api_key} if settings.edc_api_key else None,
        # Negotiated contracts and EDRs are reused for the lifetime of the process.
        connection_manager=MemoryConnectionManager(),
        verbose=False,
    )
    policies = None if settings.accept_any_policy else settings.accepted_policies
    return EdcPartnerClient(consumer, accepted_policies=policies)
