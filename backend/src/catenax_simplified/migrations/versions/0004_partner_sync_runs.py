"""partner sync runs, partner failures in a row

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "partner_sync_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("full", sa.Boolean(), nullable=False),
        sa.Column("partners_total", sa.Integer(), nullable=False),
        sa.Column("linked_twins", sa.Integer(), nullable=False),
        sa.Column("twins_cached", sa.Integer(), nullable=False),
        sa.Column("twins_fresh", sa.Integer(), nullable=False),
        sa.Column("twins_missing", sa.Integer(), nullable=False),
        sa.Column("twins_failed", sa.Integer(), nullable=False),
        sa.Column("removed_parts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("partners", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_partner_sync_runs_started_at"), "partner_sync_runs", ["started_at"], unique=False
    )
    with op.batch_alter_table("partners") as batch:
        batch.add_column(
            sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("partners") as batch:
        batch.drop_column("consecutive_failures")
    op.drop_index(op.f("ix_partner_sync_runs_started_at"), table_name="partner_sync_runs")
    op.drop_table("partner_sync_runs")
