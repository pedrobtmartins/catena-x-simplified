"""Builders for submodel payloads and DTR shell descriptors in the published shapes."""

from __future__ import annotations

from typing import Any

SERIAL_PART_V3 = "urn:samm:io.catenax.serial_part:3.0.0#SerialPart"
SERIAL_PART_V4 = "urn:samm:io.catenax.serial_part:4.0.0#SerialPart"
SERIAL_PART_IC = "urn:samm:io.catenax.industry_core.serial_part:4.0.0#SerialPart"
BATCH_V3 = "urn:samm:io.catenax.batch:3.0.0#Batch"
BOM_V3 = "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SingleLevelBomAsBuilt"
BOM_V4 = "urn:samm:io.catenax.single_level_bom_as_built:4.0.0#SingleLevelBomAsBuilt"
USAGE_V3 = "urn:samm:io.catenax.single_level_usage_as_built:3.0.0#SingleLevelUsageAsBuilt"
USAGE_V4 = "urn:samm:io.catenax.single_level_usage_as_built:4.0.0#SingleLevelUsageAsBuilt"
PCF = "urn:samm:io.catenax.pcf:7.0.0#Pcf"


def part_v3(gid: str, name: str, part_id: str, *, serial: str = "SN1") -> dict[str, Any]:
    return {
        "catenaXId": gid,
        "localIdentifiers": [{"key": "partInstanceId", "value": serial}],
        "manufacturingInformation": {
            "date": "2026-01-15T10:00:00",
            "country": "PRT",
            "sites": [{"catenaXsiteId": "BPNS000000000001", "function": "production"}],
        },
        "partTypeInformation": {"manufacturerPartId": part_id, "nameAtManufacturer": name},
    }


def part_v4(gid: str, name: str, part_id: str, *, serial: str = "SN1") -> dict[str, Any]:
    return {
        "globalAssetId": gid,
        "localIdentifiers": [{"key": "partInstanceId", "value": serial}],
        "manufacturingInformation": {
            "productionDate": "2026-02-20",
            "country": "DEU",
            "sites": [{"siteId": "BPNS000000000002", "function": "production"}],
        },
        "partTypeInformation": {"manufacturerPartId": part_id, "nameAtManufacturer": name},
    }


def _items(ids: list[str], id_key: str, bpnl: str) -> list[dict[str, Any]]:
    return [
        {
            id_key: i,
            "quantity": {"value": 1.0, "unit": "unit:piece"},
            "businessPartner": bpnl,
            "hasAlternatives": False,
            "createdOn": "2026-01-01T00:00:00Z",
            "lastModifiedOn": "2026-01-01T00:00:00Z",
        }
        for i in ids
    ]


def bom_v3(gid: str, children: list[str], supplier: str) -> dict[str, Any]:
    return {"catenaXId": gid, "childItems": _items(children, "catenaXId", supplier)}


def bom_v4(gid: str, children: list[str], supplier: str) -> dict[str, Any]:
    return {"globalAssetId": gid, "childItems": _items(children, "globalAssetId", supplier)}


def usage_v4(gid: str, parents: list[str], customer: str) -> dict[str, Any]:
    items = _items(parents, "globalAssetId", customer)
    for item in items:
        item["isOnlyPotentialParent"] = False
    return {"globalAssetId": gid, "parentItems": items, "customers": [customer]}


def shell_descriptor(
    gid: str, submodels: dict[str, str], *, manufacturer_id: str | None = None
) -> dict[str, Any]:
    """AAS v3 shell descriptor as served by a DTR; ``submodels`` maps semanticId → href."""
    descriptor: dict[str, Any] = {
        "id": f"urn:uuid:aas-{gid[-12:]}",
        "idShort": "twin",
        "globalAssetId": gid,
        "specificAssetIds": [],
        "submodelDescriptors": [
            {
                "id": f"urn:uuid:sm-{index}-{gid[-12:]}",
                "idShort": semantic_id.rsplit("#", 1)[-1],
                "semanticId": {
                    "type": "ExternalReference",
                    "keys": [{"type": "GlobalReference", "value": semantic_id}],
                },
                "endpoints": [
                    {
                        "interface": "SUBMODEL-3.0",
                        "protocolInformation": {
                            "href": href,
                            "endpointProtocol": "HTTP",
                            "endpointProtocolVersion": ["1.1"],
                            "subprotocol": "DSP",
                            "subprotocolBody": "dspEndpoint=https://edc.example/api/v1/dsp;id=x",
                            "subprotocolBodyEncoding": "plain",
                            "securityAttributes": [
                                {"type": "NONE", "key": "NONE", "value": "NONE"}
                            ],
                        },
                    }
                ],
            }
            for index, (semantic_id, href) in enumerate(submodels.items())
        ],
    }
    if manufacturer_id:
        descriptor["specificAssetIds"].append({"name": "manufacturerId", "value": manufacturer_id})
    return descriptor
