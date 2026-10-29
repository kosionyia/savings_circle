from datetime import datetime, timezone

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class Payout(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("circle_id", "week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    circle_id: int = Field(foreign_key="circle.id")
    user_id: int = Field(foreign_key="user.id")
    amount: int
    week: int
    date_created: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
