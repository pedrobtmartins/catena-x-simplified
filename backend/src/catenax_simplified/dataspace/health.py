"""Connectivity checks against a direct partner's connector, step by step.

Three levels, each including the previous one:

- ``discovery``: connector discovery of the partner's DSP endpoint (read-only);
- ``catalog``: the partner's catalog offers a Digital Twin Registry asset and the notification
  assets we need, in a Notification API version we speak (read-only);
- ``full``: negotiate for the registry asset and read one shell descriptor with the access token.
  This creates a contract negotiation and a transfer process in both connectors, so callers must
  ask for confirmation first.

Every check starts with fresh connector discovery; negotiated contracts and EDRs are still reused
through the SDK's connection manager, as for partner reads.

Each step records how long it took and, when it fails or warns, what the own EDC's management API
actually answered (``edc_trace``), why a negotiation or transfer was ended (the EDC's
``errorDetail``) and a likely cause, so the error says more than the SDK's status code.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

import requests

from ..notifications.messages import NotificationType
from .edc import DCT_TYPE_KEY, DCT_TYPE_KEYS, ConnectorConsumer, EdcNegotiator, Partner, equals
from .edc_trace import Exchange, edc_reason, install, recording
from .notifications import choose_offer, offers_in
from .partners import DTR_ASSET_TYPE
from .ports import DataspaceError

LEVELS = ("discovery", "catalog", "full")

_ALERT, _INVESTIGATION = NotificationType.ALERT, NotificationType.INVESTIGATION
# The partner's notification assets we need, by its role: a supplier receives our investigations
# and updates of its alerts; a customer receives our alerts and updates of its investigations.
NOTIFICATION_TYPES = {
    "supplier": (_INVESTIGATION.asset_type("receive"), _ALERT.asset_type("update")),
    "customer": (_ALERT.asset_type("receive"), _INVESTIGATION.asset_type("update")),
}

_SECRET = re.compile(
    r"(?i)\b(authorization|access[_-]?token|token|secret|password|api[_-]?key|x-api-key)"
    r"(\s*[:=]\s*|\"\s*:\s*\")[\"']?[^\s\"',}]+"
)
_JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*")
_SCHEME = re.compile(r"(?i)\b(bearer|basic)\s+[\w.~+/=-]+")


def scrub(text: str, limit: int = 500) -> str:
    """Remove credentials from an error message before it is stored or shown."""
    text = _SCHEME.sub(lambda m: f"{m.group(1)} [redacted]", _JWT.sub("[redacted]", text))
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)[:limit]


@dataclass(frozen=True)
class CheckStep:
    """One step of a connector check and how it went."""

    key: str  # discovery | dtr_offer | notification:<dct:type name> | registry_access
    name: str
    status: str  # ok | warn | failed | skipped
    detail: str
    # duration_ms; on a failure or warning also reason (what the EDC said), cause (a likely
    # explanation), calls (the failed management API calls) and calls_total.
    info: dict[str, Any] | None = None


class PartnerHealthChecker(Protocol):
    """Checks a partner's connector, step by step."""

    def check(
        self, partner: Partner, level: str, notification_types: Sequence[str]
    ) -> list[CheckStep]:
        """Run the checks of ``level``; ``notification_types`` are the ``dct:type``s of the
        partner's notification assets this company needs. Never raises for partner failures."""
        ...


# The SDK reports the answer of the own EDC's management API as the "EDC provider's" response
# code; a 5xx there means the own connector failed or timed out, whoever the partner is.
_OWN_CONNECTOR_ERROR = re.compile(r"Response code: \[(5\d\d)\]")


# A likely cause from what was said, first match wins: (words in the answers, explanation).
_CAUSES: list[tuple[tuple[str, ...], str]] = [
    (
        ("no accepted usage policies",),
        "Set the usage policies your company accepts on the Setup page.",
    ),
    (
        ("timed out", "timeout", "read time out", "gateway time-out"),
        "The partner's connector did not answer in time: it may be down or overloaded, or a "
        "firewall drops the connection. Try again later; if it persists, ask the partner to check "
        "their connector.",
    ),
    (
        (
            "unknownhost",
            "unknown host",
            "name or service not known",
            "could not resolve",
            "nodename nor servname",
            "no such host",
        ),
        "Your connector cannot resolve the partner's DSP address: check it for typos, or find the "
        "current one with connector discovery.",
    ),
    (
        ("connection refused", "connectexception", "no route to host"),
        "Nothing answers at the partner's DSP address: the connector is down, or the address or "
        "port is wrong.",
    ),
    (
        ("pkix", "certificate", "sslhandshake", "ssl handshake", "tls handshake"),
        "TLS failed between your connector and the partner's: an expired or untrusted certificate "
        "on either side.",
    ),
    (
        (
            "unauthorized",
            "forbidden",
            "not authorized",
            "credential",
            "verifiable presentation",
            "invalid token",
            "http 401",
            "http 403",
            "[401]",
            "[403]",
        ),
        "The partner's connector did not accept your identity: your membership or BPN credential "
        "in the wallet, or the partner's access policy for your BPNL. Ask the partner whether your "
        "BPNL is allowed, and check your wallet credentials.",
    ),
    (
        ("terminated", "policy", "contract offer", "constraint"),
        "The partner's connector ended the contract negotiation: usually the policy we accept does "
        "not match the one offered, or a constraint (FrameworkAgreement, Membership, BPNL, usage "
        "purpose) is not met. The partner's reason, if it gave one, is above.",
    ),
]


def likely_cause(step: CheckStep, failed: Sequence[Exchange], reason: str | None) -> str | None:
    """A likely explanation of a failed step from the EDC's answers, or ``None``."""
    if any(c.status in (401, 403) for c in failed):
        return (
            "Your connector's management API refused the app's credentials: check the EDC API key "
            "or OAuth client on the Setup page, and run its connection test."
        )
    text = " ".join([step.detail, reason or "", *(c.response for c in failed)]).lower()
    for words, cause in _CAUSES:
        if any(word in text for word in words):
            return cause
    statuses = {c.status for c in failed} | {
        int(m.group(1)) for m in _OWN_CONNECTOR_ERROR.finditer(step.detail)
    }
    if step.key == "discovery" and 404 in statuses:
        return (
            "No DSP endpoint answered at the partner's address: check the path (often ends in "
            "/api/v1/dsp)."
        )
    server_errors = sorted(code for code in statuses if code >= 500)
    if server_errors and not reason:
        return (
            f"Your connector's management API answered HTTP {server_errors[0]} without saying why: "
            "your connector failed, or gave up waiting for the partner's. If other partners fail "
            "the same way, check your EDC with the connection test on the Setup page."
        )
    if server_errors:
        return (
            f"Your connector could not get an answer from the partner's (HTTP {server_errors[0]}); "
            "what it reported is above."
        )
    return None


def notification_types(roles: Sequence[str]) -> list[str]:
    """``dct:type``s for these roles; a partner without known roles needs all four."""
    selected = roles or list(NOTIFICATION_TYPES)
    return [t for role in selected for t in NOTIFICATION_TYPES[role]]


def _short(asset_type: str) -> str:
    return asset_type.rsplit("#", 1)[-1]


def dataset_ids(catalog: Any) -> list[str]:
    """The ``@id`` of every dataset in a (possibly nested or federated) DCAT catalog."""

    def walk(node: Any, in_dataset: bool) -> Iterator[str]:
        if isinstance(node, list):
            for item in node:
                yield from walk(item, in_dataset)
        elif isinstance(node, dict):
            if in_dataset and (node.get("@id") or node.get("id")):
                yield str(node.get("@id") or node.get("id"))
            for key, value in node.items():
                name = key.split(":")[-1].split("#")[-1]
                if name in ("dataset", "catalog"):
                    yield from walk(value, name == "dataset")

    return list(dict.fromkeys(walk(catalog, False)))


def _skipped(key: str, name: str, reason: str) -> CheckStep:
    return CheckStep(key, name, "skipped", reason)


class EdcHealthChecker:
    """Checks a partner's connector through the own EDC with the same calls the app uses:
    discovery, the catalog's DTR and notification offers, and (``full``) a DTR negotiation
    and one shell lookup through the EDR.
    """

    def __init__(
        self,
        consumer: ConnectorConsumer,
        accepted_policies: list[dict] | None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ):
        self._consumer = consumer
        self._policies = accepted_policies
        self._session = session or requests.Session()
        self._timeout = timeout
        install(consumer)

    def check(
        self, partner: Partner, level: str, notification_types: Sequence[str]
    ) -> list[CheckStep]:
        """The steps of ``level`` (``discovery``, ``catalog`` or ``full``, each including the
        previous one); a failed step skips the rest.
        """
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        # A new negotiator per check: discovery is not served from an earlier check's cache.
        edc = EdcNegotiator(self._consumer, self._policies)
        steps = [self._traced(lambda: self._discovery(edc, partner))]
        reachable = steps[0].status == "ok"
        if level in ("catalog", "full"):
            if reachable:
                steps.append(self._traced(lambda: self._dtr_offer(edc, partner)))
                steps.extend(
                    self._traced(lambda t=t: self._notification_offer(edc, partner, t))
                    for t in notification_types
                )
            else:
                steps.append(_skipped("dtr_offer", "Digital Twin Registry offer", "not reachable"))
                steps.extend(
                    _skipped(f"notification:{_short(t)}", _short(t), "not reachable")
                    for t in notification_types
                )
        if level == "full":
            if reachable and steps[1].status == "ok":
                steps.append(self._traced(lambda: self._registry_access(edc, partner)))
            else:
                steps.append(
                    _skipped("registry_access", "Registry access (EDR)", "no registry offer")
                )
        return steps

    def _traced(self, run: Callable[[], CheckStep]) -> CheckStep:
        """``run()``, with how long it took and, for a failure or warning, what the own EDC
        answered."""
        started = time.monotonic()
        with recording() as calls:
            step = run()
        info: dict[str, Any] = {"duration_ms": int((time.monotonic() - started) * 1000)}
        if step.status in ("failed", "warn"):
            info.update(self._failure_details(step, calls))
        return replace(step, info=info)

    def _failure_details(self, step: CheckStep, calls: Sequence[Exchange]) -> dict[str, Any]:
        failed = [c for c in calls if not c.ok]
        reasons = [r for c in reversed(failed) if (r := edc_reason(c.response))]
        reason = reasons[0] if reasons else None
        ended = self._why_ended(step.detail, calls)
        if ended:
            reason = f"{reason}; {ended}" if reason else ended
        details: dict[str, Any] = {
            "calls_total": len(calls),
            "calls": [
                {
                    "method": c.method,
                    "url": c.url,
                    "status": c.status,
                    "elapsed_ms": c.elapsed_ms,
                    "request": scrub(c.request, 1500),
                    "response": scrub(c.response, 1500),
                }
                for c in failed[-5:]
            ],
        }
        if reason:
            details["reason"] = scrub(reason, 800)
        if cause := likely_cause(step, failed, reason):
            details["cause"] = cause
        return details

    def _why_ended(self, detail: str, calls: Sequence[Exchange]) -> str | None:
        """Why the own EDC ended a negotiation or transfer (its ``errorDetail``), when the
        error names one."""
        if match := re.search(r"Negotiation \[([\w:-]+)\]", detail):
            return self._error_detail("contract_negotiations", "negotiation", match.group(1))
        if "edr" in detail.lower():
            for call in reversed(calls):
                if match := re.search(r"/edrs/([^/]+)/dataaddress", call.url):
                    return self._error_detail("transfer_processes", "transfer", match.group(1))
        return None

    def _error_detail(self, controller: str, what: str, oid: str) -> str | None:
        try:
            response = getattr(self._consumer, controller).get_by_id(oid)
            data = response.json() if response is not None and response.ok else {}
        except Exception:  # best effort: the check's own result stands without it
            return None
        state = data.get("state") or data.get("edc:state")
        error = data.get("errorDetail") or data.get("edc:errorDetail")
        if not (state or error):
            return None
        return f"{what} {oid} {state or ''}{f': {error}' if error else ''}".strip()

    def _discovery(self, edc: EdcNegotiator, partner: Partner) -> CheckStep:
        name = "Connector discovery"
        try:
            address, counter_party_id, protocol = edc.counter_party(
                partner.bpnl, partner.connector_address
            )
        except DataspaceError as exc:
            return CheckStep("discovery", name, "failed", scrub(str(exc)))
        return CheckStep(
            "discovery", name, "ok", f"{protocol} at {address} (counter-party {counter_party_id})"
        )

    def _catalog_ids(self, edc: EdcNegotiator, partner: Partner, asset_type: str) -> Any:
        """The catalog filtered by ``dct:type``, trying both Dublin Core namespaces."""
        catalog: Any = None
        for key in DCT_TYPE_KEYS:
            catalog = edc.catalog(
                partner.bpnl, partner.connector_address, [equals(key, asset_type)]
            )
            if dataset_ids(catalog):
                return catalog
        return catalog

    def _dtr_offer(self, edc: EdcNegotiator, partner: Partner) -> CheckStep:
        name = "Digital Twin Registry offer"
        try:
            ids = dataset_ids(self._catalog_ids(edc, partner, DTR_ASSET_TYPE))
        except DataspaceError as exc:
            return CheckStep("dtr_offer", name, "failed", scrub(str(exc)))
        if not ids:
            return CheckStep("dtr_offer", name, "failed", "no DigitalTwinRegistry asset offered")
        return CheckStep("dtr_offer", name, "ok", f"{len(ids)} offered: {', '.join(ids[:3])}")

    def _notification_offer(
        self, edc: EdcNegotiator, partner: Partner, asset_type: str
    ) -> CheckStep:
        key, name = f"notification:{_short(asset_type)}", _short(asset_type)
        try:
            offers = offers_in(self._catalog_ids(edc, partner, asset_type))
        except DataspaceError as exc:
            return CheckStep(key, name, "failed", scrub(str(exc)))
        if not offers:
            return CheckStep(key, name, "warn", "not offered in the partner's catalog")
        offer = choose_offer(offers)
        if offer is None:
            offered = ", ".join(sorted({o.offered_version or "?" for o in offers}))
            return CheckStep(key, name, "warn", f"no compatible version (offered: {offered})")
        return CheckStep(key, name, "ok", f"Notification API {offer.api_version}")

    def _registry_access(self, edc: EdcNegotiator, partner: Partner) -> CheckStep:
        name = "Registry access (EDR)"
        try:
            endpoint, token = edc.negotiate(
                partner.bpnl, partner.connector_address, [equals(DCT_TYPE_KEY, DTR_ASSET_TYPE)]
            )
        except DataspaceError as exc:
            return CheckStep("registry_access", name, "failed", scrub(str(exc)))
        url = f"{endpoint.rstrip('/')}/shell-descriptors"
        try:
            response = self._session.get(
                url,
                params={"limit": 1},
                headers={"Authorization": token, "Accept": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            return CheckStep("registry_access", name, "failed", scrub(f"GET {url} failed: {exc}"))
        if not response.ok:
            return CheckStep(
                "registry_access",
                name,
                "failed",
                f"access token obtained, but the registry answered HTTP {response.status_code}",
            )
        return CheckStep("registry_access", name, "ok", "access token obtained; registry answered")


class DirectHealthChecker:
    """Development only (``CXS_DEV_DIRECT``): checks the partner app and registry over plain
    HTTP. Nothing here is a dataspace check."""

    def __init__(
        self,
        registries: Mapping[str, str],
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ):
        self._registries = dict(registries)
        self._session = session or requests.Session()
        self._timeout = timeout

    def _get(self, url: str, **params: Any) -> tuple[bool, str]:
        try:
            response = self._session.get(url, params=params or None, timeout=self._timeout)
        except requests.RequestException as exc:
            return False, scrub(f"GET {url} failed: {exc}")
        if not response.ok:
            return False, f"GET {url} returned HTTP {response.status_code}"
        return True, f"{url} answered (development mode, no EDC)"

    def check(
        self, partner: Partner, level: str, notification_types: Sequence[str]
    ) -> list[CheckStep]:
        """Development mode: probes the partner app and its registry directly and reports the
        dataspace steps as skipped.
        """
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        ok, detail = self._get(f"{partner.connector_address.rstrip('/')}/api/health")
        steps = [CheckStep("discovery", "Partner app", "ok" if ok else "failed", detail)]
        # At every level: nothing went through an EDC, so the connector is never "healthy" here.
        steps.append(
            _skipped("edc_discovery", "Connector discovery (EDC)", "no EDC in development mode")
        )
        if level in ("catalog", "full"):
            registry = self._registries.get(partner.bpnl)
            if not registry:
                steps.append(
                    CheckStep(
                        "dtr_offer",
                        "Partner registry",
                        "failed",
                        "no registry URL (CXS_DEV_PARTNER_DTRS)",
                    )
                )
            else:
                ok, detail = self._get(f"{registry.rstrip('/')}/shell-descriptors", limit=1)
                steps.append(
                    CheckStep("dtr_offer", "Partner registry", "ok" if ok else "failed", detail)
                )
            steps.extend(
                _skipped(f"notification:{_short(t)}", _short(t), "no catalog without an EDC")
                for t in notification_types
            )
        if level == "full":
            steps.append(
                _skipped("registry_access", "Registry access (EDR)", "no EDR without an EDC")
            )
        return steps
