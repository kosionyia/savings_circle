from datetime import datetime

from sqlmodel import Field, SQLModel


class LedgerEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    contribution_id: int = Field(foreign_key="contribution.id")
    circle_id: int
    user_id: int
    amount: int
    week: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
