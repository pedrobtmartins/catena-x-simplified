import pytest
import responses
import scenario
from fakes import FakePartnerClient, FakeRegistry
from fastapi.testclient import TestClient
from responses import matchers

from catenax_simplified.api import create_app
from catenax_simplified.config import Settings
from catenax_simplified.dataspace.edc import DCT_TYPE_KEYS, Partner
from catenax_simplified.dataspace.health import (
    LEVELS,
    CheckStep,
    DirectHealthChecker,
    EdcHealthChecker,
    dataset_ids,
    notification_types,
    scrub,
)
from catenax_simplified.dataspace.partners import DTR_ASSET_TYPE
from catenax_simplified.notifications import NotificationType
from catenax_simplified.traceability.partner_health import overall_status

PARTNER = Partner("BPNL000000000T2A", "https://edc.tier2/api/v1/dsp")
DTR_PLANE = "https://edc.tier2/api/public/dtr"
RECEIVE_INVESTIGATION = NotificationType.INVESTIGATION.asset_type("receive")
UPDATE_ALERT = NotificationType.ALERT.asset_type("update")
SUPPLIER_TYPES = [RECEIVE_INVESTIGATION, UPDATE_ALERT]


def _catalog(*datasets):
    return {"@id": "catalog-1", "@type": "dcat:Catalog", "dcat:dataset": list(datasets)}


def _notification(asset_id, version):
    return {"@id": asset_id, "@type": "dcat:Dataset", "cx-common:version": version}


class FakeConsumer:
    """Catalogs by (dct:type key, dct:type); discovery fails for the BPNLs in ``unreachable``."""

    def __init__(self, catalogs=None, unreachable=(), fail_negotiation=False):
        self.catalogs = catalogs or {}
        self.unreachable = set(unreachable)
        self.fail_negotiation = fail_negotiation
        self.discoveries = 0
        self.negotiations = []

    def get_discovery_info(self, bpnl, counter_party_address=None):
        self.discoveries += 1
        if bpnl in self.unreachable:
            raise RuntimeError("connection refused (Authorization: Bearer abc.def)")
        return (
            counter_party_address + "/2025-1",
            f"did:web:{bpnl}",
            "dataspace-protocol-http:2025-1",
        )

    def get_catalog_with_filter(
        self,
        counter_party_id,
        counter_party_address,
        filter_expression,
        timeout=None,
        protocol=None,
    ):
        condition = filter_expression[0]
        return self.catalogs.get((condition["operandLeft"], condition["operandRight"]), _catalog())

    def do_dsp(
        self, counter_party_id, counter_party_address, filter_expression, policies, protocol
    ):
        self.negotiations.append(filter_expression)
        if self.fail_negotiation:
            raise RuntimeError("PolicyMismatchError: no valid policy")
        return DTR_PLANE, "dtr-token"


def _healthy_catalogs():
    return {
        (DCT_TYPE_KEYS[0], DTR_ASSET_TYPE): _catalog({"@id": "dtr-asset"}),
        # Published with the https Dublin Core namespace: found on the second try.
        (DCT_TYPE_KEYS[1], RECEIVE_INVESTIGATION): _catalog(
            _notification("inv-1", "1.2.1"), _notification("inv-2", "2.0.0")
        ),
        (DCT_TYPE_KEYS[0], UPDATE_ALERT): _catalog(_notification("upd-1", "1.2.1")),
    }


def _by_key(steps):
    return {step.key: step for step in steps}


def test_discovery_only_is_read_only():
    consumer = FakeConsumer(_healthy_catalogs())
    steps = EdcHealthChecker(consumer, accepted_policies=None).check(
        PARTNER, "discovery", SUPPLIER_TYPES
    )
    assert [(s.key, s.status) for s in steps] == [("discovery", "ok")]
    assert "https://edc.tier2/api/v1/dsp/2025-1" in steps[0].detail
    assert consumer.negotiations == []


def test_catalog_check_reports_offers_and_versions():
    consumer = FakeConsumer(_healthy_catalogs())
    steps = _by_key(
        EdcHealthChecker(consumer, accepted_policies=None).check(PARTNER, "catalog", SUPPLIER_TYPES)
    )
    assert steps["dtr_offer"].status == "ok"
    assert "dtr-asset" in steps["dtr_offer"].detail
    assert steps["notification:ReceiveQualityInvestigationNotification"].detail == (
        "Notification API 2.0.0"
    )
    assert steps["notification:UpdateQualityAlertNotification"].detail == "Notification API 1.2.1"
    assert consumer.negotiations == []


def test_incompatible_notification_version_is_a_warning():
    catalogs = _healthy_catalogs()
    catalogs[(DCT_TYPE_KEYS[0], UPDATE_ALERT)] = _catalog(_notification("upd-1", "3.0.0"))
    steps = _by_key(
        EdcHealthChecker(FakeConsumer(catalogs), None).check(PARTNER, "catalog", SUPPLIER_TYPES)
    )
    alert = steps["notification:UpdateQualityAlertNotification"]
    assert (alert.status, alert.detail) == ("warn", "no compatible version (offered: 3.0.0)")


def test_missing_registry_offer_fails_and_skips_the_full_check():
    catalogs = _healthy_catalogs()
    del catalogs[(DCT_TYPE_KEYS[0], DTR_ASSET_TYPE)]
    consumer = FakeConsumer(catalogs)
    steps = _by_key(EdcHealthChecker(consumer, None).check(PARTNER, "full", SUPPLIER_TYPES))
    assert steps["dtr_offer"].status == "failed"
    assert steps["registry_access"].status == "skipped"
    assert consumer.negotiations == []


def test_unreachable_partner_skips_later_steps_and_hides_credentials():
    consumer = FakeConsumer(unreachable={PARTNER.bpnl})
    steps = EdcHealthChecker(consumer, None).check(PARTNER, "full", SUPPLIER_TYPES)
    assert steps[0].status == "failed"
    assert "connection refused" in steps[0].detail
    assert "abc.def" not in steps[0].detail
    assert {s.status for s in steps[1:]} == {"skipped"}


def test_discovery_is_fresh_for_every_check():
    consumer = FakeConsumer(_healthy_catalogs())
    checker = EdcHealthChecker(consumer, None)
    checker.check(PARTNER, "discovery", [])
    checker.check(PARTNER, "discovery", [])
    assert consumer.discoveries == 2


@responses.activate
def test_full_check_reads_the_registry_with_the_access_token():
    responses.get(
        f"{DTR_PLANE}/shell-descriptors",
        match=[
            matchers.query_param_matcher({"limit": "1"}),
            matchers.header_matcher({"Authorization": "dtr-token"}),
        ],
        json={"result": []},
    )
    consumer = FakeConsumer(_healthy_catalogs())
    steps = _by_key(EdcHealthChecker(consumer, None).check(PARTNER, "full", SUPPLIER_TYPES))
    assert steps["registry_access"].status == "ok"
    assert len(consumer.negotiations) == 1


@responses.activate
def test_full_check_reports_a_rejected_token():
    responses.get(f"{DTR_PLANE}/shell-descriptors", status=403)
    steps = _by_key(
        EdcHealthChecker(FakeConsumer(_healthy_catalogs()), None).check(PARTNER, "full", [])
    )
    assert steps["registry_access"].status == "failed"
    assert "HTTP 403" in steps["registry_access"].detail


def test_failed_negotiation_is_reported():
    consumer = FakeConsumer(_healthy_catalogs(), fail_negotiation=True)
    steps = _by_key(EdcHealthChecker(consumer, None).check(PARTNER, "full", []))
    assert steps["registry_access"].status == "failed"
    assert "PolicyMismatchError" in steps["registry_access"].detail


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        EdcHealthChecker(FakeConsumer(), None).check(PARTNER, "deep", [])


@responses.activate
def test_direct_checker_in_development_mode():
    responses.get("http://tier2-app/api/health", json={"status": "ok"})
    responses.get("http://tier2-dtr/api/v3/shell-descriptors", json={"result": []})
    checker = DirectHealthChecker({PARTNER.bpnl: "http://tier2-dtr/api/v3"})
    steps = _by_key(
        checker.check(Partner(PARTNER.bpnl, "http://tier2-app"), "full", SUPPLIER_TYPES)
    )
    assert steps["discovery"].status == "ok"
    assert "development mode" in steps["discovery"].detail
    assert steps["dtr_offer"].status == "ok"
    assert steps["registry_access"].status == "skipped"
    assert steps["notification:UpdateQualityAlertNotification"].status == "skipped"


@responses.activate
@pytest.mark.parametrize("level", LEVELS)
def test_development_mode_is_never_reported_healthy(level):
    responses.get("http://tier2-app/api/health", json={"status": "ok"})
    responses.get("http://tier2-dtr/api/v3/shell-descriptors", json={"result": []})
    checker = DirectHealthChecker({PARTNER.bpnl: "http://tier2-dtr/api/v3"})
    steps = checker.check(Partner(PARTNER.bpnl, "http://tier2-app"), level, SUPPLIER_TYPES)
    assert overall_status(steps) == "skipped"


def test_overall_status_precedence():
    def steps(*statuses):
        return [CheckStep(str(i), "step", s, "") for i, s in enumerate(statuses)]

    assert overall_status(steps("ok", "ok")) == "healthy"
    assert overall_status(steps("ok", "skipped")) == "skipped"
    assert overall_status(steps("warn", "skipped")) == "degraded"
    assert overall_status(steps("failed", "warn", "skipped")) == "failed"


def test_dataset_ids_reads_nested_and_single_datasets():
    catalog = {
        "dcat:dataset": {"@id": "a"},
        "dcat:catalog": [{"dcat:dataset": [{"@id": "b"}, {"@id": "a"}]}],
    }
    assert dataset_ids(catalog) == ["a", "b"]
    assert dataset_ids({"@id": "catalog-only"}) == []


def test_notification_types_follow_the_roles():
    assert notification_types(["supplier"]) == SUPPLIER_TYPES
    assert len(notification_types(["customer"])) == 2
    assert len(set(notification_types([]))) == 4


@pytest.mark.parametrize(
    ("raw", "hidden"),
    [
        ('{"Authorization": "Bearer-xyz"}', "Bearer-xyz"),
        ("token=abc123 rejected", "abc123"),
        ("x-api-key: s3cr3t", "s3cr3t"),
        ("got eyJhbGciOi.eyJzdWIi.c2ln back", "eyJhbGciOi"),
    ],
)
def test_scrub_removes_credentials(raw, hidden):
    assert hidden not in scrub(raw)


# -- API -------------------------------------------------------------------------------------


class FakeHealthChecker:
    def __init__(self, failing=()):
        self.failing = set(failing)
        self.calls = []

    def check(self, partner, level, notification_types):
        self.calls.append((partner.bpnl, level, list(notification_types)))
        status = "failed" if partner.bpnl in self.failing else "ok"
        return [CheckStep("discovery", "Connector discovery", status, "checked")]


@pytest.fixture
def checker():
    return FakeHealthChecker()


@pytest.fixture
def client(checker):
    settings = Settings(
        own_bpnl=scenario.TIER1,
        database_url="sqlite:///:memory:",
        partner_connectors={scenario.TIER2: scenario.TIER2_CONNECTOR},
        submodel_href_rewrites=[(scenario.BASE, "http://submodel-server/data")],
    )
    app = create_app(
        settings,
        registry=FakeRegistry(scenario.shells()),
        partner_client=FakePartnerClient(scenario.tier2_twins(), scenario.tier2_payloads()),
        health_checker=checker,
    )
    with (
        responses.RequestsMock(assert_all_requests_are_fired=False) as mock,
        TestClient(app) as test_client,
    ):
        for url, payload in scenario.payloads().items():
            mock.get(url.replace(scenario.BASE, "http://submodel-server/data"), json=payload)
        test_client.post("/api/sync")
        yield test_client


def test_check_one_partner_and_list_it(client, checker):
    assert client.get("/api/health").json()["can_check_partners"] is True
    check = client.post(f"/api/partners/{scenario.TIER2}/checks", json={"level": "catalog"}).json()
    assert (check["bpnl"], check["level"], check["status"]) == (
        scenario.TIER2,
        "catalog",
        "healthy",
    )
    assert check["connector_address"] == scenario.TIER2_CONNECTOR
    assert check["started_at"].endswith("Z")
    assert checker.calls == [(scenario.TIER2, "catalog", SUPPLIER_TYPES)]

    tier2 = next(p for p in client.get("/api/partners").json() if p["bpnl"] == scenario.TIER2)
    assert tier2["last_check"]["id"] == check["id"]

    history = client.get("/api/partners/checks", params={"bpnl": scenario.TIER2}).json()
    assert [c["id"] for c in history["items"]] == [check["id"]]


def test_partner_without_connector_fails_without_calling_the_checker(client, checker):
    check = client.post(f"/api/partners/{scenario.OEM}/checks", json={"level": "discovery"}).json()
    assert check["status"] == "failed"
    assert check["steps"][0]["detail"] == "no connector address known for this partner"
    assert checker.calls == []


def test_full_check_needs_confirmation(client, checker):
    url = f"/api/partners/{scenario.TIER2}/checks"
    assert client.post(url, json={"level": "full"}).status_code == 409
    assert checker.calls == []
    response = client.post(url, json={"level": "full", "confirm_state_change": True})
    assert response.status_code == 200
    assert client.post(url, json={"level": "deep"}).status_code == 422


def test_unknown_partner_is_404(client):
    response = client.post("/api/partners/BPNL00000000NONE/checks", json={"level": "discovery"})
    assert response.status_code == 404


def test_batch_checks_only_unhealthy_partners(client, checker):
    first = client.post("/api/partners/checks", json={"level": "discovery"}).json()
    assert {c["bpnl"]: c["status"] for c in first["items"]} == {
        scenario.OEM: "failed",  # no connector
        scenario.TIER2: "healthy",
    }
    again = client.post("/api/partners/checks", json={"level": "discovery"}).json()
    assert [c["bpnl"] for c in again["items"]] == [scenario.OEM]
    everyone = client.post(
        "/api/partners/checks", json={"level": "discovery", "only_unhealthy": False}
    ).json()
    assert len(everyone["items"]) == 2


def test_checks_are_unavailable_without_an_edc():
    app = create_app(Settings(own_bpnl=scenario.TIER1, database_url="sqlite:///:memory:"))
    with TestClient(app) as test_client:
        assert test_client.get("/api/health").json()["can_check_partners"] is False
        response = test_client.post("/api/partners/checks", json={"level": "discovery"})
        assert response.status_code == 503


def test_a_5xx_from_the_own_connector_says_so():
    from catenax_simplified.dataspace.health import own_connector_hint

    detail = own_connector_hint(
        "connector discovery for X failed: [Connector Service]: It was not possible to get the "
        "catalog from the EDC provider! Response code: [504]"
    )
    assert "HTTP 504 came from your own connector" in detail
    assert (
        own_connector_hint("negotiation failed: no valid policy")
        == "negotiation failed: no valid policy"
    )


def test_notification_offers_do_not_change_the_connectors_status():
    from catenax_simplified.traceability.partner_health import notifications_status

    core_ok = [
        CheckStep("discovery", "Connector discovery", "ok", ""),
        CheckStep("dtr_offer", "Digital Twin Registry offer", "ok", ""),
        CheckStep("registry_access", "Registry access (EDR)", "ok", ""),
    ]
    missing = CheckStep("notification:ReceiveQualityAlertNotification", "x", "warn", "not offered")
    ready = CheckStep("notification:UpdateQualityAlertNotification", "x", "ok", "API 2.0.0")

    assert overall_status([*core_ok, missing]) == "healthy"
    assert notifications_status([*core_ok, missing, ready]) == "incomplete"
    assert notifications_status([*core_ok, ready]) == "ready"
    assert notifications_status(core_ok) == "unchecked"
    failed_registry = [core_ok[0], CheckStep("dtr_offer", "x", "warn", "no offer")]
    assert overall_status([*failed_registry, ready]) == "degraded"
