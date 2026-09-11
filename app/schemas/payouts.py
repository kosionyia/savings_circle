from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    amount: int
    week: int
    date_created: datetime

    model_config = ConfigDict(from_attributes=True)
