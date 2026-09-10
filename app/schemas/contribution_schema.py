from datetime import datetime

from sqlmodel import Field, SQLModel

class Contribution(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int
    circle_id: int
    amount: int
    week: str
    created_at: datetime