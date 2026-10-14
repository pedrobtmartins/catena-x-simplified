"""Seed the Tractus-X umbrella's three data-exchange participants with the battery supply chain.

Tier-2 (cell maker, still on SerialPart/Usage 3.0.0) = tx-data-provider, Tier-1 (module maker) =
dataconsumerOne, OEM = dataconsumerTwo. For each one this script

1. stores its submodels in its simple-data-backend,
2. creates (or updates) in its EDC the policies, the Digital Twin Registry asset, one asset for
   its submodels and their contract definitions (Saturn / CX-0152 policies),
3. registers its shell descriptors in its DTR, pointing at its public data plane with the
   ``subprotocolBody`` the Digital Twin KIT prescribes.

Run inside the cluster (``seed-job.sh``) so the in-cluster service names resolve. Configuration:
``participants.json`` next to this file (or ``--config``). Idempotent: run it again any time.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mock_participant  # noqa: E402  (copied next to this script by seed-job.sh)

EDC_CONTEXT = {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"}
ASSET_CONTEXT = {
    "edc": "https://w3id.org/edc/v0.0.1/ns/",
    "cx-common": "https://w3id.org/catenax/ontology/common#",
    "cx-taxo": "https://w3id.org/catenax/taxonomy#",
    "dct": "http://purl.org/dc/terms/",
}
POLICY_CONTEXT = [
    "https://w3id.org/catenax/2025/9/policy/odrl.jsonld",
    "https://w3id.org/catenax/2025/9/policy/context.jsonld",
    {"@vocab": "https://w3id.org/edc/v0.0.1/ns/"},
]
DTR_TYPE = "https://w3id.org/catenax/taxonomy#DigitalTwinRegistry"


def constraint(left: str, operator: str, right: Any) -> dict:
    return {"leftOperand": left, "operator": operator, "rightOperand": right}


ACCESS = {
    "action": "access",
    "constraint": {
        "and": [
            constraint("Membership", "eq", "active"),
            constraint("FrameworkAgreement", "eq", "DataExchangeGovernance:1.0"),
        ]
    },
}
USAGE = {
    "action": "use",
    "constraint": {
        "and": [
            constraint("Membership", "eq", "active"),
            constraint("FrameworkAgreement", "eq", "DataExchangeGovernance:1.0"),
            constraint("UsagePurpose", "isAnyOf", ["cx.core.industrycore:1"]),
        ]
    },
}


class Edc:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})

    def upsert(self, kind: str, body: dict) -> None:
        response = self.session.post(f"{self.url}/v3/{kind}", data=json.dumps(body), timeout=30)
        if response.status_code == 409:
            # Assets and contract definitions are updated at the collection, policies by id.
            url = f"{self.url}/v3/{kind}"
            if kind == "policydefinitions":
                url += f"/{body['@id']}"
            response = self.session.put(url, data=json.dumps(body), timeout=30)
        if response.status_code not in (200, 204):
            raise SystemExit(f"{kind} {body['@id']}: HTTP {response.status_code} {response.text}")

    def policy(self, oid: str, permission: dict) -> None:
        self.upsert(
            "policydefinitions",
            {
                "@context": POLICY_CONTEXT,
                "@type": "PolicyDefinition",
                "@id": oid,
                "policy": {"@type": "Set", "permission": [permission]},
            },
        )

    def asset(self, oid: str, properties: dict, base_url: str) -> None:
        self.upsert(
            "assets",
            {
                "@context": ASSET_CONTEXT,
                "@type": "Asset",
                "@id": oid,
                "properties": properties,
                "dataAddress": {
                    "@type": "DataAddress",
                    "type": "HttpData",
                    "baseUrl": base_url,
                    "proxyPath": "true",
                    "proxyQueryParams": "true",
                    "proxyMethod": "true",
                    "proxyBody": "true",
                },
            },
        )

    def contract(self, oid: str, asset_id: str) -> None:
        self.upsert(
            "contractdefinitions",
            {
                "@context": EDC_CONTEXT,
                "@type": "ContractDefinition",
                "@id": oid,
                "accessPolicyId": "cxs-seed-access",
                "contractPolicyId": "cxs-seed-usage",
                "assetsSelector": [
                    {
                        "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                        "operator": "=",
                        "operandRight": asset_id,
                    }
                ],
            },
        )


def seed(key: str, p: dict, bpns: dict[str, str]) -> None:
    shells, submodels = mock_participant.build_dataset(key, bpns)
    public = p["dataplane_public"].rstrip("/")
    backend = p["submodel_backend"].rstrip("/")
    assets_id = f"{key}-submodels"
    http = requests.Session()

    for shell in shells:
        for descriptor in shell["submodelDescriptors"]:
            endpoint = descriptor["endpoints"][0]["protocolInformation"]
            path = endpoint["href"].replace("{base}", "") + "/$value"
            submodel_id = descriptor["id"]
            response = http.post(f"{backend}/{submodel_id}", json=submodels[path], timeout=30)
            response.raise_for_status()
            endpoint["href"] = f"{public}/{submodel_id}"
            endpoint["subprotocolBody"] = f"id={assets_id};dspEndpoint={p['dsp']}"
        for asset_id in shell["specificAssetIds"]:
            # Visible to every partner (the DTR's access control is off in the umbrella).
            asset_id["externalSubjectId"] = {
                "type": "ExternalReference",
                "keys": [{"type": "GlobalReference", "value": "PUBLIC_READABLE"}],
            }

    edc = Edc(p["management"], p["api_key"])
    edc.policy("cxs-seed-access", ACCESS)
    edc.policy("cxs-seed-usage", USAGE)
    edc.asset(
        f"{key}-dtr",
        {"dct:type": {"@id": DTR_TYPE}, "cx-common:version": "3.0"},
        p["dtr"].rstrip("/") + "/api/v3",
    )
    edc.contract(f"{key}-dtr-contract", f"{key}-dtr")
    edc.asset(assets_id, {}, backend)
    edc.contract(f"{key}-submodels-contract", assets_id)

    dtr = p["dtr"].rstrip("/") + "/api/v3/shell-descriptors"
    for shell in shells:
        response = http.post(dtr, json=shell, timeout=30)
        # The DTR answers an existing shell with 400 "... does already exists" (not 409).
        if response.status_code == 409 or (
            response.status_code == 400 and "already exist" in response.text
        ):
            encoded = base64.urlsafe_b64encode(shell["id"].encode()).decode()
            response = http.put(f"{dtr}/{encoded.rstrip('=')}", json=shell, timeout=30)
        if response.status_code not in (200, 201, 204):
            raise SystemExit(f"DTR {shell['id']}: HTTP {response.status_code} {response.text}")
    print(f"{key:6} {p['bpnl']}: {len(shells)} twins, {len(submodels)} submodels, 2 assets")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(HERE / "participants.json"))
    args = parser.parse_args()
    participants = json.loads(Path(args.config).read_text())
    bpns = {key: p["bpnl"] for key, p in participants.items()}
    for key, p in participants.items():
        seed(key, p, bpns)


if __name__ == "__main__":
    main()
