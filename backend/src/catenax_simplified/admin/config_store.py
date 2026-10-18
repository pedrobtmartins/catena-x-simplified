"""Settings an admin enters in the UI, stored in the database.

Only the connection settings below can be entered here. A value set by the deployment (an
environment variable or the .env file) always wins and is shown as locked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..dataspace.policies import same_policy
from ..storage import ConfigValueRow
from .security import SecretBox


@dataclass(frozen=True)
class ConfigField:
    """A connection setting an admin can enter on the Setup page, and how it is shown."""

    key: str  # the Settings attribute; the variable is CXS_<KEY>
    group: str  # registry | connector | notifications | services | names
    label: str
    secret: bool = False
    url: bool = False
    bpnl: bool = False
    # A list of twin IDs: entered as text (or a pasted CSV), stored one ID per line.
    twin_ids: bool = False
    hint: str = ""
    # Other settings that lock this one when the deployment sets them.
    locked_by: tuple[str, ...] = ()
    # A JSON list of usage policies, added to the deployment's instead of replacing them, so it
    # is never locked. Edited on its own Setup section, not with the other settings.
    policies: bool = False

    @property
    def variable(self) -> str:
        """The deployment's environment variable for this setting."""
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
        "sync_twin_ids",
        "registry",
        "Load only these twins",
        twin_ids=True,
        hint=(
            "For a test with part of a large registry: AAS IDs, one per line — or paste a CSV, "
            "every urn:uuid in it is taken. Their own children are loaded too. Empty: every twin."
        ),
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
    ConfigField(
        "edc_discovery_url",
        "services",
        "EDC Discovery address",
        url=True,
        hint="Instead of the Discovery Finder, e.g. …/api/administration/connectors/discovery",
    ),
    ConfigField("bpdm_pool_url", "services", "BPDM Pool address", url=True),
    ConfigField(
        "bp_explorer_address",
        "names",
        "Business Partner Explorer (DSP endpoint)",
        url=True,
        hint=(
            "Cofinity-X: https://business-partner-explorer-edc.dataspaceos.svc.cofinity-x.com"
            "/api/v1/dsp (pre-production: …dataspaceos.preprod.cofinity-x.com/api/v1/dsp)"
        ),
    ),
    ConfigField(
        "bp_explorer_bpnl", "names", "Its BPN", hint="Cofinity-X: BPNLCOFINITYEZFA", bpnl=True
    ),
    ConfigField(
        "bp_explorer_asset_id",
        "names",
        "Asset ID",
        hint="Only if its catalog offers you more than one asset",
    ),
)
POLICIES = ConfigField("accepted_policies", "policies", "Accepted usage policies", policies=True)
FIELDS = (*FIELDS, POLICIES)
BY_KEY: dict[str, ConfigField] = {f.key: f for f in FIELDS}

# Enough for every offer a company meets; keeps a pasted catalog from becoming a setting.
MAX_ADDED_POLICIES = 50


def parse_policies(stored: str | None) -> list[dict]:
    """The policies stored as a JSON list; anything else counts as none."""
    try:
        value = json.loads(stored or "[]")
    except ValueError:
        return []
    return [p for p in value if isinstance(p, dict)] if isinstance(value, list) else []


def merge_policies(deployment: list[dict], added: list[dict]) -> list[dict]:
    """The deployment's policies, then the added ones that mean something else."""
    merged = list(deployment)
    for policy in added:
        if not any(same_policy(policy, p) for p in merged):
            merged.append(policy)
    return merged


def locked(base: Settings, field: ConfigField) -> bool:
    """Whether the deployment sets this field (or one that decides it)."""
    if field.policies:
        return False
    return any(k in base.model_fields_set for k in (field.key, *field.locked_by))


def effective_settings(base: Settings, stored: Mapping[str, str]) -> Settings:
    """The deployment's settings with the stored values filled in where the deployment set
    nothing."""
    update: dict = {
        k: v
        for k, v in stored.items()
        if k in BY_KEY and not BY_KEY[k].policies and not locked(base, BY_KEY[k])
    }
    if stored.get(POLICIES.key):
        update[POLICIES.key] = merge_policies(
            base.accepted_policies, parse_policies(stored[POLICIES.key])
        )
    return base.model_copy(update=update)


class ConfigStore:
    """Settings entered on the Setup page, stored in the database (secrets encrypted with a
    key derived from ``CXS_SECRET_KEY``). They only fill what the deployment leaves unset.
    """

    def __init__(self, session_factory: sessionmaker[Session], box: SecretBox | None):
        """Without a ``box`` (no CXS_SECRET_KEY) nothing can be stored or read."""
        self._session_factory = session_factory
        self._box = box

    @property
    def available(self) -> bool:
        """Whether settings can be stored at all (``CXS_SECRET_KEY`` is set)."""
        return self._box is not None

    def rows(self) -> dict[str, ConfigValueRow]:
        """The stored settings by key; keys no longer known are ignored."""
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
