"""store money as kobo bigint

Revision ID: b68b98b27bd8
Revises: 937068e3b0c3
Create Date: 2026-11-01 21:00:12.674089

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b68b98b27bd8'
down_revision: Union[str, Sequence[str], None] = '937068e3b0c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Autogenerate saw these renames as drop + add, which would delete every
# amount. Rename in place instead, then convert existing naira values to kobo.
MONEY_COLUMNS = [
    ("circle", "weekly_amount", "weekly_amount_kobo"),
    ("contribution", "amount", "amount_kobo"),
    ("payout", "amount", "amount_kobo"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, old, new in MONEY_COLUMNS:
        op.alter_column(table, old, new_column_name=new, type_=sa.BigInteger())
        op.execute(f'UPDATE "{table}" SET {new} = {new} * 100')


def downgrade() -> None:
    """Downgrade schema."""
    for table, old, new in MONEY_COLUMNS:
        # Integer division: sub-naira kobo amounts are lost on downgrade
        op.execute(f'UPDATE "{table}" SET {new} = {new} / 100')
        op.alter_column(table, new, new_column_name=old, type_=sa.Integer())
