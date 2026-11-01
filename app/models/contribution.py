from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class Contribution(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "circle_id", "week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    circle_id: int = Field(foreign_key="circle.id")
    amount_kobo: int = Field(sa_type=BigInteger)
    week: int
    confirmed: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
