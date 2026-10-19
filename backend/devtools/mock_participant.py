"""A minimal stand-in for a participant's DTR and submodel server, for local UI/API development.

It serves the AAS v3 ``/api/v3/shell-descriptors`` endpoint (with cursor pagination), the
lookup endpoints (``/api/v3/lookup/shells``, ``/api/v3/shell-descriptors/{id}``) and the
submodels of one of three companies of a small battery supply chain:

- ``tier1`` (default): six battery modules, mixing v3 and v4 aspect models; cells from Tier-2,
  even modules installed in the OEM's vehicles;
- ``tier2``: the cells of those modules, published with SerialPart 3.0.0 and
  SingleLevelUsageAsBuilt 3.0.0 (a supplier that has not migrated yet);
- ``oem``: three vehicles built from the even modules (v4).

It is not a test of Catena-X conformance; integration tests use the Tractus-X umbrella
environment.

    python devtools/mock_participant.py --port 8081 [--participant tier1] [--latency 0.5]

``--latency`` makes every answer that much slower, like a remote registry behind a connector: it
shows what a long partner sync looks like.

    CXS_OWN_BPNL=BPNL000000000T1A \
    CXS_DTR_BASE_URL=http://localhost:8081 \
    uv run uvicorn catenax_simplified.main:app
"""

from __future__ import annotations

import argparse
import base64
import json
import time
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
USAGE_V3 = "urn:samm:io.catenax.single_level_usage_as_built:3.0.0#SingleLevelUsageAsBuilt"
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


PARTICIPANTS = {"tier1": TIER1, "tier2": TIER2, "oem": OEM}
VEHICLES = [_uuid("eeeeeeee", n) for n in range(1, 4)]


def _module(n: int) -> str:
    return _uuid("aaaaaaaa", n)


def _cells(n: int) -> list[str]:
    return [_uuid("cccccccc", n * 10 + c) for c in range(1, 4)]


def build_dataset(
    participant: str = "tier1", bpns: dict[str, str] | None = None
) -> tuple[list[dict], dict[str, dict]]:
    """Return (shell descriptors, submodel payloads by path) of one company.

    ``bpns`` maps ``tier1``/``tier2``/``oem`` to other BPNLs (e.g. a test environment's)."""
    bpns = {**PARTICIPANTS, **(bpns or {})}
    TIER1, TIER2, OEM = bpns["tier1"], bpns["tier2"], bpns["oem"]  # noqa: N806
    shells: list[dict] = []
    submodels: dict[str, dict] = {}

    def add_twin(gid: str, aspects: dict[str, dict], id_short: str = "batteryModule") -> None:
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
                "idShort": id_short,
                "globalAssetId": gid,
                "specificAssetIds": [{"name": "manufacturerId", "value": bpns[participant]}],
                "submodelDescriptors": descriptors,
            }
        )

    if participant == "tier2":
        for n in range(1, 7):
            lot = "L-2026-17" if n % 2 == 0 else "L-2026-12"
            for c, cell in enumerate(_cells(n), start=1):
                add_twin(
                    cell,
                    {
                        SERIAL_PART_V3: {
                            "catenaXId": cell,
                            "localIdentifiers": [
                                {"key": "partInstanceId", "value": f"C-2617-{n:02d}{c}"},
                                {"key": "batchId", "value": lot},
                            ],
                            "manufacturingInformation": {
                                "date": f"2026-0{n}-02T06:00:00",
                                "country": "POL",
                                "sites": [
                                    {"catenaXsiteId": "BPNS00000000T2S1", "function": "production"}
                                ],
                            },
                            "partTypeInformation": {
                                "manufacturerPartId": "CELL-21700-5A",
                                "nameAtManufacturer": "Li-ion cell 21700",
                                "customerPartId": "T1-CELL-0042",
                                "nameAtCustomer": "Battery cell",
                            },
                        },
                        USAGE_V3: {
                            "catenaXId": cell,
                            "parentItems": _items([_module(n)], "catenaXId", TIER1, False),
                            "customers": [TIER1],
                        },
                    },
                    id_short="batteryCell",
                )
        return shells, submodels

    if participant == "oem":
        for k, vehicle in enumerate(VEHICLES, start=1):
            add_twin(
                vehicle,
                {
                    SERIAL_PART_V4: {
                        "globalAssetId": vehicle,
                        "localIdentifiers": [
                            {"key": "van", "value": f"OEM-VAN-{k:06d}"},
                            {"key": "partInstanceId", "value": f"VIN-WCX0000000000{k:02d}"},
                        ],
                        "manufacturingInformation": {
                            "productionDate": f"2026-0{2 * k + 1}-20",
                            "country": "DEU",
                            "sites": [{"siteId": "BPNS0000000OEMS1", "function": "production"}],
                        },
                        "partTypeInformation": {
                            "manufacturerPartId": "EVC-2026",
                            "nameAtManufacturer": "EV Compact",
                        },
                    },
                    BOM_V4: {
                        "globalAssetId": vehicle,
                        "childItems": _items([_module(2 * k)], "globalAssetId", TIER1),
                    },
                },
                id_short="vehicle",
            )
        return shells, submodels

    vehicles = VEHICLES
    for n in range(1, 7):
        module = _module(n)
        cells = _cells(n)
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
    latency: float = 0.0

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        if self.latency:
            time.sleep(self.latency)
        url = urlparse(self.path)
        base = f"http://{self.headers['Host']}"
        query = parse_qs(url.query)

        def resolve(value: Any) -> Any:
            return json.loads(json.dumps(value).replace("{base}", base))

        if url.path == "/api/v3/shell-descriptors":
            limit = int(query.get("limit", ["100"])[0])
            start = int(query.get("cursor", ["0"])[0])
            page = resolve(self.shells[start : start + limit])
            nxt = start + limit
            metadata = {"cursor": str(nxt)} if nxt < len(self.shells) else {}
            self._send(200, {"paging_metadata": metadata, "result": page})
        elif url.path == "/api/v3/lookup/shells":
            wanted = {
                (a["name"], a["value"])
                for encoded in query.get("assetIds", [])
                for a in [json.loads(_b64decode(encoded))]
            }
            found = [
                shell["id"]
                for shell in self.shells
                if ("globalAssetId", shell["globalAssetId"]) in wanted
            ]
            self._send(200, {"paging_metadata": {}, "result": found})
        elif url.path.startswith("/api/v3/shell-descriptors/"):
            aas_id = _b64decode(url.path.rsplit("/", 1)[1])
            shell = next((s for s in self.shells if s["id"] == aas_id), None)
            if shell is None:
                self._send(404, {"messages": [{"text": f"{aas_id} not found"}]})
            else:
                self._send(200, resolve(shell))
        elif url.path in self.submodels:
            self._send(200, self.submodels[url.path])
        else:
            self._send(404, {"messages": [{"text": f"{url.path} not found"}]})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # quiet; the app logs what it reads


def _b64decode(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--participant", choices=sorted(PARTICIPANTS), default="tier1")
    parser.add_argument("--latency", type=float, default=0.0, help="seconds added to each answer")
    args = parser.parse_args()
    Handler.shells, Handler.submodels = build_dataset(args.participant)
    Handler.latency = args.latency
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(
        f"mock {args.participant} ({PARTICIPANTS[args.participant]}) on "
        f"http://127.0.0.1:{args.port} ({len(Handler.shells)} twins)"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
