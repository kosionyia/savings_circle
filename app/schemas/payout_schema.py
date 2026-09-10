from sqlmodel import SQLModel, Field
from datetime import datetime, timezone


class Payout(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    circle_id: int = Field(foreign_key="circle.id")
    user_id: int = Field(foreign_key="user.id")
    amount: float
    week: str
    date_created: datetime