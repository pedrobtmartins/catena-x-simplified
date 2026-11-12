"""The single place that knows which aspect model versions are supported.

A submodel is routed to an adapter by its ``semanticId``
(``urn:samm:<namespace>:<version>#<Aspect>``): SerialPart, Batch and JustInSequencePart payloads of
the same generation have the same fields, so a payload does not say which aspect it is.

The ``namespace:version`` decides, as it names the model and so the payload's schema; the
``#<Aspect>`` fragment only names an element in it and may be missing. A fragment that names
another element (``#serialPart``, ``#JustInSequencePart`` under ``serial_part``) is a publisher's
slip: the submodel is still read by its namespace, and the sync reports it (``contradiction``).
Dropping it would lose the part or the relations, and a partner's data with them. One guard:
when the fragment contradicts the namespace, the payload must have the model's main content
(``childItems`` for a BoM …); a usage payload read as an empty BoM would erase the twin's real BoM.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from . import adapters
from .model import Part, PartKind, Relations


class AspectType(StrEnum):
    """The aspect models the app reads, whatever their version. The value is the aspect's name,
    as in the ``#<Aspect>`` fragment of its semantic ID."""

    SERIAL_PART = "SerialPart"
    BATCH = "Batch"
    JUST_IN_SEQUENCE_PART = "JustInSequencePart"
    BOM_AS_BUILT = "SingleLevelBomAsBuilt"
    USAGE_AS_BUILT = "SingleLevelUsageAsBuilt"


# The aspects that describe the part itself: a just-in-sequence part and a serialized part are
# units, a batch is a lot. This order only breaks ties in ``part_preference`` (and orders
# ``part_types``): it does not make one aspect win over another by itself.
PART_TYPES: tuple[AspectType, ...] = (
    AspectType.JUST_IN_SEQUENCE_PART,
    AspectType.SERIAL_PART,
    AspectType.BATCH,
)

PART_KINDS: dict[AspectType, PartKind] = {
    AspectType.SERIAL_PART: PartKind.SERIAL,
    AspectType.BATCH: PartKind.BATCH,
    AspectType.JUST_IN_SEQUENCE_PART: PartKind.JIS,
}


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
        "io.catenax.just_in_sequence_part",
        AspectType.JUST_IN_SEQUENCE_PART,
        {"3.0.0": "v3", "4.0.0": "v4"},
    ),
    **_versions(
        "io.catenax.industry_core.just_in_sequence_part",
        AspectType.JUST_IN_SEQUENCE_PART,
        {"4.0.0": "v4"},
    ),
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


def _split(semantic_id: str) -> tuple[str, str | None] | None:
    """``("<namespace>:<version>", "<Aspect>" or None)``, or None if it is not a SAMM URN."""
    if not semantic_id.startswith(_URN_PREFIX):
        return None
    key, _, fragment = semantic_id[len(_URN_PREFIX) :].partition("#")
    return key, fragment or None


def lookup(semantic_id: str) -> SupportedAspect | None:
    """Return the supported aspect for a semantic ID by its ``namespace:version``, whatever its
    ``#<Aspect>`` fragment says (see ``contradiction``), or ``None`` if it is not supported."""
    split = _split(semantic_id)
    return SUPPORTED.get(split[0]) if split else None


def is_supported(semantic_id: str) -> bool:
    """Whether the app can read submodels with this semantic ID."""
    return lookup(semantic_id) is not None


def contradiction(semantic_id: str, among: Collection[AspectType] | None = None) -> str | None:
    """What is wrong with the semantic ID of a supported model whose fragment names another
    element (e.g. ``io.catenax.serial_part:3.0.0#JustInSequencePart``); it is read by its
    namespace all the same. ``None`` for a consistent ID or one without a fragment, and for
    models the app does not read. ``among``: only when the model or the aspect the fragment
    names is one of these."""
    split = _split(semantic_id)
    if split is None:
        return None
    key, fragment = split
    aspect = SUPPORTED.get(key)
    if aspect is None or fragment is None or fragment == aspect.type.value:
        return None
    if among is not None and aspect.type not in among and fragment not in among:
        return None
    return f"{key} is a {aspect.type.value} model, but the semantic ID names #{fragment}"


def part_preference(semantic_id: str) -> tuple[int, ...] | None:
    """Sort key among the part submodels of one twin, best first. A twin should have only one;
    with several, the one most likely to be current and the safest to act on is read:

    1. a unit (JustInSequencePart, SerialPart) before a batch: a unit read as a batch would be
       exempt from the "in two assemblies" data check and hide a real error;
    2. the newest release: industry_core 4, then io.catenax 4, then 3.x (a publisher keeps the
       model it moved to up to date, not necessarily the one it left behind);
    3. at the same release, JustInSequencePart before SerialPart (``PART_TYPES``): adding JIS
       next to a SerialPart is more likely deliberate than the reverse;
    4. within one aspect and release, the newest version (SerialPart 3.0.1 before 3.0.0).

    ``None`` if the semantic ID is not a supported part aspect."""
    aspect = lookup(semantic_id)
    if aspect is None or aspect.type not in PART_TYPES:
        return None
    key, _ = _split(semantic_id)  # type: ignore[misc]  # lookup succeeded, so it splits
    namespace, version = key.split(":", 1)
    major, *rest = (int(n) for n in version.split("."))
    return (
        1 if aspect.type == AspectType.BATCH else 0,
        -major,
        0 if ".industry_core." in namespace else 1,
        PART_TYPES.index(aspect.type),
        *(-n for n in rest),
    )


def part_types(semantic_ids: Iterable[str]) -> list[AspectType]:
    """The distinct part aspects among these semantic IDs, in ``PART_TYPES`` order. More than one
    means the twin contradicts itself (e.g. a SerialPart and a Batch for the same object)."""
    found = {a.type for s in semantic_ids if (a := lookup(s)) and a.type in PART_TYPES}
    return [t for t in PART_TYPES if t in found]


# What a payload of each model has and the others do not. Checked only when the fragment
# contradicts the namespace, so that a payload of another model is not read as this one.
_MAIN_CONTENT: dict[AspectType, str] = {
    **{t: "partTypeInformation" for t in PART_TYPES},
    AspectType.BOM_AS_BUILT: "childItems",
    AspectType.USAGE_AS_BUILT: "parentItems",
}


def parse(semantic_id: str, payload: Mapping[str, Any]) -> Part | Relations:
    """Translate a submodel payload into the internal model, by the semantic ID's namespace.

    Raises ``ValueError`` for unsupported semantic IDs and
    :class:`~catenax_simplified.aspects.adapters.AspectPayloadError` for invalid payloads,
    including one whose fragment contradicts the namespace and that lacks the namespace model's
    main content (it is probably the payload the fragment names).
    """
    aspect = lookup(semantic_id)
    if aspect is None:
        raise ValueError(f"unsupported semantic ID: {semantic_id}")
    if (reason := contradiction(semantic_id)) and _MAIN_CONTENT[aspect.type] not in payload:
        raise adapters.AspectPayloadError(
            f"not read: {reason}, and the payload has no '{_MAIN_CONTENT[aspect.type]}' "
            f"(not a {aspect.type.value} payload)"
        )
    if aspect.type in PART_KINDS:
        return adapters.parse_part(payload, PART_KINDS[aspect.type], aspect.shape, semantic_id)
    match aspect.type:
        case AspectType.BOM_AS_BUILT:
            return adapters.parse_bom(payload, aspect.shape)
        case AspectType.USAGE_AS_BUILT:
            return adapters.parse_usage(payload, aspect.shape)
    # A type in SUPPORTED without an adapter here must fail loudly, not return None.
    raise AssertionError(f"no adapter for {aspect.type}")
