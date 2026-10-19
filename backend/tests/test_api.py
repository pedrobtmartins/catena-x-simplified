import threading
import time

import pytest
import responses
import scenario
from fakes import FakePartnerClient, FakeRegistry
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
    app = create_app(
        settings,
        registry=FakeRegistry(scenario.shells()),
        partner_client=FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads()),
    )
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
    assert health["edc_configured"] is True
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
        assert client.get("/api/health").json()["edc_configured"] is False
        assert client.post("/api/partners/sync").status_code == 503


def test_settings_reject_invalid_bpnl():
    with pytest.raises(ValueError):
        Settings(own_bpnl="BPNS000000000001")


def _sync_partners(client, **kwargs) -> dict:
    """Starts a partner sync and waits for it; returns the finished progress."""
    started = client.post("/api/partners/sync", **kwargs)
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        progress = client.get("/api/partners/sync/progress").json()
        if progress["run_id"] == run_id and not progress["running"]:
            return progress
        time.sleep(0.02)
    raise AssertionError("the partner sync did not finish")


def test_partners_listing_update_and_sync(client):
    client.post("/api/sync")
    assert client.get("/api/partners/sync/progress").json() is None
    partners = {p["bpnl"]: p for p in client.get("/api/partners").json()}
    assert set(partners) == {scenario.TIER2, scenario.OEM}
    assert partners[scenario.TIER2]["roles"] == ["supplier"]
    assert partners[scenario.TIER2]["linked_twins"] == 3
    assert partners[scenario.OEM]["roles"] == ["customer"]
    assert partners[scenario.TIER2]["connector_address"] is None

    updated = client.put(
        f"/api/partners/{scenario.TIER2}",
        json={"name": "Cell supplier", "connector_address": scenario.TIER2_CONNECTOR},
    ).json()
    assert updated["name"] == "Cell supplier"
    assert (updated["connector_address"], updated["connector_source"]) == (
        scenario.TIER2_CONNECTOR,
        "api",
    )

    progress = _sync_partners(client)
    report = progress["report"]
    results = {r["bpnl"]: r for r in report["partners"]}
    assert (results[scenario.TIER2]["status"], results[scenario.TIER2]["twins_found"]) == (
        "partial",
        2,
    )
    assert results[scenario.OEM]["status"] == "no_connector"
    assert results[scenario.TIER2]["parts_cached"] == 2

    assert (progress["running"], progress["partners_done"], progress["twins_cached"]) == (
        False,
        2,
        2,
    )
    assert progress["finished_at"].endswith("Z")

    tier2 = next(p for p in client.get("/api/partners").json() if p["bpnl"] == scenario.TIER2)
    assert (tier2["cached_parts"], tier2["last_status"]) == (2, "partial")
    assert tier2["last_sync_at"].endswith("Z")

    tree = client.get(f"/api/parts/{scenario.MODULE_A}/tree").json()
    cell = next(c for c in tree["children"] if c["global_asset_id"] == scenario.CELL_1)
    assert cell["part"]["name_at_manufacturer"] == "Li-ion cell"
    assert cell["part"]["is_own"] is False

    one = _sync_partners(client, params={"bpnl": scenario.OEM})["report"]
    assert [r["bpnl"] for r in one["partners"]] == [scenario.OEM]

    picked = _sync_partners(client, json={"twins": [scenario.CELL_1]})["report"]
    assert [(r["bpnl"], r["linked_twins"]) for r in picked["partners"]] == [(scenario.TIER2, 1)]
    assert client.post("/api/partners/sync", json={"twins": []}).status_code == 422


def test_a_partner_sync_runs_in_the_background_one_at_a_time(client):
    client.post("/api/sync")
    client.put(
        f"/api/partners/{scenario.TIER2}", json={"connector_address": scenario.TIER2_CONNECTOR}
    )
    release = threading.Event()
    fake = client.app.state.partner_runner.job._client
    find_twin = fake.find_twin

    def held(partner, gid):
        release.wait(5)
        return find_twin(partner, gid)

    fake.find_twin = held
    try:
        started = client.post("/api/partners/sync")
        assert started.status_code == 202
        assert started.json()["running"] is True
        assert started.json()["report"] is None
        assert client.post("/api/partners/sync").status_code == 409
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while client.get("/api/partners/sync/progress").json()["running"]:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert _sync_partners(client)["report"]["partners"]


def test_cannot_register_own_bpnl_as_partner(client):
    response = client.put(f"/api/partners/{scenario.TIER1}", json={"name": "me"})
    assert response.status_code == 422


def test_web_ui_cache_headers(tmp_path):
    # Hashed assets are cached for good; index.html is revalidated so an upgrade shows at once.
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "assets" / "index-abc123.js").write_text("")
    with TestClient(create_app(_settings(web_dist_dir=str(tmp_path)))) as client:
        assert client.get("/").headers["cache-control"] == "no-cache"
        asset = client.get("/assets/index-abc123.js")
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert client.get("/api/health").status_code == 200


def test_the_endpoint_reports_nothing_for_consistent_boms(client):
    client.post("/api/sync")
    assert client.get("/api/data-checks").json() == {"total": 0, "findings": []}


def test_structure_and_where_used_endpoints(client):
    client.post("/api/sync")
    assert client.get("/api/parts/urn:uuid:unknown/structure").status_code == 404
    structure = client.get(f"/api/parts/{scenario.MODULE_A}/structure").json()
    assert structure["root"] == scenario.MODULE_A
    root = next(p for p in structure["parts"] if p["global_asset_id"] == scenario.MODULE_A)
    assert root["own"] and root["cached"]
    children = {link["child"] for link in structure["links"] if link["parent"] == scenario.MODULE_A}
    assert children and all(
        not p["own"] for p in structure["parts"] if p["global_asset_id"] in children
    )
    used = client.get(f"/api/parts/{scenario.MODULE_A}/where-used").json()
    assert used["paths"] and all(path[0] == scenario.MODULE_A for path in used["paths"])
