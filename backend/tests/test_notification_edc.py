import json

import pytest
import responses
from responses import matchers

from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace.edc import ASSET_ID_KEY, DCT_TYPE_KEYS, Partner
from catenax_simplified.dataspace.notification_assets import (
    NotificationAssetPublisher,
    notification_assets,
)
from catenax_simplified.dataspace.notifications import (
    EdcNotificationSender,
    NotificationRejected,
    Offer,
    choose_offer,
    offers_in,
)
from catenax_simplified.notifications import NotificationType

PARTNER = Partner("BPNL000000000T1A", "https://edc.tier1/api/v1/dsp")
ENDPOINT = "https://edc.tier1/api/public"
RECEIVE_ALERT = NotificationType.ALERT.asset_type("receive")
POLICY = {"odrl:permission": {"odrl:action": "odrl:use"}}


def _dataset(asset_id, version, prefixed=True):
    key = "cx-common:version" if prefixed else "https://w3id.org/catenax/ontology/common#version"
    return {"@id": asset_id, "@type": "dcat:Dataset", key: version, "odrl:hasPolicy": {}}


def _catalog(*datasets):
    datasets = list(datasets)
    return {
        "@id": "catalog-1",
        "@type": "dcat:Catalog",
        "dcat:dataset": datasets[0] if len(datasets) == 1 else datasets,
    }


class FakeConsumer:
    def __init__(self, catalogs):
        self.catalogs = catalogs  # by dct:type key
        self.catalog_requests = []
        self.negotiations = []

    def get_discovery_info(self, bpnl, counter_party_address=None):
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
        key = filter_expression[0]["operandLeft"]
        self.catalog_requests.append((counter_party_id, key, filter_expression[0]["operandRight"]))
        return self.catalogs.get(key, _catalog())

    def do_dsp(
        self, counter_party_id, counter_party_address, filter_expression, policies, protocol
    ):
        self.negotiations.append(filter_expression)
        return ENDPOINT, "notification-token"


def test_offers_in_reads_prefixed_expanded_and_federated_catalogs():
    catalog = {
        "@type": "dcat:Catalog",
        "dataset": [_dataset("a-1.2", "1.2", prefixed=False)],
        "dcat:catalog": [_catalog(_dataset("a-2", "2.0.0"), _dataset("a-3", "3.0"))],
    }
    assert offers_in(catalog) == [
        Offer("a-1.2", "1.2", "1.2.1"),
        Offer("a-2", "2.0.0", "2.0.0"),
        Offer("a-3", "3.0", None),
    ]


def test_choose_offer_prefers_the_highest_compatible_version():
    offers = [Offer("old", "1.2", "1.2.1"), Offer("new", "2.0", "2.0.0"), Offer("x", "3", None)]
    assert choose_offer(offers).asset_id == "new"
    assert choose_offer([Offer("x", "3", None)]) is None


@responses.activate
def test_send_negotiates_the_best_offer_and_posts_that_version():
    consumer = FakeConsumer(
        {DCT_TYPE_KEYS[0]: _catalog(_dataset("alert-1.2", "1.2"), _dataset("alert-2", "2.0"))}
    )
    responses.post(
        ENDPOINT,
        match=[
            matchers.header_matcher({"Authorization": "notification-token"}),
            matchers.json_params_matcher({"version": "2.0.0"}),
        ],
        status=201,
    )
    sender = EdcNotificationSender(consumer, accepted_policies=[POLICY])

    version = sender.send(PARTNER, RECEIVE_ALERT, lambda v: {"version": v})

    assert version == "2.0.0"
    assert consumer.catalog_requests == [
        ("did:web:BPNL000000000T1A", DCT_TYPE_KEYS[0], RECEIVE_ALERT)
    ]
    assert consumer.negotiations == [
        [{"operandLeft": ASSET_ID_KEY, "operator": "=", "operandRight": "alert-2"}]
    ]


@responses.activate
def test_send_falls_back_to_the_https_dct_namespace():
    consumer = FakeConsumer({DCT_TYPE_KEYS[1]: _catalog(_dataset("alert-1", "1.2.1"))})
    responses.post(ENDPOINT, status=201)
    sender = EdcNotificationSender(consumer, accepted_policies=[POLICY])
    assert sender.send(PARTNER, RECEIVE_ALERT, lambda v: {}) == "1.2.1"
    assert [key for _, key, _ in consumer.catalog_requests] == list(DCT_TYPE_KEYS)


def test_no_compatible_version_means_no_negotiation():
    consumer = FakeConsumer({DCT_TYPE_KEYS[0]: _catalog(_dataset("alert-3", "3.0.0"))})
    sender = EdcNotificationSender(consumer, accepted_policies=[POLICY])
    with pytest.raises(
        DataspaceError, match=r"no compatible ReceiveQualityAlertNotification .*3\.0\.0"
    ):
        sender.send(PARTNER, RECEIVE_ALERT, lambda v: {})
    assert consumer.negotiations == []


@responses.activate
def test_partner_errors_are_reported_with_their_status():
    consumer = FakeConsumer({DCT_TYPE_KEYS[0]: _catalog(_dataset("alert-2", "2.0.0"))})
    responses.post(ENDPOINT, status=409, body="already exists")
    sender = EdcNotificationSender(consumer, accepted_policies=[POLICY])
    with pytest.raises(NotificationRejected, match="HTTP 409 already exists") as rejected:
        sender.send(PARTNER, RECEIVE_ALERT, lambda v: {})
    assert rejected.value.status_code == 409


def test_sender_matches_the_sdk_consumer_signature():
    import inspect

    from tractusx_sdk.dataspace.services.connector.saturn.connector_consumer_service import (
        ConnectorConsumerService,
    )

    catalog = inspect.signature(ConnectorConsumerService.get_catalog_with_filter).parameters
    assert {"counter_party_id", "counter_party_address", "filter_expression", "protocol"} <= set(
        catalog
    )


# -- publishing our assets -------------------------------------------------------------------


class Response:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


class Controller:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.calls = []

    def create(self, obj):
        data = json.loads(obj.to_data())
        self.calls.append(("create", data))
        return Response(409 if data["@id"] in self.existing else 200)

    def update(self, obj):
        self.calls.append(("update", json.loads(obj.to_data())))
        return Response(204)


class Provider:
    def __init__(self, existing=()):
        self.assets = Controller(existing)
        self.policies = Controller(existing)
        self.contract_definitions = Controller(existing)


def test_eight_assets_two_endpoints():
    assets = notification_assets("http://app:8000/", "cxs")
    assert len(assets) == 8
    assert {a.url for a in assets} == {
        "http://app:8000/api/qualitynotifications/receive",
        "http://app:8000/api/qualitynotifications/update",
    }
    assert {(a.dct_type.rsplit("#", 1)[-1], a.version) for a in assets} >= {
        ("ReceiveQualityAlertNotification", "1.2.1"),
        ("UpdateQualityInvestigationNotification", "2.0.0"),
    }


def test_publisher_creates_or_updates_everything():
    provider = Provider(existing={"cxs-usage", "cxs-receive-alert-2.0.0"})
    ids = NotificationAssetPublisher(
        provider, "http://app:8000", prefix="cxs", headers={"X-Api-Key": "secret"}
    ).publish()

    assert len(ids) == 8
    asset = next(
        data
        for op, data in provider.assets.calls
        if data["@id"] == "cxs-receive-alert-2.0.0" and op == "update"
    )
    assert asset["properties"] == {
        "dct:type": {"@id": "https://w3id.org/catenax/taxonomy#ReceiveQualityAlertNotification"},
        "cx-common:version": "2.0.0",
    }
    address = asset["dataAddress"]
    assert address["baseUrl"] == "http://app:8000/api/qualitynotifications/receive"
    assert (address["proxyMethod"], address["proxyBody"]) == ("true", "true")
    assert address["header:X-Api-Key"] == "secret"

    usage = [data for op, data in provider.policies.calls if op == "update"]
    assert [p["@id"] for p in usage] == ["cxs-usage"]
    constraints = usage[0]["policy"]["permission"][0]["constraint"]["and"]
    assert {c["leftOperand"] for c in constraints} == {"FrameworkAgreement", "UsagePurpose"}

    contract = provider.contract_definitions.calls[0][1]
    assert (contract["accessPolicyId"], contract["contractPolicyId"]) == ("cxs-access", "cxs-usage")


def test_publisher_reports_edc_errors():
    provider = Provider()
    provider.assets.create = lambda obj: Response(400, "invalid asset")
    with pytest.raises(DataspaceError, match="HTTP 400 invalid asset"):
        NotificationAssetPublisher(provider, "http://app:8000").publish()
