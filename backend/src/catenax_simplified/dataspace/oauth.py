"""OAuth 2.0 client credentials for the APIs the app calls (DTR, EDC management, core services).

Any token endpoint works (Keycloak, Entra ID, …). The token is fetched on first use, cached until
shortly before it expires, and shared by every request; nothing is contacted at startup.
"""

from __future__ import annotations

import threading
import time

import requests
from requests.auth import AuthBase
from tractusx_sdk.dataspace.adapters.adapter import Adapter

from .ports import DataspaceError

# Renew this many seconds before the token expires, so a request never carries a stale one.
EXPIRY_MARGIN = 30


def keycloak_token_url(server_url: str, realm: str) -> str:
    """The token endpoint of a Keycloak realm (``server_url`` with or without ``/auth/``)."""
    return f"{server_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"


class ClientCredentials(AuthBase):
    """A ``requests`` auth (``session.auth = …``) and the SDK's ``add_auth_header`` interface."""

    # The SDK's discovery services check this before asking for a header.
    connected = True

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None = None,
        timeout: float = 15,
    ):
        self.token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._timeout = timeout
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def token(self) -> str:
        """A bearer token, cached until shortly before it expires."""
        with self._lock:
            if self._token is None or time.monotonic() >= self._expires_at:
                self._token, lifetime = self._request()
                self._expires_at = time.monotonic() + max(lifetime - EXPIRY_MARGIN, 0)
            return self._token

    def _request(self) -> tuple[str, float]:
        data = {"grant_type": "client_credentials"}
        if self._scope:
            data["scope"] = self._scope
        try:
            response = requests.post(
                self.token_url,
                data=data,
                auth=(self._client_id, self._client_secret),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise DataspaceError(f"token request to {self.token_url} failed: {exc}") from exc
        if not response.ok:
            reason = ""
            try:
                body = response.json()
                reason = f" ({body.get('error_description') or body.get('error')})"
            except ValueError:
                pass
            raise DataspaceError(
                f"token request to {self.token_url} failed: HTTP {response.status_code}{reason}"
            )
        try:
            body = response.json()
            return body["access_token"], float(body.get("expires_in") or 300)
        except (ValueError, KeyError) as exc:
            raise DataspaceError(f"{self.token_url} returned no access token") from exc

    def add_auth_header(self, headers: dict | None = None) -> dict:
        """``headers`` with ``Authorization: Bearer …`` added."""
        return {**(headers or {}), "Authorization": f"Bearer {self.token()}"}

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self.token()}"
        return request


def authenticate_sdk_service(service: object, auth: AuthBase) -> int:
    """Attach ``auth`` to every HTTP session inside an SDK connector service and return how many
    there are. The SDK sets static headers once; a session auth adds a fresh token per request.
    A service holds several adapters (one per controller group), so all of them are walked."""
    seen: set[int] = set()
    adapters: list[Adapter] = []

    def walk(node: object, depth: int) -> None:
        if id(node) in seen or depth > 4:
            return
        seen.add(id(node))
        if isinstance(node, Adapter):
            adapters.append(node)
            return
        if isinstance(node, dict):
            children = list(node.values())
        elif isinstance(node, (list, tuple)):
            children = list(node)
        elif hasattr(node, "__dict__") and type(node).__module__.startswith("tractusx_sdk"):
            children = list(vars(node).values())
        else:
            return
        for child in children:
            walk(child, depth + 1)

    walk(service, 0)
    for adapter in adapters:
        adapter.session.auth = auth
    return len(adapters)
