from datetime import datetime

from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint
class Contribution(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "circle_id", "week"),
    )

    id: int | None = Field(default=None, primary_key=True)

    user_id: int = Field(foreign_key="user.id")
    circle_id: int = Field(foreign_key="circle.id")

    amount: int
    week: str

    confirmed: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)