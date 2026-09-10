from datetime import datetime

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint
class Contribution(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "circle_id", "week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int
    circle_id: int
    amount: int
    week: str
    created_at: datetime