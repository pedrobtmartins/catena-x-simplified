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


class SubmodelReader(Protocol):
    def read(self, ref: SubmodelRef) -> dict[str, Any]:
        """Return the submodel in value-only serialization."""
        ...
