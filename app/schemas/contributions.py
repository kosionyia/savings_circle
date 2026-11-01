from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ContributeIn(BaseModel):
    amount_kobo: int = Field(gt=0)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"amount_kobo": 500000}]
        }
    )


class ContributionOut(BaseModel):
    id: int
    user_id: int
    circle_id: int
    amount_kobo: int
    week: int
    confirmed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
