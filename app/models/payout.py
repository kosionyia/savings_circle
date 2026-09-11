from sqlmodel import SQLModel, Field
from datetime import datetime
from sqlalchemy import UniqueConstraint


class Payout(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("circle_id", "week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    circle_id: int = Field(foreign_key="circle.id")
    user_id: int = Field(foreign_key="user.id")
    amount: int
    week: str
    date_created: datetime