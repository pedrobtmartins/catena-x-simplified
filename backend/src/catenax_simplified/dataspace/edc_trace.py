"""What the own EDC's management API answered while a connector check ran.

The Tractus-X SDK turns a failed call into an error that keeps only the status code ("It was not
possible to get the catalog from the EDC provider! Response code: [502]"); the reason is in the
answer's body, which it drops. ``install`` adds a response hook to the SDK's HTTP sessions, and
``recording`` collects the calls made by the current thread while it is active, so a check can
show the answer. Other threads (partner reads, notifications) share the sessions and are not
recorded.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

from .oauth import sdk_adapters

EXCERPT = 2000
_active = threading.local()


@dataclass(frozen=True)
class Exchange:
    """One call to the own EDC's management API and its answer (bodies cut to ``EXCERPT``)."""

    method: str
    url: str
    status: int
    elapsed_ms: int
    request: str
    response: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def install(service: object) -> int:
    """Records the calls of an SDK connector service from now on (once per session); returns
    how many sessions it watches."""
    sessions = 0
    for adapter in sdk_adapters(service):
        session: requests.Session = adapter.session
        if not getattr(session, "_cxs_recorded", False):
            session.hooks.setdefault("response", []).append(_record)
            session._cxs_recorded = True  # type: ignore[attr-defined]
        sessions += 1
    return sessions


@contextmanager
def recording() -> Iterator[list[Exchange]]:
    """Collects the calls this thread makes through an installed service while it is open."""
    previous = getattr(_active, "calls", None)
    calls: list[Exchange] = []
    _active.calls = calls
    try:
        yield calls
    finally:
        _active.calls = previous


def _record(response: requests.Response, *args: Any, **kwargs: Any) -> None:
    calls = getattr(_active, "calls", None)
    if calls is None:
        return
    request = response.request
    parts = urlsplit(request.url or "")
    calls.append(
        Exchange(
            method=request.method or "",
            url=f"{parts.scheme}://{parts.netloc}{parts.path}",
            status=response.status_code,
            elapsed_ms=int(response.elapsed.total_seconds() * 1000),
            request=_text(request.body),
            response=_text(response.content),
        )
    )


def _text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    return str(body)[:EXCERPT]


def edc_reason(body: str) -> str | None:
    """The message in an EDC error answer: its JSON error list (``[{"message": …}]``) or an
    object's ``message``/``error``/``errorDetail``; otherwise the start of the text."""
    text = (body or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return text[:400]
    items = data if isinstance(data, list) else [data]
    messages = []
    for item in items:
        if isinstance(item, dict):
            for key in ("message", "errorDetail", "error", "detail", "edc:errorDetail"):
                if isinstance(item.get(key), str) and item[key].strip():
                    messages.append(item[key].strip())
                    break
    return "; ".join(dict.fromkeys(messages))[:800] or text[:400]
