from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from catenax_simplified.dataspace import DataspaceError, SubmodelRef, TwinRef
from catenax_simplified.dataspace.dtr import twin_from_descriptor
from catenax_simplified.dataspace.submodels import value_url


class FakeRegistry:
    def __init__(self, shells: list[dict[str, Any]], fail_after: int | None = None):
        self.shells = shells
        self.fail_after = fail_after

    def iter_twins(self) -> Iterator[TwinRef]:
        for index, shell in enumerate(self.shells):
            if self.fail_after is not None and index >= self.fail_after:
                raise DataspaceError("DTR unavailable")
            twin = twin_from_descriptor(shell)
            if twin is not None:
                yield twin


class FakeReader:
    """Serves payloads by value URL; an exception value is raised instead of returned."""

    def __init__(self, payloads: dict[str, Any]):
        self.payloads = payloads
        self.reads: list[str] = []

    def read(self, ref: SubmodelRef) -> dict[str, Any]:
        url = value_url(ref)
        self.reads.append(url)
        payload = self.payloads.get(url)
        if payload is None:
            raise DataspaceError(f"GET {url} returned HTTP 404")
        if isinstance(payload, Exception):
            raise payload
        return payload
