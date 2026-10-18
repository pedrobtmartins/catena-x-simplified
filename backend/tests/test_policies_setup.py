import json

import scenario
from fakes import FakeReader, FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.admin import hash_password
from catenax_simplified.admin.config_store import effective_settings, merge_policies
from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.dataspace.edc import ASSET_ID_KEY, EdcNegotiator, OfferedPolicy, equals

PASSWORD = "correct horse battery"
KEY = "k" * 40
OWN_DSP = "https://edc.own.example/api/v1/dsp"


def _permission(*constraints: tuple[str, str]) -> dict:
    return {
        "permission": {
            "action": "use",
            "constraint": {
                "and": [
                    {"leftOperand": left, "operator": "eq", "rightOperand": right}
                    for left, right in constraints
                ]
            },
        }
    }


FRAMEWORK = ("FrameworkAgreement", "DataExchangeGovernance:1.0")
INDUSTRY_CORE = _permission(FRAMEWORK, ("UsagePurpose", "cx.core.industrycore:1"))
WITH_MEMBERSHIP = _permission(
    ("Membership", "active"), FRAMEWORK, ("UsagePurpose", "cx.core.industrycore:1")
)
# The same as INDUSTRY_CORE, spelled the Jupiter way.
INDUSTRY_CORE_JUPITER = {
    "odrl:permission": {
        "odrl:action": {"@id": "odrl:use"},
        "odrl:constraint": {
            "odrl:and": [
                {
                    "odrl:leftOperand": {"@id": "cx-policy:FrameworkAgreement"},
                    "odrl:operator": {"@id": "odrl:eq"},
                    "odrl:rightOperand": "DataExchangeGovernance:1.0",
                },
                {
                    "odrl:leftOperand": {"@id": "cx-policy:UsagePurpose"},
                    "odrl:operator": {"@id": "odrl:eq"},
                    "odrl:rightOperand": "cx.core.industrycore:1",
                },
            ]
        },
    }
}


def _client(tmp_path) -> TestClient:
    settings = Settings(
        own_bpnl=scenario.TIER1,
        database_url=f"sqlite:///{tmp_path}/app.db",
        admin_password_hash=hash_password(PASSWORD),
        secret_key=KEY,
        accepted_policies=[WITH_MEMBERSHIP],
    )
    return TestClient(
        create_app(
            settings,
            registry=FakeRegistry(scenario.shells()),
            reader=FakeReader(scenario.payloads()),
        )
    )


def _login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200


def test_an_admin_adds_policies_next_to_the_deployments(tmp_path):
    with _client(tmp_path) as client:
        before = client.get("/api/setup/policies").json()
        assert [p["policy"] for p in before["deployment"]] == [WITH_MEMBERSHIP]
        assert before["added"] == [] and before["editable"] is True
        assert "Membership=active" in before["deployment"][0]["description"]

        assert client.put("/api/setup/policies", json={"added": [INDUSTRY_CORE]}).status_code == 401
        _login(client)
        # The Jupiter spelling of the same policy is kept once.
        response = client.put(
            "/api/setup/policies", json={"added": [INDUSTRY_CORE, INDUSTRY_CORE_JUPITER]}
        )
        assert response.status_code == 200
        assert [p["policy"] for p in response.json()["added"]] == [INDUSTRY_CORE]
        # Applied at once: the negotiations use both lists.
        assert client.app.state.settings.accepted_policies == [WITH_MEMBERSHIP, INDUSTRY_CORE]

        assert client.put("/api/setup/policies", json={"added": []}).json()["added"] == []
        assert client.app.state.settings.accepted_policies == [WITH_MEMBERSHIP]


def test_only_odrl_policies_can_be_added(tmp_path):
    with _client(tmp_path) as client:
        _login(client)
        response = client.put("/api/setup/policies", json={"added": [{"name": "x"}]})
        assert response.status_code == 422
        assert "not an ODRL policy" in response.json()["detail"]


def test_the_policies_are_not_one_of_the_generic_settings(tmp_path):
    with _client(tmp_path) as client:
        _login(client)
        assert "accepted_policies" not in {f["key"] for f in client.get("/api/setup/config").json()}
        response = client.put(
            "/api/setup/config", json={"values": {"accepted_policies": json.dumps([INDUSTRY_CORE])}}
        )
        assert response.status_code == 422


def test_offered_policies_need_an_edc(tmp_path):
    with _client(tmp_path) as client:
        _login(client)
        response = client.post(
            "/api/setup/policies/offers",
            json={"bpnl": scenario.TIER1, "connector_address": OWN_DSP, "asset_id": "bundle"},
        )
        assert response.status_code == 503


def test_stored_policies_add_to_the_deployments():
    base = Settings(own_bpnl=scenario.TIER1, accepted_policies=[WITH_MEMBERSHIP])
    stored = {"accepted_policies": json.dumps([INDUSTRY_CORE_JUPITER, INDUSTRY_CORE])}
    assert effective_settings(base, stored).accepted_policies == [
        WITH_MEMBERSHIP,
        INDUSTRY_CORE_JUPITER,
    ]
    assert merge_policies([INDUSTRY_CORE], [INDUSTRY_CORE_JUPITER]) == [INDUSTRY_CORE]
    assert effective_settings(base, {}).accepted_policies == [WITH_MEMBERSHIP]


class CatalogConsumer:
    def __init__(self, catalog: dict):
        self.catalog = catalog
        self.filters: list[list[dict]] = []

    def get_discovery_info(self, bpnl, counter_party_address=None):
        return (
            counter_party_address + "/2025-1",
            f"did:web:{bpnl}",
            "dataspace-protocol-http:2025-1",
        )

    def get_catalog_with_filter(
        self, counter_party_id, counter_party_address, filter_expression, protocol
    ):
        self.filters.append(filter_expression)
        return self.catalog


def test_offered_policies_say_which_are_accepted_and_negotiate_nothing():
    offer = {"@id": "offer-1", "@type": "odrl:Offer", **INDUSTRY_CORE}
    catalog = {
        "dcat:dataset": [
            {"@id": "bundle", "odrl:hasPolicy": [offer, {"@id": "offer-2", **WITH_MEMBERSHIP}]},
        ]
    }
    consumer = CatalogConsumer(catalog)
    negotiator = EdcNegotiator(consumer, [WITH_MEMBERSHIP])

    offers = negotiator.offered_policies(scenario.TIER1, OWN_DSP, [equals(ASSET_ID_KEY, "bundle")])

    assert offers == [
        OfferedPolicy("bundle", INDUSTRY_CORE, accepted=False),
        OfferedPolicy("bundle", WITH_MEMBERSHIP, accepted=True),
    ]
    assert consumer.filters == [[equals(ASSET_ID_KEY, "bundle")]]
