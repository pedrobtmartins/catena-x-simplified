import pytest
import responses
import scenario
from fakes import FakeReader, FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace.business_partners import BpdmPool
from catenax_simplified.wiring import build_partner_directory, central_auth

POOL = "https://business-partners.example/pool/api"
NEW = "BPNL0000000NEW1A"


class FakeOAuth:
    def add_auth_header(self, headers=None):
        return {**(headers or {}), "Authorization": "Bearer token"}


class FakeDirectory:
    def __init__(self, names, failing=()):
        self.names = names
        self.failing = set(failing)

    def legal_name(self, bpnl):
        if bpnl in self.failing:
            raise DataspaceError(f"BPDM lookup of {bpnl} failed: HTTP 503")
        return self.names.get(bpnl)


@responses.activate
def test_pool_returns_the_legal_name():
    responses.get(
        f"{POOL}/v7/legal-entities/{NEW}",
        json={"bpnl": NEW, "legalName": "New Cells GmbH", "legalShortName": "New Cells"},
    )
    assert BpdmPool(POOL + "/", FakeOAuth()).legal_name(NEW) == "New Cells GmbH"
    assert responses.calls[0].request.headers["Authorization"] == "Bearer token"


@responses.activate
def test_pool_unknown_bpnl_and_failures():
    pool = BpdmPool(POOL, FakeOAuth())
    responses.get(f"{POOL}/v7/legal-entities/{NEW}", status=404)
    assert pool.legal_name(NEW) is None
    responses.replace(responses.GET, f"{POOL}/v7/legal-entities/{NEW}", status=401)
    with pytest.raises(DataspaceError, match="HTTP 401"):
        pool.legal_name(NEW)


def test_names_need_a_pool_and_the_central_idp():
    def build(**settings):
        settings = Settings(own_bpnl=scenario.TIER1, bpdm_pool_url=POOL, **settings)
        return build_partner_directory(settings, central_auth(settings))

    assert build() is None
    assert build(central_idp_url="https://centralidp.example/auth/") is not None


def _client(directory=None):
    settings = Settings(own_bpnl=scenario.TIER1, database_url="sqlite:///:memory:")
    app = create_app(
        settings,
        registry=FakeRegistry(scenario.shells()),
        reader=FakeReader(scenario.payloads()),
        directory=directory,
    )
    return TestClient(app)


def test_look_up_a_legal_name():
    with _client(FakeDirectory({NEW: "New Cells GmbH"})) as client:
        assert client.get("/api/health").json()["can_look_up_names"] is True
        assert client.get(f"/api/partners/{NEW}/legal-entity").json() == {
            "bpnl": NEW,
            "legal_name": "New Cells GmbH",
        }
        unknown = client.get("/api/partners/BPNL0000000UNKNO/legal-entity").json()
        assert unknown["legal_name"] is None
        assert client.get("/api/partners").json() == []  # nothing stored


def test_names_not_configured_or_failing():
    with _client() as client:
        assert client.get("/api/health").json()["can_look_up_names"] is False
        response = client.get(f"/api/partners/{NEW}/legal-entity")
        assert response.status_code == 503
        assert "CXS_BPDM_POOL_URL" in response.json()["detail"]
        assert client.post("/api/partners/names").status_code == 503
    with _client(FakeDirectory({}, failing=[NEW])) as client:
        assert client.get(f"/api/partners/{NEW}/legal-entity").status_code == 502


def test_fill_the_names_of_unnamed_partners():
    directory = FakeDirectory(
        {scenario.TIER2: "Tier-2 Cells AG", NEW: "New Cells GmbH"}, failing=[scenario.OEM]
    )
    with _client(directory) as client:
        client.post("/api/sync")
        client.put(f"/api/partners/{NEW}", json={"name": "Our name for them"})
        results = {r["bpnl"]: r for r in client.post("/api/partners/names").json()}
        assert set(results) == {scenario.TIER2, scenario.OEM}  # NEW already had a name
        assert results[scenario.TIER2] == {
            "bpnl": scenario.TIER2,
            "status": "named",
            "name": "Tier-2 Cells AG",
            "message": None,
        }
        assert results[scenario.OEM]["status"] == "failed"
        names = {p["bpnl"]: p["name"] for p in client.get("/api/partners").json()}
        assert names == {
            scenario.TIER2: "Tier-2 Cells AG",
            scenario.OEM: None,
            NEW: "Our name for them",
        }
