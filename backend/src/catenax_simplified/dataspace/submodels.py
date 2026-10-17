"""Reading submodels of the participant's own twins.

Directly (the ``href``, or the internal backend behind it through ``CXS_SUBMODEL_HREF_REWRITES``),
or — when the public data plane refuses a direct read — through the own EDC, like a partner's
submodel: negotiate with the own connector for the submodel's asset and read with the EDR.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

import requests

from .ports import DataspaceError, SubmodelRef

log = logging.getLogger(__name__)

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


class SubmodelHttpError(DataspaceError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


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
            raise SubmodelHttpError(
                f"GET {url} returned HTTP {response.status_code}", response.status_code
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataspaceError(f"GET {url} did not return JSON") from exc
        if not isinstance(payload, dict):
            raise DataspaceError(f"GET {url} did not return a JSON object")
        return payload


class EdcFallbackSubmodelReader:
    """Reads directly; once a data plane refuses a direct read (401/403: it wants an EDR), every
    submodel behind it is read through the own EDC instead."""

    REFUSED = (401, 403)

    def __init__(self, direct: HttpSubmodelReader, read_via_edc: Callable[[SubmodelRef], Any]):
        self._direct = direct
        self._read_via_edc = read_via_edc
        self._via_edc: set[str] = set()

    @staticmethod
    def _data_plane(ref: SubmodelRef) -> str:
        return urlsplit(ref.href).netloc

    def read(self, ref: SubmodelRef) -> dict[str, Any]:
        data_plane = self._data_plane(ref)
        if data_plane in self._via_edc:
            return self._read_via_edc(ref)
        try:
            return self._direct.read(ref)
        except SubmodelHttpError as exc:
            if exc.status not in self.REFUSED:
                raise
            log.info(
                "%s refused a direct read (HTTP %d): reading own submodels there through the EDC",
                data_plane,
                exc.status,
            )
            self._via_edc.add(data_plane)
            return self._read_via_edc(ref)
