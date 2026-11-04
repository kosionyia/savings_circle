from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class IdempotencyKey(SQLModel, table=True):
    __tablename__ = "idempotency_key"

    key: str = Field(primary_key=True)
    user_id: int = Field(primary_key=True, foreign_key="user.id")
    endpoint: str = Field(primary_key=True)
    request_hash: str = Field(max_length=64)
    response_status: int | None = Field(default=None)
    response_body: dict | None = Field(default=None, sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
