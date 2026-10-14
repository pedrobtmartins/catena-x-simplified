"""The KIT's notification state model, seen from either side.

The initiator creates, sends and closes; the receiver acknowledges, then accepts or declines.
``RECEIVED`` is set on the initiator's side when the receiver answers the send with HTTP 201, and
``CLOSED`` can only come from the initiator — to close normally or to abort.
"""

from __future__ import annotations

from enum import StrEnum

from .messages import Status


class Direction(StrEnum):
    OUTBOUND = "outbound"  # we are the initiator
    INBOUND = "inbound"  # we are the receiver


class TransitionError(ValueError):
    """A status change the state model does not allow (HTTP 422)."""


_RANK = {
    Status.CREATED: 0,
    Status.SENT: 1,
    Status.RECEIVED: 2,
    Status.ACKNOWLEDGED: 3,
    Status.ACCEPTED: 4,
    Status.DECLINED: 4,
    Status.CLOSED: 5,
}

# Changes made in this app, then sent to the partner (except discarding a draft).
_LOCAL = {
    Direction.OUTBOUND: {
        Status.CREATED: {Status.CLOSED},
        Status.SENT: {Status.CLOSED},
        Status.RECEIVED: {Status.CLOSED},
        Status.ACKNOWLEDGED: {Status.CLOSED},
        Status.ACCEPTED: {Status.CLOSED},
        Status.DECLINED: {Status.CLOSED},
    },
    Direction.INBOUND: {
        Status.RECEIVED: {Status.ACKNOWLEDGED},
        Status.ACKNOWLEDGED: {Status.ACCEPTED, Status.DECLINED},
    },
}

# What the partner may set through an update, by our side of the notification.
_FROM_PARTNER = {
    Direction.OUTBOUND: {Status.RECEIVED, Status.ACKNOWLEDGED, Status.ACCEPTED, Status.DECLINED},
    Direction.INBOUND: {Status.CLOSED},
}


def local_targets(direction: Direction, current: Status) -> set[Status]:
    """Statuses a user of this app can move the notification to."""
    return set(_LOCAL[direction].get(current, set()))


def check_local(direction: Direction, current: Status, new: Status) -> None:
    if new not in _LOCAL[direction].get(current, set()):
        who = "initiator" if direction is Direction.OUTBOUND else "receiver"
        raise TransitionError(f"the {who} cannot change {current} to {new}")


def apply_partner_update(direction: Direction, current: Status, new: Status) -> Status:
    """The status after a partner's update; repeats are idempotent.

    Partners may skip intermediate states (e.g. ACCEPTED without a separate ACKNOWLEDGED), but
    never move a notification backwards or change a final decision.
    """
    if new not in _FROM_PARTNER[direction]:
        if direction is Direction.OUTBOUND and new is Status.CLOSED:
            raise TransitionError("only the initiator can close a notification")
        raise TransitionError(f"a partner cannot set {new} on this notification")
    if new == current:
        return current
    if current is Status.CLOSED:
        raise TransitionError("the notification is closed")
    if _RANK[new] < _RANK[current]:
        if new is Status.RECEIVED:  # informational only; keep the further state
            return current
        raise TransitionError(f"cannot change {current} back to {new}")
    if _RANK[new] == _RANK[current]:
        raise TransitionError(f"cannot change {current} to {new}")
    return new
