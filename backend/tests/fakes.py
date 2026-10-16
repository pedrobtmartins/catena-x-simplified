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

    def get_twin(self, aas_id: str) -> TwinRef | None:
        self.requests = getattr(self, "requests", []) + [("get", aas_id)]
        shell = next((s for s in self.shells if s.get("id") == aas_id), None)
        return twin_from_descriptor(shell) if shell else None

    def find_aas_ids(self, global_asset_id: str) -> list[str]:
        self.requests = getattr(self, "requests", []) + [("lookup", global_asset_id)]
        return [s["id"] for s in self.shells if s.get("globalAssetId") == global_asset_id]


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


class FakePartnerClient:
    """Partner twins by (bpnl, globalAssetId); payloads by value URL, as FakeReader."""

    def __init__(self, twins: dict, payloads: dict, unreachable: set | None = None):
        self.twins = twins
        self.reader = FakeReader(payloads)
        self.unreachable = unreachable or set()
        self.lookups: list[tuple[str, str]] = []

    def find_twin(self, partner, global_asset_id):
        if partner.bpnl in self.unreachable:
            raise DataspaceError(f"negotiation with {partner.bpnl} failed: timeout")
        self.lookups.append((partner.bpnl, global_asset_id))
        shell = self.twins.get((partner.bpnl, global_asset_id))
        return twin_from_descriptor(shell) if shell else None

    def read_submodel(self, partner, ref):
        return self.reader.read(ref)
