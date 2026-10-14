from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PartRow(Base):
    __tablename__ = "parts"

    global_asset_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    semantic_id: Mapped[str] = mapped_column(String(255))
    manufacturer_id: Mapped[str | None] = mapped_column(String(32), index=True)
    is_own: Mapped[bool] = mapped_column(Boolean, index=True)
    manufacturer_part_id: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_part_id: Mapped[str | None] = mapped_column(String(255))
    name_at_manufacturer: Mapped[str | None] = mapped_column(String(255))
    name_at_customer: Mapped[str | None] = mapped_column(String(255))
    local_identifiers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    production_date: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(8))
    site_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    classifications: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RelationRow(Base):
    __tablename__ = "relations"
    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", "source", name="uq_relation"),
        Index("ix_relations_declared", "declared_by", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[str] = mapped_column(String(255), index=True)
    child_id: Mapped[str] = mapped_column(String(255), index=True)
    source: Mapped[str] = mapped_column(String(16))
    declared_by: Mapped[str] = mapped_column(String(255))
    business_partner: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(64))
    is_only_potential_parent: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncRunRow(Base):
    """One own-twin sync run and what it reported."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    twins: Mapped[int] = mapped_column(default=0)
    parts: Mapped[int] = mapped_column(default=0)
    relation_sets: Mapped[int] = mapped_column(default=0)
    unsupported_submodels: Mapped[int] = mapped_column(default=0)
    removed_parts: Mapped[int] = mapped_column(default=0)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class PartnerRow(Base):
    """A direct partner: how to reach its connector and how its last sync went."""

    __tablename__ = "partners"

    bpnl: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    connector_address: Mapped[str | None] = mapped_column(String(512))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ok | partial | failed | no_connector
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_message: Mapped[str | None] = mapped_column(String(2000))
    twins_found: Mapped[int] = mapped_column(default=0)
    twins_missing: Mapped[int] = mapped_column(default=0)


class PartnerCheckRow(Base):
    """One connectivity check of a partner's connector and its steps."""

    __tablename__ = "partner_checks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bpnl: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(16))  # discovery | catalog | full
    status: Mapped[str] = mapped_column(String(16))  # healthy | degraded | failed
    connector_address: Mapped[str | None] = mapped_column(String(512))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # [{key, name, status, detail}], in the order they ran.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class NotificationRow(Base):
    """A quality alert or investigation exchanged with one direct partner."""

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("partner_bpnl", "notification_id", name="uq_notification"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The KIT's notificationId, shared with the partner.
    notification_id: Mapped[str] = mapped_column(String(64))
    # messageId of the message that created the notification on the receiver's side.
    initial_message_id: Mapped[str | None] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(16))  # alert | investigation
    direction: Mapped[str] = mapped_column(String(16), index=True)  # outbound | inbound
    partner_bpnl: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(String(1000))
    affected_items: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_response_by: Mapped[str | None] = mapped_column(String(64))
    related_message_id: Mapped[str | None] = mapped_column(String(64))
    # Local link to the notification this one was forwarded from (the previous hop).
    forwarded_from_id: Mapped[int | None] = mapped_column(index=True)
    # Notification API version used on the wire, when known.
    api_version: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationMessageRow(Base):
    """Every message sent or received for a notification, as exchanged."""

    __tablename__ = "notification_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    notification_pk: Mapped[int] = mapped_column(index=True)
    direction: Mapped[str] = mapped_column(String(16))  # outbound | inbound
    operation: Mapped[str] = mapped_column(String(16))  # receive | update
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str | None] = mapped_column(String(16))
    information: Mapped[str | None] = mapped_column(String(1000))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
