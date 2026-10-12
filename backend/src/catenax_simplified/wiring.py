"""Builds the infrastructure adapters from the settings."""

from __future__ import annotations

from tractusx_sdk.dataspace.managers import OAuth2Manager
from tractusx_sdk.industry.services import AasService

from .config import Settings
from .dataspace.dtr import SdkTwinRegistry
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
