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

    # Optional OAuth2 client credentials (Keycloak) for the DTR.
    oauth_url: str | None = None
    oauth_realm: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None

    # Own submodels: rewrite the public data plane prefix of an href to the internal backend.
    submodel_href_rewrites: list[tuple[str, str]] = []
    submodel_headers: dict[str, str] = {}

    # Own EDC (Tractus-X connector 0.12, Saturn) for reading direct partners' twins.
    edc_management_url: str | None = None  # e.g. https://edc.example.com
    edc_management_path: str = "/management"
    edc_api_key: str | None = None  # sent as X-Api-Key
    # Usage policies the company accepts, as offered in partners' catalogs (JSON list of policy
    # bodies without @id/@type). Empty = negotiate nothing.
    accepted_policies: list[dict] = []
    # Accept any offered policy. Development only; never in production.
    accept_any_policy: bool = False
    # Partners' DSP endpoints by BPNL (JSON object); addresses set through the API win.
    partner_connectors: dict[str, str] = {}

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

    # Periodic sync of own twins (and partners, when an EDC is configured); 0 disables it
    # (both can still be triggered through the API).
    sync_interval_seconds: int = 0

    # Directory with the built web UI; served at "/" when set.
    web_dist_dir: str | None = None
