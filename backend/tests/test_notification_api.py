import time

import pytest
import scenario
from fakes import FakeReader, FakeRegistry
from fastapi.testclient import TestClient

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.dataspace import DataspaceError

API_KEY = "s3cret"
NOTIFICATION_ID = "41d743c3-6e8a-4393-88af-10494e50bea9"


class RecordingSender:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, partner, asset_type, build):
        if self.fail:
            raise DataspaceError(f"negotiation with {partner.bpnl} failed: timeout")
        self.sent.append((partner, asset_type.rsplit("#", 1)[-1], build("1.2.1")))
        return "1.2.1"


class FakePublisher:
    def __init__(self):
        self.calls = 0

    def publish(self):
        self.calls += 1
        return ["cxs-receive-alert-2.0.0"]


@pytest.fixture
def sender():
    return RecordingSender()


@pytest.fixture
def client(sender):
    settings = Settings(
        own_bpnl=scenario.TIER1,
        database_url="sqlite:///:memory:",
        notification_api_key=API_KEY,
        partner_connectors={scenario.OEM: "https://edc.oem/api/v1/dsp"},
    )
    app = create_app(
        settings,
        registry=FakeRegistry(scenario.shells()),
        reader=FakeReader(scenario.payloads()),
        notification_sender=sender,
        asset_publisher=FakePublisher(),
    )
    with TestClient(app) as test_client:
        assert test_client.post("/api/sync").status_code == 200
        yield test_client


def _alert_from_tier2(**content):
    return {
        "header": {
            "messageId": "3b4edc05-e214-47a1-b0c2-1d831cdd9ba9",
            "context": "Traceability-QualityNotification-Alert:2.0.0",
            "sentDateTime": "2026-10-14T14:35:24Z",
            "senderBpn": scenario.TIER2,
            "receiverBpn": scenario.TIER1,
        },
        "content": {
            "notificationId": NOTIFICATION_ID,
            "status": "SENT",
            "severity": "CRITICAL",
            "information": "Thermal runaway risk",
            "listOfAffectedItems": [
                scenario.CELL_1,
                "urn:uuid:ffffffff-0000-4000-8000-000000000000",
            ],
            **content,
        },
    }


def _receive(client, body, key=API_KEY):
    return client.post("/api/qualitynotifications/receive", json=body, headers={"X-Api-Key": key})


def test_receive_endpoint_follows_the_notification_api(client):
    assert _receive(client, _alert_from_tier2(), key="wrong").status_code == 401
    assert _receive(client, _alert_from_tier2()).status_code == 201
    assert _receive(client, _alert_from_tier2()).status_code == 409
    assert _receive(client, {"header": {}}).status_code == 400
    not_json = client.post(
        "/api/qualitynotifications/receive",
        content=b"{not json",
        headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
    )
    assert not_json.status_code == 400
    latin1_key = client.post(
        "/api/qualitynotifications/receive",
        json=_alert_from_tier2(),
        headers={"X-Api-Key": "clé".encode("latin-1")},
    )
    assert latin1_key.status_code == 401

    page = client.get("/api/notifications", params={"direction": "inbound"}).json()
    assert page["total"] == 1
    assert client.get("/api/notifications/summary").json() == {
        "inbound_open": 1,
        "inbound_new": 1,
        "outbound_open": 0,
    }

    detail = client.get(f"/api/notifications/{page['items'][0]['id']}").json()
    assert (detail["type"], detail["status"], detail["severity"]) == (
        "alert",
        "RECEIVED",
        "CRITICAL",
    )
    assert detail["actions"] == ["ACKNOWLEDGED"]
    # Partner parts are only cached after a partner sync.
    assert [item["part"] for item in detail["items"]] == [None, None]
    assert detail["messages"][0]["direction"] == "inbound"


def test_update_endpoint(client):
    _receive(client, _alert_from_tier2())
    closing = _alert_from_tier2(status="CLOSED")
    closing["header"]["messageId"] = "3b4edc05-e214-47a1-b0c2-1d831cdd9ba8"
    response = client.post(
        "/api/qualitynotifications/update", json=closing, headers={"X-Api-Key": API_KEY}
    )
    assert response.status_code == 200
    accepted = _alert_from_tier2(status="ACCEPTED")
    response = client.post(
        "/api/qualitynotifications/update", json=accepted, headers={"X-Api-Key": API_KEY}
    )
    assert response.status_code == 422


def test_forward_received_alert_to_customers(client, sender):
    _receive(client, _alert_from_tier2())
    (received,) = client.get("/api/notifications").json()["items"]
    plan = client.get(f"/api/notifications/{received['id']}/forward-plan").json()
    assert plan["own_parts"] == [scenario.MODULE_A]
    assert plan["recipients"] == {scenario.OEM: [scenario.MODULE_A]}

    created = client.post(
        "/api/notifications",
        json={
            "type": "alert",
            "affected_items": [scenario.MODULE_A],
            "severity": "CRITICAL",
            "description": "Modules with affected cells",
            "forwarded_from": received["id"],
            "send": True,
        },
    )
    assert created.status_code == 201
    (alert,) = created.json()
    assert (alert["partner_bpnl"], alert["status"], alert["api_version"]) == (
        scenario.OEM,
        "RECEIVED",
        "1.2.1",
    )
    partner, asset_type, body = sender.sent[0]
    assert partner.connector_address == "https://edc.oem/api/v1/dsp"
    assert asset_type == "ReceiveQualityAlertNotification"
    assert body["content"]["listOfAffectedItems"] == [scenario.MODULE_A]

    source = client.get(f"/api/notifications/{received['id']}").json()
    assert [n["id"] for n in source["forwarded_to"]] == [alert["id"]]
    detail = client.get(f"/api/notifications/{alert['id']}").json()
    assert detail["forwarded_from"]["id"] == received["id"]
    assert detail["items"][0]["part"]["name_at_manufacturer"] == "Battery module"
    assert detail["actions"] == ["CLOSED"]


def test_failed_send_returns_the_draft_with_its_error(client, sender):
    sender.fail = True
    body = {
        "type": "alert",
        "affected_items": [scenario.MODULE_A],
        "severity": "MINOR",
        "description": "x",
    }
    (draft,) = client.post("/api/notifications", json={**body, "send": True}).json()
    assert draft["status"] == "CREATED"
    assert "timeout" in draft["last_error"]
    response = client.post(f"/api/notifications/{draft['id']}/send")
    assert response.status_code == 502
    sender.fail = False
    assert client.post(f"/api/notifications/{draft['id']}/send").json()["status"] == "RECEIVED"


def test_plan_and_validation(client):
    plan = client.post(
        "/api/notifications/plan",
        json={"type": "investigation", "affected_items": [scenario.CELL_3, scenario.MODULE_A]},
    ).json()
    assert plan == {
        "type": "investigation",
        "recipients": {scenario.TIER2: [scenario.CELL_3]},
        "unmatched": [scenario.MODULE_A],
    }
    response = client.post(
        "/api/notifications",
        json={
            "type": "investigation",
            "affected_items": [scenario.MODULE_A],
            "severity": "MINOR",
            "description": "x",
        },
    )
    assert response.status_code == 422
    assert "no direct supplier known" in response.json()["detail"]
    assert (
        client.post("/api/notifications/999/status", json={"status": "CLOSED"}).status_code == 404
    )


def test_assets_are_published_at_startup(client):
    deadline = time.monotonic() + 5
    while (health := client.get("/api/health").json())["notification_assets"][
        "state"
    ] == "publishing" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert health["notification_assets"]["state"] == "published"
    assert health["can_send_notifications"] is True
    assert health["notification_assets"]["asset_ids"] == ["cxs-receive-alert-2.0.0"]
    assert client.post("/api/notifications/assets").json()["state"] == "published"
