"""A minimal stand-in for a participant's DTR and submodel server, for local UI/API development.

It serves the AAS v3 ``/api/v3/shell-descriptors`` endpoint (with cursor pagination) and the
submodels of a small Tier-1 data set that mixes v3 and v4 aspect models. It is not a test of
Catena-X conformance; integration tests use the Tractus-X umbrella environment.

    python devtools/mock_participant.py --port 8081

    CXS_OWN_BPNL=BPNL000000000T1A \
    CXS_DTR_BASE_URL=http://localhost:8081 \
    uv run uvicorn catenax_simplified.main:app
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

TIER1 = "BPNL000000000T1A"
TIER2 = "BPNL000000000T2A"
OEM = "BPNL000000000OEM"

SERIAL_PART_V3 = "urn:samm:io.catenax.serial_part:3.0.0#SerialPart"
SERIAL_PART_V4 = "urn:samm:io.catenax.serial_part:4.0.0#SerialPart"
BOM_V3 = "urn:samm:io.catenax.single_level_bom_as_built:3.0.0#SingleLevelBomAsBuilt"
BOM_V4 = "urn:samm:io.catenax.single_level_bom_as_built:4.0.0#SingleLevelBomAsBuilt"
USAGE_V4 = "urn:samm:io.catenax.single_level_usage_as_built:4.0.0#SingleLevelUsageAsBuilt"


def _uuid(prefix: str, n: int) -> str:
    return f"urn:uuid:{prefix}-0000-4000-8000-{n:012d}"


def _items(ids: list[str], key: str, bpnl: str, potential: bool | None = None) -> list[dict]:
    items = []
    for i in ids:
        item: dict[str, Any] = {
            key: i,
            "quantity": {"value": 12.0 if "cccc" in i else 1.0, "unit": "unit:piece"},
            "businessPartner": bpnl,
            "createdOn": "2026-09-01T08:00:00Z",
            "lastModifiedOn": "2026-09-01T08:00:00Z",
        }
        if potential is None:
            item["hasAlternatives"] = False
        else:
            item["isOnlyPotentialParent"] = potential
        items.append(item)
    return items


def build_dataset() -> tuple[list[dict], dict[str, dict]]:
    """Return (shell descriptors, submodel payloads by path)."""
    shells: list[dict] = []
    submodels: dict[str, dict] = {}

    def add_twin(gid: str, aspects: dict[str, dict]) -> None:
        descriptors = []
        for index, (semantic_id, payload) in enumerate(aspects.items()):
            path = f"/data/{gid}/{index}/submodel"
            submodels[path + "/$value"] = payload
            descriptors.append(
                {
                    "id": f"urn:uuid:5b000000-0000-4000-8000-{len(submodels):012d}",
                    "idShort": semantic_id.rsplit("#", 1)[1][0].lower()
                    + semantic_id.rsplit("#", 1)[1][1:],
                    "semanticId": {
                        "type": "ExternalReference",
                        "keys": [{"type": "GlobalReference", "value": semantic_id}],
                    },
                    "endpoints": [
                        {
                            "interface": "SUBMODEL-3.0",
                            "protocolInformation": {
                                # Rewritten by the app via CXS_SUBMODEL_HREF_REWRITES in real
                                # setups; here the "public" URL is the mock itself.
                                "href": f"{{base}}{path}",
                                "endpointProtocol": "HTTP",
                                "endpointProtocolVersion": ["1.1"],
                                "subprotocol": "DSP",
                                "subprotocolBody": "dspEndpoint=http://edc.invalid/api/v1/dsp;"
                                f"id={gid}",
                                "subprotocolBodyEncoding": "plain",
                                "securityAttributes": [
                                    {"type": "NONE", "key": "NONE", "value": "NONE"}
                                ],
                            },
                        }
                    ],
                }
            )
        shells.append(
            {
                "id": gid.replace("urn:uuid:", "urn:uuid:aa5"),
                "idShort": "batteryModule",
                "globalAssetId": gid,
                "specificAssetIds": [{"name": "manufacturerId", "value": TIER1}],
                "submodelDescriptors": descriptors,
            }
        )

    vehicles = [_uuid("eeeeeeee", n) for n in range(1, 4)]
    for n in range(1, 7):
        module = _uuid("aaaaaaaa", n)
        cells = [_uuid("cccccccc", n * 10 + c) for c in range(1, 4)]
        serial = f"MOD-2026-{n:04d}"
        if n % 2:  # odd modules are still published with v3 models
            add_twin(
                module,
                {
                    SERIAL_PART_V3: {
                        "catenaXId": module,
                        "localIdentifiers": [{"key": "partInstanceId", "value": serial}],
                        "manufacturingInformation": {
                            "date": f"2026-0{n}-15T10:00:00",
                            "country": "PRT",
                            "sites": [
                                {"catenaXsiteId": "BPNS00000000T1S1", "function": "production"}
                            ],
                        },
                        "partTypeInformation": {
                            "manufacturerPartId": "BM-48V-12S",
                            "nameAtManufacturer": "Battery module 48V",
                            "customerPartId": "OEM-BAT-0815",
                            "nameAtCustomer": "HV battery module",
                        },
                    },
                    BOM_V3: {"catenaXId": module, "childItems": _items(cells, "catenaXId", TIER2)},
                },
            )
        else:
            aspects = {
                SERIAL_PART_V4: {
                    "globalAssetId": module,
                    "localIdentifiers": [{"key": "partInstanceId", "value": serial}],
                    "manufacturingInformation": {
                        "productionDate": f"2026-0{n}-15",
                        "country": "PRT",
                        "sites": [{"siteId": "BPNS00000000T1S1", "function": "production"}],
                    },
                    "partTypeInformation": {
                        "manufacturerPartId": "BM-48V-12S",
                        "nameAtManufacturer": "Battery module 48V",
                        "customerPartId": "OEM-BAT-0815",
                        "nameAtCustomer": "HV battery module",
                        "partClassification": [
                            {
                                "standard": "GIN 20510-21513",
                                "id": "1004712",
                                "description": "Battery",
                            }
                        ],
                    },
                },
                BOM_V4: {
                    "globalAssetId": module,
                    "childItems": _items(cells, "globalAssetId", TIER2),
                },
            }
            # v4 modules also publish where they were installed (one vehicle each).
            aspects[USAGE_V4] = {
                "globalAssetId": module,
                "parentItems": _items([vehicles[n // 2 - 1]], "globalAssetId", OEM, False),
                "customers": [OEM],
            }
            add_twin(module, aspects)
    return shells, submodels


class Handler(BaseHTTPRequestHandler):
    shells: list[dict] = []
    submodels: dict[str, dict] = {}

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        url = urlparse(self.path)
        base = f"http://{self.headers['Host']}"
        if url.path == "/api/v3/shell-descriptors":
            query = parse_qs(url.query)
            limit = int(query.get("limit", ["100"])[0])
            start = int(query.get("cursor", ["0"])[0])
            page = json.loads(
                json.dumps(self.shells[start : start + limit]).replace("{base}", base)
            )
            nxt = start + limit
            metadata = {"cursor": str(nxt)} if nxt < len(self.shells) else {}
            self._send(200, {"paging_metadata": metadata, "result": page})
        elif url.path in self.submodels:
            self._send(200, self.submodels[url.path])
        else:
            self._send(404, {"messages": [{"text": f"{url.path} not found"}]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    Handler.shells, Handler.submodels = build_dataset()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"mock participant on http://127.0.0.1:{args.port} ({len(Handler.shells)} twins)")
    server.serve_forever()


if __name__ == "__main__":
    main()
