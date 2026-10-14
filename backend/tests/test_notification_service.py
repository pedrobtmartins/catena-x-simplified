"""Notifications between three participants (Tier-2 → Tier-1 → OEM), each with its own database,
connected by a loopback that delivers what one sends to the other's endpoints."""

from datetime import UTC, datetime
from itertools import count

import pytest
import scenario
from builders import (
    BOM_V4,
    SERIAL_PART_V3,
    SERIAL_PART_V4,
    USAGE_V4,
    bom_v4,
    part_v3,
    part_v4,
    shell_descriptor,
    usage_v4,
)
from fakes import FakeReader, FakeRegistry

from catenax_simplified.dataspace import DataspaceError
from catenax_simplified.dataspace.notifications import NotificationRejected
from catenax_simplified.notifications import (
    NotificationError,
    NotificationService,
    NotificationType,
    Severity,
    Status,
)
from catenax_simplified.storage import (
    NotificationRepository,
    init_schema,
    make_engine,
    make_session_factory,
)
from catenax_simplified.traceability import OwnTwinSync

CLOCK = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
ALERT, INVESTIGATION = NotificationType.ALERT, NotificationType.INVESTIGATION


class Loopback:
    """Plays both EDCs: delivers ``build(version)`` to the partner's service."""

    def __init__(self):
        self.peers: dict[str, NotificationService] = {}
        self.sent: list[tuple[str, str, str, dict]] = []
        self.versions: dict[str, str] = {}
        self.unreachable: set[str] = set()

    def send(self, partner, asset_type, build):
        if partner.bpnl in self.unreachable:
            raise DataspaceError(f"negotiation with {partner.bpnl} failed: timeout")
        version = self.versions.get(partner.bpnl, "2.0.0")
        body = build(version)
        self.sent.append((partner.bpnl, asset_type.rsplit("#", 1)[-1], version, body))
        peer = self.peers[partner.bpnl]
        try:
            (peer.receive if "#Receive" in asset_type else peer.update)(body)
        except NotificationError as exc:
            raise NotificationRejected(partner.bpnl, exc.status_code, str(exc)) from exc
        return version


def _ids():
    counter = count(1)
    return lambda: f"00000000-0000-4000-8000-{next(counter):012d}"


def _participant(bpnl, shells, payloads, loopback) -> NotificationService:
    factory = make_session_factory(make_engine("sqlite:///:memory:"))
    init_schema(factory.kw["bind"])
    OwnTwinSync(
        FakeRegistry(shells), FakeReader(payloads), factory, own_bpnl=bpnl, clock=lambda: CLOCK
    ).run()
    everyone = (scenario.TIER1, scenario.TIER2, scenario.OEM)
    connectors = {b: f"https://edc.{b.lower()}/api/v1/dsp" for b in everyone}
    service = NotificationService(
        factory,
        bpnl,
        loopback,
        configured_connectors=connectors,
        clock=lambda: CLOCK,
        id_factory=_ids(),
    )
    loopback.peers[bpnl] = service
    return service


def _href(gid, aspect):
    return f"https://edc.example/{gid}/{aspect}"


@pytest.fixture
def loopback():
    return Loopback()


@pytest.fixture
def tier1(loopback):
    return _participant(scenario.TIER1, scenario.shells(), scenario.payloads(), loopback)


@pytest.fixture
def tier2(loopback):
    # Cells 1 and 2 were delivered to Tier-1 for module A.
    shells, payloads = [], {}
    for cell in (scenario.CELL_1, scenario.CELL_2):
        shells.append(
            shell_descriptor(
                cell, {SERIAL_PART_V3: _href(cell, "sp"), USAGE_V4: _href(cell, "usage")}
            )
        )
        payloads[_href(cell, "sp") + "/$value"] = part_v3(cell, "Li-ion cell", "CELL-21700")
        payloads[_href(cell, "usage") + "/$value"] = usage_v4(
            cell, [scenario.MODULE_A], scenario.TIER1
        )
    return _participant(scenario.TIER2, shells, payloads, loopback)


@pytest.fixture
def oem(loopback):
    vehicle = scenario.VEHICLE
    shells = [
        shell_descriptor(
            vehicle, {SERIAL_PART_V4: _href(vehicle, "sp"), BOM_V4: _href(vehicle, "bom")}
        )
    ]
    payloads = {
        _href(vehicle, "sp") + "/$value": part_v4(vehicle, "Vehicle", "VEH-1"),
        _href(vehicle, "bom") + "/$value": bom_v4(vehicle, [scenario.MODULE_A], scenario.TIER1),
    }
    return _participant(scenario.OEM, shells, payloads, loopback)


def _inbound(service: NotificationService):
    with service._sessions() as session:
        rows, _ = NotificationRepository(session).list(direction="inbound")
        return rows


def test_plan_groups_affected_parts_by_direct_partner(tier1):
    alert = tier1.plan(ALERT, [scenario.MODULE_A, scenario.MODULE_B, scenario.CELL_1])
    assert alert.recipients == {scenario.OEM: [scenario.MODULE_A]}
    # Module B has no known customer; cells are not own parts.
    assert alert.unmatched == [scenario.MODULE_B, scenario.CELL_1]

    investigation = tier1.plan(INVESTIGATION, [scenario.CELL_1, scenario.CELL_3, scenario.MODULE_A])
    assert investigation.recipients == {scenario.TIER2: [scenario.CELL_1, scenario.CELL_3]}
    assert investigation.unmatched == [scenario.MODULE_A]


def test_create_refuses_parts_without_a_recipient(tier1):
    with pytest.raises(NotificationError, match="no direct customer known for: urn:uuid:aaaa"):
        tier1.create(ALERT, [scenario.MODULE_B], Severity.MINOR, "scratches")


def test_alert_travels_hop_by_hop_and_back(tier1, tier2, oem, loopback):
    # Tier-2 finds a defective cell batch and alerts its direct customer.
    (draft,) = tier2.create(ALERT, [scenario.CELL_1], Severity.CRITICAL, "Thermal runaway risk")
    assert (draft.status, draft.partner_bpnl) == ("CREATED", scenario.TIER1)
    sent = tier2.send(draft.id)
    assert (sent.status, sent.api_version) == ("RECEIVED", "2.0.0")
    assert loopback.sent[-1][1] == "ReceiveQualityAlertNotification"

    (received,) = _inbound(tier1)
    assert (received.type, received.partner_bpnl, received.status) == (
        "alert",
        scenario.TIER2,
        "RECEIVED",
    )
    assert received.notification_id == draft.notification_id
    assert received.affected_items == [scenario.CELL_1]

    # Tier-1 acknowledges, then forwards: cell 1 is in module A, installed in the OEM's vehicle.
    tier1.change_status(received.id, Status.ACKNOWLEDGED)
    assert tier2.get(draft.id).status == "ACKNOWLEDGED"
    plan = tier1.forward_plan(received.id)
    assert plan.own_parts == [scenario.MODULE_A]
    assert plan.recipients == {scenario.OEM: [scenario.MODULE_A]}

    (forwarded,) = tier1.create(
        ALERT,
        plan.recipients[scenario.OEM],
        Severity.CRITICAL,
        "Modules with affected cells",
        forwarded_from=received.id,
    )
    assert forwarded.forwarded_from_id == received.id
    assert forwarded.related_message_id is None  # the OEM does not know Tier-2's alert
    tier1.send(forwarded.id)

    (at_oem,) = _inbound(oem)
    assert at_oem.affected_items == [scenario.MODULE_A]
    oem.change_status(at_oem.id, Status.ACKNOWLEDGED)
    oem.change_status(at_oem.id, Status.ACCEPTED, "Vehicles recalled")
    assert tier1.get(forwarded.id).status == "ACCEPTED"

    tier1.change_status(received.id, Status.ACCEPTED, "Modules replaced")
    tier2.change_status(draft.id, Status.CLOSED)
    assert tier1.get(received.id).status == "CLOSED"

    with tier2._sessions() as session:
        log = NotificationRepository(session).messages(draft.id)
    assert [(m.direction, m.status) for m in log] == [
        ("outbound", "SENT"),
        ("inbound", "ACKNOWLEDGED"),
        ("inbound", "ACCEPTED"),
        ("outbound", "CLOSED"),
    ]
    assert log[2].information == "Modules replaced"


def test_investigation_is_forwarded_to_suppliers(tier1, tier2, oem):
    (draft,) = oem.create(INVESTIGATION, [scenario.MODULE_A], Severity.MAJOR, "Range loss")
    oem.send(draft.id)
    (received,) = _inbound(tier1)
    plan = tier1.forward_plan(received.id)
    assert plan.own_parts == [scenario.MODULE_A]
    assert plan.recipients == {scenario.TIER2: [scenario.CELL_1, scenario.CELL_2]}


def test_uses_the_partners_version(tier1, tier2, loopback):
    loopback.versions[scenario.TIER1] = "1.2.1"
    (draft,) = tier2.create(ALERT, [scenario.CELL_2], Severity.MINOR, "Label misprint")
    assert tier2.send(draft.id).api_version == "1.2.1"
    assert "listOfAffectedItems" in loopback.sent[-1][3]["content"]


def test_failed_delivery_keeps_the_draft(tier1, tier2, loopback):
    (draft,) = tier2.create(ALERT, [scenario.CELL_1], Severity.MINOR, "Label misprint")
    loopback.unreachable.add(scenario.TIER1)
    with pytest.raises(NotificationError, match="timeout"):
        tier2.send(draft.id)
    row = tier2.get(draft.id)
    assert row.status == "CREATED"
    assert row.last_error == "negotiation with BPNL000000000T1A failed: timeout"
    loopback.unreachable.clear()
    assert tier2.send(draft.id).status == "RECEIVED"
    assert tier2.get(draft.id).last_error is None


def test_initiator_can_abort_and_then_nothing_changes(tier1, tier2):
    (draft,) = tier2.create(ALERT, [scenario.CELL_1], Severity.MINOR, "Label misprint")
    tier2.send(draft.id)
    (received,) = _inbound(tier1)
    tier2.change_status(draft.id, Status.CLOSED)
    assert tier1.get(received.id).status == "CLOSED"
    with pytest.raises(NotificationError, match="receiver cannot change CLOSED"):
        tier1.change_status(received.id, Status.ACKNOWLEDGED)


def test_receive_rejects_duplicates_and_foreign_receivers(tier1, tier2, loopback):
    (draft,) = tier2.create(ALERT, [scenario.CELL_1], Severity.MINOR, "Label misprint")
    tier2.send(draft.id)
    body = loopback.sent[-1][3]
    with pytest.raises(NotificationError, match="already exists") as conflict:
        tier1.receive(body)
    assert conflict.value.status_code == 409

    body = {**body, "header": {**body["header"], "receiverBpn": scenario.OEM}}
    with pytest.raises(NotificationError, match="not this company") as foreign:
        tier1.receive(body)
    assert foreign.value.status_code == 422

    with pytest.raises(NotificationError, match="must have a header") as malformed:
        tier1.receive({"header": {}})
    assert malformed.value.status_code == 400


def test_update_for_unknown_notification_is_404(tier1, tier2, loopback):
    (draft,) = tier2.create(ALERT, [scenario.CELL_1], Severity.MINOR, "Label misprint")
    tier2.send(draft.id)
    body = loopback.sent[-1][3]
    update = {
        "header": {**body["header"], "messageId": "00000000-0000-4000-8000-000000000999"},
        "content": {"notificationId": "00000000-0000-4000-8000-000000000998", "status": "CLOSED"},
    }
    with pytest.raises(NotificationError) as missing:
        tier1.update(update)
    assert missing.value.status_code == 404

    # Some implementations reference the notification by its first message instead.
    update["header"]["relatedMessageId"] = body["header"]["messageId"]
    assert tier1.update(update).status == "CLOSED"


def test_sending_needs_a_connector_address(tier1, loopback):
    service = NotificationService(tier1._sessions, scenario.TIER1, loopback)
    (draft,) = service.create(ALERT, [scenario.MODULE_A], Severity.MINOR, "x")
    with pytest.raises(NotificationError, match="no connector address known"):
        service.send(draft.id)
    assert service.get(draft.id).status == "CREATED"


def test_without_edc_drafts_can_be_created_and_discarded(tier1):
    service = NotificationService(tier1._sessions, scenario.TIER1, sender=None)
    (draft,) = service.create(ALERT, [scenario.MODULE_A], Severity.MINOR, "x")
    with pytest.raises(NotificationError, match="no EDC configured") as unavailable:
        service.send(draft.id)
    assert unavailable.value.status_code == 503
    assert service.change_status(draft.id, Status.CLOSED).status == "CLOSED"


def test_rejected_update_changes_nothing_locally(tier1, tier2, loopback):
    (draft,) = tier2.create(ALERT, [scenario.CELL_1], Severity.MINOR, "Label misprint")
    tier2.send(draft.id)
    (received,) = _inbound(tier1)
    tier1.change_status(received.id, Status.ACKNOWLEDGED)
    tier1.change_status(received.id, Status.DECLINED, "Not our cells")
    # A rejected update leaves our side unchanged and records the error.
    loopback.peers[scenario.TIER1] = tier2  # misrouted: the wrong receiver rejects it
    with pytest.raises(NotificationError, match="rejected the notification: HTTP 422"):
        tier2.change_status(draft.id, Status.CLOSED)
    row = tier2.get(draft.id)
    assert row.status == "DECLINED"
    assert "422" in row.last_error
