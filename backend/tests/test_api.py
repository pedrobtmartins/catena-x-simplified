import pytest
import responses
import scenario
from fakes import FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(own_bpnl=scenario.TIER1, database_url="sqlite:///:memory:", **overrides)


@pytest.fixture
def client():
    # Real HTTP submodel reader (with href rewriting) against mocked submodel endpoints.
    settings = _settings(
        submodel_href_rewrites=[(scenario.BASE, "http://submodel-server/data")],
    )
    app = create_app(settings, registry=FakeRegistry(scenario.shells()))
    with (
        responses.RequestsMock(assert_all_requests_are_fired=False) as mock,
        TestClient(app) as test_client,
    ):
        for url, payload in scenario.payloads().items():
            mock.get(url.replace(scenario.BASE, "http://submodel-server/data"), json=payload)
        yield test_client


def test_health(client):
    assert client.get("/api/health").json() == {
        "status": "ok",
        "own_bpnl": scenario.TIER1,
        "dtr_configured": True,
    }


def test_sync_then_browse(client):
    assert client.get("/api/sync/last").status_code == 404

    report = client.post("/api/sync").json()
    assert report["complete"] is True
    assert (report["parts"], report["relation_sets"], report["issues"]) == (2, 3, [])
    assert client.get("/api/sync/last").json() == report

    page = client.get("/api/parts").json()
    assert page["total"] == 2
    assert {p["global_asset_id"] for p in page["items"]} == {scenario.MODULE_A, scenario.MODULE_B}

    part = client.get(f"/api/parts/{scenario.MODULE_A}").json()
    assert part["kind"] == "serial"
    assert part["site_ids"] == ["BPNS000000000002"]

    tree = client.get(f"/api/parts/{scenario.MODULE_A}/tree").json()
    assert tree["part"]["global_asset_id"] == scenario.MODULE_A
    assert [c["global_asset_id"] for c in tree["children"]] == [scenario.CELL_1, scenario.CELL_2]
    assert tree["children"][0] == {
        "global_asset_id": scenario.CELL_1,
        "part": None,
        "business_partner": scenario.TIER2,
        "quantity": 1.0,
        "unit": "unit:piece",
        "is_only_potential_parent": False,
        "declared_in": ["bom"],
    }
    assert tree["parents"][0]["global_asset_id"] == scenario.VEHICLE


def test_search_and_filters(client):
    client.post("/api/sync")
    assert client.get("/api/parts", params={"search": "mod-1"}).json()["total"] == 2
    assert client.get("/api/parts", params={"search": "000000000002"}).json()["total"] == 1
    assert client.get("/api/parts", params={"kind": "batch"}).json()["total"] == 0
    page = client.get("/api/parts", params={"limit": 1, "offset": 1}).json()
    assert (len(page["items"]), page["total"]) == (1, 2)
    assert client.get("/api/parts", params={"kind": "other"}).status_code == 422


def test_unknown_part(client):
    assert client.get("/api/parts/urn:uuid:does-not-exist").status_code == 404
    assert client.get("/api/parts/urn:uuid:does-not-exist/tree").status_code == 404


def test_sync_without_dtr_is_unavailable():
    with TestClient(create_app(_settings())) as client:
        assert client.get("/api/health").json()["dtr_configured"] is False
        assert client.post("/api/sync").status_code == 503


def test_settings_reject_invalid_bpnl():
    with pytest.raises(ValueError):
        Settings(own_bpnl="BPNS000000000001")
