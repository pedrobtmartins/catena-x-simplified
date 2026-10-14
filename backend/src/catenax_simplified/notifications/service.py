"""Quality notifications between direct partners: create, send, receive, update, forward.

Recipients and affected items come from the local one-level tree: an alert goes to the direct
customers of the affected own parts, an investigation to the direct suppliers of the affected
supplier parts. A received notification can be forwarded one hop further (assisted forwarding):
the next hop's affected parts are derived from the local tree and the new notification is linked
to the received one locally.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..dataspace import DataspaceError
from ..dataspace.edc import Partner
from ..dataspace.notifications import NotificationSender
from ..storage import (
    NotificationMessageRow,
    NotificationRepository,
    NotificationRow,
    PartnerRepository,
    PartRepository,
)
from .messages import (
    INFORMATION_MAX_LENGTH,
    Message,
    MessageFormatError,
    NotificationType,
    Severity,
    Status,
    build_message,
    new_uuid,
    parse_message,
    timestamp,
)
from .states import Direction, TransitionError, apply_partner_update, check_local


class NotificationError(Exception):
    """Base for errors the API maps to an HTTP status."""

    status_code = 422


class Malformed(NotificationError):
    status_code = 400


class NotFound(NotificationError):
    status_code = 404


class Conflict(NotificationError):
    status_code = 409


class Invalid(NotificationError):
    status_code = 422


class Unavailable(NotificationError):
    status_code = 503


class DeliveryFailed(NotificationError):
    status_code = 502


@dataclass
class Plan:
    """Who gets a notification about which items, derived from the local tree."""

    type: NotificationType
    recipients: dict[str, list[str]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)


@dataclass
class ForwardPlan(Plan):
    source_id: int = 0
    # Own parts affected by the received notification.
    own_parts: list[str] = field(default_factory=list)


def plan_recipients(
    repository: PartRepository, own_bpnl: str, type_: NotificationType, items: Sequence[str]
) -> Plan:
    """Alert: ``items`` are own parts → their direct customers. Investigation: ``items`` are
    supplier parts in own BoMs → their direct suppliers."""
    plan = Plan(type=type_)
    parts = repository.get_parts(items)
    for item in dict.fromkeys(items):
        part = parts.get(item)
        partners: list[str] = []
        if type_ is NotificationType.ALERT:
            if part is not None and part.is_own:
                partners = [r.business_partner for r in repository.parents(item)]
        else:
            if part is None or not part.is_own:
                relations = repository.parents(item)
                known = repository.get_parts([r.parent_id for r in relations])
                partners = [
                    r.business_partner
                    for r in relations
                    if r.parent_id in known and known[r.parent_id].is_own
                ]
                if not partners and part is not None and part.manufacturer_id:
                    partners = [part.manufacturer_id]
        partners = [p for p in dict.fromkeys(partners) if p and p != own_bpnl]
        if not partners:
            plan.unmatched.append(item)
        for bpnl in partners:
            plan.recipients.setdefault(bpnl, []).append(item)
    return plan


class NotificationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        own_bpnl: str,
        sender: NotificationSender | None = None,
        configured_connectors: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = new_uuid,
    ):
        self._sessions = session_factory
        self._own_bpnl = own_bpnl
        self._sender = sender
        self._connectors = dict(configured_connectors or {})
        self._clock = clock
        self._new_id = id_factory

    @property
    def can_send(self) -> bool:
        return self._sender is not None

    # -- creating ------------------------------------------------------------------------

    def plan(self, type_: NotificationType, items: Sequence[str]) -> Plan:
        with self._sessions() as session:
            return plan_recipients(PartRepository(session), self._own_bpnl, type_, items)

    def forward_plan(self, pk: int) -> ForwardPlan:
        """The next hop for a received notification.

        Received alert (items = supplier parts) → own parts containing them → alert to their
        customers. Received investigation (items = own parts) → supplier parts in their BoMs →
        investigation to those suppliers.
        """
        with self._sessions() as session:
            row = self._get(session, pk)
            if row.direction != Direction.INBOUND:
                raise Invalid("only received notifications can be forwarded")
            parts = PartRepository(session)
            items: list[str] = []
            if row.type == NotificationType.ALERT:
                own_parts = self._own_parents(parts, row.affected_items)
                items = own_parts
            else:
                own = parts.get_parts(row.affected_items)
                own_parts = [gid for gid in row.affected_items if gid in own and own[gid].is_own]
                for gid in own_parts:
                    items += [r.child_id for r in parts.children(gid) if r.business_partner]
            plan = plan_recipients(
                parts, self._own_bpnl, NotificationType(row.type), list(dict.fromkeys(items))
            )
            return ForwardPlan(
                type=plan.type,
                recipients=plan.recipients,
                unmatched=plan.unmatched,
                source_id=row.id,
                own_parts=own_parts,
            )

    @staticmethod
    def _own_parents(parts: PartRepository, items: Sequence[str]) -> list[str]:
        result: list[str] = []
        for gid in items:
            parents = [r.parent_id for r in parts.parents(gid)]
            known = parts.get_parts(parents)
            result += [p for p in parents if p in known and known[p].is_own]
        return list(dict.fromkeys(result))

    def create(
        self,
        type_: NotificationType,
        items: Sequence[str],
        severity: Severity,
        description: str,
        expected_response_by: datetime | None = None,
        forwarded_from: int | None = None,
    ) -> list[NotificationRow]:
        """Create one draft (CREATED) per recipient of the plan."""
        if not items:
            raise Invalid("select at least one affected part")
        if len(description) > INFORMATION_MAX_LENGTH:
            raise Invalid(f"the description exceeds {INFORMATION_MAX_LENGTH} characters")
        now = self._clock()
        with self._sessions.begin() as session:
            repository = NotificationRepository(session)
            source = self._get(session, forwarded_from) if forwarded_from is not None else None
            plan = plan_recipients(PartRepository(session), self._own_bpnl, type_, items)
            if plan.unmatched:
                role = "customer" if type_ is NotificationType.ALERT else "supplier"
                raise Invalid(f"no direct {role} known for: {', '.join(plan.unmatched)}")
            rows = []
            for bpnl, affected in sorted(plan.recipients.items()):
                related = None
                if source is not None and source.partner_bpnl == bpnl:
                    # relatedMessageId only references notifications the recipient knows.
                    related = source.initial_message_id
                rows.append(
                    repository.add(
                        NotificationRow(
                            notification_id=self._new_id(),
                            type=type_.value,
                            direction=Direction.OUTBOUND.value,
                            partner_bpnl=bpnl,
                            status=Status.CREATED.value,
                            severity=severity.value,
                            description=description,
                            affected_items=list(affected),
                            expected_response_by=timestamp(expected_response_by)
                            if expected_response_by
                            else None,
                            related_message_id=related,
                            forwarded_from_id=source.id if source else None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                )
            return rows

    # -- local actions -------------------------------------------------------------------

    def get(self, pk: int) -> NotificationRow:
        with self._sessions() as session:
            return self._get(session, pk)

    def _get(self, session: Session, pk: int) -> NotificationRow:
        row = NotificationRepository(session).get(pk)
        if row is None:
            raise NotFound("notification not found")
        return row

    def _partner(self, session: Session, bpnl: str) -> Partner:
        stored = PartnerRepository(session).get(bpnl)
        address = (stored.connector_address if stored else None) or self._connectors.get(bpnl)
        if not address:
            raise Invalid(
                f"no connector address known for {bpnl} "
                "(set it with PUT /api/partners/{bpnl} or CXS_PARTNER_CONNECTORS)"
            )
        return Partner(bpnl=bpnl, connector_address=address)

    def _deliver(
        self, partner: Partner, type_: NotificationType, message: Message, operation: str
    ) -> str:
        if self._sender is None:
            raise Unavailable("no EDC configured")
        try:
            return self._sender.send(
                partner,
                type_.asset_type(operation),
                lambda version: build_message(message, version, operation=operation),
            )
        except DataspaceError as exc:
            raise DeliveryFailed(str(exc)) from exc

    def _message(self, row: NotificationRow, status: Status, information: str | None) -> Message:
        return Message(
            message_id=self._new_id(),
            type=NotificationType(row.type),
            sender_bpn=self._own_bpnl,
            receiver_bpn=row.partner_bpnl,
            notification_id=row.notification_id,
            status=status,
            sent_at=timestamp(self._clock()),
            expected_response_by=row.expected_response_by,
            related_message_id=row.related_message_id,
            severity=Severity(row.severity),
            information=information,
            affected_items=tuple(row.affected_items),
        )

    def _log(
        self,
        session: Session,
        row: NotificationRow,
        direction: Direction,
        operation: str,
        message: Message,
        payload: Mapping[str, Any],
    ) -> None:
        NotificationRepository(session).log(
            NotificationMessageRow(
                notification_pk=row.id,
                direction=direction.value,
                operation=operation,
                message_id=message.message_id,
                status=message.status.value if message.status else None,
                information=message.information,
                at=self._clock(),
                payload=dict(payload),
            )
        )

    def send(self, pk: int) -> NotificationRow:
        """Send a draft: CREATED → SENT, then RECEIVED once the partner answers with success.

        A failed delivery puts the draft back to CREATED with the error, so it can be retried.
        """
        with self._sessions.begin() as session:
            row = self._get(session, pk)
            if row.direction != Direction.OUTBOUND or row.status != Status.CREATED:
                raise Invalid(f"only drafts can be sent (status is {row.status})")
            if self._sender is None:
                raise Unavailable("no EDC configured")
            partner = self._partner(session, row.partner_bpnl)
            row.status = Status.SENT.value
            row.updated_at = self._clock()
            message = self._message(row, Status.SENT, row.description)

        error: DeliveryFailed | None = None
        try:
            version = self._deliver(partner, message.type, message, "receive")
        except DeliveryFailed as exc:
            error = exc
        with self._sessions.begin() as session:
            row = self._get(session, pk)
            row.updated_at = self._clock()
            if error is not None:
                row.status = Status.CREATED.value
                row.last_error = str(error)[:2000]
            else:
                row.status = Status.RECEIVED.value
                row.initial_message_id = message.message_id
                row.api_version = version
                row.last_error = None
                payload = build_message(message, version, operation="receive")
                self._log(session, row, Direction.OUTBOUND, "receive", message, payload)
        if error is not None:
            raise error
        return row

    def change_status(
        self, pk: int, new: Status, information: str | None = None
    ) -> NotificationRow:
        """A status change by this side, sent to the partner as an update (except discarding a
        draft). Nothing changes locally if the partner cannot be reached."""
        if information and len(information) > INFORMATION_MAX_LENGTH:
            raise Invalid(f"the information exceeds {INFORMATION_MAX_LENGTH} characters")
        with self._sessions() as session:
            row = self._get(session, pk)
            current = Status(row.status)
            try:
                check_local(Direction(row.direction), current, new)
            except TransitionError as exc:
                raise Invalid(str(exc)) from exc
            needs_update = current is not Status.CREATED
            if needs_update and self._sender is None:
                raise Unavailable("no EDC configured")
            if needs_update:
                partner = self._partner(session, row.partner_bpnl)
                message = self._message(row, new, information)

        error: DeliveryFailed | None = None
        version = None
        if needs_update:
            try:
                version = self._deliver(partner, message.type, message, "update")
            except DeliveryFailed as exc:
                error = exc
        with self._sessions.begin() as session:
            row = self._get(session, pk)
            if error is not None:
                row.last_error = str(error)[:2000]
            elif row.status != current.value:
                raise Conflict(f"the notification changed to {row.status} meanwhile")
            else:
                row.status = new.value
                row.last_error = None
                row.updated_at = self._clock()
                if version is not None:
                    row.api_version = row.api_version or version
                    payload = build_message(message, version, operation="update")
                    self._log(session, row, Direction.OUTBOUND, "update", message, payload)
        if error is not None:
            raise error
        return row

    # -- partner requests (Notification API) ---------------------------------------------

    @staticmethod
    def _parse(body: Any, operation: str) -> Message:
        try:
            return parse_message(body, operation=operation)
        except MessageFormatError as exc:
            raise Malformed(str(exc)) from exc

    def _check_parties(self, message: Message) -> None:
        if message.receiver_bpn != self._own_bpnl:
            raise Invalid(f"receiverBpn {message.receiver_bpn} is not this company")
        if message.sender_bpn == self._own_bpnl:
            raise Invalid("senderBpn is this company")

    def receive(self, body: Any) -> NotificationRow:
        """``POST /qualitynotifications/receive`` — a partner sends a new notification."""
        message = self._parse(body, "receive")
        self._check_parties(message)
        now = self._clock()
        with self._sessions.begin() as session:
            repository = NotificationRepository(session)
            if repository.find(message.sender_bpn, message.notification_id) is not None:
                raise Conflict("a notification with this notificationId already exists")
            row = repository.add(
                NotificationRow(
                    notification_id=message.notification_id,
                    initial_message_id=message.message_id,
                    type=message.type.value,
                    direction=Direction.INBOUND.value,
                    partner_bpnl=message.sender_bpn,
                    status=Status.RECEIVED.value,
                    severity=message.severity.value,
                    description=message.information,
                    affected_items=list(message.affected_items),
                    expected_response_by=message.expected_response_by,
                    related_message_id=message.related_message_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._log(session, row, Direction.INBOUND, "receive", message, message.raw)
            return row

    def update(self, body: Any) -> NotificationRow:
        """``POST /qualitynotifications/update`` — a partner changes a notification's status."""
        message = self._parse(body, "update")
        self._check_parties(message)
        with self._sessions.begin() as session:
            repository = NotificationRepository(session)
            row = repository.find(message.sender_bpn, message.notification_id)
            if row is None and message.related_message_id:
                # Some implementations reference the notification by its first message.
                row = repository.find_by_message(message.sender_bpn, message.related_message_id)
            if row is None:
                raise NotFound("no notification with this notificationId")
            if row.type != message.type.value:
                raise Invalid(f"the notification is an {row.type}, not an {message.type.value}")
            try:
                new = apply_partner_update(
                    Direction(row.direction), Status(row.status), message.status
                )
            except TransitionError as exc:
                raise Invalid(str(exc)) from exc
            row.status = new.value
            row.updated_at = self._clock()
            self._log(session, row, Direction.INBOUND, "update", message, message.raw)
            return row
