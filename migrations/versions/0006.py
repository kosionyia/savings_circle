"""add payout status and updated_at

Revision ID: f765b0c6d574
Revises: 70f7cbcbb0f4
Create Date: 2026-11-04 11:00:33.821348

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f765b0c6d574'
down_revision: Union[str, Sequence[str], None] = '70f7cbcbb0f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


payout_status = sa.Enum(
    "SCHEDULED", "APPROVED", "INITIATED", "CONFIRMED", "FAILED", "REVERSED",
    name="payoutstatus",
)


def upgrade() -> None:
    """Upgrade schema."""
    # add_column does not create enum types the way create_table does
    payout_status.create(op.get_bind(), checkfirst=True)

    # Add as nullable, backfill existing rows, then require a value. Adding
    # NOT NULL directly fails on a table that already has rows.
    op.add_column("payout", sa.Column("status", payout_status, nullable=True))
    op.add_column(
        "payout", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Payouts made before the state machine were paid in one step. Note they
    # have no journal entries: the ledger only covers payouts from now on.
    op.execute("UPDATE payout SET status = 'CONFIRMED', updated_at = date_created")
    op.alter_column("payout", "status", nullable=False)
    op.alter_column("payout", "updated_at", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("payout", "updated_at")
    op.drop_column("payout", "status")
    payout_status.drop(op.get_bind(), checkfirst=True)
