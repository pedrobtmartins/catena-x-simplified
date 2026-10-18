"""Quality notification payloads of the Traceability KIT's Notification API, 1.2.1 and 2.0.0.

Both versions share the message header (``io.catenax.shared.message_header`` 2.0.0) and the
content fields used here; 2.0.0 adds optional fields (``relatedQualityTaskId``, attachments,
``populationFilterList``) and no longer requires ``listOfAffectedItems``. A single tolerant
parser therefore reads both versions, and the serializer only differs in what it must include.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

HEADER_VERSION = "2.0.0"  # io.catenax.shared.message_header
API_VERSIONS = ("2.0.0", "1.2.1")  # Notification API versions we speak, preferred first
INFORMATION_MAX_LENGTH = 1000

_UUID = re.compile(r"^(urn:uuid:)?[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_BPNL = re.compile(r"^BPNL[0-9A-Za-z]{12}$")


class NotificationType(StrEnum):
    """Quality alert (to customers) or quality investigation (to suppliers)."""

    ALERT = "alert"  # supplier → direct customer (bottom-up)
    INVESTIGATION = "investigation"  # customer → direct supplier (top-down)

    @property
    def context(self) -> str:
        """The message header's ``context`` for this type (Notification API 2.0.0)."""
        name = "Alert" if self is NotificationType.ALERT else "Investigation"
        return f"Traceability-QualityNotification-{name}:2.0.0"

    def asset_type(self, operation: str) -> str:
        """The KIT's ``dct:type`` of the partner's asset for ``receive`` or ``update``."""
        name = "Alert" if self is NotificationType.ALERT else "Investigation"
        verb = {"receive": "Receive", "update": "Update"}[operation]
        return f"https://w3id.org/catenax/taxonomy#{verb}Quality{name}Notification"


class Status(StrEnum):
    """Statuses of the KIT state model, shared by both sides."""

    CREATED = "CREATED"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"


class Severity(StrEnum):
    """Severities defined by the Notification API."""

    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"
    LIFE_THREATENING = "LIFE-THREATENING"


class MessageFormatError(ValueError):
    """The request body is not a valid quality notification (HTTP 400)."""


@dataclass(frozen=True)
class Message:
    """A quality notification message as exchanged between partners."""

    message_id: str
    type: NotificationType
    sender_bpn: str
    receiver_bpn: str
    notification_id: str
    status: Status | None
    sent_at: str | None = None
    expected_response_by: str | None = None
    related_message_id: str | None = None
    severity: Severity | None = None
    information: str | None = None
    affected_items: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


def new_uuid() -> str:
    """A new ``notificationId`` or ``messageId``."""
    return str(uuid.uuid4())


def timestamp(value: datetime) -> str:
    """A UTC timestamp in the format the Notification API uses."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def api_version_of(offered: str | None) -> str | None:
    """Map an offered ``cx-common:version`` (``2``, ``2.0``, ``1.2.1`` …) to the API version we
    serialize, by major version; ``None`` if we do not speak it."""
    match = re.match(r"^\s*v?(\d+)", offered or "")
    if not match:
        return None
    major = int(match.group(1))
    return next((v for v in API_VERSIONS if int(v.split(".")[0]) == major), None)


def _type_from_context(context: Any) -> NotificationType:
    if isinstance(context, str):
        lowered = context.lower()
        if "qualitynotification-alert" in lowered:
            return NotificationType.ALERT
        if "qualitynotification-investigation" in lowered:
            return NotificationType.INVESTIGATION
    raise MessageFormatError(f"unsupported header.context {context!r}")


def _text(data: Mapping[str, Any], key: str, *, required: bool = False) -> str | None:
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise MessageFormatError(f"missing {key}")
        return None
    if not isinstance(value, str):
        raise MessageFormatError(f"{key} must be a string")
    return value


def _enum(enum: type[StrEnum], value: Any, key: str) -> Any:
    if value is None:
        return None
    try:
        return enum(value)
    except ValueError as exc:
        raise MessageFormatError(f"unsupported {key} {value!r}") from exc


def parse_message(body: Any, *, operation: str) -> Message:
    """Parse a ``receive`` or ``update`` request body of Notification API 1.2.1 or 2.0.0."""
    if not isinstance(body, Mapping):
        raise MessageFormatError("body must be a JSON object")
    header, content = body.get("header"), body.get("content")
    if not isinstance(header, Mapping) or not isinstance(content, Mapping):
        raise MessageFormatError("body must have a header and a content object")

    message_id = _text(header, "messageId", required=True)
    notification_id = _text(content, "notificationId", required=True)
    for key, value in (("messageId", message_id), ("notificationId", notification_id)):
        if not _UUID.match(value):
            raise MessageFormatError(f"{key} must be a UUID")
    sender, receiver = (
        _text(header, "senderBpn", required=True),
        _text(header, "receiverBpn", required=True),
    )
    for key, value in (("senderBpn", sender), ("receiverBpn", receiver)):
        if not _BPNL.match(value):
            raise MessageFormatError(f"{key} must be a BPNL")

    status = _enum(Status, content.get("status"), "status")
    severity = _enum(Severity, content.get("severity"), "severity")
    information = _text(content, "information")
    if information and len(information) > INFORMATION_MAX_LENGTH:
        raise MessageFormatError(f"information exceeds {INFORMATION_MAX_LENGTH} characters")
    items = content.get("listOfAffectedItems") or []
    if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
        raise MessageFormatError("listOfAffectedItems must be a list of strings")
    if operation == "receive":
        if status is None or severity is None:
            raise MessageFormatError("a new notification needs a status and a severity")
    elif status is None:
        raise MessageFormatError("an update needs a status")

    return Message(
        message_id=message_id,
        type=_type_from_context(header.get("context")),
        sender_bpn=sender,
        receiver_bpn=receiver,
        notification_id=notification_id,
        status=status,
        sent_at=_text(header, "sentDateTime"),
        expected_response_by=_text(header, "expectedResponseBy"),
        related_message_id=_text(header, "relatedMessageId"),
        severity=severity,
        information=information,
        affected_items=tuple(dict.fromkeys(items)),
        raw=body,
    )


def build_message(message: Message, api_version: str, *, operation: str) -> dict[str, Any]:
    """Serialize for ``receive`` or ``update`` in the given Notification API version."""
    if api_version not in API_VERSIONS:
        raise ValueError(f"unsupported Notification API version {api_version}")
    header: dict[str, Any] = {
        "messageId": message.message_id,
        "context": message.type.context,
        "sentDateTime": message.sent_at,
        "senderBpn": message.sender_bpn,
        "receiverBpn": message.receiver_bpn,
        "version": HEADER_VERSION,
    }
    if message.expected_response_by:
        header["expectedResponseBy"] = message.expected_response_by
    if message.related_message_id:
        header["relatedMessageId"] = message.related_message_id

    content: dict[str, Any] = {"notificationId": message.notification_id}
    if message.status is not None:
        content["status"] = message.status.value
    if message.severity is not None:
        content["severity"] = message.severity.value
    if message.information:
        content["information"] = message.information
    if operation == "receive":
        # Required in 1.2.1, optional in 2.0.0; always meaningful for us.
        content["listOfAffectedItems"] = list(message.affected_items)
    return {"header": header, "content": content}
