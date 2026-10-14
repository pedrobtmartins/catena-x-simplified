import copy

import pytest

from catenax_simplified.notifications import (
    Direction,
    MessageFormatError,
    NotificationType,
    Severity,
    Status,
    TransitionError,
    build_message,
    local_targets,
    parse_message,
)
from catenax_simplified.notifications.messages import api_version_of
from catenax_simplified.notifications.states import apply_partner_update, check_local

# Shaped like the KIT's Notification API examples.
RECEIVE_1_2_1 = {
    "header": {
        "messageId": "3b4edc05-e214-47a1-b0c2-1d831cdd9ba9",
        "context": "Traceability-QualityNotification-Investigation:2.0.0",
        "sentDateTime": "2026-10-14T14:35:24Z",
        "senderBpn": "BPNL000000000OEM",
        "receiverBpn": "BPNL000000000T1A",
        "expectedResponseBy": "2026-10-21T14:35:24Z",
    },
    "content": {
        "notificationId": "41d743c3-6e8a-4393-88af-10494e50bea9",
        "status": "SENT",
        "severity": "CRITICAL",
        "information": "Gear boxes loose oil while driving.",
        "listOfAffectedItems": [
            "urn:uuid:57e4e3c1-a6f0-46a0-90df-1fb17cbc157d",
            "urn:uuid:57e4e3c1-a6f0-46a0-90df-1fb17cbc157d",
        ],
    },
}

RECEIVE_2_0_0 = {
    "header": {
        **RECEIVE_1_2_1["header"],
        "context": "Traceability-QualityNotification-Alert:2.0.0",
        "version": "2.0.0",
    },
    "content": {
        "notificationId": "41d743c3-6e8a-4393-88af-10494e50bea9",
        "status": "SENT",
        "severity": "LIFE-THREATENING",
        "relatedQualityTaskId": "Q-Task 123",
        "senderAttachments": [
            {"attachmentName": "x", "fileExtension": "png", "contractOfferId": "offer-1"}
        ],
        "populationFilterList": [],
    },
}


def test_parses_1_2_1():
    message = parse_message(RECEIVE_1_2_1, operation="receive")
    assert message.type is NotificationType.INVESTIGATION
    assert (message.sender_bpn, message.receiver_bpn) == ("BPNL000000000OEM", "BPNL000000000T1A")
    assert (message.status, message.severity) == (Status.SENT, Severity.CRITICAL)
    assert message.affected_items == ("urn:uuid:57e4e3c1-a6f0-46a0-90df-1fb17cbc157d",)
    assert message.expected_response_by == "2026-10-21T14:35:24Z"


def test_parses_2_0_0_without_affected_items():
    message = parse_message(RECEIVE_2_0_0, operation="receive")
    assert message.type is NotificationType.ALERT
    assert message.severity is Severity.LIFE_THREATENING
    assert message.affected_items == ()


@pytest.mark.parametrize(
    ("path", "value", "error"),
    [
        (("header", "messageId"), "not-a-uuid", "messageId must be a UUID"),
        (("header", "context"), "Traceability-Something:1.0.0", "unsupported header.context"),
        (("header", "senderBpn"), "BPNS0000000000AB", "senderBpn must be a BPNL"),
        (("content", "severity"), "HUGE", "unsupported severity"),
        (("content", "information"), "x" * 1001, "exceeds 1000"),
        (("content", "listOfAffectedItems"), "urn:uuid:1", "must be a list"),
        (("content", "status"), None, "needs a status and a severity"),
    ],
)
def test_rejects_malformed_messages(path, value, error):
    body = copy.deepcopy(RECEIVE_1_2_1)
    body[path[0]][path[1]] = value
    with pytest.raises(MessageFormatError, match=error):
        parse_message(body, operation="receive")


def test_update_needs_only_id_and_status():
    content = {"notificationId": "41d743c3-6e8a-4393-88af-10494e50bea9", "status": "ACCEPTED"}
    body = {"header": RECEIVE_1_2_1["header"], "content": content}
    assert parse_message(body, operation="update").status is Status.ACCEPTED
    del body["content"]["status"]
    with pytest.raises(MessageFormatError, match="needs a status"):
        parse_message(body, operation="update")


@pytest.mark.parametrize("version", ["1.2.1", "2.0.0"])
def test_build_and_parse_round_trip(version):
    message = parse_message(RECEIVE_1_2_1, operation="receive")
    body = build_message(message, version, operation="receive")
    assert body["header"]["version"] == "2.0.0"  # the message header's version
    assert body["content"]["listOfAffectedItems"] == list(message.affected_items)
    assert parse_message(body, operation="receive") == message
    update = build_message(message, version, operation="update")
    assert "listOfAffectedItems" not in update["content"]


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        ("2.0.0", "2.0.0"),
        ("2.0", "2.0.0"),
        ("1.2", "1.2.1"),
        ("1.2.1", "1.2.1"),
        ("3.0.0", None),
        (None, None),
        ("latest", None),
    ],
)
def test_api_version_of(offered, expected):
    assert api_version_of(offered) == expected


def test_asset_types():
    assert (
        NotificationType.ALERT.asset_type("receive")
        == "https://w3id.org/catenax/taxonomy#ReceiveQualityAlertNotification"
    )
    assert (
        NotificationType.INVESTIGATION.asset_type("update")
        == "https://w3id.org/catenax/taxonomy#UpdateQualityInvestigationNotification"
    )


def test_local_transitions():
    assert local_targets(Direction.INBOUND, Status.RECEIVED) == {Status.ACKNOWLEDGED}
    assert local_targets(Direction.INBOUND, Status.ACKNOWLEDGED) == {
        Status.ACCEPTED,
        Status.DECLINED,
    }
    assert local_targets(Direction.INBOUND, Status.ACCEPTED) == set()
    assert local_targets(Direction.OUTBOUND, Status.ACCEPTED) == {Status.CLOSED}
    assert local_targets(Direction.OUTBOUND, Status.CLOSED) == set()
    with pytest.raises(TransitionError, match="receiver cannot change RECEIVED to CLOSED"):
        check_local(Direction.INBOUND, Status.RECEIVED, Status.CLOSED)


@pytest.mark.parametrize(
    ("direction", "current", "new", "expected"),
    [
        (Direction.OUTBOUND, Status.RECEIVED, Status.ACKNOWLEDGED, Status.ACKNOWLEDGED),
        (Direction.OUTBOUND, Status.RECEIVED, Status.ACCEPTED, Status.ACCEPTED),  # skips a step
        (Direction.OUTBOUND, Status.ACCEPTED, Status.ACCEPTED, Status.ACCEPTED),  # repeat
        (Direction.OUTBOUND, Status.ACKNOWLEDGED, Status.RECEIVED, Status.ACKNOWLEDGED),
        (Direction.OUTBOUND, Status.ACCEPTED, Status.DECLINED, "cannot change ACCEPTED"),
        (Direction.OUTBOUND, Status.ACCEPTED, Status.ACKNOWLEDGED, "back to"),
        (Direction.OUTBOUND, Status.CLOSED, Status.ACCEPTED, "is closed"),
        (Direction.OUTBOUND, Status.ACCEPTED, Status.CLOSED, "only the initiator"),
        (Direction.INBOUND, Status.ACCEPTED, Status.CLOSED, Status.CLOSED),
        (Direction.INBOUND, Status.RECEIVED, Status.ACCEPTED, "cannot set ACCEPTED"),
    ],
)
def test_partner_updates(direction, current, new, expected):
    if isinstance(expected, Status):
        assert apply_partner_update(direction, current, new) is expected
    else:
        with pytest.raises(TransitionError, match=expected):
            apply_partner_update(direction, current, new)
