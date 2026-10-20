"""Builds the infrastructure adapters from the settings."""

from __future__ import annotations

from tractusx_sdk.dataspace.managers.connection.memory.memory_connection_manager import (
    MemoryConnectionManager,
)
from tractusx_sdk.dataspace.services.connector.service_factory import ServiceFactory
from tractusx_sdk.industry.services import AasService

from .admin import AdminAuth
from .config import Settings
from .dataspace.business_partners import BpdmPool, BpExplorer, BusinessPartnerDirectory
from .dataspace.connections import ConnectionTester
from .dataspace.direct import DirectNotificationSender, DirectPartnerClient
from .dataspace.discovery import ConnectorDiscovery, EdcDiscovery, SdkConnectorDiscovery
from .dataspace.dtr import SdkTwinRegistry
from .dataspace.edc import Partner
from .dataspace.health import DirectHealthChecker, EdcHealthChecker
from .dataspace.notification_assets import NotificationAssetPublisher
from .dataspace.notifications import EdcNotificationSender
from .dataspace.oauth import ClientCredentials, authenticate_sdk_service, keycloak_token_url
from .dataspace.partners import EdcPartnerClient, parse_subprotocol_body
from .dataspace.ports import DataspaceError
from .dataspace.submodels import EdcFallbackSubmodelReader, HttpSubmodelReader


def dtr_auth(settings: Settings) -> ClientCredentials | None:
    """OAuth 2.0 client of the own DTR, if configured."""
    token_url = settings.oauth_token_url or (
        keycloak_token_url(settings.oauth_url, settings.oauth_realm or "")
        if settings.oauth_url
        else None
    )
    if not token_url:
        return None
    return ClientCredentials(
        token_url,
        settings.oauth_client_id or "",
        settings.oauth_client_secret or "",
        scope=settings.oauth_scope,
    )


def edc_auth(settings: Settings) -> ClientCredentials | None:
    """OAuth 2.0 client of the own EDC's management API, if configured."""
    if not settings.edc_oauth_token_url:
        return None
    return ClientCredentials(
        settings.edc_oauth_token_url,
        settings.edc_oauth_client_id or "",
        settings.edc_oauth_client_secret or "",
        scope=settings.edc_oauth_scope,
    )


def central_auth(settings: Settings) -> ClientCredentials | None:
    """The technical user of the central IdP, shared by the core services (discovery, BPDM)."""
    if not settings.central_idp_url:
        return None
    return ClientCredentials(
        keycloak_token_url(settings.central_idp_url, settings.central_idp_realm),
        settings.central_idp_client_id or "",
        settings.central_idp_client_secret or "",
    )


def build_twin_registry(settings: Settings) -> SdkTwinRegistry | None:
    """The own DTR client (Tractus-X SDK), or ``None`` without ``CXS_DTR_BASE_URL``."""
    if not settings.dtr_base_url:
        return None
    service = AasService(
        base_url=settings.dtr_base_url,
        base_lookup_url=settings.dtr_lookup_url or settings.dtr_base_url,
        api_path=settings.dtr_api_path,
        auth_service=dtr_auth(settings),
    )
    # Sent as Edc-Bpn: the DTR shows a shell's globalAssetId and specific asset IDs to its owner
    # and to the BPNs they are shared with; an anonymous call sees no shells at all.
    return SdkTwinRegistry(service, page_size=settings.dtr_page_size, bpn=settings.own_bpnl)


def build_submodel_reader(settings: Settings, partner_client=None):
    """Own submodels: read directly, and through the own EDC where the public data plane
    refuses that (``partner_client``: the EDC client also used for partners; the own BPNL is
    the counterparty of that negotiation)."""
    direct = HttpSubmodelReader(
        rewrites=settings.submodel_href_rewrites, headers=settings.submodel_headers
    )
    if not isinstance(partner_client, EdcPartnerClient):
        return direct
    own_bpnl = settings.own_bpnl

    def read_via_edc(ref):
        if "dspEndpoint" not in parse_subprotocol_body(ref.subprotocol_body):
            raise DataspaceError(
                f"submodel at {ref.href} names no dspEndpoint of the own connector"
            )
        return partner_client.read_submodel(Partner(own_bpnl, ""), ref)

    return EdcFallbackSubmodelReader(direct, read_via_edc)


def _edc_headers(settings: Settings) -> dict[str, str] | None:
    return {"X-Api-Key": settings.edc_api_key} if settings.edc_api_key else None


def _accepted_policies(settings: Settings) -> list[dict] | None:
    return None if settings.accept_any_policy else settings.accepted_policies


def build_edc_consumer(settings: Settings):
    """The Saturn consumer service of our EDC; ``None`` if no EDC is configured. One instance
    is shared by partner reads and notification sending."""
    if not settings.edc_management_url or settings.dev_direct:
        return None
    consumer = ServiceFactory.get_connector_consumer_service(
        dataspace_version="saturn",
        base_url=settings.edc_management_url,
        dma_path=settings.edc_management_path,
        headers=_edc_headers(settings),
        # Negotiated contracts and EDRs are reused for the lifetime of the process.
        connection_manager=MemoryConnectionManager(),
        verbose=False,
    )
    return _with_edc_auth(consumer, settings)


def _with_edc_auth(service, settings: Settings):
    auth = edc_auth(settings)
    if auth is not None:
        authenticate_sdk_service(service, auth)
    return service


def build_partner_client(settings: Settings, consumer=None):
    """How partners' twins are read: through the own EDC, or directly in development mode;
    ``None`` without either.
    """
    if settings.dev_direct:
        return DirectPartnerClient(settings.dev_partner_dtrs) if settings.dev_partner_dtrs else None
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return EdcPartnerClient(consumer, accepted_policies=_accepted_policies(settings))


def build_notification_sender(settings: Settings, consumer=None):
    """How notifications are delivered: through the own EDC, or directly in development mode;
    ``None`` without either.
    """
    if settings.dev_direct:
        return DirectNotificationSender(settings.notification_api_key)
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return EdcNotificationSender(consumer, accepted_policies=_accepted_policies(settings))


def build_health_checker(settings: Settings, consumer=None):
    """How partners' connectors are checked: through the own EDC, or the partner apps directly
    in development mode.
    """
    if settings.dev_direct:
        return DirectHealthChecker(settings.dev_partner_dtrs)
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return EdcHealthChecker(consumer, accepted_policies=_accepted_policies(settings))


def build_connector_discovery(
    settings: Settings, auth: ClientCredentials | None
) -> ConnectorDiscovery | None:
    """The EDC Discovery directly when its address is set, else through the Discovery Finder."""
    if settings.dev_direct or auth is None:
        return None
    if settings.edc_discovery_url:
        return EdcDiscovery(settings.edc_discovery_url, auth, dsp_path=settings.dsp_default_path)
    if settings.discovery_finder_url:
        return SdkConnectorDiscovery(
            settings.discovery_finder_url, auth, dsp_path=settings.dsp_default_path
        )
    return None


def build_bp_explorer(settings: Settings, consumer=None) -> BpExplorer | None:
    """The Business Partner Explorer through our EDC, if both are configured."""
    if settings.dev_direct or not settings.bp_explorer_address:
        return None
    consumer = consumer or build_edc_consumer(settings)
    if consumer is None:
        return None
    return BpExplorer(
        consumer,
        accepted_policies=_accepted_policies(settings),
        address=settings.bp_explorer_address,
        bpnl=settings.bp_explorer_bpnl,
        asset_id=settings.bp_explorer_asset_id,
    )


def build_partner_directory(
    settings: Settings, auth: ClientCredentials | None, consumer=None
) -> BusinessPartnerDirectory | None:
    """Where partners' legal names come from: the Business Partner Explorer if configured, else
    the BPDM Pool."""
    explorer = build_bp_explorer(settings, consumer)
    if explorer is not None:
        return explorer
    if not settings.bpdm_pool_url or auth is None:
        return None
    return BpdmPool(settings.bpdm_pool_url, auth)


def build_asset_publisher(settings: Settings) -> NotificationAssetPublisher | None:
    """Publishes the notification assets in the own EDC; ``None`` in development mode or
    without the EDC and ``CXS_NOTIFICATION_BASE_URL``.
    """
    if settings.dev_direct or not (settings.edc_management_url and settings.notification_base_url):
        return None
    provider = ServiceFactory.get_connector_provider_service(
        dataspace_version="saturn",
        base_url=settings.edc_management_url,
        dma_path=settings.edc_management_path,
        headers=_edc_headers(settings),
        verbose=False,
    )
    _with_edc_auth(provider, settings)
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


def build_connection_tester(settings: Settings, consumer=None) -> ConnectionTester:
    """The Setup page's connection tests, with their own credentials so every test asks for
    fresh tokens.
    """
    # Own OAuth clients, so a test always asks the IdPs for a fresh token; an own explorer client,
    # so a test always reads the catalog again.
    return ConnectionTester(
        settings,
        dtr_auth=dtr_auth(settings),
        edc_auth=edc_auth(settings),
        central_auth=central_auth(settings),
        bp_explorer=build_bp_explorer(settings, consumer),
    )


def build_admin_auth(settings: Settings) -> AdminAuth | None:
    """The admin login; ``None`` unless both the password hash and the secret key are set."""
    if not (settings.admin_password_hash and settings.secret_key):
        return None
    return AdminAuth(
        settings.admin_username,
        settings.admin_password_hash,
        settings.secret_key,
        settings.admin_session_hours,
    )
