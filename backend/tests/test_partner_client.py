import base64
import json
from types import SimpleNamespace

import pytest
import responses
from builders import SERIAL_PART_V3, shell_descriptor
from responses import matchers

from catenax_simplified.dataspace import DataspaceError, SubmodelRef
from catenax_simplified.dataspace.partners import (
    ASSET_ID_KEY,
    DCT_TYPE_KEY,
    DTR_ASSET_TYPE,
    EdcPartnerClient,
    Partner,
    parse_subprotocol_body,
)

PARTNER = Partner(bpnl="BPNL000000000T2A", connector_address="https://edc.tier2/api/v1/dsp")
DTR_PLANE = "https://edc.tier2/api/public/dtr"
CELL = "urn:uuid:cccccccc-0000-4000-8000-000000000001"
HREF = "https://edc.tier2/api/public/cells/1/submodel"
POLICY = {"odrl:permission": {"odrl:action": "odrl:use"}}


class FakeEdrs:
    """The own EDC's EDR controller: a renewed EDR carries the next token."""

    def __init__(self):
        self.refreshed: list[str] = []

    def refresh(self, oid, verify=True):
        self.refreshed.append(oid)
        endpoint = DTR_PLANE if oid == "transfer-dtr" else "https://ignored"
        prefix = "dtr" if oid == "transfer-dtr" else "submodel"
        token = f"{prefix}-token-{len(self.refreshed) + 1}"
        return SimpleNamespace(ok=True, json=lambda: {"endpoint": endpoint, "authorization": token})


class FakeConsumer:
    def __init__(self, fail_on=None):
        self.discoveries: list[tuple[str, str]] = []
        self.negotiations: list[dict] = []
        self.fail_on = fail_on
        self.edrs = FakeEdrs()

    def get_transfer_id(
        self, counter_party_id, counter_party_address, filter_expression, policies, protocol
    ):
        # The SDK hands back the cached transfer of the same asset: no new negotiation.
        return "transfer-dtr" if filter_expression[0]["operandLeft"] == DCT_TYPE_KEY else "t-sub"

    def get_discovery_info(self, bpnl, counter_party_address=None):
        self.discoveries.append((bpnl, counter_party_address))
        return (
            counter_party_address + "/2025-1",
            f"did:web:{bpnl}",
            "dataspace-protocol-http:2025-1",
        )

    def do_dsp(
        self, counter_party_id, counter_party_address, filter_expression, policies, protocol
    ):
        self.negotiations.append(
            {
                "id": counter_party_id,
                "address": counter_party_address,
                "filter": filter_expression,
                "policies": policies,
                "protocol": protocol,
            }
        )
        if self.fail_on and self.fail_on in str(filter_expression):
            raise RuntimeError("PolicyMismatchError: no valid policy")
        if filter_expression[0]["operandLeft"] == DCT_TYPE_KEY:
            return DTR_PLANE, "dtr-token"
        return "https://ignored", "submodel-token"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _mock_dtr(found: bool = True, token: str = "dtr-token"):
    lookup_param = _b64(json.dumps({"name": "globalAssetId", "value": CELL}))
    responses.get(
        f"{DTR_PLANE}/lookup/shells",
        match=[
            matchers.query_param_matcher({"assetIds": lookup_param}),
            matchers.header_matcher({"Authorization": token}),
        ],
        json={"paging_metadata": {}, "result": ["urn:uuid:aas-cell-1"] if found else []},
    )
    descriptor = shell_descriptor(CELL, {SERIAL_PART_V3: HREF})
    descriptor["submodelDescriptors"][0]["endpoints"][0]["protocolInformation"][
        "subprotocolBody"
    ] = "dspEndpoint=https://edc2.tier2/api/v1/dsp;id=cells-serialpart"
    responses.get(
        f"{DTR_PLANE}/shell-descriptors/{_b64('urn:uuid:aas-cell-1')}",
        match=[matchers.header_matcher({"Authorization": token})],
        json=descriptor,
    )


@responses.activate
def test_find_twin_negotiates_for_the_registry_and_looks_up_by_catena_x_id():
    _mock_dtr()
    consumer = FakeConsumer()
    client = EdcPartnerClient(consumer, accepted_policies=[POLICY])

    twin = client.find_twin(PARTNER, CELL)

    assert twin.global_asset_id == CELL
    assert twin.submodels[0].subprotocol_body.endswith("id=cells-serialpart")
    negotiation = consumer.negotiations[0]
    assert negotiation["filter"] == [
        {"operandLeft": DCT_TYPE_KEY, "operator": "=", "operandRight": DTR_ASSET_TYPE}
    ]
    assert negotiation["policies"] == [POLICY]
    assert negotiation["id"] == "did:web:BPNL000000000T2A"
    assert negotiation["address"] == "https://edc.tier2/api/v1/dsp/2025-1"
    assert negotiation["protocol"] == "dataspace-protocol-http:2025-1"


@responses.activate
def test_registry_access_is_reused_within_its_ttl():
    _mock_dtr()
    _mock_dtr()
    _mock_dtr()
    consumer, clock = FakeConsumer(), Clock()
    client = EdcPartnerClient(
        consumer, accepted_policies=[POLICY], clock=clock, token_ttl_seconds=60
    )

    client.find_twin(PARTNER, CELL)
    clock.now = 59
    client.find_twin(PARTNER, CELL)
    assert len(consumer.negotiations) == 1
    clock.now = 61
    client.find_twin(PARTNER, CELL)
    assert len(consumer.negotiations) == 2
    assert len(consumer.discoveries) == 1  # discovery is cached per connector


@responses.activate
def test_unknown_twin_returns_none():
    _mock_dtr(found=False)
    assert (
        EdcPartnerClient(FakeConsumer(), accepted_policies=[POLICY]).find_twin(PARTNER, CELL)
        is None
    )


@responses.activate
def test_a_failing_get_lookup_is_retried_as_a_post():
    _mock_dtr()
    responses.replace(responses.GET, f"{DTR_PLANE}/lookup/shells", status=500)
    responses.post(
        f"{DTR_PLANE}/lookup/shellsByAssetLink",
        match=[
            matchers.json_params_matcher([{"name": "globalAssetId", "value": CELL}]),
            matchers.header_matcher({"Authorization": "dtr-token"}),
        ],
        json={"paging_metadata": {}, "result": ["urn:uuid:aas-cell-1"]},
    )

    twin = EdcPartnerClient(FakeConsumer(), accepted_policies=[POLICY]).find_twin(PARTNER, CELL)

    assert twin.global_asset_id == CELL


@responses.activate
def test_a_refused_token_is_renewed_and_the_call_repeated():
    responses.get(f"{DTR_PLANE}/lookup/shells", status=403)  # the expired token
    _mock_dtr(token="dtr-token-2")
    consumer = FakeConsumer()

    twin = EdcPartnerClient(consumer, accepted_policies=[POLICY]).find_twin(PARTNER, CELL)

    assert twin.global_asset_id == CELL
    assert consumer.edrs.refreshed == ["transfer-dtr"]
    assert len(consumer.negotiations) == 1  # renewed, not negotiated again


@responses.activate
def test_a_token_refused_again_is_reported_and_not_retried_as_a_post():
    responses.get(f"{DTR_PLANE}/lookup/shells", status=403)
    consumer = FakeConsumer()

    with pytest.raises(DataspaceError, match="refused the access token"):
        EdcPartnerClient(consumer, accepted_policies=[POLICY]).find_twin(PARTNER, CELL)
    assert consumer.edrs.refreshed == ["transfer-dtr"]  # once


@responses.activate
def test_a_submodel_read_with_a_refused_token_is_repeated_with_a_renewed_one():
    responses.get(
        f"{HREF}/$value",
        match=[matchers.header_matcher({"Authorization": "submodel-token"})],
        status=401,
    )
    responses.get(
        f"{HREF}/$value",
        match=[matchers.header_matcher({"Authorization": "submodel-token-2"})],
        json={"ok": True},
    )
    ref = SubmodelRef(SERIAL_PART_V3, HREF, None, "dspEndpoint=https://edc2.tier2/api/v1/dsp;id=x")
    consumer = FakeConsumer()

    payload = EdcPartnerClient(consumer, accepted_policies=[POLICY]).read_submodel(PARTNER, ref)

    assert payload == {"ok": True}
    assert consumer.edrs.refreshed == ["t-sub"]


@responses.activate
def test_when_both_lookups_fail_the_error_names_both():
    _mock_dtr()
    responses.replace(responses.GET, f"{DTR_PLANE}/lookup/shells", status=500)
    responses.post(f"{DTR_PLANE}/lookup/shellsByAssetLink", status=502)

    with pytest.raises(DataspaceError, match="GET .*500.*POST .*502"):
        EdcPartnerClient(FakeConsumer(), accepted_policies=[POLICY]).find_twin(PARTNER, CELL)


@responses.activate
def test_read_submodel_negotiates_for_its_asset_at_its_dsp_endpoint():
    responses.get(
        HREF + "/$value",
        match=[matchers.header_matcher({"Authorization": "submodel-token"})],
        json={"catenaXId": CELL},
    )
    consumer = FakeConsumer()
    ref = SubmodelRef(
        SERIAL_PART_V3,
        HREF,
        "SUBMODEL-3.0",
        "dspEndpoint=https://edc2.tier2/api/v1/dsp;id=cells-serialpart",
    )

    payload = EdcPartnerClient(consumer, accepted_policies=[POLICY]).read_submodel(PARTNER, ref)

    assert payload == {"catenaXId": CELL}
    negotiation = consumer.negotiations[0]
    assert negotiation["address"] == "https://edc2.tier2/api/v1/dsp/2025-1"
    assert negotiation["filter"] == [
        {"operandLeft": ASSET_ID_KEY, "operator": "=", "operandRight": "cells-serialpart"}
    ]


@responses.activate
def test_submodels_of_a_shared_asset_reuse_its_access_within_the_ttl():
    for n in (1, 2, 3):
        responses.get(f"{HREF}{n}/$value", json={"n": n})
    consumer, clock = FakeConsumer(), Clock()
    client = EdcPartnerClient(
        consumer, accepted_policies=[POLICY], clock=clock, token_ttl_seconds=60
    )

    def ref(n, asset="cells-bundle"):
        body = f"dspEndpoint=https://edc2.tier2/api/v1/dsp;id={asset}"
        return SubmodelRef(SERIAL_PART_V3, f"{HREF}{n}", "SUBMODEL-3.0", body)

    assert client.read_submodel(PARTNER, ref(1)) == {"n": 1}
    clock.now = 59
    assert client.read_submodel(PARTNER, ref(2)) == {"n": 2}
    assert len(consumer.negotiations) == 1
    client.read_submodel(PARTNER, ref(3, asset="other-asset"))
    assert len(consumer.negotiations) == 2
    clock.now = 61
    client.read_submodel(PARTNER, ref(1))
    assert len(consumer.negotiations) == 3


def test_no_accepted_policies_means_no_negotiation():
    consumer = FakeConsumer()
    with pytest.raises(DataspaceError, match="no accepted usage policies"):
        EdcPartnerClient(consumer, accepted_policies=[]).find_twin(PARTNER, CELL)
    assert consumer.negotiations == []


@responses.activate
def test_accept_any_policy_passes_none_to_the_sdk():
    _mock_dtr()
    consumer = FakeConsumer()
    EdcPartnerClient(consumer, accepted_policies=None).find_twin(PARTNER, CELL)
    assert consumer.negotiations[0]["policies"] is None


def test_failed_negotiation_becomes_a_dataspace_error():
    consumer = FakeConsumer(fail_on=DTR_ASSET_TYPE)
    with pytest.raises(DataspaceError, match="negotiation with BPNL000000000T2A failed"):
        EdcPartnerClient(consumer, accepted_policies=[POLICY]).find_twin(PARTNER, CELL)


def test_submodel_without_asset_id_is_rejected():
    ref = SubmodelRef(SERIAL_PART_V3, HREF, None, "dspEndpoint=https://x")
    with pytest.raises(DataspaceError, match="no asset id"):
        EdcPartnerClient(FakeConsumer(), accepted_policies=[POLICY]).read_submodel(PARTNER, ref)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "dspEndpoint=https://a/api/v1/dsp;id=x",
            {"dspEndpoint": "https://a/api/v1/dsp", "id": "x"},
        ),
        (
            " id = urn:uuid:1 ; dspEndpoint=https://a ",
            {"id": "urn:uuid:1", "dspEndpoint": "https://a"},
        ),
        ("", {}),
        (None, {}),
    ],
)
def test_parse_subprotocol_body(body, expected):
    assert parse_subprotocol_body(body) == expected


def test_calls_match_the_sdk_consumer_signatures():
    import inspect

    from tractusx_sdk.dataspace.services.connector.saturn.connector_consumer_service import (
        ConnectorConsumerService,
    )

    do_dsp = inspect.signature(ConnectorConsumerService.do_dsp).parameters
    assert {
        "counter_party_id",
        "counter_party_address",
        "filter_expression",
        "policies",
        "protocol",
    } <= set(do_dsp)
    transfer = inspect.signature(ConnectorConsumerService.get_transfer_id).parameters
    assert set(do_dsp) - {"max_wait", "poll_interval"} <= set(transfer)
    from tractusx_sdk.dataspace.controllers.connector.saturn.edr_controller import EdrController

    assert "oid" in inspect.signature(EdrController.refresh).parameters
    discovery = inspect.signature(ConnectorConsumerService.get_discovery_info).parameters
    assert {"bpnl", "counter_party_address"} <= set(discovery)
