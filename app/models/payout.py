from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Index, text
from sqlmodel import Field, SQLModel

class PayoutStatus(str, Enum):
    SCHEDULED = "scheduled"
    APPROVED = "approved"
    INITIATED = "initiated"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REVERSED = "reversed"


class Payout(SQLModel, table=True):
    __table_args__ = (
        # One live payout per turn. A reversed payout frees the turn so the
        # admin can schedule it again.
        Index(
            "uq_payout_live_turn",
            "circle_id",
            "week",
            unique=True,
            postgresql_where=text("status <> 'REVERSED'"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    circle_id: int = Field(foreign_key="circle.id")
    user_id: int = Field(foreign_key="user.id")
    # Set at initiate, from the pot's ledger balance at that moment
    amount_kobo: int | None = Field(default=None, sa_type=BigInteger)
    week: int
    date_created: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    status: PayoutStatus = PayoutStatus.SCHEDULED
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        # Refreshed automatically whenever the row is updated
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)},
    )



