"""Development mode (CXS_DEV_DIRECT): partners reached without EDCs."""

import base64
import json

import pytest
import responses
from builders import SERIAL_PART_V3, shell_descriptor
from responses import matchers

from catenax_simplified.config import Settings
from catenax_simplified.dataspace.direct import DirectNotificationSender, DirectPartnerClient
from catenax_simplified.dataspace.edc import Partner
from catenax_simplified.dataspace.notifications import NotificationRejected
from catenax_simplified.notifications import NotificationType
from catenax_simplified.wiring import (
    build_asset_publisher,
    build_notification_sender,
    build_partner_client,
)

TIER2 = "BPNL000000000T2A"
DTR = "http://localhost:8102/api/v3"
CELL = "urn:uuid:cccccccc-0000-4000-8000-000000000021"
HREF = "http://localhost:8102/data/cell/0/submodel"


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


@responses.activate
def test_direct_partner_client_reads_the_partner_registry():
    lookup = _b64(json.dumps({"name": "globalAssetId", "value": CELL}))
    responses.get(
        f"{DTR}/lookup/shells",
        match=[matchers.query_param_matcher({"assetIds": lookup})],
        json={"result": ["urn:uuid:aas-cell"]},
    )
    responses.get(
        f"{DTR}/shell-descriptors/{_b64('urn:uuid:aas-cell')}",
        json=shell_descriptor(CELL, {SERIAL_PART_V3: HREF}),
    )
    responses.get(HREF + "/$value", json={"catenaXId": CELL})
    client = DirectPartnerClient({TIER2: DTR})
    partner = Partner(TIER2, "http://localhost:8002")

    twin = client.find_twin(partner, CELL)

    assert twin.global_asset_id == CELL
    assert client.read_submodel(partner, twin.submodels[0]) == {"catenaXId": CELL}


@responses.activate
def test_direct_sender_posts_to_the_partner_app():
    responses.post(
        "http://localhost:8001/api/qualitynotifications/update",
        match=[matchers.header_matcher({"X-Api-Key": "demo"})],
        status=200,
    )
    sender = DirectNotificationSender("demo")
    partner = Partner("BPNL000000000T1A", "http://localhost:8001/")
    asset_type = NotificationType.ALERT.asset_type("update")
    assert sender.send(partner, asset_type, lambda version: {"v": version}) == "2.0.0"

    responses.post("http://localhost:8001/api/qualitynotifications/receive", status=409)
    with pytest.raises(NotificationRejected, match="HTTP 409"):
        sender.send(partner, NotificationType.ALERT.asset_type("receive"), lambda v: {})


def test_dev_direct_replaces_the_edc_and_publishes_nothing():
    settings = Settings(
        own_bpnl="BPNL000000000T1A",
        dev_direct=True,
        dev_partner_dtrs={TIER2: DTR},
        edc_management_url="https://edc.example",
        notification_base_url="http://app:8000",
    )
    assert isinstance(build_partner_client(settings), DirectPartnerClient)
    assert isinstance(build_notification_sender(settings), DirectNotificationSender)
    assert build_asset_publisher(settings) is None
