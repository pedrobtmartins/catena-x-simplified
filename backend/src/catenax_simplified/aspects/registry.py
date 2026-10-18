"""The single place that knows which aspect model versions are supported.

A submodel is routed to an adapter by its ``semanticId``
(``urn:samm:<namespace>:<version>#<Aspect>``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from . import adapters
from .model import Part, PartKind, Relations


class AspectType(StrEnum):
    """The aspect models the app reads, whatever their version."""

    SERIAL_PART = "SerialPart"
    BATCH = "Batch"
    BOM_AS_BUILT = "SingleLevelBomAsBuilt"
    USAGE_AS_BUILT = "SingleLevelUsageAsBuilt"


@dataclass(frozen=True)
class SupportedAspect:
    """One supported aspect model version and the payload shape its adapter expects."""

    type: AspectType
    shape: str  # "v3" or "v4", see adapters


def _versions(namespace: str, aspect: AspectType, shapes: Mapping[str, str]) -> dict:
    return {
        f"{namespace}:{version}": SupportedAspect(aspect, shape)
        for version, shape in shapes.items()
    }


# Keyed by "<namespace>:<version>"; the "#<Aspect>" fragment is not needed for routing.
SUPPORTED: dict[str, SupportedAspect] = {
    **_versions(
        "io.catenax.serial_part",
        AspectType.SERIAL_PART,
        {"3.0.0": "v3", "3.0.1": "v3", "4.0.0": "v4"},
    ),
    **_versions("io.catenax.industry_core.serial_part", AspectType.SERIAL_PART, {"4.0.0": "v4"}),
    **_versions(
        "io.catenax.batch",
        AspectType.BATCH,
        {"3.0.0": "v3", "3.0.1": "v3", "4.0.0": "v4"},
    ),
    **_versions("io.catenax.industry_core.batch", AspectType.BATCH, {"4.0.0": "v4"}),
    **_versions(
        "io.catenax.single_level_bom_as_built",
        AspectType.BOM_AS_BUILT,
        {"3.0.0": "v3", "4.0.0": "v4"},
    ),
    **_versions(
        "io.catenax.industry_core.single_level_bom_as_built",
        AspectType.BOM_AS_BUILT,
        {"4.0.0": "v4"},
    ),
    **_versions(
        "io.catenax.single_level_usage_as_built",
        AspectType.USAGE_AS_BUILT,
        {"3.0.0": "v3", "4.0.0": "v4"},
    ),
    **_versions(
        "io.catenax.industry_core.single_level_usage_as_built",
        AspectType.USAGE_AS_BUILT,
        {"4.0.0": "v4"},
    ),
}

_URN_PREFIX = "urn:samm:"


def lookup(semantic_id: str) -> SupportedAspect | None:
    """Return the supported aspect for a semantic ID, or ``None`` if it is not supported."""
    if not semantic_id.startswith(_URN_PREFIX):
        return None
    key = semantic_id[len(_URN_PREFIX) :].split("#", 1)[0]
    return SUPPORTED.get(key)


def is_supported(semantic_id: str) -> bool:
    """Whether the app can read submodels with this semantic ID."""
    return lookup(semantic_id) is not None


def parse(semantic_id: str, payload: Mapping[str, Any]) -> Part | Relations:
    """Translate a submodel payload into the internal model.

    Raises ``ValueError`` for unsupported semantic IDs and
    :class:`~catenax_simplified.aspects.adapters.AspectPayloadError` for invalid payloads.
    """
    aspect = lookup(semantic_id)
    if aspect is None:
        raise ValueError(f"unsupported semantic ID: {semantic_id}")
    match aspect.type:
        case AspectType.SERIAL_PART:
            return adapters.parse_part(payload, PartKind.SERIAL, aspect.shape, semantic_id)
        case AspectType.BATCH:
            return adapters.parse_part(payload, PartKind.BATCH, aspect.shape, semantic_id)
        case AspectType.BOM_AS_BUILT:
            return adapters.parse_bom(payload, aspect.shape)
        case AspectType.USAGE_AS_BUILT:
            return adapters.parse_usage(payload, aspect.shape)
