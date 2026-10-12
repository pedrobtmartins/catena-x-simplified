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

    # Periodic sync of own twins; 0 disables it (sync can still be triggered via the API).
    sync_interval_seconds: int = 0

    # Directory with the built web UI; served at "/" when set.
    web_dist_dir: str | None = None
