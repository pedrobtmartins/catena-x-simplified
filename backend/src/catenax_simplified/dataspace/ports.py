"""Interfaces between the application and the participant's dataspace infrastructure.

The rest of the application depends only on these types; the implementations (Tractus-X SDK,
HTTP) live next to them and can be replaced in tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol


class DataspaceError(Exception):
    """A dataspace component (DTR, submodel server, EDC) failed or answered unexpectedly."""


@dataclass(frozen=True)
class SubmodelRef:
    semantic_id: str
    href: str
    interface: str | None = None
    # "dspEndpoint=…;id=…": where to negotiate for the submodel's asset (partner twins).
    subprotocol_body: str | None = None


@dataclass(frozen=True)
class TwinRef:
    aas_id: str
    global_asset_id: str
    manufacturer_id: str | None
    submodels: tuple[SubmodelRef, ...]


class TwinRegistry(Protocol):
    def iter_twins(self) -> Iterator[TwinRef]:
        """Yield every shell descriptor visible to the application."""
        ...

    def get_twin(self, aas_id: str) -> TwinRef | None:
        """The twin with this AAS ID; None if the registry does not have it."""
        ...

    def find_aas_ids(self, global_asset_id: str) -> list[str]:
        """The AAS IDs of the shells for a ``globalAssetId``."""
        ...


class SubmodelReader(Protocol):
    def read(self, ref: SubmodelRef) -> dict[str, Any]:
        """Return the submodel in value-only serialization."""
        ...
