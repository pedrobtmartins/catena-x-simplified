"""partner checks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "partner_checks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bpnl", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("connector_address", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("partner_checks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_partner_checks_bpnl"), ["bpnl"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_partner_checks_started_at"), ["started_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("partner_checks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_partner_checks_started_at"))
        batch_op.drop_index(batch_op.f("ix_partner_checks_bpnl"))

    op.drop_table("partner_checks")
