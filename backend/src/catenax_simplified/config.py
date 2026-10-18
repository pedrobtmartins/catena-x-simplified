"""The application settings: one ``CXS_*`` variable each. ``backend/.env.example`` and
``backend/README.md`` describe them; an admin can fill the connection settings on the Setup
page.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from ``CXS_*`` environment variables (or a ``.env`` file).

    Complex values (lists, dicts) are given as JSON, e.g.
    ``CXS_SUBMODEL_HREF_REWRITES='[["https://edc.example/api/public", "http://submodels:8080"]]'``.
    """

    model_config = SettingsConfigDict(env_prefix="CXS_", env_file=".env", extra="ignore")

    own_bpnl: str = Field(pattern=r"^BPNL[0-9A-Za-z]{12}$")
    database_url: str = "sqlite:///./catenax-simplified.db"

    # Own Digital Twin Registry (AAS API v3).
    dtr_base_url: str | None = None
    dtr_lookup_url: str | None = None  # defaults to dtr_base_url
    dtr_api_path: str = "/api/v3"
    dtr_page_size: int = 100

    # Optional OAuth 2.0 client credentials for the own DTR: a Keycloak server and realm, or any
    # token endpoint (CXS_OAUTH_TOKEN_URL wins).
    oauth_url: str | None = None
    oauth_realm: str | None = None
    oauth_token_url: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_scope: str | None = None

    # Own submodels: rewrite the public data plane prefix of an href to the internal backend.
    submodel_href_rewrites: list[tuple[str, str]] = []
    submodel_headers: dict[str, str] = {}

    # Own EDC (Tractus-X connector 0.12, Saturn) for reading direct partners' twins.
    edc_management_url: str | None = None  # e.g. https://edc.example.com
    edc_management_path: str = "/management"
    edc_api_key: str | None = None  # sent as X-Api-Key
    # Or OAuth 2.0 client credentials for the management API (any token endpoint); both can be set.
    edc_oauth_token_url: str | None = None
    edc_oauth_client_id: str | None = None
    edc_oauth_client_secret: str | None = None
    edc_oauth_scope: str | None = None
    # Usage policies the company accepts, as offered in partners' catalogs (JSON list of policy
    # bodies without @id/@type). Empty = negotiate nothing.
    accepted_policies: list[dict] = []
    # Accept any offered policy. Development only; never in production.
    accept_any_policy: bool = False
    # Partners' DSP endpoints by BPNL (JSON object); addresses set through the API win.
    partner_connectors: dict[str, str] = {}

    # Central IdP of the dataspace (Keycloak, realm CX-Central): a technical user for the core
    # services below. Independent of the DTR's credentials.
    central_idp_url: str | None = None  # e.g. https://centralidp.example.com/auth/
    central_idp_realm: str = "CX-Central"
    central_idp_client_id: str | None = None
    central_idp_client_secret: str | None = None
    # Discovery Finder (…/api/v1.0/administration/connectors/discovery/search): finds partners'
    # DSP endpoints by BPNL.
    discovery_finder_url: str | None = None
    # EDC Discovery (…/api/administration/connectors/discovery): when set, asked directly, without
    # the Discovery Finder. Some operators publish only this address.
    edc_discovery_url: str | None = None
    # BPDM Pool API, up to the version segment (e.g. https://business-partners.example/pool/api):
    # partners' legal names by BPNL.
    bpdm_pool_url: str | None = None
    # Or a BPDM Pool offered through an EDC, such as the Cofinity-X Business Partner Explorer
    # (needs our EDC and a subscription): its DSP endpoint, the BPN of its connector and, if its
    # catalog offers us more than one asset, the asset to negotiate for. Wins over the BPDM Pool.
    bp_explorer_address: str | None = None
    bp_explorer_bpnl: str = Field(default="BPNLCOFINITYEZFA", pattern=r"^BPNL[0-9A-Za-z]{12}$")
    bp_explorer_asset_id: str | None = None

    # Quality notifications. Where our EDC's data plane reaches this app (e.g. http://app:8000);
    # when set with an EDC, the notification assets are published in our EDC at startup.
    notification_base_url: str | None = None
    # Required as X-Api-Key on the receiving endpoints; also put in the assets' data address so
    # our data plane sends it. Leave unset only if the endpoints are not reachable otherwise.
    notification_api_key: str | None = None
    notification_asset_prefix: str = "cxs-qualitynotification"
    # ODRL permissions (JSON) of the notification assets' access and usage policies; empty uses
    # the defaults (access: active membership; usage: DataExchangeGovernance:1.0 +
    # cx.core.qualityNotifications:1).
    notification_access_policy: list[dict] = []
    notification_usage_policy: list[dict] = []

    # Development only: reach partners without EDCs (local multi-participant demos). Partner
    # connector addresses are then the partner apps' base URLs; their twins are read from
    # CXS_DEV_PARTNER_DTRS (BPNL → DTR URL with API path). Never in a dataspace.
    dev_direct: bool = False
    dev_partner_dtrs: dict[str, str] = {}

    # Load only these own twins (for a test with a subset of a large DTR): AAS IDs, or text
    # containing them, e.g. a pasted CSV — every urn:uuid:… in it is taken; without any, the text
    # is split on whitespace, commas and semicolons. Own children in their bills of material are
    # followed. Empty: the whole DTR.
    sync_twin_ids: str | None = None
    # Periodic sync of own twins (and partners, when an EDC is configured); 0 disables it
    # (both can still be triggered through the API).
    sync_interval_seconds: int = 0

    # Administration. With CXS_ADMIN_PASSWORD_HASH and CXS_SECRET_KEY set, an admin signs in to
    # change the configuration and the partners; without them partners stay editable by anyone and
    # the configuration only through the deployment.
    admin_username: str = "admin"
    # python -m catenax_simplified.admin hash-password
    admin_password_hash: str | None = None
    # Signs admin sessions and encrypts secrets entered in the UI (python -m
    # catenax_simplified.admin secret-key). Keep it stable: another key cannot read the stored
    # secrets.
    secret_key: str | None = Field(default=None, min_length=32)
    admin_session_hours: int = Field(default=8, ge=1, le=24)

    # Directory with the built web UI; served at "/" when set.
    web_dist_dir: str | None = None

    # Directory of extra CA certificates (a company's private root) trusted next to certifi's
    # public CAs; the image sets /etc/catenax-simplified/ca-certificates. See trust.py.
    extra_ca_dir: str | None = None
