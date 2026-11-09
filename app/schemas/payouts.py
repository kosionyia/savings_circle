from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.payout import PayoutStatus


class PayoutIn(BaseModel):
    user_id: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"user_id": 2}]
        }
    )


class PayoutOut(BaseModel):
    id: int
    circle_id: int
    user_id: int
    amount_kobo: int | None
    week: int
    status: PayoutStatus
    date_created: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
