"""Settings an admin enters in the UI, stored in the database.

Only the connection settings below can be entered here. A value set by the deployment (an
environment variable or the .env file) always wins and is shown as locked.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..storage import ConfigValueRow
from .security import SecretBox


@dataclass(frozen=True)
class ConfigField:
    key: str  # the Settings attribute; the variable is CXS_<KEY>
    group: str  # registry | connector | notifications | services
    label: str
    secret: bool = False
    url: bool = False
    hint: str = ""
    # Other settings that lock this one when the deployment sets them.
    locked_by: tuple[str, ...] = ()

    @property
    def variable(self) -> str:
        return f"CXS_{self.key.upper()}"


FIELDS: tuple[ConfigField, ...] = (
    ConfigField("dtr_base_url", "registry", "Registry address", url=True),
    ConfigField("dtr_api_path", "registry", "API path", hint="Usually /api/v3"),
    ConfigField(
        "oauth_token_url",
        "registry",
        "Token URL",
        url=True,
        hint="Leave empty if the registry needs no sign-in",
        # A Keycloak server from the deployment defines the token URL already.
        locked_by=("oauth_url",),
    ),
    ConfigField("oauth_client_id", "registry", "Client ID"),
    ConfigField("oauth_client_secret", "registry", "Client secret", secret=True),
    ConfigField(
        "oauth_scope", "registry", "Scope", hint="Only if your identity provider needs one"
    ),
    ConfigField(
        "edc_management_url",
        "connector",
        "Management API address",
        url=True,
        hint="The control plane, without the management path",
    ),
    ConfigField("edc_management_path", "connector", "Management path", hint="Usually /management"),
    ConfigField("edc_api_key", "connector", "API key", secret=True),
    ConfigField("edc_oauth_token_url", "connector", "Token URL", url=True),
    ConfigField("edc_oauth_client_id", "connector", "Client ID"),
    ConfigField("edc_oauth_client_secret", "connector", "Client secret", secret=True),
    ConfigField("edc_oauth_scope", "connector", "Scope"),
    ConfigField(
        "notification_base_url",
        "notifications",
        "Address of this app for your connector",
        url=True,
        hint="How your connector's data plane reaches this app inside your network",
    ),
    ConfigField("notification_api_key", "notifications", "Inbox key", secret=True),
    ConfigField(
        "central_idp_url",
        "services",
        "Central IdP address",
        url=True,
        hint="e.g. https://centralidp.example.com/auth/",
    ),
    ConfigField("central_idp_realm", "services", "Realm", hint="Usually CX-Central"),
    ConfigField("central_idp_client_id", "services", "Technical user (client ID)"),
    ConfigField("central_idp_client_secret", "services", "Client secret", secret=True),
    ConfigField("discovery_finder_url", "services", "Discovery Finder address", url=True),
    ConfigField("bpdm_pool_url", "services", "BPDM Pool address", url=True),
)
BY_KEY: dict[str, ConfigField] = {f.key: f for f in FIELDS}


def locked(base: Settings, field: ConfigField) -> bool:
    """Whether the deployment sets this field (or one that decides it)."""
    return any(k in base.model_fields_set for k in (field.key, *field.locked_by))


def effective_settings(base: Settings, stored: Mapping[str, str]) -> Settings:
    """The deployment's settings with the stored values filled in where the deployment set
    nothing."""
    update = {k: v for k, v in stored.items() if k in BY_KEY and not locked(base, BY_KEY[k])}
    return base.model_copy(update=update)


class ConfigStore:
    def __init__(self, session_factory: sessionmaker[Session], box: SecretBox | None):
        """Without a ``box`` (no CXS_SECRET_KEY) nothing can be stored or read."""
        self._session_factory = session_factory
        self._box = box

    @property
    def available(self) -> bool:
        return self._box is not None

    def rows(self) -> dict[str, ConfigValueRow]:
        with self._session_factory() as session:
            rows = session.scalars(select(ConfigValueRow)).all()
            session.expunge_all()
        return {row.key: row for row in rows if row.key in BY_KEY}

    def values(self) -> tuple[dict[str, str], list[str]]:
        """Stored values (secrets decrypted) and the keys whose secret cannot be decrypted any
        more (CXS_SECRET_KEY changed)."""
        if self._box is None:
            return {}, []
        values, unreadable = {}, []
        for key, row in self.rows().items():
            if row.secret:
                plain = self._box.decrypt(row.value)
                if plain is None:
                    unreadable.append(key)
                    continue
                values[key] = plain
            else:
                values[key] = row.value
        return values, unreadable

    def save(self, changes: Mapping[str, str | None], user: str) -> None:
        """Set (a string) or remove (``None``) stored values."""
        if self._box is None:
            raise RuntimeError("CXS_SECRET_KEY is not set")
        now = datetime.now(UTC)
        with self._session_factory() as session:
            for key, value in changes.items():
                field = BY_KEY[key]
                row = session.get(ConfigValueRow, key)
                if value is None:
                    if row is not None:
                        session.delete(row)
                    continue
                stored = self._box.encrypt(value) if field.secret else value
                if row is None:
                    row = ConfigValueRow(key=key)
                    session.add(row)
                row.value, row.secret, row.updated_at, row.updated_by = (
                    stored,
                    field.secret,
                    now,
                    user,
                )
            session.commit()
