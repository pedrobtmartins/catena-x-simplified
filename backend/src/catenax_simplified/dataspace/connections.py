"""Tests the connections to the participant's own services and the dataspace's core services.

Every call is read-only: a one-shell page of the DTR, a one-asset query of the EDC management
API, a token of the central IdP, the Discovery Finder's endpoint list, the own BPNL in BPDM and
the Business Partner Explorer's catalog (no negotiation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from ..config import Settings
from .business_partners import BpExplorer
from .health import scrub
from .ports import DataspaceError

EDC_NAMESPACE = "https://w3id.org/edc/v0.0.1/ns/"


@dataclass(frozen=True)
class ConnectionCheck:
    key: str  # dtr | edc | central_idp | discovery | bpdm | bp_explorer
    name: str
    status: str  # ok | failed | skipped | not_configured
    detail: str


class _Failed(Exception):
    pass


def _http_failure(response: requests.Response) -> str:
    if response.status_code in (401, 403):
        return f"HTTP {response.status_code}: the credentials were rejected"
    return f"HTTP {response.status_code}: {scrub(response.text, 200)}"


class ConnectionTester:
    def __init__(
        self,
        settings: Settings,
        dtr_auth: Any = None,
        edc_auth: Any = None,
        central_auth: Any = None,
        bp_explorer: BpExplorer | None = None,
        timeout: float = 15,
    ):
        """The ``*_auth`` objects are the OAuth clients the app itself uses (``token()``);
        ``bp_explorer``: the explorer client, if it and our EDC are configured."""
        self._settings = settings
        self._dtr_auth = dtr_auth
        self._edc_auth = edc_auth
        self._central_auth = central_auth
        self._bp_explorer = bp_explorer
        self._timeout = timeout

    def run(self) -> list[ConnectionCheck]:
        central = self._central_idp()
        central_ok = central.status == "ok"
        return [
            self._dtr(),
            self._edc(),
            central,
            self._discovery(central_ok),
            self._bpdm(central_ok),
            self._bp_explorer_offer(),
        ]

    def _bearer(self, auth: Any) -> dict[str, str]:
        if auth is None:
            return {}
        try:
            return {"Authorization": f"Bearer {auth.token()}"}
        except DataspaceError as exc:
            raise _Failed(scrub(str(exc))) from exc

    def _call(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            return requests.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            raise _Failed(f"{url} is not reachable: {scrub(str(exc), 300)}") from exc

    def _check(self, key: str, name: str, test) -> ConnectionCheck:
        try:
            return ConnectionCheck(key, name, "ok", test())
        except _Failed as exc:
            return ConnectionCheck(key, name, "failed", str(exc))

    def _dtr(self) -> ConnectionCheck:
        s = self._settings
        name = "Digital Twin Registry"
        if not s.dtr_base_url:
            return ConnectionCheck("dtr", name, "not_configured", "CXS_DTR_BASE_URL is not set")

        def test() -> str:
            headers = {"Edc-Bpn": s.own_bpnl, **self._bearer(self._dtr_auth)}
            url = f"{s.dtr_base_url.rstrip('/')}{s.dtr_api_path}/shell-descriptors"
            response = self._call("GET", url, params={"limit": 1}, headers=headers)
            if not response.ok:
                raise _Failed(_http_failure(response))
            how = "with an OAuth token" if self._dtr_auth else "without authentication"
            return f"The registry answered {how}."

        return self._check("dtr", name, test)

    def _edc(self) -> ConnectionCheck:
        s = self._settings
        name = "EDC management API"
        if s.dev_direct:
            return ConnectionCheck("edc", name, "not_configured", "Development mode: no EDC")
        if not s.edc_management_url:
            return ConnectionCheck(
                "edc", name, "not_configured", "CXS_EDC_MANAGEMENT_URL is not set"
            )

        def test() -> str:
            headers = self._bearer(self._edc_auth)
            if s.edc_api_key:
                headers["X-Api-Key"] = s.edc_api_key
            base = s.edc_management_url.rstrip("/") + s.edc_management_path
            body = {"@context": {"@vocab": EDC_NAMESPACE}, "@type": "QuerySpec", "limit": 1}
            response = self._call("POST", f"{base}/v3/assets/request", json=body, headers=headers)
            if not response.ok:
                raise _Failed(_http_failure(response))
            how = " and ".join(
                part
                for part, used in (
                    ("an OAuth token", self._edc_auth),
                    ("the API key", s.edc_api_key),
                )
                if used
            )
            return f"The management API answered with {how or 'no credentials'}."

        return self._check("edc", name, test)

    def _central_idp(self) -> ConnectionCheck:
        name = "Central IdP"
        if self._central_auth is None:
            return ConnectionCheck(
                "central_idp", name, "not_configured", "CXS_CENTRAL_IDP_URL is not set"
            )

        def test() -> str:
            self._bearer(self._central_auth)
            return "A token was issued for the technical user."

        return self._check("central_idp", name, test)

    def _needs_central(self, key: str, name: str, setting: str | None, variable: str):
        if not setting:
            return ConnectionCheck(key, name, "not_configured", f"{variable} is not set")
        if self._central_auth is None:
            return ConnectionCheck(key, name, "not_configured", "needs CXS_CENTRAL_IDP_URL")
        return None

    def _discovery(self, central_ok: bool) -> ConnectionCheck:
        s = self._settings
        name = "Connector discovery"
        missing = self._needs_central(
            "discovery",
            name,
            s.edc_discovery_url or s.discovery_finder_url,
            "CXS_EDC_DISCOVERY_URL or CXS_DISCOVERY_FINDER_URL",
        )
        if missing:
            return missing
        if not central_ok:
            return ConnectionCheck("discovery", name, "skipped", "needs a central IdP token")

        def test_edc_discovery() -> str:
            # The own BPNL: every participant's connector is registered there.
            response = self._call(
                "POST",
                s.edc_discovery_url,
                json=[s.own_bpnl],
                headers=self._bearer(self._central_auth),
            )
            if not response.ok:
                raise _Failed(_http_failure(response))
            try:
                entries = response.json()
            except ValueError as exc:
                raise _Failed("the EDC Discovery answered without JSON") from exc
            if not isinstance(entries, list):
                raise _Failed("the EDC Discovery did not answer with a list")
            own = [
                endpoint
                for entry in entries
                if isinstance(entry, dict) and entry.get("bpn") == s.own_bpnl
                for endpoint in entry.get("connectorEndpoint") or []
            ]
            registered = (
                f"{len(own)} connector(s) registered for {s.own_bpnl}"
                if own
                else (f"no connector registered yet for {s.own_bpnl}")
            )
            return f"EDC Discovery at {s.edc_discovery_url} answered: {registered}."

        if s.edc_discovery_url:
            return self._check("discovery", name, test_edc_discovery)

        def test() -> str:
            response = self._call(
                "POST",
                s.discovery_finder_url,
                json={"types": ["bpn"]},
                headers=self._bearer(self._central_auth),
            )
            if not response.ok:
                failure = _http_failure(response)
                if response.status_code == 400 and s.discovery_finder_url.rstrip("/").endswith(
                    "/connectors/discovery"
                ):
                    failure += (
                        " — this looks like the EDC Discovery's address: enter it as the EDC"
                        " Discovery address (CXS_EDC_DISCOVERY_URL) instead"
                    )
                raise _Failed(failure)
            endpoints = {
                e.get("type"): e.get("endpointAddress")
                for e in (response.json() or {}).get("endpoints") or []
            }
            if not endpoints.get("bpn"):
                raise _Failed("the Discovery Finder knows no EDC Discovery service (type bpn)")
            return f"EDC Discovery at {endpoints['bpn']}."

        return self._check("discovery", name, test)

    def _bpdm(self, central_ok: bool) -> ConnectionCheck:
        s = self._settings
        name = "Partner names (BPDM)"
        missing = self._needs_central("bpdm", name, s.bpdm_pool_url, "CXS_BPDM_POOL_URL")
        if missing:
            return missing
        if not central_ok:
            return ConnectionCheck("bpdm", name, "skipped", "needs a central IdP token")

        def test() -> str:
            url = f"{s.bpdm_pool_url.rstrip('/')}/v7/legal-entities/{s.own_bpnl}"
            response = self._call("GET", url, headers=self._bearer(self._central_auth))
            if response.status_code == 404:
                return "The pool answered, but your BPNL is not in it."
            if not response.ok:
                raise _Failed(_http_failure(response))
            legal_name = (response.json() or {}).get("legalName")
            return f"Your legal name: {legal_name}." if legal_name else "The pool answered."

        return self._check("bpdm", name, test)

    def _bp_explorer_offer(self) -> ConnectionCheck:
        s = self._settings
        name = "Partner names (Business Partner Explorer)"
        if not s.bp_explorer_address:
            return ConnectionCheck(
                "bp_explorer", name, "not_configured", "CXS_BP_EXPLORER_ADDRESS is not set"
            )
        if self._bp_explorer is None:
            return ConnectionCheck(
                "bp_explorer", name, "not_configured", "needs your EDC (CXS_EDC_MANAGEMENT_URL)"
            )
        explorer = self._bp_explorer

        def test() -> str:
            try:
                asset_id = explorer.find_offer()
            except DataspaceError as exc:
                raise _Failed(scrub(str(exc))) from exc
            return f"{explorer.bpnl} offers {asset_id}; names are read through your EDC."

        return self._check("bp_explorer", name, test)
