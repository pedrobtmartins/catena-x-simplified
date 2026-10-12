"""Reading submodels of the participant's own twins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import requests

from .ports import DataspaceError, SubmodelRef

VALUE_ONLY_INTERFACE = "SUBMODEL-VALUE-3.1"
VALUE_SUFFIX = "/$value"


def value_url(ref: SubmodelRef) -> str:
    """URL of the value-only serialization (Digital Twin KIT / Industry Core KIT).

    ``SUBMODEL-VALUE-3.1`` endpoints already point to ``…/$value``; for ``SUBMODEL-3.x``
    endpoints the ``/$value`` segment is appended to the ``href``.
    """
    href = ref.href.rstrip("/")
    if ref.interface == VALUE_ONLY_INTERFACE or href.endswith(VALUE_SUFFIX):
        return href
    return href + VALUE_SUFFIX


def rewrite(url: str, rewrites: Sequence[tuple[str, str]]) -> str:
    """Apply the first matching ``(prefix, replacement)`` rewrite.

    The ``href`` of an own submodel points to the participant's public EDC data plane. The
    application reads its own data from the backend behind it instead, so the public prefix is
    rewritten to the internal submodel server URL.
    """
    for prefix, replacement in rewrites:
        if url.startswith(prefix):
            return replacement + url[len(prefix) :]
    return url


class HttpSubmodelReader:
    def __init__(
        self,
        session: requests.Session | None = None,
        rewrites: Sequence[tuple[str, str]] = (),
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self._session = session or requests.Session()
        self._rewrites = list(rewrites)
        self._headers = {"Accept": "application/json", **(headers or {})}
        self._timeout = timeout

    def read(self, ref: SubmodelRef) -> dict[str, Any]:
        url = rewrite(value_url(ref), self._rewrites)
        try:
            response = self._session.get(url, headers=self._headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise DataspaceError(f"GET {url} failed: {exc}") from exc
        if not response.ok:
            raise DataspaceError(f"GET {url} returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataspaceError(f"GET {url} did not return JSON") from exc
        if not isinstance(payload, dict):
            raise DataspaceError(f"GET {url} did not return a JSON object")
        return payload
