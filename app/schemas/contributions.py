from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContributeIn(BaseModel):
    amount: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"amount": 5000}]
        }
    )


class ContributionOut(BaseModel):
    id: int
    user_id: int
    circle_id: int
    amount: int
    week: int
    confirmed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
