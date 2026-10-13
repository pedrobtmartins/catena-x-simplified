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
    health = client.get("/api/health").json()
    assert {k: health[k] for k in ("status", "own_bpnl", "dtr_configured", "dtr_url")} == {
        "status": "ok",
        "own_bpnl": scenario.TIER1,
        "dtr_configured": True,
        "dtr_url": None,  # the registry is injected in tests
    }
    assert health["sync_interval_seconds"] == 0
    assert "io.catenax.serial_part:3.0.0" in health["supported_aspects"]


def test_sync_then_browse(client):
    assert client.get("/api/sync/last").status_code == 404

    report = client.post("/api/sync").json()
    assert report["complete"] is True
    assert (report["parts"], report["relation_sets"], report["issues"]) == (2, 3, [])
    assert report["id"] == 1
    assert report["started_at"].endswith("Z")
    assert client.get("/api/sync/last").json() == report

    page = client.get("/api/parts").json()
    assert page["total"] == 2
    counts = {
        p["global_asset_id"]: (p["parents_count"], p["children_count"]) for p in page["items"]
    }
    assert counts == {scenario.MODULE_A: (1, 2), scenario.MODULE_B: (0, 1)}

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
    v3 = client.get("/api/parts", params={"aspect_major": 3}).json()
    assert [p["global_asset_id"] for p in v3["items"]] == [scenario.MODULE_B]
    v4 = client.get("/api/parts", params={"aspect_major": 4}).json()
    assert [p["global_asset_id"] for p in v4["items"]] == [scenario.MODULE_A]


def test_stats(client):
    client.post("/api/sync")
    assert client.get("/api/stats").json() == {
        "own_parts": 2,
        "own_parts_by_kind": {"serial": 2},
        "own_parts_by_semantic_id": {
            "urn:samm:io.catenax.serial_part:3.0.0#SerialPart": 1,
            "urn:samm:io.catenax.serial_part:4.0.0#SerialPart": 1,
        },
        "supplier_links": 3,
        "suppliers": 1,
        "customer_links": 1,
        "customers": 1,
    }


def test_sync_runs_are_recorded_newest_first(client):
    assert client.get("/api/sync/runs").json() == {"items": []}
    first = client.post("/api/sync").json()
    second = client.post("/api/sync").json()
    runs = client.get("/api/sync/runs").json()["items"]
    assert [r["id"] for r in runs] == [second["id"], first["id"]]
    assert client.get("/api/sync/runs", params={"limit": 1}).json()["items"] == [second]


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
