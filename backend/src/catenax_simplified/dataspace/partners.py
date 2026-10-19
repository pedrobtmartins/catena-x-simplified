"""Reading direct partners' twins through the dataspace (EDC + the partner's DTR).

Flow per the Industry Core / Digital Twin KITs:

1. negotiate for the partner's Digital Twin Registry asset (``dct:type`` DigitalTwinRegistry);
2. look the twin up by its Catena-X ID (``/lookup/shells``, or ``POST
   /lookup/shellsByAssetLink`` where the GET fails on the partner's side) and read its shell
   descriptor through the partner's data plane;
3. negotiate for the submodel's asset (``id`` in the descriptor's ``subprotocolBody``) at the
   ``dspEndpoint`` it names, and read ``{href}/$value`` with the access token.

Contract negotiations and access tokens are reused through the Tractus-X SDK's connection
manager; a negotiation happens only once per partner, asset and accepted policy set. On top of
that, the endpoint and token of an asset (the registry, or a submodel asset shared by many twins)
are kept until shortly before the token expires (its JWT ``exp``; ``token_ttl_seconds`` for a
token that does not say): reading the next submodel of that asset is then a plain GET, without
the catalog request and EDR lookup that even a reused negotiation costs. Threads reading the same
asset at once wait for one negotiation instead of each starting their own.

Reads through a partner's data plane are retried on what is usually passing (a connection that
fails, a timeout, HTTP 429/502/503/504), with a growing pause that honours ``Retry-After``.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

import requests
from requests.adapters import HTTPAdapter
from tractusx_sdk.dataspace.tools.encoding_tools import encode_as_base64_url_safe

from .dtr import twin_from_descriptor
from .edc import (
    ASSET_ID_KEY,
    DCT_TYPE_KEY,
    ConnectorConsumer,
    EdcNegotiator,
    Partner,
    equals,
)
from .ports import DataspaceError, SubmodelRef, TwinRef
from .submodels import value_url

log = logging.getLogger(__name__)

T = TypeVar("T")

DTR_ASSET_TYPE = "https://w3id.org/catenax/taxonomy#DigitalTwinRegistry"
# Answers worth trying again: the partner's side is busy or briefly unavailable.
RETRY_STATUSES = {429, 502, 503, 504}
# A token is renewed this long before it expires, so a read does not start with one about to.
TOKEN_EXPIRY_MARGIN_SECONDS = 30.0

__all__ = [
    "ASSET_ID_KEY",
    "DCT_TYPE_KEY",
    "DTR_ASSET_TYPE",
    "EdcPartnerClient",
    "Partner",
    "PartnerDataClient",
    "parse_subprotocol_body",
]


class PartnerDataClient(Protocol):
    """Reads direct partners' twins and submodels."""

    def find_twin(self, partner: Partner, global_asset_id: str) -> TwinRef | None:
        """The partner's twin with this Catena-X ID, or ``None`` if its registry has none."""
        ...

    def read_submodel(self, partner: Partner, ref: SubmodelRef) -> dict[str, Any]:
        """A submodel of a partner twin, in value-only serialization."""
        ...


def parse_subprotocol_body(body: str | None) -> dict[str, str]:
    """``"dspEndpoint=https://…;id=a1"`` → ``{"dspEndpoint": "https://…", "id": "a1"}``."""
    result: dict[str, str] = {}
    for part in (body or "").split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            result[key.strip()] = value.strip()
    return result


class DataPlaneError(DataspaceError):
    """A partner's data plane answered with an HTTP error."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def token_lifetime(token: str, now: float | None = None) -> float | None:
    """Seconds until a JWT access token expires (its ``exp``), or ``None`` if it does not say.
    The token is not verified: only its expiry is read, to know how long to reuse it."""
    raw = token.split()[-1] if token else ""
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = float(claims["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    return exp - (time.time() if now is None else now)


def _retry_after(response: requests.Response | None) -> float | None:
    value = response.headers.get("Retry-After") if response is not None else None
    try:
        return float(value) if value else None
    except ValueError:
        return None  # an HTTP date: use the own pause


def _data_plane_error(url: str, status: int, method: str = "GET") -> str:
    """A failed read through the partner's data plane, saying where it failed: this call already
    went through the EDC (the URL and token come from the EDR)."""
    message = (
        f"{method} {url} returned HTTP {status} "
        "from the partner's data plane (reached with the EDR)"
    )
    if status >= 500:
        return f"{message}: the partner's data plane or the service behind it failed"
    if status in (401, 403):
        return f"{message}: it refused the access token"
    return message


class EdcPartnerClient:
    """Reads direct partners' twins through the own EDC: negotiates for the partner's DTR,
    looks twins up by Catena-X ID, then negotiates for each submodel's asset at the
    ``dspEndpoint`` its descriptor names. Endpoint and token of an asset are reused until
    shortly before the token expires; passing failures are retried. Safe to use from several
    threads at once.
    """

    def __init__(
        self,
        consumer: ConnectorConsumer,
        accepted_policies: list[dict] | None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        token_ttl_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        connect_timeout: float = 10.0,
        retries: int = 2,
        retry_pause_seconds: float = 1.0,
        sleep: Callable[[float], None] | None = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        """``accepted_policies``: see ``EdcNegotiator``; ``None`` accepts any policy
        (development only). ``timeout``: for reading an answer, ``connect_timeout``: for
        reaching the data plane. ``token_ttl_seconds``: how long a token that names no expiry
        is reused. ``retries``: further tries of a read that failed in a passing way, after
        ``retry_pause_seconds``, then twice that, and so on."""
        self._edc = EdcNegotiator(consumer, accepted_policies)
        if session is None:
            session = requests.Session()
            # Partners and twins are read in parallel: room for that many connections per host.
            adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        self._session = session
        self._timeout = (connect_timeout, timeout)
        self._token_ttl = token_ttl_seconds
        self._clock = clock
        self._wall_clock = wall_clock
        self._retries = retries
        self._retry_pause = retry_pause_seconds
        self._sleep = sleep
        # cache key → (reuse until, by ``clock``; endpoint; token)
        self._access: dict[tuple[str, str, str, str], tuple[float, str, str]] = {}
        self._access_locks: dict[tuple[str, str, str, str], threading.Lock] = {}
        self._locks_lock = threading.Lock()

    # -- dataspace -----------------------------------------------------------------------

    def _negotiated(
        self, bpnl: str, address: str, key: str, value: str, refresh: bool = False
    ) -> tuple[str, str]:
        """(endpoint, token) for the asset with ``key`` = ``value``, reused until shortly
        before the token expires; ``refresh`` renews the EDR instead. One negotiation per asset
        at a time: other threads wait for it and use its token."""
        cache_key = (bpnl, address, key, value)
        with self._locks_lock:
            lock = self._access_locks.setdefault(cache_key, threading.Lock())
        seen = self._access.get(cache_key)
        with lock:
            cached = self._access.get(cache_key)
            # Another thread renewed it while this one waited: use that.
            renewed = cached is not None and cached is not seen
            if cached and (renewed or not refresh) and self._clock() < cached[0]:
                return cached[1], cached[2]
            endpoint, token = self._edc.negotiate(
                bpnl, address, [equals(key, value)], refresh=refresh
            )
            self._access[cache_key] = (self._clock() + self._reuse_for(token), endpoint, token)
            return endpoint, token

    def _reuse_for(self, token: str) -> float:
        """How long to reuse a token: until shortly before its expiry, if it names one."""
        lifetime = token_lifetime(token, self._wall_clock())
        if lifetime is None:
            return self._token_ttl
        return max(0.0, lifetime - TOKEN_EXPIRY_MARGIN_SECONDS)

    def _with_access(
        self, bpnl: str, address: str, key: str, value: str, call: Callable[[str, str], T]
    ) -> T:
        """``call(endpoint, token)`` with the asset's access. A token the partner refuses (it
        can expire while the cache still holds it) is renewed once and the call repeated."""
        endpoint, token = self._negotiated(bpnl, address, key, value)
        try:
            return call(endpoint, token)
        except DataPlaneError as exc:
            if exc.status not in (401, 403):
                raise
            log.info("%s; renewing the EDR and trying again", exc)
        endpoint, token = self._negotiated(bpnl, address, key, value, refresh=True)
        return call(endpoint, token)

    def _get_json(self, url: str, token: str, params: Any = None) -> Any:
        return self._call("GET", url, token, params=params)

    def _call(self, method: str, url: str, token: str, **kwargs: Any) -> Any:
        """One read through the partner's data plane, tried again on what is usually passing
        (both lookups are reads, the POST one too)."""
        for attempt in range(self._retries + 1):
            last = attempt == self._retries
            try:
                response = self._session.request(
                    method,
                    url,
                    headers={"Authorization": token, "Accept": "application/json"},
                    timeout=self._timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                if last:
                    raise DataspaceError(f"{method} {url} failed: {exc}") from exc
                log.info("%s %s failed (%s); trying again", method, url, exc)
                self._pause(attempt, None)
                continue
            if response.status_code in RETRY_STATUSES and not last:
                log.info("%s %s returned HTTP %d; trying again", method, url, response.status_code)
                self._pause(attempt, response)
                continue
            break
        if response.status_code == 404:
            return None
        if not response.ok:
            raise DataPlaneError(
                _data_plane_error(url, response.status_code, method), response.status_code
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DataspaceError(f"{method} {url} did not return JSON") from exc

    def _pause(self, attempt: int, response: requests.Response | None) -> None:
        pause = self._retry_pause * 2**attempt
        asked = _retry_after(response)
        (self._sleep or time.sleep)(min(asked, 30.0) if asked is not None else pause)

    def _lookup(self, base: str, token: str, global_asset_id: str) -> Any:
        """The AAS IDs for a Catena-X ID. Some registries fail on the GET lookup while the
        POST one (same AAS API v3, body instead of a base64 query) works, so a 5xx is retried
        that way."""
        asset_id = {"name": "globalAssetId", "value": global_asset_id}
        try:
            return self._get_json(
                f"{base}/lookup/shells",
                token,
                params={"assetIds": encode_as_base64_url_safe(json.dumps(asset_id))},
            )
        except DataPlaneError as exc:
            if exc.status < 500:
                raise
            log.warning("%s; trying POST /lookup/shellsByAssetLink", exc)
            try:
                return self._call(
                    "POST", f"{base}/lookup/shellsByAssetLink", token, json=[asset_id]
                )
            except DataspaceError as retry:
                raise DataspaceError(f"{exc}; the POST lookup failed too: {retry}") from retry

    # -- PartnerDataClient ---------------------------------------------------------------

    def find_twin(self, partner: Partner, global_asset_id: str) -> TwinRef | None:
        """The partner's twin with this Catena-X ID, or ``None``."""
        return self._with_access(
            partner.bpnl,
            partner.connector_address,
            DCT_TYPE_KEY,
            DTR_ASSET_TYPE,
            lambda endpoint, token: self._find_twin(endpoint, token, partner, global_asset_id),
        )

    def _find_twin(
        self, endpoint: str, token: str, partner: Partner, global_asset_id: str
    ) -> TwinRef | None:
        base = endpoint.rstrip("/")
        lookup = self._lookup(base, token, global_asset_id)
        aas_ids = (lookup or {}).get("result") or []
        if not aas_ids:
            return None
        if len(aas_ids) > 1:
            log.warning(
                "%s has %d twins for %s; using the first",
                partner.bpnl,
                len(aas_ids),
                global_asset_id,
            )
        descriptor = self._get_json(
            f"{base}/shell-descriptors/{encode_as_base64_url_safe(aas_ids[0])}", token
        )
        if not descriptor:
            return None
        return twin_from_descriptor(descriptor)

    def read_submodel(self, partner: Partner, ref: SubmodelRef) -> dict[str, Any]:
        """The submodel's value-only form, read with the token of its asset."""
        body = parse_subprotocol_body(ref.subprotocol_body)
        if "id" not in body:
            raise DataspaceError(f"submodel descriptor at {ref.href} names no asset id")
        address = body.get("dspEndpoint") or partner.connector_address
        payload = self._with_access(
            partner.bpnl,
            address,
            ASSET_ID_KEY,
            body["id"],
            lambda _, token: self._get_json(value_url(ref), token),
        )
        if not isinstance(payload, dict):
            raise DataspaceError(f"submodel at {ref.href} is missing or not a JSON object")
        return payload
