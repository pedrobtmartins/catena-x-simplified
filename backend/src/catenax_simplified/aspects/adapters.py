"""Payload adapters for the published aspect model versions.

Two payload shapes are in use in the network:

* ``v3`` — SerialPart/Batch 3.x, SingleLevelBomAsBuilt/SingleLevelUsageAsBuilt 3.0.0
  (``catenaXId``, ``catenaXsiteId``, ``date``, ``classificationID`` …);
* ``v4`` — the 4.0.0 models, both under ``io.catenax.*`` (26.03) and
  ``io.catenax.industry_core.*`` (26.09), which share the same payload
  (``globalAssetId``, ``siteId``, ``productionDate``, ``id`` …).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ids import normalize_global_asset_id
from .model import Classification, Part, PartKind, Relation, Relations, RelationSource


class AspectPayloadError(ValueError):
    """The submodel payload does not match the expected aspect model."""


def _require_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AspectPayloadError(f"missing or invalid '{key}'")
    return value


def _id_key(shape: str) -> str:
    return "catenaXId" if shape == "v3" else "globalAssetId"


def parse_part(payload: Mapping[str, Any], kind: PartKind, shape: str, semantic_id: str) -> Part:
    """A SerialPart or Batch payload, v3 or v4 shape, into the internal ``Part``. v3 field
    names (``catenaXId``, ``date``, ``classificationID`` …) are mapped to the v4 ones.
    """
    info = payload.get("manufacturingInformation") or {}
    type_info = payload.get("partTypeInformation") or {}

    if shape == "v3":
        production_date = info.get("date")
        site_ids = tuple(
            s["catenaXsiteId"] for s in info.get("sites") or [] if "catenaXsiteId" in s
        )
        classifications = tuple(
            Classification(
                standard=c.get("classificationStandard", ""),
                id=c.get("classificationID", ""),
                description=c.get("classificationDescription"),
            )
            for c in type_info.get("partClassification") or []
        )
    else:
        production_date = info.get("productionDate")
        site_ids = tuple(s["siteId"] for s in info.get("sites") or [] if "siteId" in s)
        classifications = tuple(
            Classification(
                standard=c.get("standard", ""),
                id=c.get("id", ""),
                description=c.get("description"),
            )
            for c in type_info.get("partClassification") or []
        )

    return Part(
        global_asset_id=normalize_global_asset_id(_require_str(payload, _id_key(shape))),
        kind=kind,
        semantic_id=semantic_id,
        manufacturer_part_id=type_info.get("manufacturerPartId"),
        customer_part_id=type_info.get("customerPartId"),
        name_at_manufacturer=type_info.get("nameAtManufacturer"),
        name_at_customer=type_info.get("nameAtCustomer"),
        local_identifiers={
            i["key"]: i["value"]
            for i in payload.get("localIdentifiers") or []
            if "key" in i and "value" in i
        },
        production_date=production_date,
        country=info.get("country"),
        site_ids=site_ids,
        classifications=classifications,
    )


def _quantity(item: Mapping[str, Any]) -> tuple[float | None, str | None]:
    quantity = item.get("quantity") or {}
    value = quantity.get("value")
    return (float(value) if value is not None else None, quantity.get("unit"))


def parse_bom(payload: Mapping[str, Any], shape: str) -> Relations:
    """A SingleLevelBomAsBuilt payload into the parent's ``Relations``: one per child, with
    its supplier and quantity.
    """
    id_key = _id_key(shape)
    parent_id = normalize_global_asset_id(_require_str(payload, id_key))
    items = []
    for child in payload.get("childItems") or []:
        quantity, unit = _quantity(child)
        items.append(
            Relation(
                parent_id=parent_id,
                child_id=normalize_global_asset_id(_require_str(child, id_key)),
                source=RelationSource.BOM,
                business_partner=child.get("businessPartner"),
                quantity=quantity,
                unit=unit,
            )
        )
    return Relations(declared_by=parent_id, source=RelationSource.BOM, items=tuple(items))


def parse_usage(payload: Mapping[str, Any], shape: str) -> Relations:
    """A SingleLevelUsageAsBuilt payload into the child's ``Relations``: one per parent, with
    its customer and quantity.
    """
    id_key = _id_key(shape)
    child_id = normalize_global_asset_id(_require_str(payload, id_key))
    items = []
    for parent in payload.get("parentItems") or []:
        quantity, unit = _quantity(parent)
        items.append(
            Relation(
                parent_id=normalize_global_asset_id(_require_str(parent, id_key)),
                child_id=child_id,
                source=RelationSource.USAGE,
                business_partner=parent.get("businessPartner"),
                quantity=quantity,
                unit=unit,
                is_only_potential_parent=bool(parent.get("isOnlyPotentialParent", False)),
            )
        )
    return Relations(
        declared_by=child_id,
        source=RelationSource.USAGE,
        items=tuple(items),
        customers=tuple(payload.get("customers") or ()),
    )
