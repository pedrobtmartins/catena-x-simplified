"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notification_pk", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("information", sa.String(length=1000), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_notification_messages_message_id"), ["message_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_notification_messages_notification_pk"),
            ["notification_pk"],
            unique=False,
        )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notification_id", sa.String(length=64), nullable=False),
        sa.Column("initial_message_id", sa.String(length=64), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("partner_bpnl", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("affected_items", sa.JSON(), nullable=False),
        sa.Column("expected_response_by", sa.String(length=64), nullable=True),
        sa.Column("related_message_id", sa.String(length=64), nullable=True),
        sa.Column("forwarded_from_id", sa.Integer(), nullable=True),
        sa.Column("api_version", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("partner_bpnl", "notification_id", name="uq_notification"),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_notifications_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_notifications_direction"), ["direction"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_notifications_forwarded_from_id"), ["forwarded_from_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_notifications_initial_message_id"), ["initial_message_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_notifications_partner_bpnl"), ["partner_bpnl"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_notifications_status"), ["status"], unique=False)

    op.create_table(
        "partners",
        sa.Column("bpnl", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("connector_address", sa.String(length=512), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_message", sa.String(length=2000), nullable=True),
        sa.Column("twins_found", sa.Integer(), nullable=False),
        sa.Column("twins_missing", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bpnl"),
    )
    op.create_table(
        "parts",
        sa.Column("global_asset_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("semantic_id", sa.String(length=255), nullable=False),
        sa.Column("manufacturer_id", sa.String(length=32), nullable=True),
        sa.Column("is_own", sa.Boolean(), nullable=False),
        sa.Column("manufacturer_part_id", sa.String(length=255), nullable=True),
        sa.Column("customer_part_id", sa.String(length=255), nullable=True),
        sa.Column("name_at_manufacturer", sa.String(length=255), nullable=True),
        sa.Column("name_at_customer", sa.String(length=255), nullable=True),
        sa.Column("local_identifiers", sa.JSON(), nullable=False),
        sa.Column("production_date", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("site_ids", sa.JSON(), nullable=False),
        sa.Column("classifications", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("global_asset_id"),
    )
    with op.batch_alter_table("parts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_parts_is_own"), ["is_own"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_parts_manufacturer_id"), ["manufacturer_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_parts_manufacturer_part_id"), ["manufacturer_part_id"], unique=False
        )

    op.create_table(
        "relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_id", sa.String(length=255), nullable=False),
        sa.Column("child_id", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("declared_by", sa.String(length=255), nullable=False),
        sa.Column("business_partner", sa.String(length=32), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("is_only_potential_parent", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_id", "child_id", "source", name="uq_relation"),
    )
    with op.batch_alter_table("relations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_relations_child_id"), ["child_id"], unique=False)
        batch_op.create_index("ix_relations_declared", ["declared_by", "source"], unique=False)
        batch_op.create_index(batch_op.f("ix_relations_parent_id"), ["parent_id"], unique=False)

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("twins", sa.Integer(), nullable=False),
        sa.Column("parts", sa.Integer(), nullable=False),
        sa.Column("relation_sets", sa.Integer(), nullable=False),
        sa.Column("unsupported_submodels", sa.Integer(), nullable=False),
        sa.Column("removed_parts", sa.Integer(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("sync_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sync_runs_started_at"), ["started_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sync_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sync_runs_started_at"))

    op.drop_table("sync_runs")
    with op.batch_alter_table("relations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_relations_parent_id"))
        batch_op.drop_index("ix_relations_declared")
        batch_op.drop_index(batch_op.f("ix_relations_child_id"))

    op.drop_table("relations")
    with op.batch_alter_table("parts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_parts_manufacturer_part_id"))
        batch_op.drop_index(batch_op.f("ix_parts_manufacturer_id"))
        batch_op.drop_index(batch_op.f("ix_parts_is_own"))

    op.drop_table("parts")
    op.drop_table("partners")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notifications_status"))
        batch_op.drop_index(batch_op.f("ix_notifications_partner_bpnl"))
        batch_op.drop_index(batch_op.f("ix_notifications_initial_message_id"))
        batch_op.drop_index(batch_op.f("ix_notifications_forwarded_from_id"))
        batch_op.drop_index(batch_op.f("ix_notifications_direction"))
        batch_op.drop_index(batch_op.f("ix_notifications_created_at"))

    op.drop_table("notifications")
    with op.batch_alter_table("notification_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_messages_notification_pk"))
        batch_op.drop_index(batch_op.f("ix_notification_messages_message_id"))

    op.drop_table("notification_messages")
